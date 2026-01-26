"""
pjsua/pjsua.py - High-Level User Agent

High-level SIP User Agent API for easy integration.
"""

import asyncio
import threading
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import IntEnum

from ..pjlib import (
    Socket, TimerHeap, create_pool, get_local_ip
)
from ..pjsip import (
    SipEndpoint, SipEndpoint, EndpointConfig,
    SipMessage, SipMethod, SipStatusCode,
    SipViaHeader, SipFromHeader, SipToHeader, SipContactHeader,
    Dialog, DialogState,
    Transport, TransportConfig, TransportType, UdpTransport,
    Transaction, TransactionState,
    create_request, create_response,
    parse_sip_message, generate_branch, generate_call_id, generate_tag
)
from ..pjmedia import (
    MediaStream, MediaStreamConfig, SdpSession,
    create_offer, parse_sdp, get_media_info_from_sdp
)
from .call import Call, CallState, CallInfo
from .acc import Account, AccountConfig, AccountInfo


class UaState(IntEnum):
    """User agent states."""
    CREATED = 0
    INIT = 1
    STARTED = 2
    CLOSING = 3
    CLOSED = 6


@dataclass
class UaConfig:
    """User agent configuration."""
    user_agent: str = "pjsip_python/1.0"
    local_ip: str = "127.0.0.1"
    local_port: int = 5060
    stun_server: Optional[str] = None
    stun_port: int = 3478
    turn_server: Optional[str] = None
    turn_port: int = 3478
    no_udp: bool = False
    no_tcp: bool = False


class Ua:
    """
    High-level User Agent.

    Provides simple API for SIP calls, registration, and presence.
    """

    def __init__(self, config: Optional[UaConfig] = None):
        """
        Initialize User Agent.

        Args:
            config: UA configuration.
        """
        self._config = config or UaConfig()
        self._state = UaState.CREATED
        self._endpoint: Optional[SipEndpoint] = None
        self._transport: Optional[Transport] = None
        self._local_addr: tuple = ("", 0)
        self._accounts: Dict[int, Account] = {}
        self._calls: Dict[int, Call] = {}
        self._next_call_id = 0
        self._lock = threading.Lock()
        self._on_incoming_call: Optional[Callable] = None
        self._on_reg_state: Optional[Callable] = None
        self._on_call_state: Optional[Callable] = None

    @classmethod
    async def create(cls, config: Optional[UaConfig] = None) -> 'Ua':
        """Create and initialize UA."""
        ua = cls(config)
        await ua._init()
        return ua

    async def _init(self) -> None:
        """Initialize UA internals."""
        from ..pjsip.sip_util import get_local_ip

        self._endpoint = SipEndpoint.create()

        if not self._config.no_udp:
            local_host = self._config.local_ip
            if local_host == '0.0.0.0':
                local_host = ''  # '' для bind() на всех интерфейсах

            transport_config = TransportConfig(
                local_host=local_host,
                local_port=self._config.local_port
            )
            self._transport = self._endpoint.create_transport(
                TransportType.UDP, transport_config
            )
            if self._transport:
                self._transport.start()
                bound_addr = self._transport.local_addr
                bound_ip, bound_port = bound_addr
                if bound_ip in ('', '0.0.0.0'):
                    real_ip = get_local_ip()
                    self._local_addr = (real_ip, bound_port)
                else:
                    self._local_addr = bound_addr

        self._state = UaState.INIT

    async def start(self) -> None:
        """Start the UA."""
        if self._state != UaState.INIT:
            return
        self._state = UaState.STARTED

    async def destroy(self) -> None:
        """Destroy the UA and release resources."""
        self._state = UaState.CLOSING

        for call in list(self._calls.values()):
            await call.hangup()
        self._calls.clear()

        for acc in list(self._accounts.values()):
            await acc.unregister()
        self._accounts.clear()

        if self._endpoint:
            self._endpoint.destroy()
            self._endpoint = None

        self._state = UaState.CLOSED

    async def create_account(self, config: Dict[str, Any]) -> Account:
        """
        Create an account for registration.

        Args:
            config: Account configuration dict.

        Returns:
            Account instance.
        """
        acc = Account()
        await acc.create(self, config)
        self._accounts[id(acc)] = acc
        return acc

    async def call(self, target_uri: str, options: Dict = None) -> Call:
        """
        Make an outgoing call.

        Args:
            target_uri: Target SIP URI.
            options: Call options (sdp, media, etc.).

        Returns:
            Call instance.
        """
        options = options or {}
        call = Call()
        await call.make(self, target_uri, options)
        self._calls[id(call)] = call
        return call

    def enum_accounts(self) -> List[Account]:
        """Get list of all accounts."""
        return list(self._accounts.values())

    def get_account(self, index: int) -> Optional[Account]:
        """Get account by index."""
        return self._accounts.get(index)

    @property
    def local_addr(self) -> tuple:
        """Get local SIP address."""
        return self._local_addr

    @property
    def local_ip(self) -> str:
        """Get local IP address."""
        return self._local_addr[0] if self._local_addr else ""

    @property
    def local_port(self) -> int:
        """Get local port."""
        return self._local_addr[1] if self._local_addr else 0

    def set_on_incoming_call(self, callback: Callable) -> None:
        """Set callback for incoming calls."""
        self._on_incoming_call = callback

    def set_on_reg_state(self, callback: Callable) -> None:
        """Set callback for registration state changes."""
        self._on_reg_state = callback

    def set_on_call_state(self, callback: Callable) -> None:
        """Set callback for call state changes."""
        self._on_call_state = callback

    def _notify_call_state(self, call: Call, state: CallState) -> None:
        """Notify call state change."""
        if self._on_call_state:
            try:
                self._on_call_state(call, state)
            except Exception:
                pass

    def _remove_call(self, call: Call) -> None:
        """Remove call from list."""
        with self._lock:
            self._calls.pop(id(call), None)

    @property
    def state(self) -> UaState:
        """Get UA state."""
        return self._state

    def get_stats(self) -> Dict[str, Any]:
        """Get UA statistics."""
        return {
            'state': self._state.name,
            'local_addr': self._local_addr,
            'account_count': len(self._accounts),
            'call_count': len(self._calls)
        }


def create_ua(config: Optional[UaConfig] = None) -> Ua:
    """Create User Agent."""
    return Ua(config)
