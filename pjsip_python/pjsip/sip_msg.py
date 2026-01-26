"""
pjsip/sip_msg.h - SIP Message Parsing and Building

SIP message parsing and construction utilities including:
- Message parsing from bytes/string
- Header manipulation
- Request/Response building
"""

import re
import random
import hashlib
import time
from typing import Optional, Dict, List, Any, Tuple, Union
from enum import IntEnum, Enum
from dataclasses import dataclass, field
from collections import OrderedDict

from ..pjlib.sock import get_local_hostname


class SipMethod(Enum):
    """SIP methods."""
    INVITE = "INVITE"
    ACK = "ACK"
    BYE = "BYE"
    CANCEL = "CANCEL"
    REGISTER = "REGISTER"
    OPTIONS = "OPTIONS"
    SUBSCRIBE = "SUBSCRIBE"
    NOTIFY = "NOTIFY"
    REFER = "REFER"
    INFO = "INFO"
    MESSAGE = "MESSAGE"
    UPDATE = "UPDATE"
    PRACK = "PRACK"


class SipStatusCode(IntEnum):
    """SIP status codes."""
    TRYING = 100
    RINGING = 180
    CALL_IS_BEING_FORWARDED = 181
    QUEUED = 182
    PROGRESS = 183
    OK = 200
    ACCEPTED = 202
    MULTIPLE_CHOICES = 300
    MOVED_PERMANENTLY = 301
    MOVED_TEMPORARILY = 302
    SEE_OTHER = 303
    NOT_MODIFIED = 304
    USE_PROXY = 305
    ALTERNATIVE_SERVICE = 380
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    PAYMENT_REQUIRED = 402
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    NOT_ACCEPTABLE = 406
    PROXY_AUTHENTICATION_REQUIRED = 407
    REQUEST_TIMEOUT = 408
    GONE = 410
    LENGTH_REQUIRED = 411
    CONDITIONAL_REQUEST_FAILED = 412
    TOO_MANY_HOPS = 421
    AMBIGUOUS = 423
    BUSY_HERE = 486
    REQUEST_TERMINATED = 487
    NOT_ACCEPTABLE_HERE = 488
    BAD_EVENT = 489
    REQUEST_PENDING = 491
    UNDECIPHERABLE = 493
    SERVER_INTERNAL_ERROR = 500
    NOT_IMPLEMENTED = 501
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    SERVER_TIMEOUT = 504
    VERSION_NOT_SUPPORTED = 505
    MESSAGE_TOO_LARGE = 513


SIP_METHODS = {m.value: m for m in SipMethod}


@dataclass
class SipHeader:
    """SIP header field."""
    name: str
    value: str
    compact: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.name}: {self.value}"

    def to_bytes(self) -> bytes:
        return f"{self.name}: {self.value}\r\n".encode()


@dataclass
class SipViaHeader:
    """SIP Via header value."""
    protocol: str = "SIP/2.0"
    transport: str = "UDP"
    host: str = "127.0.0.1"
    port: int = 0
    branch: Optional[str] = None
    received: Optional[str] = None
    rport: Optional[int] = None
    ttl: Optional[int] = None
    maddr: Optional[str] = None
    hidden: bool = False

    @classmethod
    def parse(cls, value: str) -> 'SipViaHeader':
        """Parse Via header value."""
        via = cls()
        parts = value.split(';')

        protocol_parts = parts[0].strip().split('/')
        if len(protocol_parts) >= 3:
            via.protocol = f"{protocol_parts[0]}/{protocol_parts[1]}/{protocol_parts[2]}"
            if len(protocol_parts) > 3:
                via.transport = protocol_parts[3]
        else:
            via.protocol = parts[0].strip()

        addr_part = parts[0].strip().split()[-1] if parts[0].strip() else ""
        if ':' in addr_part:
            host, port = addr_part.rsplit(':', 1)
            try:
                via.port = int(port)
            except ValueError:
                via.port = 0
            via.host = host
        elif addr_part:
            via.host = addr_part

        for part in parts[1:]:
            part = part.strip()
            if '=' in part:
                key, val = part.split('=', 1)
                key = key.lower()
                val = val.strip()
                if key == 'branch':
                    via.branch = val
                elif key == 'received':
                    via.received = val
                elif key == 'rport':
                    via.rport = int(val) if val else None
                elif key == 'ttl':
                    via.ttl = int(val)
                elif key == 'maddr':
                    via.maddr = val
                elif key == 'hidden':
                    via.hidden = True

        return via

    def build(self, include_branch: bool = True) -> str:
        """Build Via header value."""
        result = f"SIP/2.0/{self.transport} {self.host}"
        if self.port > 0:
            result += f":{self.port}"

        if self.hidden:
            result += ";hidden"

        if self.branch and include_branch:
            result += f";branch={self.branch}"

        if self.received:
            result += f";received={self.received}"

        if self.rport is not None:
            result += f";rport={self.rport}"

        if self.ttl is not None:
            result += f";ttl={self.ttl}"

        if self.maddr:
            result += f";maddr={self.maddr}"

        return result


