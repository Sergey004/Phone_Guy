"""
pjsip/sip_uri.h - SIP URI Parsing

SIP URI parsing and manipulation according to RFC 3261.
Supports user@host:port;params?headers format.
"""

import re
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class UriTransport(Enum):
    """SIP URI transport parameter values."""
    UDP = "UDP"
    TCP = "TCP"
    TLS = "TLS"
    SCTP = "SCTP"
    WS = "WS"
    WSS = "WSS"


@dataclass
class SipUri:
    """
    SIP URI representation.

    Parses URIs in the format:
    sip:user@host:port;params?headers

    Attributes:
        scheme: URI scheme (sip, sips, tel)
        user: User part
        password: Password (if present)
        host: Host part
        port: Port number (0 if not specified)
        transport: Transport parameter
        lr: Loose routing parameter
        rport: Received port parameter
        maddr: Multicast address parameter
        ttl: Time-to-live parameter
        user_param: User parameter (phone, ip)
        method_param: Method parameter
        headers: Query headers (dict)
        other_params: Other parameters
    """
    scheme: str = "sip"
    user: str = ""
    password: str = ""
    host: str = ""
    port: int = 0
    transport: Optional[UriTransport] = None
    lr: bool = False
    rport: Optional[int] = None
    maddr: Optional[str] = None
    ttl: Optional[int] = None
    user_param: Optional[str] = None
    method_param: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    other_params: Dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        """Build URI string representation."""
        result = ""

        if self.scheme:
            result += f"{self.scheme}:"

        if self.user or self.password:
            if self.user:
                result += self.user
            if self.password:
                result += f":{self.password}"
            result += "@"

        result += self.host

        if self.port > 0:
            result += f":{self.port}"

        if self.transport:
            result += f";transport={self.transport.value.lower()}"

        if self.lr:
            result += ";lr"

        if self.rport is not None:
            result += f";rport={self.rport}"

        if self.maddr:
            result += f";maddr={self.maddr}"

        if self.ttl is not None:
            result += f";ttl={self.ttl}"

        if self.user_param:
            result += f";user={self.user_param}"

        if self.method_param:
            result += f";method={self.method_param}"

        for key, value in self.other_params.items():
            if value:
                result += f";{key}={value}"
            else:
                result += f";{key}"

        if self.headers:
            query = '&'.join(f"{k}={v}" for k, v in self.headers.items())
            result += f"?{query}"

        return result

    def is_sips(self) -> bool:
        """Check if URI is secure (sips)."""
        return self.scheme == "sips"

    def get_host_port(self) -> Tuple[str, int]:
        """Get host and port as tuple."""
        return (self.host, self.port)

    def get_user_at_host(self) -> str:
        """Get user@host portion."""
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host

    @classmethod
    def parse(cls, uri_str: str) -> 'SipUri':
        """
        Parse a SIP URI string.

        Args:
            uri_str: URI string to parse.

        Returns:
            SipUri instance.
        """
        uri = cls()

        original = uri_str.strip()

        if original.startswith('sips:'):
            uri.scheme = 'sips'
            uri_str = original[5:]
        elif original.startswith('sip:'):
            uri.scheme = 'sip'
            uri_str = original[4:]
        elif original.startswith('tel:'):
            uri.scheme = 'tel'
            uri_str = original[4:]
        else:
            match = re.match(r'^(\w+):(.+)$', original)
            if match:
                uri.scheme = match.group(1)
                uri_str = match.group(2)
            else:
                uri.host = original
                return uri

        if '@' in uri_str:
            user_part, rest = uri_str.rsplit('@', 1)
            if ':' in user_part:
                uri.user, uri.password = user_part.split(':', 1)
            else:
                uri.user = user_part
            uri_str = rest

        if '?' in uri_str:
            uri_str, headers_part = uri_str.split('?', 1)
            for header in headers_part.split('&'):
                if '=' in header:
                    k, v = header.split('=', 1)
                    uri.headers[k.strip()] = v.strip()

        if ';' in uri_str:
            params_part = uri_str.split(';', 1)
            uri_str = params_part[0]
            params = params_part[1] if len(params_part) > 1 else ""

            for param in params.split(';'):
                param = param.strip()
                if not param:
                    continue

                if '=' in param:
                    key, value = param.split('=', 1)
                    key = key.strip().lower()
                    value = value.strip()

                    if key == 'transport':
                        try:
                            uri.transport = UriTransport(value.upper())
                        except ValueError:
                            uri.other_params['transport'] = value
                    elif key == 'lr':
                        uri.lr = True
                    elif key == 'rport':
                        uri.rport = int(value) if value else None
                    elif key == 'maddr':
                        uri.maddr = value
                    elif key == 'ttl':
                        uri.ttl = int(value)
                    elif key == 'user':
                        uri.user_param = value
                    elif key == 'method':
                        uri.method_param = value
                    else:
                        uri.other_params[key] = value
                else:
                    key = param.strip().lower()
                    if key == 'lr':
                        uri.lr = True
                    else:
                        uri.other_params[key] = ""

        if ':' in uri_str and not uri.transport:
            host_part, port_str = uri_str.rsplit(':', 1)
            try:
                uri.port = int(port_str)
                uri.host = host_part
            except ValueError:
                uri.host = uri_str
        else:
            uri.host = uri_str

        return uri

    def clone(self) -> 'SipUri':
        """Create a copy of this URI."""
        new_uri = SipUri(
            scheme=self.scheme,
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            transport=self.transport,
            lr=self.lr,
            rport=self.rport,
            maddr=self.maddr,
            ttl=self.ttl,
            user_param=self.user_param,
            method_param=self.method_param,
            headers=self.headers.copy(),
            other_params=self.other_params.copy()
        )
        return new_uri

    def with_port(self, port: int) -> 'SipUri':
        """Create a copy with a different port."""
        new_uri = self.clone()
        new_uri.port = port
        return new_uri

    def with_transport(self, transport: UriTransport) -> 'SipUri':
        """Create a copy with a different transport."""
        new_uri = self.clone()
        new_uri.transport = transport
        return new_uri


