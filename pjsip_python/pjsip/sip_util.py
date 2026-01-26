"""
pjsip/sip_util.h - SIP Utilities

Utility functions for SIP message manipulation and
common operations.
"""

import re
import socket
import random
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass

from .sip_msg import (
    SipMessage, SipMethod, SipStatusCode,
    SipViaHeader, SipFromHeader, SipToHeader, SipContactHeader, SipHeader
)
from .sip_uri import SipUri, UriTransport


def get_local_ip(exclude_loopback: bool = True) -> str:
    """Get the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()

        if exclude_loopback and ip.startswith('127.'):
            return get_local_ip(exclude_loopback=False)
        return ip
    except Exception:
        return '127.0.0.1'


def get_local_hostname() -> str:
    """Get the local hostname."""
    return socket.gethostname()


def generate_branch() -> str:
    """Generate a random branch parameter (RFC 3891)."""
    return f"z9hG4bK{random.randint(1000000000, 9999999999)}"


def generate_call_id() -> str:
    """Generate a random Call-ID."""
    return f"{random.randint(1000000000, 9999999999)}@{get_local_hostname()}"


def generate_tag() -> str:
    """Generate a random tag."""
    return str(random.randint(1000000000, 9999999999))


def create_via_header(
    local_addr: str = "127.0.0.1",
    port: int = 5060,
    transport: str = "UDP",
    branch: Optional[str] = None,
    received: Optional[str] = None,
    rport: Optional[int] = None
) -> SipViaHeader:
    """
    Create a Via header.

    Args:
        local_addr: Local IP address.
        port: Local port.
        transport: Transport type (UDP, TCP).
        branch: Branch parameter (generated if None).
        received: Received parameter.
        rport: RPort parameter.

    Returns:
        SipViaHeader instance.
    """
    via = SipViaHeader(
        transport=transport,
        host=local_addr,
        port=port,
        branch=branch or generate_branch()
    )
    via.received = received
    via.rport = rport
    return via


def create_contact_header(
    uri: str,
    display_name: Optional[str] = None,
    expires: Optional[int] = None,
    q: Optional[float] = None
) -> SipContactHeader:
    """
    Create a Contact header.

    Args:
        uri: Contact URI.
        display_name: Optional display name.
        expires: Expires value.
        q: Q value.

    Returns:
        SipContactHeader instance.
    """
    contact = SipContactHeader(uri=uri)
    contact.display_name = display_name
    contact.expires = expires
    contact.q = q
    return contact


def get_remote_hdrs(request: SipMessage) -> Dict[str, str]:
    """
    Get headers from request needed for response.

    Args:
        request: Incoming request.

    Returns:
        Dictionary of header values.
    """
    headers = {}

    via = request.get_via()
    if via:
        headers['via'] = str(via)

    from_hdr = request.get_from()
    if from_hdr.uri:
        headers['from'] = from_hdr.build()

    to_hdr = request.get_to()
    if to_hdr.uri:
        headers['to'] = to_hdr.build()

    call_id = request.get_call_id()
    if call_id:
        headers['call-id'] = call_id

    cseq, method = request.get_cseq()
    if cseq:
        headers['cseq'] = f"{cseq} {method}"

    return headers


def get_request_uri(request: SipMessage) -> SipUri:
    """
    Get the request URI from a request.

    Args:
        request: SIP request.

    Returns:
        SipUri instance.
    """
    if request.uri:
        return SipUri.parse(request.uri)
    return SipUri()


def get_first_line(request: SipMessage) -> str:
    """
    Get the first line of a request or response.

    Args:
        request: SIP message.

    Returns:
        First line string.
    """
    if request.is_request:
        return f"{request.method_str} {request.uri} SIP/2.0"
    else:
        return f"SIP/2.0 {request.status_code} {request.reason}"


def get_header_value(request: SipMessage, name: str, default: str = "") -> str:
    """
    Get header value with default.

    Args:
        request: SIP message.
        name: Header name.
        default: Default value if not found.

    Returns:
        Header value or default.
    """
    header = request.get_header(name)
    return header.value if header else default


def set_header_value(request: SipMessage, name: str, value: str) -> None:
    """
    Set header value.

    Args:
        request: SIP message.
        name: Header name.
        value: New value.
    """
    request.set_header(name, value, replace=True)


def remove_header(request: SipMessage, name: str) -> bool:
    """
    Remove header from message.

    Args:
        request: SIP message.
        name: Header name.

    Returns:
        True if header was removed.
    """
    return request.remove_header(name)


def add_header(request: SipMessage, name: str, value: str) -> SipHeader:
    """
    Add header to message (allows duplicates).

    Args:
        request: SIP message.
        name: Header name.
        value: Header value.

    Returns:
        SipHeader instance.
    """
    return request.add_header(name, value)


def create_via_from_transport(transport_addr: Tuple[str, int]) -> SipViaHeader:
    """
    Create Via header from transport address.

    Args:
        transport_addr: Transport (host, port).

    Returns:
        SipViaHeader instance.
    """
    return create_via_header(
        local_addr=transport_addr[0],
        port=transport_addr[1]
    )


def get_sip_uri_for_domain(domain: str, port: int = 5060) -> str:
    """
    Get SIP URI for a domain.

    Args:
        domain: Domain name or IP.
        port: Port number.

    Returns:
        SIP URI string.
    """
    if port == 5060:
        return f"sip:{domain}"
    return f"sip:{domain}:{port}"


def get_sips_uri_for_domain(domain: str, port: int = 5061) -> str:
    """
    Get SIPS URI for a domain.

    Args:
        domain: Domain name or IP.
        port: Port number.

    Returns:
        SIPS URI string.
    """
    if port == 5061:
        return f"sips:{domain}"
    return f"sips:{domain}:{port}"


def is_method_supported(request: SipMessage, method: str) -> bool:
    """
    Check if a method is supported (from Allow header).

    Args:
        request: SIP request.
        method: Method name to check.

    Returns:
        True if method is in Allow header.
    """
    allow = request.get_header('Allow')
    if allow:
        methods = [m.strip() for m in allow.value.split(',')]
        return method.upper() in methods
    return False


def is_uri_secure(uri: SipUri) -> bool:
    """
    Check if URI is secure (sips).

    Args:
        uri: SIP URI.

    Returns:
        True if URI uses sips scheme.
    """
    return uri.scheme == "sips"


def extract_media_info(sdp_body: str) -> Optional[Tuple[str, int]]:
    """
    Extract media IP and port from SDP body.

    Args:
        sdp_body: SDP body string.

    Returns:
        Tuple of (media_ip, media_port) or None.
    """
    lines = sdp_body.split('\r\n')
    connection = None
    media_port = None

    for line in lines:
        if line.startswith('c='):
            parts = line.split(' ')
            if len(parts) >= 3:
                connection = parts[2]
        elif line.startswith('m='):
            parts = line.split(' ')
            if len(parts) >= 2:
                try:
                    media_port = int(parts[1])
                except ValueError:
                    pass

    if connection and media_port:
        return (connection, media_port)
    return None


def create_failure_response(
    request: SipMessage,
    status_code: int,
    reason: str,
    extra_headers: Optional[Dict[str, str]] = None
) -> SipMessage:
    """
    Create a failure response.

    Args:
        request: Original request.
        status_code: Status code.
        reason: Reason phrase.
        extra_headers: Additional headers.

    Returns:
        SipResponse instance.
    """
    from .sip_msg import create_response

    via = request.get_via()
    contact = request.get_contact()

    return create_response(
        status_code=status_code,
        reason=reason,
        request=request,
        via=via,
        contact=contact,
        extra_headers=extra_headers
    )


def create_success_response(
    request: SipMessage,
    status_code: int = 200,
    reason: str = "OK",
    extra_headers: Optional[Dict[str, str]] = None
) -> SipMessage:
    """
    Create a success response.

    Args:
        request: Original request.
        status_code: Status code.
        reason: Reason phrase.
        extra_headers: Additional headers.

    Returns:
        SipResponse instance.
    """
    from .sip_msg import create_response

    via = request.get_via()
    contact = request.get_contact()

    return create_response(
        status_code=status_code,
        reason=reason,
        request=request,
        via=via,
        contact=contact,
        extra_headers=extra_headers
    )


def create_redirect_response(
    request: SipMessage,
    contacts: List[str]
) -> SipMessage:
    """
    Create a redirect response.

    Args:
        request: Original request.
        contacts: List of contact URIs.

    Returns:
        SipResponse instance.
    """
    from .sip_msg import create_response

    via = request.get_via()

    extra_headers = {}
    for contact in contacts:
        extra_headers['Contact'] = contact

    return create_response(
        status_code=302,
        reason="Moved Temporarily",
        request=request,
        via=via,
        extra_headers=extra_headers
    )


@dataclass
class MsgInfo:
    """Extracted message information for logging."""
    type: str
    method: str = ""
    status_code: int = 0
    call_id: str = ""
    from_tag: str = ""
    to_tag: str = ""
    cseq: str = ""
    via_branch: str = ""

    @classmethod
    def from_msg(cls, msg: SipMessage) -> 'MsgInfo':
        """Create from message."""
        info = cls(type="request" if msg.is_request else "response")

        if msg.is_request:
            info.method = msg.method_str
        else:
            info.status_code = msg.status_code

        info.call_id = msg.get_call_id() or ""
        info.from_tag = msg.get_from().tag or ""
        info.to_tag = msg.get_to().tag or ""
        info.cseq = str(msg.get_cseq()[0])

        via = msg.get_via()
        if via:
            info.via_branch = via.branch or ""

        return info


def log_msg(msg: SipMessage, direction: str = "->") -> str:
    """
    Format message for logging.

    Args:
        msg: SIP message.
        direction: Direction indicator.

    Returns:
        Log string.
    """
    info = MsgInfo.from_msg(msg)

    if msg.is_request:
        return f"{direction} {info.method} {info.call_id} (From-tag={info.from_tag})"
    else:
        return f"{direction} {info.status_code} {info.call_id} (From-tag={info.from_tag}, To-tag={info.to_tag})"