@dataclass
class SipFromHeader:
    """SIP From header value."""
    uri: str = ""
    display_name: Optional[str] = None
    tag: Optional[str] = None

    @classmethod
    def parse(cls, value: str) -> 'SipFromHeader':
        """Parse From header value."""
        from_hdr = cls()

        if '<' in value:
            match = re.match(r'([^<]*)<([^>]*)>', value)
            if match:
                from_hdr.display_name = match.group(1).strip().strip('"')
                from_hdr.uri = match.group(2).strip()
        else:
            parts = value.split(';')
            from_hdr.uri = parts[0].strip()
            if len(parts) > 1:
                for part in parts[1:]:
                    if part.strip().startswith('tag='):
                        from_hdr.tag = part.strip()[4:]

        return from_hdr

    def build(self) -> str:
        """Build From header value."""
        result = ""
        if self.display_name:
            result = f'"{self.display_name}" '

        result += f"<{self.uri}>"

        if self.tag:
            result += f";tag={self.tag}"

        return result


@dataclass
class SipToHeader:
    """SIP To header value."""
    uri: str = ""
    display_name: Optional[str] = None
    tag: Optional[str] = None

    @classmethod
    def parse(cls, value: str) -> 'SipToHeader':
        """Parse To header value."""
        to_hdr = cls()

        if '<' in value:
            match = re.match(r'([^<]*)<([^>]*)>', value)
            if match:
                to_hdr.display_name = match.group(1).strip().strip('"')
                to_hdr.uri = match.group(2).strip()
        else:
            parts = value.split(';')
            to_hdr.uri = parts[0].strip()
            if len(parts) > 1:
                for part in parts[1:]:
                    if part.strip().startswith('tag='):
                        to_hdr.tag = part.strip()[4:]

        return to_hdr

    def build(self) -> str:
        """Build To header value."""
        result = ""
        if self.display_name:
            result = f'"{self.display_name}" '

        result += f"<{self.uri}>"

        if self.tag:
            result += f";tag={self.tag}"

        return result


@dataclass
class SipContactHeader:
    """SIP Contact header value."""
    uri: str = ""
    display_name: Optional[str] = None
    expires: Optional[int] = None
    q: Optional[float] = None
    pub_gruu: Optional[str] = None
    temp_gruu: Optional[str] = None

    @classmethod
    def parse(cls, value: str) -> 'SipContactHeader':
        """Parse Contact header value."""
        contact = cls()

        if '<' in value:
            match = re.match(r'([^<]*)<([^>]*)>', value)
            if match:
                contact.display_name = match.group(1).strip().strip('"')
                contact.uri = match.group(2).strip()
        else:
            parts = value.split(';')
            contact.uri = parts[0].strip()

        for part in parts[1:]:
            part = part.strip()
            if '=' in part:
                key, val = part.split('=', 1)
                key = key.lower().strip()
                val = val.strip().strip('"')
                if key == 'expires':
                    try:
                        contact.expires = int(val)
                    except ValueError:
                        pass
                elif key == 'q':
                    try:
                        contact.q = float(val)
                    except ValueError:
                        pass
                elif key == 'pub-gruu':
                    contact.pub_gruu = val
                elif key == 'temp-gruu':
                    contact.temp_gruu = val

        return contact

    def build(self) -> str:
        """Build Contact header value."""
        result = ""
        if self.display_name:
            result = f'"{self.display_name}" '

        result += f"<{self.uri}>"

        if self.q is not None:
            result += f";q={self.q}"

        if self.expires is not None:
            result += f";expires={self.expires}"

        if self.pub_gruu:
            result += f";pub-gruu={self.pub_gruu}"

        if self.temp_gruu:
            result += f";temp-gruu={self.temp_gruu}"

        return result