@dataclass
class TelUri:
    """TEL URI representation (RFC 3966)."""
    global_number: str = ""
    local_number: str = ""
    is_global: bool = False
    extension: Optional[str] = None
    context: Optional[str] = None
    phone_context: Optional[str] = None

    def __str__(self) -> str:
        """Build TEL URI string."""
        result = "tel:"

        if self.is_global:
            result += self.global_number
        else:
            result += self.local_number

        if self.extension:
            result += f";ext={self.extension}"

        if self.context:
            result += f";context={self.context}"

        if self.phone_context:
            result += f";phone-context={self.phone_context}"

        return result

    @classmethod
    def parse(cls, uri_str: str) -> 'TelUri':
        """Parse a TEL URI string."""
        uri = cls()

        if uri_str.startswith('tel:'):
            uri_str = uri_str[4:]

        for part in uri_str.split(';'):
            if '=' in part:
                key, value = part.split('=', 1)
                key = key.strip().lower()
                value = value.strip()

                if key == 'ext':
                    uri.extension = value
                elif key == 'context':
                    uri.context = value
                elif key == 'phone-context':
                    uri.phone_context = value
            else:
                if value.startswith('+') or value.replace('-', '').replace(' ', '').isdigit():
                    if value.startswith('+') or len(value) > 8:
                        uri.global_number = value
                        uri.is_global = True
                    else:
                        uri.local_number = value

        return uri


def parse_sip_uri(uri_str: str) -> SipUri:
    """Parse a SIP URI string."""
    return SipUri.parse(uri_str)


def parse_tel_uri(uri_str: str) -> TelUri:
    """Parse a TEL URI string."""
    return TelUri.parse(uri_str)


def create_sip_uri(
    user: str = "",
    host: str = "",
    port: int = 0,
    transport: Optional[UriTransport] = None
) -> SipUri:
    """Create a simple SIP URI."""
    uri = SipUri()
    uri.user = user
    uri.host = host
    uri.port = port
    uri.transport = transport
    return uri


def is_uri_valid(uri_str: str) -> bool:
    """Check if a string is a valid URI format."""
    if not uri_str:
        return False

    if uri_str.startswith('sips:'):
        return True
    if uri_str.startswith('sip:'):
        return True
    if uri_str.startswith('tel:'):
        return True

    match = re.match(r'^[\w.-]+@[\w.-]+$', uri_str)
    return match is not None
