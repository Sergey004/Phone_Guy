"""
pjsua/acc.py - Account Management

Account and registration management.
"""

import asyncio
import threading
import time
from typing import Optional, Dict, Any, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import IntEnum, auto

from ..pjsip import (
    SipMessage,
    SipMethod,
    SipStatusCode,
    SipViaHeader,
    SipFromHeader,
    SipToHeader,
    SipContactHeader,
    Dialog,
    DialogState,
    Transaction,
    TransactionState,
    create_request,
    create_response,
    parse_sip_message,
    generate_branch,
    generate_call_id,
    generate_tag,
    DigestAuth,
    generate_auth_header,
    parse_sip_message as parse_msg,
    create_via_header,
    create_contact_header,
)
from ..pjmedia import SdpSession, create_offer

if TYPE_CHECKING:
    from .pjsua import Ua


class RegState(IntEnum):
    """Registration states."""

    UNREGISTERED = 0
    REGISTERING = auto()
    REGISTERED = auto()
    UNREGISTERING = auto()
    FAILED = auto()


@dataclass
class AccountInfo:
    """Account information."""

    uri: str = ""
    registrar_uri: str = ""
    realm: str = ""
    username: str = ""
    display_name: str = ""
    reg_state: RegState = RegState.UNREGISTERED
    reg_expires: int = 0
    reg_contact: str = ""