class SipMessage:
    """
    SIP message representation.

    Supports both requests and responses with full
    header manipulation capabilities.
    """

    def __init__(self):
        self._type: str = ""
        self._method: Optional[SipMethod] = None
        self._method_str: str = ""
        self._status_code: int = 0
        self._reason: str = ""
        self._uri: str = ""
        self._version: str = "SIP/2.0"

        self._headers: OrderedDict[str, List[SipHeader]] = OrderedDict()
        self._body: bytes = b""
        self._body_str: str = ""

    @property
    def is_request(self) -> bool:
        """Check if message is a request."""
        return self._type == "request"

    @property
    def is_response(self) -> bool:
        """Check if message is a response."""
        return self._type == "response"

    @property
    def method(self) -> Optional[SipMethod]:
        """Get method (for requests)."""
        return self._method

    @method.setter
    def method(self, value: Union[SipMethod, str]) -> None:
        """Set method."""
        if isinstance(value, SipMethod):
            self._method = value
            self._method_str = value.value
        else:
            self._method = SIP_METHODS.get(value)
            self._method_str = value

    @property
    def method_str(self) -> str:
        """Get method as string."""
        return self._method_str

    @property
    def status_code(self) -> int:
        """Get status code (for responses)."""
        return self._status_code

    @status_code.setter
    def status_code(self, value: int) -> None:
        """Set status code."""
        self._status_code = value

    @property
    def reason(self) -> str:
        """Get reason phrase (for responses)."""
        return self._reason

    @reason.setter
    def reason(self, value: str) -> None:
        """Set reason phrase."""
        self._reason = value

    @property
    def uri(self) -> str:
        """Get request URI (for requests)."""
        return self._uri

    @uri.setter
    def uri(self, value: str) -> None:
        """Set request URI."""
        self._uri = value

    @property
    def version(self) -> str:
        """Get SIP version."""
        return self._version

    @property
    def body(self) -> bytes:
        """Get message body as bytes."""
        return self._body

    @body.setter
    def body(self, value: Union[bytes, str]) -> None:
        """Set message body."""
        if isinstance(value, str):
            self._body = value.encode('utf-8')
            self._body_str = value
        else:
            self._body = value
            self._body_str = value.decode('utf-8', errors='replace')

    @property
    def body_str(self) -> str:
        """Get message body as string."""
        return self._body_str

    def get_header(self, name: str) -> Optional[SipHeader]:
        """Get first header value by name."""
        name_lower = name.lower()
        headers = self._headers.get(name_lower, [])
        return headers[0] if headers else None

    def get_headers(self, name: str) -> List[SipHeader]:
        """Get all header values by name."""
        return self._headers.get(name.lower(), [])

    def set_header(self, name: str, value: str, replace: bool = True) -> SipHeader:
        """
        Set a header value.

        Args:
            name: Header name.
            value: Header value.
            replace: If True, remove existing headers with same name.

        Returns:
            SipHeader instance.
        """
        header = SipHeader(name=name, value=value)
        name_lower = name.lower()

        if replace or name_lower not in self._headers:
            self._headers[name_lower] = []

        self._headers[name_lower].append(header)
        return header

    def add_header(self, name: str, value: str) -> SipHeader:
        """Add a header value (allows duplicates)."""
        return self.set_header(name, value, replace=False)

    def remove_header(self, name: str) -> bool:
        """
        Remove all headers with given name.

        Returns:
            True if headers were removed.
        """
        name_lower = name.lower()
        if name_lower in self._headers:
            del self._headers[name_lower]
            return True
        return False

    def has_header(self, name: str) -> bool:
        """Check if header exists."""
        return name.lower() in self._headers

    def get_via(self) -> Optional[SipViaHeader]:
        """Get Via header."""
        via_hdr = self.get_header('Via')
        if via_hdr:
            return SipViaHeader.parse(via_hdr.value)
        return None

    def set_via(self, via: SipViaHeader) -> None:
        """Set Via header."""
        self.set_header('Via', via.build())

    def get_from(self) -> SipFromHeader:
        """Get From header."""
        from_hdr = self.get_header('From')
        if from_hdr:
            return SipFromHeader.parse(from_hdr.value)
        return SipFromHeader()

    def set_from(self, from_hdr: SipFromHeader) -> None:
        """Set From header."""
        self.set_header('From', from_hdr.build())

    def get_to(self) -> SipToHeader:
        """Get To header."""
        to_hdr = self.get_header('To')
        if to_hdr:
            return SipToHeader.parse(to_hdr.value)
        return SipToHeader()

    def set_to(self, to_hdr: SipToHeader) -> None:
        """Set To header."""
        self.set_header('To', to_hdr.build())

    def get_contact(self) -> Optional[SipContactHeader]:
        """Get Contact header."""
        contact_hdr = self.get_header('Contact')
        if contact_hdr:
            return SipContactHeader.parse(contact_hdr.value)
        return None

    def set_contact(self, contact: SipContactHeader) -> None:
        """Set Contact header."""
        self.set_header('Contact', contact.build())

    def get_call_id(self) -> Optional[str]:
        """Get Call-ID header."""
        call_id = self.get_header('Call-ID')
        return call_id.value if call_id else None

    def set_call_id(self, call_id: str) -> None:
        """Set Call-ID header."""
        self.set_header('Call-ID', call_id)

    def get_cseq(self) -> Tuple[int, str]:
        """Get CSeq header (returns (number, method))."""
        cseq = self.get_header('CSeq')
        if cseq:
            parts = cseq.value.strip().split()
            if len(parts) >= 2:
                try:
                    return int(parts[0]), ' '.join(parts[1:])
                except ValueError:
                    pass
        return 0, ""

    def set_cseq(self, seq: int, method: str) -> None:
        """Set CSeq header."""
        self.set_header('CSeq', f"{seq} {method}")

    def get_expires(self) -> Optional[int]:
        """Get Expires header."""
        expires = self.get_header('Expires')
        if expires:
            try:
                return int(expires.value)
            except ValueError:
                pass
        return None

    def set_expires(self, seconds: int) -> None:
        """Set Expires header."""
        self.set_header('Expires', str(seconds))

    def get_content_type(self) -> Optional[str]:
        """Get Content-Type header."""
        ct = self.get_header('Content-Type')
        return ct.value if ct else None

    def set_content_type(self, content_type: str) -> None:
        """Set Content-Type header."""
        self.set_header('Content-Type', content_type)

    def get_content_length(self) -> int:
        """Get Content-Length header."""
        cl = self.get_header('Content-Length')
        if cl:
            try:
                return int(cl.value)
            except ValueError:
                pass
        return 0

    def set_content_length(self, length: int) -> None:
        """Set Content-Length header."""
        self.set_header('Content-Length', str(length))

    def build(self) -> bytes:
        """Build message to bytes."""
        lines = []

        if self.is_request:
            line = f"{self._method_str} {self._uri} {self._version}"
        else:
            line = f"{self._version} {self._status_code} {self._reason}"

        lines.append(line)

        for name, headers in self._headers.items():
            for header in headers:
                if header.compact:
                    lines.append(f"{header.compact}: {header.value}")
                else:
                    lines.append(f"{name}: {header.value}")

        if 'content-length' not in self._headers:
            lines.append(f"Content-Length: {len(self._body)}")
        lines.append("")

        if self._body:
            lines.append(self._body_str)

        return '\r\n'.join(lines).encode('utf-8')

    @classmethod
    def parse(cls, data: Union[bytes, str]) -> Optional['SipMessage']:
        """
        Parse SIP message from bytes/string.

        Args:
            data: Raw SIP message data.

        Returns:
            SipMessage instance or None if parse failed.
        """
        try:
            if isinstance(data, bytes):
                text = data.decode('utf-8', errors='replace')
            else:
                text = data

            lines = text.split('\r\n')

            if not lines:
                return None

            msg = cls()

            first_line = lines[0].strip()
            parts = first_line.split(' ')

            if len(parts) >= 3 and parts[0] == "SIP/2.0":
                msg._type = "response"
                msg._status_code = int(parts[1])
                msg._reason = ' '.join(parts[2:]) if len(parts) > 2 else ""
                msg._version = "SIP/2.0"
            elif len(parts) >= 2:
                msg._type = "request"
                msg._method_str = parts[0]
                msg._method = SIP_METHODS.get(parts[0])
                msg._uri = ' '.join(parts[1:])
                msg._version = "SIP/2.0"
            else:
                return None

            body_start = 0
            for i, line in enumerate(lines[1:], 1):
                line = line.rstrip('\r')
                if not line:
                    body_start = i + 1
                    break

                if ':' in line:
                    name, value = line.split(':', 1)
                    name = name.strip()
                    value = value.strip()

                    compact = None
                    name_lower = name.lower()
                    if name_lower == 'v':
                        compact = 'v'
                        name = 'Via'
                    elif name_lower == 'f':
                        compact = 'f'
                        name = 'From'
                    elif name_lower == 't':
                        compact = 't'
                        name = 'To'
                    elif name_lower == 'i':
                        compact = 'i'
                        name = 'Call-ID'
                    elif name_lower == 'c':
                        compact = 'c'
                        name = 'Content-Type'
                    elif name_lower == 'l':
                        compact = 'l'
                        name = 'Content-Length'
                    elif name_lower == 'm':
                        compact = 'm'
                        name = 'Contact'
                    elif name_lower == 'b':
                        compact = 'b'
                        name = 'Supported'
                    elif name_lower == 'k':
                        compact = 'k'
                        name = 'Allow'

                    header = SipHeader(name=name, value=value, compact=compact)
                    name_lower = name.lower()
                    if name_lower not in msg._headers:
                        msg._headers[name_lower] = []
                    msg._headers[name_lower].append(header)

            if body_start > 0 and body_start < len(lines):
                body_lines = [line.rstrip('\r') for line in lines[body_start:] if line.strip('\r\n')]
                if body_lines:
                    msg._body_str = '\r\n'.join(body_lines)
                    msg._body = msg._body_str.encode('utf-8')

            return msg

        except Exception:
            return None


