"""
Media stream implementation using SimpleRTPClient for G.711 audio.
"""

import asyncio
from typing import Optional, Tuple

from .rtp_simple import SimpleRTPClient


class SimpleMediaStream:
    """Simplified media stream using SimpleRTPClient."""

    def __init__(
        self,
        local_ip: str,
        local_port: int,
        remote_ip: Optional[str] = None,
        remote_port: Optional[int] = None,
        payload_type: int = 8,
        a_law: bool = True,
    ):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.a_law = a_law

        self._remote_addr: Optional[Tuple[str, int]] = None
        self._rtp_client: Optional[SimpleRTPClient] = None
        self._started = False

        print(
            f"[SimpleMediaStream] Created: {local_ip}:{local_port}, PT={payload_type}, a-law={a_law}"
        )

    def set_remote(self, remote_ip: str, remote_port: int):
        """Set remote RTP address."""
        print(f"[SimpleMediaStream] Remote: {remote_ip}:{remote_port}")
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self._remote_addr = (remote_ip, remote_port)

        if self._rtp_client:
            self._rtp_client.set_remote(remote_ip, remote_port)

    def start(self):
        """Start media stream."""
        if self._started:
            return

        if not (self.remote_ip and self.remote_port):
            print("[SimpleMediaStream] Cannot start - remote not set")
            return

        self._rtp_client = SimpleRTPClient(
            local_ip=self.local_ip,
            local_port=self.local_port,
            remote_ip=self.remote_ip,
            remote_port=self.remote_port,
            payload_type=self.payload_type,
            a_law=self.a_law,
        )
        self._rtp_client.start()
        self._started = True

        print(f"[SimpleMediaStream] Started RTP client")

    def stop(self):
        """Stop media stream."""
        if self._rtp_client:
            self._rtp_client.stop()
            self._rtp_client = None
        self._started = False
        print("[SimpleMediaStream] Stopped")

    def send_frame(self, pcm_data: bytes):
        """
        Send 16-bit linear PCM audio frame.
        Will be encoded to G.711 before transmission.
        """
        if not self._rtp_client:
            return

        self._rtp_client.write(pcm_data)

    def send_g711(self, g711_data: bytes):
        """
        Send pre-encoded G.711 audio data directly.
        """
        if not self._rtp_client:
            return

        self._rtp_client.write_g711(g711_data)

    def receive_frame(self) -> bytes:
        """Receive 16-bit linear PCM audio frame."""
        if not self._rtp_client:
            return b"\x00" * 320

        return self._rtp_client.read()

    @property
    def remote_addr(self) -> Optional[Tuple[str, int]]:
        """Get remote address."""
        return self._remote_addr

    @property
    def running(self) -> bool:
        """Check if stream is running."""
        return self._started and (self._rtp_client is not None)
