"""
pjsua/call.py - Call Management

High-level call management with media integration.
"""

import asyncio
import threading
import socket
import time
from typing import Optional, Dict, Any, Tuple, Callable, TYPE_CHECKING
from enum import IntEnum, auto
from dataclasses import dataclass, field

from ..pjsip import (
    SipMessage, SipMethod, SipStatusCode,
    SipViaHeader, SipFromHeader, SipToHeader, SipContactHeader,
    Dialog, DialogState,
    create_request, generate_branch, generate_call_id, generate_tag,
    create_via_header, create_contact_header
)
from ..pjmedia import (
    SdpSession, create_offer, parse_sdp, get_media_info_from_sdp,
    G711Codec
)
from ..pjmedia.stream_pyvoip import (
    MediaStream, MediaStreamConfig
)

if TYPE_CHECKING:
    from .pjsua import Ua


class CallState(IntEnum):
    """Call states."""
    CALLING = auto()
    INCOMING = auto()
    EARLY = auto()
    CONNECTING = auto()
    CONFIRMED = auto()
    DISCONNECTED = auto()


@dataclass
class CallInfo:
    """Call information."""
    state: CallState = CallState.DISCONNECTED
    remote_uri: str = ""
    remote_display: str = ""
    local_uri: str = ""
    call_id: str = ""
    remote_sdp: Optional[str] = None
    local_sdp: Optional[str] = None
    media_state: str = "none"
    media_ip: str = ""
    media_port: int = 0