def create_request(
    method: Union[str, SipMethod],
    uri: str,
    from_uri: str,
    to_uri: str,
    call_id: str,
    cseq: int,
    via: Optional[SipViaHeader] = None,
    contact: Optional[SipContactHeader] = None,
    body: bytes = b"",
    content_type: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None
) -> SipMessage:
    """
    Create a SIP request.

    Args:
        method: SIP method.
        uri: Request URI.
        from_uri: From URI.
        to_uri: To URI.
        call_id: Call-ID.
        cseq: CSeq number.
        via: Via header.
        contact: Contact header.
        body: Message body.
        content_type: Content-Type header.
        extra_headers: Additional headers.

    Returns:
        SipMessage instance.
    """
    msg = SipMessage()
    msg._type = "request"
    msg.method = method
    msg._uri = uri
    msg._version = "SIP/2.0"

    if via:
        msg.set_via(via)
    else:
        branch = generate_branch()
        via_hdr = SipViaHeader(branch=branch)
        msg.set_via(via_hdr)

    from_hdr = SipFromHeader(uri=from_uri)
    msg.set_from(from_hdr)

    to_hdr = SipToHeader(uri=to_uri)
    msg.set_to(to_hdr)

    msg.set_call_id(call_id)
    msg.set_cseq(cseq, method if isinstance(method, str) else method.value)

    if contact:
        msg.set_contact(contact)

    if body:
        msg.body = body
        if content_type:
            msg.set_content_type(content_type)
        msg.set_content_length(len(body))

    if extra_headers:
        for name, value in extra_headers.items():
            msg.set_header(name, value)

    return msg


