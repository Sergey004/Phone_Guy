"""
pjmedia/codec.h - Codec Framework

Audio codec framework with G.711 and L16 implementations.
"""

from typing import Optional, Tuple, List, Any
from enum import IntEnum
from dataclasses import dataclass


class CodecID(IntEnum):
    """Codec ID constants."""
    PCMA = 8
    PCMU = 0
    L16_441 = 10
    L16_16 = 11
    UNKNOWN = 99


@dataclass
class CodecInfo:
    """Codec information."""
    id: CodecID
    name: str
    sample_rate: int
    channel_count: int
    frame_time: int
    ptime: int
    avg_bitrate: int
    clock_rate: int

    def to_sdp_fmtp(self) -> str:
        """Get SDP fmtp line."""
        return ""


@dataclass  
class CodecParam:
    """Codec parameters."""
    info: CodecInfo
    has_vad: bool = False
    vad: bool = False
    cng: bool = False
    ptime: int = 20
    mode: int = 0


class Codec:
    """Base codec class."""

    @property
    def id(self) -> CodecID:
        """Get codec ID."""
        return CodecID.UNKNOWN

    @property
    def name(self) -> str:
        """Get codec name."""
        return "unknown"

    @property
    def sample_rate(self) -> int:
        """Get sample rate."""
        return 8000

    def get_info(self) -> CodecInfo:
        """Get codec info."""
        return CodecInfo(
            id=self.id,
            name=self.name,
            sample_rate=self.sample_rate,
            channel_count=1,
            frame_time=20,
            ptime=20,
            avg_bitrate=64000,
            clock_rate=self.sample_rate
        )

    def create_param(self) -> CodecParam:
        """Create default codec parameters."""
        return CodecParam(info=self.get_info())

    def encode(self, data: bytes) -> bytes:
        """Encode audio data."""
        return data

    def decode(self, data: bytes) -> bytes:
        """Decode audio data."""
        return data

    def encode_frame(self, data: bytes) -> bytes:
        """Encode one frame."""
        return self.encode(data)

    def decode_frame(self, data: bytes) -> bytes:
        """Decode one frame."""
        return self.decode(data)
class G711Codec(Codec):
    """G.711 codec (A-law and u-law)."""

    PAYLOAD_TYPE_PCMA = 8
    PAYLOAD_TYPE_PCMU = 0

    def __init__(self, a_law: bool = True):
        self._a_law = a_law

    @property
    def id(self) -> CodecID:
        return CodecID.PCMA if self._a_law else CodecID.PCMU

    @property
    def name(self) -> str:
        return "PCMA" if self._a_law else "PCMU"

    def encode(self, data: bytes) -> bytes:
        """Encode 8-bit linear PCM to G.711 (pyVoIP compatible)."""
        import audioop
        data = audioop.bias(data, 1, -128)
        if self._a_law:
            return audioop.lin2alaw(data, 1)
        return audioop.lin2ulaw(data, 1)

    def decode(self, data: bytes) -> bytes:
        """Decode G.711 to 8-bit linear PCM (pyVoIP compatible)."""
        import audioop
        if self._a_law:
            data = audioop.alaw2lin(data, 1)
        else:
            data = audioop.ulaw2lin(data, 1)
        return audioop.bias(data, 1, 128)


class L16Codec(Codec):
    """L16 linear PCM codec."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self._sample_rate = sample_rate
        self._channels = channels

    @property
    def id(self) -> CodecID:
        if self._sample_rate == 44100:
            return CodecID.L16_441
        return CodecID.L16_16

    @property
    def name(self) -> str:
        return f"L16/{self._sample_rate}/{self._channels}"

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def encode(self, data: bytes) -> bytes:
        """L16 passthrough (already linear PCM)."""
        return data

    def decode(self, data: bytes) -> bytes:
        """L16 passthrough."""
        return data


def create_codec(codec_id: CodecID, param: Optional[CodecParam] = None) -> Optional[Codec]:
    """Create a codec by ID."""
    if codec_id == CodecID.PCMA:
        return G711Codec(a_law=True)
    elif codec_id == CodecID.PCMU:
        return G711Codec(a_law=False)
    elif codec_id in (CodecID.L16_16, CodecID.L16_441):
        sample_rate = 16000 if codec_id == CodecID.L16_16 else 44100
        return L16Codec(sample_rate)
    return None


def get_codec_name(codec_id: CodecID) -> str:
    """Get codec name by ID."""
    codec = create_codec(codec_id)
    return codec.name if codec else "unknown"


G711_ALAW = G711Codec(a_law=True)
G711_ULAW = G711Codec(a_law=False)
