"""
pjmedia/stream.h - Media Stream

Media stream implementation for bidirectional audio.
Integrates codec, RTP/RTCP, and jitter buffer.
"""

import asyncio
import socket
import threading
import time
from typing import Optional, Callable, Dict, Any, Tuple
from dataclasses import dataclass

from .rtp import RtpSession, RtpHeader
from .rtcp import RtcpSession
from .jbuf import JitterBuffer, create_jitter_buffer
from .codec import Codec, G711Codec
from .sdp import SdpSession


@dataclass
class MediaStreamConfig:
    """Media stream configuration."""
    local_ip: str = "127.0.0.1"
    local_port: int = 4000
    remote_ip: str = "127.0.0.1"
    remote_port: int = 4000
    payload_type: int = 8
    clock_rate: int = 8000
    ptime: int = 20
    jb_min_delay_ms: int = 60
    jb_max_delay_ms: int = 200
    jb_max_size: int = 100


class MediaStream:
    """
    Bidirectional media stream.

    Handles encoding/decoding and RTP transmission/reception.
    """

    def __init__(self, config: Optional[MediaStreamConfig] = None):
        """
        Initialize media stream.

        Args:
            config: Stream configuration.
        """
        self._config = config or MediaStreamConfig()
        self._rtp_session: Optional[RtpSession] = None
        self._rtcp_session: Optional[RtcpSession] = None
        self._jitter_buffer: Optional[JitterBuffer] = None
        self._codec: Optional[Codec] = None
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._local_rtp_addr: Tuple[str, int] = ("", 0)
        self._remote_rtp_addr: Tuple[str, int] = ("", 0)
        self._rx_thread: Optional[threading.Thread] = None
        self._on_rx_frame: Optional[Callable] = None
        self._lock = threading.Lock()

    @property
    def local_addr(self) -> Tuple[str, int]:
        """Get local RTP address."""
        return self._local_rtp_addr

    @property
    def remote_addr(self) -> Tuple[str, int]:
        """Get remote RTP address."""
        return self._remote_rtp_addr

    def start(self) -> bool:
        """
        Start the media stream.

        Returns:
            True if started successfully.
        """
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._config.local_ip, self._config.local_port))
            self._local_rtp_addr = self._sock.getsockname()

            self._rtp_session = RtpSession(
                payload_type=self._config.payload_type
            )
            self._rtp_session.set_clock_rate(self._config.clock_rate)
            self._rtp_session.init()

            self._rtcp_session = RtcpSession(ssrc=self._rtp_session.ssrc)

            self._jitter_buffer = create_jitter_buffer(
                self._config.jb_min_delay_ms,
                self._config.jb_max_delay_ms,
                self._config.jb_max_size
            )
            self._jitter_buffer.set_clock_rate(self._config.clock_rate)

            self._codec = G711Codec(a_law=self._config.payload_type == 8)

            self._remote_rtp_addr = (self._config.remote_ip, self._config.remote_port)

            self._running = True
            self._rx_thread = threading.Thread(target=self._rx_loop)
            self._rx_thread.start()

            return True

        except Exception:
            return False

    def stop(self) -> None:
        """Stop the media stream."""
        self._running = False

        if self._rx_thread:
            self._rx_thread.join(timeout=1.0)
            self._rx_thread = None

        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def destroy(self) -> None:
        """Destroy the stream and release resources."""
        self.stop()

    def set_remote(self, addr: Tuple[str, int]) -> None:
        """
        Set remote RTP address.

        Args:
            addr: Remote (host, port).
        """
        self._remote_rtp_addr = addr

    def send_frame(self, pcm_data: bytes) -> int:
        """
        Send PCM audio frame.

        Args:
            pcm_data: 16-bit linear PCM audio data.

        Returns:
            Number of bytes sent.
        """
        if not self._running or not self._sock:
            return 0

        try:
            g711_data = self._codec.encode(pcm_data)
            rtp_data = self._rtp_session.encode_rtp(g711_data)
            self._sock.sendto(rtp_data, self._remote_rtp_addr)
            return len(rtp_data)
        except Exception:
            return 0

    def send_g711(self, g711_data: bytes) -> int:
        """
        Send G.711 audio data.

        Args:
            g711_data: G.711 encoded audio.

        Returns:
            Number of bytes sent.
        """
        if not self._running or not self._sock:
            return 0

        try:
            rtp_data = self._rtp_session.encode_rtp(g711_data)
            print(f"DEBUG: RTP to {self._remote_rtp_addr}: {len(rtp_data)} bytes, seq={self._rtp_session.sequence}, ts={self._rtp_session.timestamp}")
            self._sock.sendto(rtp_data, self._remote_rtp_addr)
            return len(rtp_data)
        except Exception as e:
            print(f"DEBUG: RTP send error: {e}")
            return 0

    def _rx_loop(self) -> None:
        """Receive loop (runs in thread)."""
        while self._running and self._sock:
            try:
                data, addr = self._sock.recvfrom(4096)
                if len(data) < 12:
                    continue

                header, payload = self._rtp_session.decode_rtp(data)

                now = time.time()
                self._jitter_buffer.put(
                    type('Frame', (), {
                        'data': payload,
                        'timestamp': header.timestamp,
                        'seq': header.sequence
                    })()
                )

                if self._on_rx_frame:
                    try:
                        self._on_rx_frame(payload, header)
                    except Exception:
                        pass

            except Exception:
                pass

    def set_on_rx_frame(self, callback: Callable) -> None:
        """Set callback for received frames."""
        self._on_rx_frame = callback

    def get_frame(self) -> Optional[bytes]:
        """
        Get decoded audio frame from jitter buffer.

        Returns:
            Decoded PCM audio or None.
        """
        if not self._jitter_buffer:
            return None

        frame = self._jitter_buffer.get()
        if frame and frame.data:
            pcm = self._codec.decode(frame.data)
            return pcm
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get stream statistics."""
        stats = {}
        if self._rtp_session:
            stats['rtp'] = self._rtp_session.get_stats()
        if self._jitter_buffer:
            stats['jitter_buffer'] = self._jitter_buffer.get_stats()
        if self._rtcp_session:
            stats['rtcp'] = self._rtcp_session.get_stats()
        return stats

    def get_jitter(self) -> float:
        """Get current jitter in milliseconds."""
        if self._jitter_buffer:
            return self._jitter_buffer.get_stats().get('avg_jitter', 0) * 1000
        return 0.0


def create_media_stream(
    local_ip: str = "127.0.0.1",
    local_port: int = 4000,
    remote_ip: str = "127.0.0.1",
    remote_port: int = 4000,
    payload_type: int = 8,
    clock_rate: int = 8000
) -> MediaStream:
    """Create media stream."""
    config = MediaStreamConfig(
        local_ip=local_ip,
        local_port=local_port,
        remote_ip=remote_ip,
        remote_port=remote_port,
        payload_type=payload_type,
        clock_rate=clock_rate
    )
    return MediaStream(config)


def get_media_info_from_sdp(sdp: SdpSession) -> Tuple[str, int, int]:
    """
    Extract media info from SDP - finds PCMA (8) specifically across all media blocks.

    Args:
        sdp: SDP session description.

    Returns:
        Tuple of (media_ip, media_port, payload_type).
    """
    if not sdp.medias:
        return ("", 0, 0)

    ip, _ = sdp.get_connection_address()
    if not ip:
        return ("", 0, 0)

    preferred_pt = 8

    for media in sdp.medias:
        if media.media != "audio":
            continue

        for fmt in media.fmt:
            try:
                pt = int(fmt)
                if pt == preferred_pt:
                    return (ip, media.port, pt)
            except ValueError:
                continue

    first_media = sdp.medias[0]
    if first_media.fmt:
        try:
            pt = int(first_media.fmt[0])
        except ValueError:
            pt = preferred_pt
    else:
        pt = preferred_pt

    return (ip, first_media.port, pt)