def create_response(
    status_code: int,
    reason: str,
    request: Optional[SipMessage] = None,
    via: Optional[SipViaHeader] = None,
    contact: Optional[SipContactHeader] = None,
    body: bytes = b"",
    content_type: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None
) -> SipMessage:
    """
    Create a SIP response.

    Args:
        status_code: Status code.
        reason: Reason phrase.
        request: Original request (to copy headers).
        via: Via header from request.
        contact: Contact header.
        body: Message body.
        content_type: Content-Type header.
        extra_headers: Additional headers.

    Returns:
        SipMessage instance.
    """
    msg = SipMessage()
    msg._type = "response"
    msg._status_code = status_code
    msg._reason = reason
    msg._version = "SIP/2.0"

    if request:
        msg.set_call_id(request.get_call_id() or "")

        from_hdr = request.get_from()
        if from_hdr.uri:
            msg.set_from(from_hdr)

        to_hdr = request.get_to()
        msg.set_to(to_hdr)

        if via:
            msg.set_via(via)
        else:
            request_via = request.get_via()
            if request_via:
                msg.set_via(request_via)

        request_cseq, request_method = request.get_cseq()
        if request_cseq > 0:
            msg.set_cseq(request_cseq, request_method)

    if contact:
        msg.set_contact(contact)

    if body:
        msg.body = body
        if content_type:
            msg.set_content_type(content_type)
        msg.set_content_length(len(body))

    if extra_headers:
        for name, value in extra_headers.items():
            msg.set_header(name, value)

    return msg


def generate_branch() -> str:
    """Generate a random branch parameter (RFC 3891)."""
    return f"z9hG4bK{random.randint(1000000000, 9999999999)}"


def generate_call_id() -> str:
    """Generate a random Call-ID."""
    return f"{random.randint(1000000000, 9999999999)}@{get_local_hostname()}"


def generate_tag() -> str:
    """Generate a random tag."""
    return str(random.randint(1000000000, 9999999999))