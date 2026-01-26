"""
MediaStream implementation using pyVoIP-style RTPClient.

This replaces the async-based MediaStream with a simpler threading-based
approach that's more compatible with the pyVoIP design.
"""

import socket
import threading
import time
from typing import Optional, Callable, Tuple, Dict, Any
from dataclasses import dataclass

from .rtp_pyvoip import RTPClient, PayloadType, RTPPacketManager


@dataclass
class MediaStreamConfig:
    """Media stream configuration."""

    local_ip: str = "127.0.0.1"
    local_port: int = 4000
    remote_ip: str = "127.0.0.1"
    remote_port: int = 4000
    payload_type: int = 8  # PCMA
    clock_rate: int = 8000
    ptime: int = 20  # milliseconds


class MediaStream:
    """
    Bidirectional media stream using pyVoIP-style RTPClient.

    This implementation uses threading for recv/trans instead of asyncio,
    which is more compatible with the pyVoIP approach.
    """

    def __init__(self, config: Optional[MediaStreamConfig] = None):
        """
        Initialize media stream.

        Args:
            config: Stream configuration.
        """
        self._config = config or MediaStreamConfig()
        self._rtp_client: Optional[RTPClient] = None
        self._codec_payload_type = self._config.payload_type
        self._running = False
        self._local_addr: Tuple[str, int] = ("", 0)
        self._remote_addr: Tuple[str, int] = ("", 0)
        self._on_rx_frame: Optional[Callable] = None
        self._rx_buffer = RTPPacketManager()
        self._lock = threading.Lock()

    @property
    def local_addr(self) -> Tuple[str, int]:
        """Get local RTP address."""
        return self._local_addr

    @property
    def remote_addr(self) -> Tuple[str, int]:
        """Get remote RTP address."""
        return self._remote_addr

    def start(self) -> bool:
        """
        Start the media stream.

        Returns:
            True if started successfully.
        """
        try:
            self._rtp_client = RTPClient(
                inIP=self._config.local_ip,
                inPort=self._config.local_port,
                outIP=self._config.remote_ip,
                outPort=self._config.remote_port,
                payload_type=self._codec_payload_type,
            )
            self._rtp_client.start()

            self._local_addr = self._rtp_client.local_addr
            self._remote_addr = self._rtp_client.remote_addr
            self._running = True

            return True

        except Exception as e:
            print(f"[MediaStream] Start failed: {e}")
            return False

    def stop(self) -> None:
        """Stop the media stream."""
        self._running = False
        if self._rtp_client:
            self._rtp_client.stop()
            self._rtp_client = None

    def destroy(self) -> None:
        """Destroy the stream and release resources."""
        self.stop()

    def set_remote(self, addr: Tuple[str, int]) -> None:
        """
        Set remote RTP address.

        Args:
            addr: Remote (host, port).
        """
        print(f"[MediaStream] Setting remote to {addr[0]}:{addr[1]}")
        self._remote_addr = addr
        if self._rtp_client:
            self._rtp_client.set_remote(addr)
            print(
                f"[MediaStream] RTP client remote set to {self._rtp_client.remote_addr[0]}:{self._rtp_client.remote_addr[1]}"
            )

    def send_frame(self, pcm_data: bytes) -> int:
        """
        Send PCM audio frame.

        Args:
            pcm_data: 16-bit linear PCM audio data.

        Returns:
            Number of bytes sent.
        """
        if not self._running or not self._rtp_client:
            return 0

        try:
            self._rtp_client.write(pcm_data)
            return len(pcm_data)
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
        print(
            f"[MediaStream.send_g711] Called with {len(g711_data)} bytes, running={self._running}, rtp_client={self._rtp_client is not None}"
        )
        if not self._running or not self._rtp_client:
            print(
                f"[MediaStream.send_g711] FAILED - running={self._running}, rtp_client={self._rtp_client is not None}"
            )
            return 0

        try:
            self._rtp_client.write(g711_data)
            print(f"[MediaStream.send_g711] Sent {len(g711_data)} bytes to RTP client")
            return len(g711_data)
        except Exception as e:
            print(f"[MediaStream.send_g711] Exception: {e}")
            return 0

    def read(self, length: int = 160, blocking: bool = True) -> bytes:
        """
        Read audio data from receive buffer.

        Args:
            length: Number of bytes to read.
            blocking: Wait for data if True.

        Returns:
            Audio data.
        """
        if not self._rtp_client:
            return b"\x00" * length

        return self._rtp_client.read(length, blocking)

    def get_frame(self) -> Optional[bytes]:
        """
        Get decoded audio frame.

        Returns:
            Decoded PCM audio or None.
        """
        data = self.read(160, blocking=False)
        if data and data != b"\x00" * 160:
            return data
        return None

    def set_on_rx_frame(self, callback: Callable) -> None:
        """Set callback for received frames."""
        self._on_rx_frame = callback

    def get_stats(self) -> Dict[str, Any]:
        """Get stream statistics."""
        return {
            "local_addr": self._local_addr,
            "remote_addr": self._remote_addr,
            "payload_type": self._codec_payload_type,
            "running": self._running,
        }

    @property
    def rtp_client(self) -> Optional[RTPClient]:
        """Get underlying RTP client."""
        return self._rtp_client


def create_media_stream(
    local_ip: str = "127.0.0.1",
    local_port: int = 4000,
    remote_ip: str = "127.0.0.1",
    remote_port: int = 4000,
    payload_type: int = 8,
    clock_rate: int = 8000,
) -> MediaStream:
    """Create media stream."""
    config = MediaStreamConfig(
        local_ip=local_ip,
        local_port=local_port,
        remote_ip=remote_ip,
        remote_port=remote_port,
        payload_type=payload_type,
        clock_rate=clock_rate,
    )
    return MediaStream(config)


def get_media_info_from_sdp(sdp) -> Tuple[str, int, int]:
    """
    Extract media info from SDP.

    Returns:
        Tuple of (media_ip, media_port, payload_type).
    """
    try:
        if hasattr(sdp, "find_media"):
            media = sdp.find_media("audio")
            if media:
                port = media.port if hasattr(media, "port") else 0

                ip = ""
                if hasattr(sdp, "connection") and sdp.connection:
                    ip = (
                        sdp.connection.split()[-1]
                        if " " in sdp.connection
                        else sdp.connection
                    )

                if not ip and media.connection:
                    ip = media.connection.split()[-1]

                pt = 8
                if hasattr(media, "fmt") and media.fmt:
                    try:
                        pt = int(media.fmt[0])
                    except (ValueError, IndexError):
                        pass

                return (ip, port, pt)
    except Exception as e:
        print(f"[MediaStream] SDP parse error: {e}")

    return ("", 0, 8)