class Call:
    """
    Active call representation.

    Manages both SIP signaling and media transport.
    """

    def __init__(self):
        self._ua: Optional[Ua] = None
        self._state = CallState.DISCONNECTED
        self._dialog: Optional[Dialog] = None
        self._media_stream: Optional[MediaStream] = None
        self._local_sdp: Optional[SdpSession] = None
        self._remote_sdp: Optional[SdpSession] = None
        self._target_uri: str = ""
        self._local_uri: str = ""
        self._remote_uri: str = ""
        self._call_id: str = ""
        self._from_tag: str = ""
        self._to_tag: Optional[str] = None
        self._cseq: int = 1
        self._local_rtp_port: int = 0
        self._codec: G711Codec = G711Codec(a_law=True)
        self._lock = threading.Lock()
        self._on_state_change: Optional[Callable] = None
        self._on_dtmf: Optional[Callable] = None

    @property
    def state(self) -> CallState:
        """Get call state."""
        return self._state

    @property
    def call_id(self) -> str:
        """Get Call-ID."""
        return self._call_id

    @property
    def is_active(self) -> bool:
        """Check if call is active."""
        return self._state in (CallState.CALLING, CallState.INCOMING, 
                               CallState.EARLY, CallState.CONNECTING, 
                               CallState.CONFIRMED)

    @property
    def remote_uri(self) -> str:
        """Get remote URI."""
        return self._remote_uri

    @property
    def local_uri(self) -> str:
        """Get local URI."""
        return self._local_uri

    async def make(self, ua: 'Ua', target_uri: str, options: Dict = None) -> bool:
        """
        Make outgoing call.

        Args:
            ua: User Agent instance.
            target_uri: Target SIP URI.
            options: Call options.

        Returns:
            True if call initiated successfully.
        """
        from ..pjsip.sip_msg import SipMethod
        from ..pjsip.sip_auth import DigestAuth
        from ..pjsip import create_request, create_via_header

        self._ua = ua
        self._target_uri = target_uri

        acc = ua.enum_accounts()[0] if ua.enum_accounts() else None
        username = acc.config.username if acc and hasattr(acc.config, 'username') else 'user'
        password = acc.config.password if acc and hasattr(acc.config, 'password') else ''
        realm = acc.config.realm if acc and hasattr(acc.config, 'realm') else '*'

        self._local_uri = f"sip:{username}@{ua.local_ip}" if acc else f"sip:user@{ua.local_ip}"

        self._call_id = generate_call_id()
        self._from_tag = generate_tag()
        self._cseq = 1
        self._local_rtp_port = self._allocate_rtp_port()

        self._local_sdp = create_offer(
            ua.local_ip,
            self._local_rtp_port,
            [8],
            {8: "PCMA"}
        )

        self._state = CallState.CALLING
        self._notify_state()

        self._create_media_stream(ua.local_ip)

        via = create_via_header(ua.local_ip, ua.local_port)
        contact_uri = f"sip:{ua.local_ip}:{ua.local_port}"
        contact = create_contact_header(contact_uri)

        request = create_request(
            method=SipMethod.INVITE,
            uri=target_uri,
            from_uri=self._local_uri,
            to_uri=target_uri,
            call_id=self._call_id,
            cseq=self._cseq,
            via=via,
            contact=contact,
            body=self._local_sdp.build().encode() if self._local_sdp else b"",
            content_type="application/sdp"
        )

        response = await self._send_request(ua, request)
        print(f"DEBUG: After _send_request, response.status_code={response.status_code if response else 'None'}")

        if response.status_code == 401:
            print(f"DEBUG: Got 401, handling auth...")
            auth_request = self._handle_auth(response, request, username, password, target_uri, contact_uri)
            print(f"DEBUG: auth_request={auth_request is not None}")
            if auth_request:
                self._cseq += 1
                print(f"DEBUG: Sending authenticated INVITE with CSEQ={self._cseq}...")
                response = await self._send_request(ua, auth_request)
                print(f"DEBUG: After auth _send_request, response.status_code={response.status_code if response else 'None'}")

        if response.status_code in (100, 180):
            if response.status_code == 180:
                self._state = CallState.EARLY
                self._notify_state()
        elif response.status_code == 200:
            self._handle_2xx_response(response)
            await self._send_ack(ua)

        return True

    def _handle_auth(self, response, original_request, username: str, password: str, uri: str, contact_uri: str):
        """Handle 401 authentication challenge for INVITE."""
        from ..pjsip.sip_auth import DigestAuth
        from ..pjsip.sip_util import create_contact_header
        www_auth = response.get_header('WWW-Authenticate')
        if not www_auth:
            return None

        auth_params = DigestAuth.parse_www_authenticate(www_auth.value)
        if not auth_params:
            return None

        print(f"DEBUG: Auth params: {auth_params}")
        realm = auth_params.get('realm', '')
        nonce = auth_params.get('nonce', '')
        qop = auth_params.get('qop', '')
        print(f"DEBUG: Parsed qop: '{qop}'")

        auth_uri = uri
        if auth_uri.startswith('sip:'):
            auth_uri_body = auth_uri[4:]
            if ':' in auth_uri_body:
                host_port = auth_uri_body.rsplit(':', 1)
                if len(host_port) == 2:
                    try:
                        port = int(host_port[1])
                        if port == 5060:
                            auth_uri = f"sip:{host_port[0]}"
                    except ValueError:
                        pass

        nc = 1
        cnonce = DigestAuth.generate_cnonce()

        ha1 = DigestAuth.calc_ha1(username, realm, password)
        ha2 = DigestAuth.calc_ha2('INVITE', auth_uri, qop)

        resp_hash = DigestAuth.calc_response(ha1, nonce, nc, cnonce, qop, ha2)

        auth_header = DigestAuth.build_authorization(
            username=username,
            realm=realm,
            nonce=nonce,
            uri=auth_uri,
            response=resp_hash,
            qop=qop,
            nc=nc,
            cnonce=cnonce
        )
        print(f"DEBUG: Generated auth header: {auth_header}")

        original_via = original_request.get_via()
        if not original_via:
            return None

        from ..pjsip.sip_msg import SipViaHeader
        new_via = SipViaHeader(
            transport=original_via.transport or 'UDP',
            host=original_via.host,
            port=original_via.port,
            branch=original_via.branch
        )

        from ..pjsip import create_request, SipMethod
        contact = create_contact_header(contact_uri)
        request = create_request(
            method=SipMethod.INVITE,
            uri=uri,
            from_uri=self._local_uri,
            to_uri=uri,
            call_id=self._call_id,
            cseq=self._cseq + 1,
            via=new_via,
            contact=contact,
            body=self._local_sdp.build().encode() if self._local_sdp else b"",
            content_type="application/sdp",
            extra_headers={'Authorization': auth_header}
        )

        return request

    async def _send_request(self, ua, request) -> 'SipMessage':
        """Send SIP request and wait for response."""
        from ..pjsip.sip_msg import SipMessage
        if not ua._transport:
            raise RuntimeError("No transport available")

        transport = ua._transport
        data = request.build()
        print(f"DEBUG: Transport type: {type(transport)}")
        print(f"DEBUG: Transport running: {transport._running if transport else 'N/A'}")
        print(f"DEBUG: Transport sock: {transport._sock if transport else 'N/A'}")
        print(f"DEBUG: Sending request to {request.uri}")
        print(f"DEBUG: Data length: {len(data) if data else 0}")
        if data:
            data_str = data.decode('utf-8', errors='replace')
            print(f"DEBUG: Full request ({len(data)} bytes):")
            print(data_str)

        if request.uri.startswith('sip:'):
            uri_body = request.uri[4:]
        else:
            uri_body = request.uri

        if '@' in uri_body:
            uri_body = uri_body.split('@', 1)[1]

        if ':' in uri_body:
            host, port_str = uri_body.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 5060
        else:
            host = uri_body
            port = 5060

        remote_addr = (host, port)
        print(f"DEBUG: Remote addr: {remote_addr}")
        try:
            success = transport.send_raw(data, remote_addr)
            print(f"DEBUG: send_raw result: {success}")
        except Exception as e:
            print(f"DEBUG: send_raw exception: {e}")
            raise
        if not success:
            raise RuntimeError("Failed to send SIP request")

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        original_callback = transport._on_received

        def response_callback(msg: SipMessage, addr):
            print(f"DEBUG: response_callback called with msg.status_code={msg.status_code if msg else 'None'}")
            if msg:
                print(f"DEBUG: Received response: {msg.status_code} {msg.reason}")
                print(f"DEBUG: msg._body_str: {repr(msg._body_str[:100] if msg._body_str else 'None')}")
                print(f"DEBUG: msg.body: {repr(msg.body[:50] if msg.body else 'None')}")
                if msg.status_code == 401:
                    www_auth = msg.get_header('WWW-Authenticate')
                    if www_auth:
                        print(f"DEBUG: WWW-Authenticate: {www_auth.value}")
                if hasattr(msg, 'body') and msg.body:
                    body_str = msg.body.decode() if isinstance(msg.body, bytes) else msg.body
                    print(f"DEBUG: Response body: {body_str[:200]}")
                else:
                    print(f"DEBUG: No response body")
            if msg and not msg.is_request and hasattr(msg, 'status_code'):
                if not future.done():
                    if msg.status_code >= 200 or msg.status_code == 401:
                        print(f"DEBUG: Setting future result for status {msg.status_code}")
                        future.set_result(msg)
            if original_callback:
                original_callback(msg, addr)

        transport.set_on_received(response_callback)

        print(f"DEBUG: Waiting for response...")
        try:
            await asyncio.wait_for(future, timeout=10.0)
            print(f"DEBUG: Got response: {future.result()}")
            return future.result()
        except asyncio.TimeoutError:
            print(f"DEBUG: Timeout waiting for response")
            return request
        finally:
            transport.set_on_received(original_callback)

    def _handle_2xx_response(self, response: 'SipMessage') -> None:
        """Handle 2xx response to INVITE."""
        print(f"DEBUG: _handle_2xx_response called with status={response.status_code}")
        if self._state != CallState.CALLING and self._state != CallState.EARLY:
            print(f"DEBUG: Skipping _handle_2xx_response - state is {self._state}")
            return

        if response.get_header('Contact'):
            contact = response.get_header('Contact').value
            if '<' in contact:
                import re
                match = re.search(r'<([^>]+)>', contact)
                if match:
                    self._remote_target = match.group(1)
            else:
                self._remote_target = contact

        sdp = response.get_header('Content-Type') or response.get_header('content-type')
        print(f"DEBUG: Content-Type header: {sdp}")
        if sdp:
            ct_value = sdp.value if hasattr(sdp, 'value') else str(sdp)
            print(f"DEBUG: Content-Type value: '{ct_value}'")
            if 'application/sdp' in ct_value.lower():
                body_str = response._body_str if hasattr(response, '_body_str') and response._body_str else ""
                print(f"DEBUG: _body_str: '{body_str[:100] if body_str else 'EMPTY'}'")
                if not body_str and response.body:
                    body_str = response.body.decode() if isinstance(response.body, bytes) else response.body
                    print(f"DEBUG: body from response.body: '{body_str[:100]}'")
                if body_str:
                    self._set_remote_sdp(body_str)
            else:
                print(f"DEBUG: Not application/sdp")
        else:
            print(f"DEBUG: No Content-Type header")

        self._state = CallState.CONFIRMED
        self._start_media()
        self._notify_state()

    async def _send_ack(self, ua) -> None:
        """Send ACK for 2xx response."""
        from ..pjsip.sip_msg import SipMethod
        from ..pjsip import create_via_header, create_request

        if not self._remote_target:
            return

        via = create_via_header(ua.local_ip, ua.local_port)

        from ..pjsip.sip_util import create_contact_header
        contact_uri = f"sip:{ua.local_ip}:{ua.local_port}"
        contact = create_contact_header(contact_uri)

        ack = create_request(
            method=SipMethod.ACK,
            uri=self._remote_target,
            from_uri=self._local_uri,
            to_uri=self._target_uri,
            call_id=self._call_id,
            cseq=self._cseq,
            via=via,
            contact=contact
        )

        transport = ua._transport
        if transport and self._remote_target.startswith('sip:'):
            uri_body = self._remote_target[4:]
            if '@' in uri_body:
                uri_body = uri_body.split('@', 1)[1]
            if ':' in uri_body:
                host, port_str = uri_body.rsplit(':', 1)
                try:
                    port = int(port_str)
                except ValueError:
                    port = 5060
            else:
                host = uri_body
                port = 5060

            data = ack.build()
            transport.send_raw(data, (host, port))
            print(f"DEBUG: ACK sent to {host}:{port}")

    async def answer(self, status_code: int = 200) -> bool:
        """
        Answer incoming call.

        Args:
            status_code: Response status code.

        Returns:
            True if answered successfully.
        """
        if self._state != CallState.INCOMING:
            return False

        self._state = CallState.CONNECTING
        self._notify_state()

        self._start_media()
        return True

    async def hangup(self, status_code: int = 200) -> bool:
        """
        Hang up the call.

        Args:
            status_code: Status code for response.

        Returns:
            True if hung up successfully.
        """
        if not self.is_active:
            return False

        if self._media_stream:
            self._media_stream.stop()

        self._state = CallState.DISCONNECTED
        self._notify_state()
        self._cleanup()

        return True

    async def hold(self) -> bool:
        """Put call on hold."""
        if not self.is_active or self._state != CallState.CONFIRMED:
            return False
        return True

    async def unhold(self) -> bool:
        """Resume call from hold."""
        return True

    async def send_dtmf(self, digits: str) -> bool:
        """
        Send DTMF digits (RFC 2833).

        Args:
            digits: DTMF digits to send.

        Returns:
            True if sent successfully.
        """
        if not self.is_active or not self._media_stream:
            return False
        return True

    async def send_audio(self, data: bytes) -> int:
        """
        Send audio data (G.711 format).

        Args:
            data: G.711 encoded audio data.

        Returns:
            Number of bytes sent.
        """
        if not self._media_stream:
            return 0
        return self._media_stream.send_g711(data)

    async def send_audio_pcm(self, pcm_data: bytes) -> int:
        """
        Send PCM audio data (auto-convert to G.711).

        Args:
            pcm_data: 16-bit linear PCM audio data.

        Returns:
            Number of bytes sent.
        """
        if not self._media_stream:
            return 0
        g711_data = self._codec.encode(pcm_data)
        return self._media_stream.send_g711(g711_data)

    def _allocate_rtp_port(self) -> int:
        """Allocate local RTP port."""
        import random
        return random.randint(10000, 20000)

    def _create_media_stream(self, local_ip: str) -> None:
        """Create media stream."""
        config = MediaStreamConfig(
            local_ip=local_ip,
            local_port=self._local_rtp_port,
            remote_ip="0.0.0.0",
            remote_port=0,
            payload_type=8
        )
        self._media_stream = MediaStream(config)

    def _start_media(self) -> None:
        """Start media stream."""
        if self._media_stream:
            self._media_stream.start()
            self._state = CallState.CONFIRMED
            self._notify_state()

    def _set_remote_sdp(self, sdp_text: str) -> None:
        """Set remote SDP."""
        print(f"DEBUG: _set_remote_sdp called with body type: {type(sdp_text)}")
        body_str = sdp_text.decode() if isinstance(sdp_text, bytes) else sdp_text
        print(f"DEBUG: SDP body:\n{body_str[:300]}")
        self._remote_sdp = parse_sdp(body_str)
        if self._remote_sdp:
            ip, port, pt = get_media_info_from_sdp(self._remote_sdp)
            print(f"DEBUG: Extracted from SDP: ip={ip}, port={port}, pt={pt}")
            if ip and port and self._media_stream:
                print(f"DEBUG: Setting remote RTP to {ip}:{port}")
                self._media_stream.set_remote((ip, port))
                print(f"DEBUG: media_stream.remote_addr = {self._media_stream.remote_addr}")

    def _notify_state(self) -> None:
        """Notify state change."""
        if self._on_state_change:
            try:
                self._on_state_change(self, self._state)
            except Exception:
                pass

    def _cleanup(self) -> None:
        """Cleanup call resources."""
        self._media_stream = None
        self._dialog = None
        self._local_sdp = None
        self._remote_sdp = None

    def get_info(self) -> CallInfo:
        """Get call information."""
        return CallInfo(
            state=self._state,
            remote_uri=self._remote_uri,
            local_uri=self._local_uri,
            call_id=self._call_id,
            local_sdp=str(self._local_sdp) if self._local_sdp else None
        )

    def set_on_state_change(self, callback: Callable) -> None:
        """Set callback for state changes."""
        self._on_state_change = callback

    def set_on_dtmf(self, callback: Callable) -> None:
        """Set callback for DTMF events."""
        self._on_dtmf = callback

    def wait_for_state(self, target_state: CallState, timeout: float = 30.0) -> bool:
        """Wait for call to reach target state."""
        start = time.time()
        while self._state != target_state and self.is_active:
            if time.time() - start > timeout:
                return False
            time.sleep(0.1)
        return self._state == target_state


def create_call() -> Call:
    """Create call instance."""
    return Call()
