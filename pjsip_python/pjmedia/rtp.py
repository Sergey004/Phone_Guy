"""
pjmedia/rtp.h - RTP Session

RTP (Real-time Transport Protocol) session implementation.
Handles RTP header encoding/decoding and session management.
"""

import struct
import random
import time
from typing import Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import IntEnum


class RtpPayloadType(IntEnum):
    """RTP payload type constants."""
    PCMU = 0
    PCMA = 8
    G722 = 9
    L16_MONO = 10
    L16_STEREO = 11
    MPA = 14
    DYNAMIC1 = 96
    DYNAMIC2 = 97
    DYNAMIC3 = 98
    DYNAMIC4 = 99
    DYNAMIC5 = 100


@dataclass
class RtpHeader:
    """
    RTP header structure (12 bytes).

    Attributes:
        version: RTP version (2).
        padding: Padding flag.
        extension: Extension flag.
        csrc_count: CSRC count.
        marker: Marker bit.
        payload_type: Payload type.
        sequence: Sequence number.
        timestamp: Timestamp.
        ssrc: Synchronization source.
    """
    version: int = 2
    padding: int = 0
    extension: int = 0
    csrc_count: int = 0
    marker: int = 0
    payload_type: int = 8
    sequence: int = 0
    timestamp: int = 0
    ssrc: int = 0

    def pack(self) -> bytes:
        """Pack header to bytes."""
        first_byte = (self.version << 6) | (self.padding << 5) | (self.extension << 4) | self.csrc_count
        second_byte = (self.marker << 7) | self.payload_type
        return struct.pack('!BBHII', first_byte, second_byte, self.sequence, self.timestamp, self.ssrc)

    def unpack(self, data: bytes) -> bool:
        """Unpack header from bytes."""
        if len(data) < 12:
            return False

        first_byte, second_byte, self.sequence, self.timestamp, self.ssrc = struct.unpack('!BBHII', data[:12])
        self.version = (first_byte >> 6) & 0x03
        self.padding = (first_byte >> 5) & 0x01
        self.extension = (first_byte >> 4) & 0x01
        self.csrc_count = first_byte & 0x0F
        self.marker = (second_byte >> 7) & 0x01
        self.payload_type = second_byte & 0x7F
        return True

    @property
    def bytes(self) -> int:
        """Get header size in bytes."""
        return 12 + (self.csrc_count * 4)


@dataclass
class RtpPacket:
    """
    RTP packet with header and payload.
    """
    header: RtpHeader = field(default_factory=RtpHeader)
    payload: bytes = b""

    def pack(self) -> bytes:
        """Pack packet to bytes."""
        return self.header.pack() + self.payload

    def unpack(self, data: bytes) -> bool:
        """Unpack packet from bytes."""
        if not self.header.unpack(data):
            return False
        self.payload = data[self.header.bytes:]
        return True


class RtpSession:
    """
    RTP session for sending/receiving RTP packets.

    Manages sequence numbers, timestamps, and SSRC.
    """

    def __init__(
        self,
        ssrc: Optional[int] = None,
        sequence: int = 0,
        timestamp: int = 0,
        payload_type: int = 8
    ):
        self._ssrc = ssrc if ssrc is not None else random.randint(0, 0xFFFFFFFF)
        self._sequence = sequence & 0xFFFF
        self._timestamp = timestamp
        self._payload_type = payload_type
        self._start_time = 0
        self._packet_count = 0
        self._octet_count = 0
        self._jitter = 0.0
        self._transit = 0
        self._last_rtp_time = 0
        self._clock_rate = 8000

    @property
    def ssrc(self) -> int:
        """Get SSRC."""
        return self._ssrc

    @property
    def sequence(self) -> int:
        """Get sequence number."""
        return self._sequence

    @property
    def timestamp(self) -> int:
        """Get timestamp."""
        return self._timestamp

    def set_payload_type(self, pt: int) -> None:
        """Set payload type."""
        self._payload_type = pt

    def set_clock_rate(self, rate: int) -> None:
        """Set clock rate (samples per second)."""
        self._clock_rate = rate

    def init(self, ssrc: Optional[int] = None, sequence: int = 0, timestamp: int = 0) -> None:
        """Initialize session."""
        self._ssrc = ssrc if ssrc is not None else random.randint(0, 0xFFFFFFFF)
        self._sequence = sequence & 0xFFFF
        self._timestamp = timestamp
        self._start_time = time.time()
        self._packet_count = 0
        self._octet_count = 0
        self._jitter = 0.0
        self._transit = 0
        self._last_rtp_time = 0

    def update_seq(self, new_seq: int) -> None:
        """Update sequence number (handle wraparound)."""
        delta = new_seq - self._sequence
        if delta > 0xFF:
            self._sequence = new_seq
        else:
            self._sequence = (self._sequence + delta) & 0xFFFF

    def encode_rtp(
        self,
        payload: bytes,
        marker: int = 0,
        timestamp: Optional[int] = None
    ) -> bytes:
        """
        Encode RTP packet.

        Args:
            payload: Payload data.
            marker: Marker bit value.
            timestamp: Timestamp (auto-increment if None).

        Returns:
            Encoded RTP packet bytes.
        """
        if timestamp is not None:
            self._timestamp = timestamp

        header = RtpHeader(
            version=2,
            payload_type=self._payload_type,
            sequence=self._sequence,
            timestamp=self._timestamp,
            ssrc=self._ssrc,
            marker=marker
        )

        packet = RtpPacket(header=header, payload=payload)
        self._sequence = (self._sequence + 1) & 0xFFFF
        self._packet_count += 1
        self._octet_count += len(payload)
        self._timestamp += 160  # 160 samples = 20ms at 8kHz

        return packet.pack()

    def decode_rtp(self, data: bytes) -> Tuple[RtpHeader, bytes]:
        """
        Decode RTP packet.

        Args:
            data: Raw RTP data.

        Returns:
            Tuple of (header, payload).
        """
        packet = RtpPacket()
        if not packet.unpack(data):
            return RtpHeader(), b""

        return packet.header, packet.payload

    def update(self, arrival_time: float) -> float:
        """Update jitter calculation from arrival time."""
        if self._last_rtp_time == 0:
            self._last_rtp_time = arrival_time * (self._clock_rate / 1000.0)
            return 0.0

        transit = arrival_time * (self._clock_rate / 1000.0) - self._timestamp
        d = abs(transit - self._transit)
        self._transit = transit
        self._jitter += (d - self._jitter) / 16.0

        return self._jitter

    def get_stats(self) -> dict:
        """Get session statistics."""
        return {
            'ssrc': self._ssrc,
            'packet_count': self._packet_count,
            'octet_count': self._octet_count,
            'sequence': self._sequence,
            'timestamp': self._timestamp,
            'jitter': self._jitter
        }

    def reset(self) -> None:
        """Reset session."""
        self._sequence = random.randint(0, 0xFFFF)
        self._timestamp = random.randint(0, 0xFFFFFFFF)
        self._packet_count = 0
        self._octet_count = 0
        self._jitter = 0.0
        self._transit = 0
        self._last_rtp_time = 0


def create_rtp_session(
    ssrc: Optional[int] = None,
    sequence: int = 0,
    timestamp: int = 0,
    payload_type: int = 8
) -> RtpSession:
    """Create RTP session."""
    return RtpSession(ssrc, sequence, timestamp, payload_type)
