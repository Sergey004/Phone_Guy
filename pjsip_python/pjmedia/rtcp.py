"""
pjmedia/rtcp.h - RTCP Session

RTCP (RTP Control Protocol) implementation for sender/receiver
statistics reporting.
"""

import struct
import time
import random
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import IntEnum


class RtcpPacketType(IntEnum):
    """RTCP packet type constants."""
    SR = 200
    RR = 201
    SDES = 202
    BYE = 203
    APP = 204


@dataclass
class RtcpSR:
    """RTCP Sender Report."""
    ntp_sec: int = 0
    ntp_frac: int = 0
    rtp_ts: int = 0
    packet_count: int = 0
    octet_count: int = 0


@dataclass
class RtcpRR:
    """RTCP Receiver Report block."""
    ssrc: int = 0
    fraction: int = 0
    lost: int = 0
    last_seq: int = 0
    jitter: int = 0
    lsr: int = 0
    dlsr: int = 0


@dataclass
class RtcpSDES:
    """RTCP Source Description."""
    ssrc: int = 0
    cname: str = ""


class RtcpSession:
    """
    RTCP session for statistics reporting.
    """

    def __init__(self, ssrc: Optional[int] = None):
        self._ssrc = ssrc if ssrc is not None else random.randint(0, 0xFFFFFFFF)
        self._remote_ssrc = 0
        self._packet_count = 0
        self._octet_count = 0
        self._seq = 0
        self._jitter = 0.0
        self._transit = 0
        self._last_sr_time = 0
        self._last_sr_ntp = 0
        self._last_rr_time = 0
        self._send_interval = 5.0

    @property
    def ssrc(self) -> int:
        """Get local SSRC."""
        return self._ssrc

    @property
    def remote_ssrc(self) -> int:
        """Get remote SSRC."""
        return self._remote_ssrc

    def set_remote_ssrc(self, ssrc: int) -> None:
        """Set remote SSRC."""
        self._remote_ssrc = ssrc

    def update(self, rtp_header, arrival_time: float) -> None:
        """Update statistics from received RTP packet."""
        self._packet_count += 1
        self._octet_count += len(rtp_header.payload)

        transit = arrival_time * 8000 - rtp_header.timestamp
        d = abs(transit - self._transit)
        self._transit = transit
        self._jitter += (d - self._jitter) / 16.0

    def handle_sr(self, sr_data: bytes) -> bool:
        """Handle received Sender Report."""
        if len(sr_data) < 20:
            return False

        self._remote_ssrc, self._packet_count, self._octet_count = struct.unpack('!III', sr_data[4:16])
        return True

    def handle_rr(self, rr_data: bytes) -> bool:
        """Handle received Receiver Report."""
        return True

    def create_sr(self) -> bytes:
        """Create Sender Report."""
        now = time.time()
        ntp_sec = int(now)
        ntp_frac = int((now - ntp_sec) * 0xFFFFFFFF)

        header = (2 << 24) | (RtcpPacketType.SR << 16) | 7
        ssrc = self._ssrc

        packet = struct.pack('!IIIIIII',
            header,
            ssrc,
            ntp_sec,
            ntp_frac,
            self._octet_count,
            self._packet_count,
            self._octet_count
        )

        packet += struct.pack('!I', self._remote_ssrc)

        return packet

    def create_rr(self) -> bytes:
        """Create Receiver Report."""
        header = (2 << 24) | (RtcpPacketType.RR << 16) | 1
        ssrc = self._ssrc

        fraction = 0
        lost = 0
        last_seq = self._seq

        packet = struct.pack('!III', header, ssrc, self._remote_ssrc)

        packet += struct.pack('!IBBHII',
            fraction,
            lost & 0x00FFFFFF,
            last_seq,
            int(self._jitter),
            0,
            0
        )

        return packet

    def get_stats(self) -> Dict[str, Any]:
        """Get RTCP statistics."""
        return {
            'ssrc': self._ssrc,
            'remote_ssrc': self._remote_ssrc,
            'packet_count': self._packet_count,
            'octet_count': self._octet_count,
            'jitter': self._jitter
        }

    def reset(self) -> None:
        """Reset statistics."""
        self._packet_count = 0
        self._octet_count = 0
        self._jitter = 0.0
        self._transit = 0


def create_rtcp_session(ssrc: Optional[int] = None) -> RtcpSession:
    """Create RTCP session."""
    return RtcpSession(ssrc)
