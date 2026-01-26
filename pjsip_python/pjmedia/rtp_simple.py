"""
Simple RTP implementation based on queue-based design.
Supports G.711 A-law/μ-law encoding/decoding.
"""

import audioop
import random
import socket
import threading
import time
import warnings
from collections import deque
from typing import Optional


class PayloadType:
    """RTP payload types for audio codecs."""

    PCMU = 0
    PCMA = 8
    G722 = 9
    G729 = 18
    EVENT = 101
    CN = 13

    @staticmethod
    def get_clock_rate(ptype: int) -> int:
        """Get clock rate for payload type."""
        return 8000


class SimpleRTPClient:
    """Simplified RTP client using queue for G.711 audio transmission."""

    def __init__(
        self,
        local_ip: str,
        local_port: int,
        remote_ip: str,
        remote_port: int,
        payload_type: int = 8,
        a_law: bool = True,
    ):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.a_law = a_law

        self.clock_rate = PayloadType.get_clock_rate(payload_type)
        self._running = False

        self._tx_queue = deque(maxlen=1000)
        self._rx_queue = deque(maxlen=1000)
        self._tx_lock = threading.Lock()
        self._rx_lock = threading.Lock()

        self.out_sequence = random.randint(1, 100)
        self.out_timestamp = random.randint(1, 10000)
        self.out_ssrc = random.randint(1000, 65530)

        self._socket: Optional[socket.socket] = None
        self._tx_thread: Optional[threading.Thread] = None
        self._rx_thread: Optional[threading.Thread] = None

        print(
            f"[SimpleRTP] init: {local_ip}:{local_port} -> {remote_ip}:{remote_port}, PT={payload_type}"
        )

    @property
    def running(self) -> bool:
        return self._running

    def start(self):
        """Start RTP transmission and reception."""
        if self._running:
            return

        self._running = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((self.local_ip, self.local_port))
        self._socket.settimeout(0.01)

        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self._tx_thread.start()

        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

        print(
            f"[SimpleRTP] Started: {self.local_ip}:{self.local_port} -> {self.remote_ip}:{self.remote_port}"
        )

    def stop(self):
        """Stop RTP transmission and reception."""
        self._running = False
        if self._socket:
            self._socket.close()
            self._socket = None
        if self._tx_thread:
            self._tx_thread.join(timeout=1.0)
        if self._rx_thread:
            self._rx_thread.join(timeout=1.0)
        print("[SimpleRTP] Stopped")

    def set_remote(self, remote_ip: str, remote_port: int):
        """Update remote address."""
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        print(f"[SimpleRTP] Remote updated: {remote_ip}:{remote_port}")

    def write(self, data: bytes):
        """
        Write 16-bit linear PCM audio data.
        Will be encoded to G.711 before transmission.
        """
        if len(data) < 320:
            return
        with self._tx_lock:
            self._tx_queue.append(("pcm", data))

    def write_g711(self, data: bytes):
        """
        Write pre-encoded G.711 audio data directly.
        """
        if len(data) < 160:
            return
        with self._tx_lock:
            self._tx_queue.append(("g711", data))

    def read(self, length: int = 160, blocking: bool = True) -> bytes:
        """Read 16-bit linear PCM audio data."""
        if blocking and self._running:
            retry = 0
            while len(self._rx_queue) == 0 and retry < 100:
                time.sleep(0.001)
                retry += 1

        with self._rx_lock:
            if self._rx_queue:
                return self._rx_queue.popleft()
        return b"\x00" * 320

    def _encode_to_g711(self, data: bytes) -> bytes:
        """Encode to G.711 A-law or μ-law."""
        if self.a_law:
            return audioop.lin2alaw(data, 1)
        else:
            return audioop.lin2ulaw(data, 1)

    def _decode_from_g711(self, data: bytes) -> bytes:
        """Decode from G.711 A-law or μ-law to 16-bit linear PCM."""
        if self.a_law:
            return audioop.alaw2lin(data, 1)
        else:
            return audioop.ulaw2lin(data, 1)

    def _build_rtp_packet(self, payload: bytes) -> bytes:
        """Build RTP packet header and payload."""
        packet = bytearray()

        byte0 = 0x80
        byte0 |= self.payload_type
        packet.append(byte0)

        packet.extend(self.out_sequence.to_bytes(2, byteorder="big"))
        packet.extend(self.out_timestamp.to_bytes(4, byteorder="big"))
        packet.extend(self.out_ssrc.to_bytes(4, byteorder="big"))

        packet.extend(payload)

        return bytes(packet)

    def _tx_loop(self):
        """Transmission loop - sends RTP packets at correct timing."""
        while self._running and self._socket:
            try:
                start_time = time.monotonic()

                payload_bytes = None
                with self._tx_lock:
                    if self._tx_queue:
                        msg_type, data = self._tx_queue.popleft()
                        if msg_type == "g711":
                            payload_bytes = data
                        else:
                            payload_bytes = self._encode_to_g711(data)

                if payload_bytes:
                    packet = self._build_rtp_packet(payload_bytes)

                    try:
                        self._socket.sendto(packet, (self.remote_ip, self.remote_port))
                    except OSError as e:
                        if self._running:
                            warnings.warn(f"RTP send failed: {e}", RuntimeWarning)

                    self.out_sequence = (self.out_sequence + 1) & 0xFFFF
                    self.out_timestamp = (self.out_timestamp + 160) & 0xFFFFFFFF

                delay = 160 / self.clock_rate
                elapsed = time.monotonic() - start_time
                sleep_time = max(0, delay - elapsed)
                time.sleep(sleep_time)

            except Exception as e:
                if self._running:
                    warnings.warn(f"RTP TX error: {e}", RuntimeWarning)

    def _rx_loop(self):
        """Receive loop - handles incoming RTP packets."""
        while self._running and self._socket:
            try:
                data, _ = self._socket.recvfrom(8192)
                self._parse_rtp_packet(data)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                if self._running:
                    warnings.warn(f"RTP RX error: {e}", RuntimeWarning)

    def _parse_rtp_packet(self, data: bytes):
        """Parse incoming RTP packet."""
        if len(data) < 12:
            return

        byte0 = data[0]
        version = (byte0 >> 6) & 0x03

        if version != 2:
            return

        payload_type = byte0 & 0x7F
        sequence = int.from_bytes(data[2:4], byteorder="big")
        timestamp = int.from_bytes(data[4:8], byteorder="big")
        ssrc = int.from_bytes(data[8:12], byteorder="big")

        payload = data[12:]

        if len(payload) == 0:
            return

        if payload_type == self.payload_type:
            decoded = self._decode_from_g711(payload)
            with self._rx_lock:
                if len(self._rx_queue) < 100:
                    self._rx_queue.append(decoded)
        elif payload_type == PayloadType.CN:
            pass
        elif payload_type == PayloadType.EVENT:
            pass
