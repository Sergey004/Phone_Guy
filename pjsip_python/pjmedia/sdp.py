"""
pjmedia/sdp.h - SDP Parsing and Negotiation

SDP (Session Description Protocol) parsing and negotiation.
"""

import re
import time
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class SdpMediaType(Enum):
    """SDP media types."""
    AUDIO = "audio"
    VIDEO = "video"
    TEXT = "text"
    APPLICATION = "application"
    MESSAGE = "message"


class SdpProto(Enum):
    """SDP transport protocols."""
    RTP_AVP = "RTP/AVP"
    RTP_SAVP = "RTP/SAVP"
    UDP = "UDP"
    TCP = "TCP"
    TLS = "TLS"


class SdpDirection(Enum):
    """SDP direction attributes."""
    SENDRECV = "sendrecv"
    SENDONLY = "sendonly"
    RECVONLY = "recvonly"
    INACTIVE = "inactive"


@dataclass
class SdpAttribute:
    """SDP attribute."""
    name: str
    value: str = ""

    @classmethod
    def parse(cls, line: str) -> 'SdpAttribute':
        """Parse attribute line."""
        if '=' in line:
            name, value = line.split('=', 1)
            return cls(name=name.strip(), value=value.strip())
        return cls(name=line.strip(), value="")

    def build(self) -> str:
        """Build attribute line."""
        if self.value:
            return f"a={self.name}:{self.value}"
        return f"a={self.name}"


@dataclass
class SdpMedia:
    """SDP media description."""
    media: str = "audio"
    port: int = 0
    proto: str = "RTP/AVP"
    fmt: List[str] = field(default_factory=list)
    title: str = ""
    connection: Optional[str] = None
    bandwidth: List[str] = field(default_factory=list)
    key: Optional[str] = None
    attributes: List[SdpAttribute] = field(default_factory=list)

    @classmethod
    def parse(cls, lines: List[str]) -> 'SdpMedia':
        """Parse media description from SDP lines."""
        media = cls()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or not line.startswith('m='):
                break
            parts = line.split()
            if len(parts) >= 4:
                media.media = parts[0][2:]
                media.port = int(parts[1])
                if '/' in parts[1]:
                    port = parts[1].split('/')
                    media.port = int(port[0])
                media.proto = parts[2]
                media.fmt = parts[3:]
            i += 1

            while i < len(lines):
                line = lines[i].strip()
                if not line or line.startswith('m='):
                    break
                if line.startswith('i=') and not media.title:
                    media.title = line[2:]
                elif line.startswith('c='):
                    media.connection = line[2:]
                elif line.startswith('b='):
                    media.bandwidth.append(line[2:])
                elif line.startswith('k='):
                    media.key = line[2:]
                elif line.startswith('a='):
                    attr = SdpAttribute.parse(line[2:])
                    media.attributes.append(attr)
                i += 1

        return media

    def build(self) -> str:
        """Build media description."""
        lines = []
        line = f"m={self.media} {self.port} {self.proto} " + ' '.join(self.fmt)
        lines.append(line)

        if self.title:
            lines.append(f"i={self.title}")
        if self.connection:
            lines.append(f"c={self.connection}")
        for b in self.bandwidth:
            lines.append(f"b={b}")
        if self.key:
            lines.append(f"k={self.key}")
        for attr in self.attributes:
            lines.append(attr.build())

        return '\r\n'.join(lines)