class Account:
    """
    SIP Account for registration and presence.
    """

    def __init__(self):
        self._ua: Optional["Ua"] = None
        self.config: Optional[AccountConfig] = None
        self._info = AccountInfo()
        self._reg_state = RegState.UNREGISTERED
        self._reg_expires: int = 3600
        self._reg_timer: Optional[threading.Timer] = None
        self._cseq: int = 1
        self._call_id: str = ""
        self._from_tag: str = ""
        self._to_tag: Optional[str] = None
        self._contact: Optional[str] = None
        self._dialog: Optional[Dialog] = None
        self._lock = threading.Lock()
        self._on_reg_state: Optional[Callable] = None

        self._response_queue: asyncio.Queue = asyncio.Queue()

    @property
    def uri(self) -> str:
        """Get account URI."""
        return self.config.id if self.config else ""

    @property
    def registrar_uri(self) -> str:
        """Get registrar URI."""
        return self.config.reg_uri if self.config else ""

    @property
    def reg_state(self) -> RegState:
        """Get registration state."""
        return self._reg_state

    @property
    def info(self) -> AccountInfo:
        """Get account info."""
        self._info.uri = self.uri
        self._info.registrar_uri = self.registrar_uri
        self._info.reg_state = self._reg_state
        self._info.reg_expires = self._reg_expires
        return self._info

    async def create(self, ua: "Ua", config: Dict[str, Any]) -> bool:
        """
        Create account from configuration.

        Args:
            ua: User Agent instance.
            config: Account configuration dict.

        Returns:
            True if created successfully.
        """
        self.config = AccountConfig(**config) if isinstance(config, dict) else config
        self._ua = ua

        self._call_id = generate_call_id()
        self._from_tag = generate_tag()
        self._cseq = 1

        if not self.config.id:
            username = self.config.username or "user"
            host = ua.local_ip
            port = ua.local_port
            self.config.id = (
                f"sip:{username}@{host}:{port}"
                if port != 5060
                else f"sip:{username}@{host}"
            )

        if not self.config.reg_uri:
            domain = getattr(self.config, "realm", "") or ua.local_ip
            self.config.reg_uri = f"sip:{domain}"

        if not self.config.contact:
            self._contact = f"sip:{ua.local_ip}"
        else:
            self._contact = self.config.contact

        return True

    async def register(self) -> bool:
        """
        Register account with registrar.

        Returns:
            True if registration successful.
        """
        if not self._ua:
            return False

        self._reg_state = RegState.REGISTERING
        self._notify_reg_state()

        real_local_ip = self._ua.local_ip or "127.0.0.1"
        real_local_port = self._ua.local_port or 5060

        if self._ua._transport and self._ua._transport.local_addr:
            bound_ip, bound_port = self._ua._transport.local_addr
            if bound_ip and bound_ip not in ("", "0.0.0.0"):
                real_local_ip = bound_ip
            if bound_port:
                real_local_port = bound_port

        via = create_via_header(real_local_ip, real_local_port)

        contact_uri = (
            self._contact or f"sip:{real_local_ip}:{real_local_port}"
            if real_local_port != 5060
            else f"sip:{real_local_ip}"
        )
        contact = SipContactHeader(uri=contact_uri)

        request = create_request(
            method=SipMethod.REGISTER,
            uri=self.registrar_uri,
            from_uri=self.uri,
            to_uri=self.uri,
            call_id=self._call_id,
            cseq=self._cseq,
            via=via,
            contact=contact,
        )

        try:
            response = await self._send_request(request)

            if response.status_code == 401:
                new_request = self._handle_auth(response, request)
                if not new_request:
                    self._reg_state = RegState.FAILED
                    self._notify_reg_state()
                    return False

                response = await self._send_request(new_request)

            if response.status_code == 200:
                self._reg_state = RegState.REGISTERED
                expires = response.get_expires()
                if expires:
                    self._reg_expires = expires
                    self._schedule_reregister(expires - 10)
                self._notify_reg_state()
                return True
            else:
                self._reg_state = RegState.FAILED

        except Exception:
            self._reg_state = RegState.FAILED

        self._notify_reg_state()
        return False

    def _handle_auth(
        self, response: SipMessage, original_request: SipMessage
    ) -> Optional[SipMessage]:
        """Handle 401 authentication challenge."""
        www_auth = response.get_header("WWW-Authenticate")
        if not www_auth:
            return None

        auth_params = DigestAuth.parse_www_authenticate(www_auth.value)
        if not auth_params:
            return None

        realm = auth_params.get("realm", "")
        nonce = auth_params.get("nonce", "")
        qop = auth_params.get("qop", "")

        username = self.config.username if self.config else ""
        password = self.config.password if self.config else ""

        auth_uri = self.registrar_uri
        if auth_uri.startswith("sip:"):
            auth_uri_body = auth_uri[4:]
            if ":" in auth_uri_body:
                host_port = auth_uri_body.rsplit(":", 1)
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
        ha2 = DigestAuth.calc_ha2("REGISTER", auth_uri, qop)

        resp_hash = DigestAuth.calc_response(ha1, nonce, nc, cnonce, qop, ha2)

        auth_header = DigestAuth.build_authorization(
            username=username,
            realm=realm,
            nonce=nonce,
            uri=auth_uri,
            response=resp_hash,
            qop=qop,
            nc=nc,
            cnonce=cnonce,
        )

        original_via = original_request.get_via()
        if not original_via:
            return None

        new_via = SipViaHeader(
            transport=original_via.transport or "UDP",
            host=original_via.host,
            port=original_via.port,
            branch=original_via.branch,
        )

        request = create_request(
            method=SipMethod.REGISTER,
            uri=self.registrar_uri,
            from_uri=self.uri,
            to_uri=self.uri,
            call_id=self._call_id,
            cseq=self._cseq + 1,
            via=new_via,
            extra_headers={"Authorization": auth_header},
        )

        self._cseq += 1
        return request

    async def unregister(self) -> bool:
        """
        Unregister account.

        Returns:
            True if unregistered successfully.
        """
        if self._reg_state != RegState.REGISTERED:
            return True

        self._cancel_reg_timer()
        self._reg_state = RegState.UNREGISTERING
        self._notify_reg_state()

        local_ip = "127.0.0.1"
        local_port = 5060
        if self._ua:
            local_ip = self._ua.local_ip or "127.0.0.1"
            local_port = self._ua.local_port or 5060
        via = create_via_header(local_ip, local_port)

        request = create_request(
            method=SipMethod.REGISTER,
            uri=self.registrar_uri,
            from_uri=self.uri,
            to_uri=self.uri,
            call_id=self._call_id,
            cseq=self._cseq + 1,
            via=via,
            extra_headers={"Expires": "0"},
        )

        self._cseq += 1

        try:
            response = await self._send_request(request)
            success = response.status_code == 200
        except Exception:
            success = False

        self._reg_state = RegState.UNREGISTERED if success else RegState.FAILED
        self._notify_reg_state()
        return success

    async def _send_request(self, request: SipMessage) -> SipMessage:
        """Send request via transport and wait for response."""
        if not self._ua or not self._ua._transport:
            raise RuntimeError("No transport available")

        transport = self._ua._transport
        data = request.build()

        reg_uri = self.config.reg_uri if self.config else ""
        if not reg_uri:
            raise RuntimeError("No registrar URI configured")

        if reg_uri.startswith("sip:"):
            uri_body = reg_uri[4:]
        else:
            uri_body = reg_uri

        if ":" in uri_body:
            host, port_str = uri_body.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 5060
        else:
            host = uri_body
            port = 5060

        remote_addr = (host, port)
        success = transport.send_raw(data, remote_addr)
        if not success:
            raise RuntimeError("Failed to send SIP request")

        loop = asyncio.get_event_loop()
        future = loop.create_future()

        original_callback = transport._on_received

        def response_callback(msg: SipMessage, addr):
            if msg and not msg.is_request and hasattr(msg, "status_code"):
                if not future.done() and (
                    msg.status_code >= 200 or msg.status_code == 401
                ):
                    future.set_result(msg)
            if original_callback:
                original_callback(msg, addr)

        transport.set_on_received(response_callback)

        try:
            await asyncio.wait_for(future, timeout=5.0)
            return future.result()
        except asyncio.TimeoutError:
            return request
        finally:
            transport.set_on_received(original_callback)

    def _schedule_reregister(self, delay: int) -> None:
        """Schedule re-registration."""
        self._cancel_reg_timer()
        self._reg_timer = threading.Timer(delay, lambda: asyncio.run(self.register()))
        self._reg_timer.start()

    def _cancel_reg_timer(self) -> None:
        """Cancel registration timer."""
        if self._reg_timer:
            self._reg_timer.cancel()
            self._reg_timer = None

    def _notify_reg_state(self) -> None:
        """Notify registration state change."""
        if self._on_reg_state:
            try:
                self._on_reg_state(self, self._reg_state)
            except Exception:
                pass

    async def set_presence(self, status: str = "online", note: str = "") -> bool:
        """
        Set presence status.

        Args:
            status: Presence status (online, away, busy, etc.).
            note: Optional status note.

        Returns:
            True if set successfully.
        """
        return True

    def set_on_reg_state(self, callback: Callable) -> None:
        """Set callback for registration state changes."""
        self._on_reg_state = callback

    def destroy(self) -> None:
        """Destroy account and cleanup."""
        self._cancel_reg_timer()


@dataclass
class AccountConfig:
    """Account configuration."""

    id: str = ""
    reg_uri: str = ""
    username: str = ""
    password: str = ""
    realm: str = "*"
    contact: str = ""
    expires: int = 3600


def create_account_config() -> AccountConfig:
    """Create default account config."""
    return AccountConfig()