@dataclass
class SdpSession:
    """SDP session description."""
    version: int = 0
    origin: str = ""
    session_name: str = "-"
    session_info: str = ""
    uri: str = ""
    email: str = ""
    phone: str = ""
    connection: Optional[str] = None
    bandwidth: List[str] = field(default_factory=list)
    timezones: List[str] = field(default_factory=list)
    encryption: Optional[str] = None
    attributes: List[SdpAttribute] = field(default_factory=list)
    medias: List[SdpMedia] = field(default_factory=list)
    timing: str = "0 0"

    @classmethod
    def parse(cls, text: str) -> 'SdpSession':
        """Parse SDP text."""
        sdp = cls()
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            elif line.startswith('v='):
                sdp.version = int(line[2:])
            elif line.startswith('o='):
                sdp.origin = line[2:]
            elif line.startswith('s='):
                sdp.session_name = line[2:]
            elif line.startswith('i='):
                sdp.session_info = line[2:]
            elif line.startswith('u='):
                sdp.uri = line[2:]
            elif line.startswith('e='):
                sdp.email = line[2:]
            elif line.startswith('p='):
                sdp.phone = line[2:]
            elif line.startswith('c='):
                sdp.connection = line[2:]
            elif line.startswith('b='):
                sdp.bandwidth.append(line[2:])
            elif line.startswith('t='):
                sdp.timing = line[2:]
            elif line.startswith('k='):
                sdp.encryption = line[2:]
            elif line.startswith('a='):
                sdp.attributes.append(SdpAttribute.parse(line[2:]))
            elif line.startswith('m='):
                media_lines = [line]
                j = i + 1
                while j < len(lines) and lines[j].strip() and not lines[j].startswith(('v=', 'o=', 's=', 'm=')):
                    media_lines.append(lines[j].strip())
                    j += 1
                sdp.medias.append(SdpMedia.parse(media_lines))
                i = j - 1
            i += 1

        return sdp

    def build(self) -> str:
        """Build SDP text."""
        lines = []
        lines.append(f"v={self.version}")
        lines.append(f"o=- {self.origin}")
        lines.append(f"s={self.session_name}")

        if self.session_info:
            lines.append(f"i={self.session_info}")
        if self.uri:
            lines.append(f"u={self.uri}")
        if self.email:
            lines.append(f"e={self.email}")
        if self.phone:
            lines.append(f"p={self.phone}")
        if self.connection:
            lines.append(f"c={self.connection}")
        for b in self.bandwidth:
            lines.append(f"b={b}")
        lines.append(f"t={self.timing}")
        if self.encryption:
            lines.append(f"k={self.encryption}")
        for attr in self.attributes:
            lines.append(attr.build())
        for media in self.medias:
            lines.append(media.build())

        return '\r\n'.join(lines) + '\r\n'

    def get_media_payload_types(self) -> List[int]:
        """Get list of payload types from media lines."""
        result = []
        for media in self.medias:
            for fmt in media.fmt:
                try:
                    result.append(int(fmt))
                except ValueError:
                    pass
        return result

    def find_media(self, media_type: str) -> Optional[SdpMedia]:
        """Find media by type."""
        for media in self.medias:
            if media.media == media_type:
                return media
        return None

    def get_connection_address(self) -> Tuple[Optional[str], Optional[int]]:
        """Get connection address from session or media."""
        for media in self.medias:
            if media.connection:
                parts = media.connection.split()
                if len(parts) >= 3:
                    host = parts[2]
                    if ':' in host:
                        h, p = host.rsplit(':', 1)
                        return (h, int(p))
                    return (host, 0)
        if self.connection:
            parts = self.connection.split()
            if len(parts) >= 3:
                host = parts[2]
                if ':' in host:
                    h, p = host.rsplit(':', 1)
                    return (h, int(p))
                return (host, 0)
        return (None, None)


def create_offer(
    local_ip: str,
    local_port: int,
    payload_types: List[int],
    codec_names: Dict[int, str],
    sample_rate: int = 8000
) -> SdpSession:
    """Create SDP offer."""
    sdp = SdpSession()
    sdp.version = 0
    sdp.origin = f"{int(time.time())} {int(time.time())} IN IP4 {local_ip}"
    sdp.connection = f"IN IP4 {local_ip}"

    media = SdpMedia()
    media.media = "audio"
    media.port = local_port
    media.proto = "RTP/AVP"
    media.fmt = [str(pt) for pt in payload_types]

    for pt in payload_types:
        codec_name = codec_names.get(pt, "unknown")
        if pt == 8:
            attr = SdpAttribute(name="rtpmap", value=f"{pt} PCMA/8000")
        elif pt == 0:
            attr = SdpAttribute(name="rtpmap", value=f"{pt} PCMU/8000")
        elif pt == 9:
            attr = SdpAttribute(name="rtpmap", value=f"{pt} G722/8000")
        else:
            attr = SdpAttribute(name="rtpmap", value=f"{pt} {codec_name}/{sample_rate}")
        media.attributes.append(attr)

    media.attributes.append(SdpAttribute(name="sendrecv", value=""))

    sdp.medias.append(media)
    return sdp


def parse_sdp(text: str) -> SdpSession:
    """Parse SDP text."""
    return SdpSession.parse(text)


def build_sdp(sdp: SdpSession) -> str:
    """Build SDP text."""
    return sdp.build()


def sdp_negotiate(offer: SdpSession, answer: SdpSession) -> Tuple[SdpSession, bool]:
    """Negotiate SDP (simplified)."""
    if not offer.medias or not answer.medias:
        return answer, False

    answer_medias = []
    for offer_media in offer.medias:
        answer_media = None
        for ans_media in answer.medias:
            if ans_media.media == offer_media.media:
                answer_media = ans_media
                break

        if not answer_media:
            continue

        negotiated_media = SdpMedia()
        negotiated_media.media = offer_media.media
        negotiated_media.port = answer_media.port
        negotiated_media.proto = offer_media.proto

        for fmt in offer_media.fmt:
            if fmt in answer_media.fmt:
                negotiated_media.fmt.append(fmt)

        if not negotiated_media.fmt:
            continue

        for attr in offer_media.attributes:
            if attr.name == "rtpmap":
                pt = attr.value.split()[0]
                if pt in negotiated_media.fmt:
                    negotiated_media.attributes.append(attr)
            elif attr.name in ("sendrecv", "sendonly", "recvonly", "inactive"):
                negotiated_media.attributes.append(attr)

        answer_medias.append(negotiated_media)

    answer.medias = answer_medias
    return answer, len(answer_medias) > 0
