"""
pjsip/sip_transaction.h - Transaction State Machine

SIP transaction state machine implementation according to RFC 3261.
Handles INVITE and non-INVITE transactions for both client and server.
"""

import time
import threading
from typing import Optional, Dict, Callable, Any, Tuple
from enum import IntEnum, auto
from dataclasses import dataclass, field

from .sip_msg import SipMessage, SipMethod, SipStatusCode
from .sip_uri import SipUri


class TransactionState(IntEnum):
    """Transaction state constants (RFC 3261)."""
    NULL = 0
    CALLING = auto()
    TRYING = auto()
    PROCEEDING = auto()
    COMPLETED = auto()
    CONFIRMED = auto()
    TERMINATED = auto()
    DESTROYED = auto()


class TransactionRole(IntEnum):
    """Transaction role (UAC = client, UAS = server)."""
    UAC = 0
    UAS = auto()


@dataclass
class Transaction:
    """
    SIP transaction base class.

    Attributes:
        method: SIP method.
        call_id: Call-ID header value.
        from_tag: From tag.
        to_tag: To tag (set by UAS).
        cseq: CSeq number.
        branch: Branch parameter.
        state: Current transaction state.
        role: UAC or UAS.
        remote_uri: Remote URI (UAC) or local URI (UAS).
        local_uri: Local URI (UAC) or remote URI (UAS).
        timeout: Transaction timeout in seconds.
        timer_a: Initial retransmit timer.
        timer_b: Invite transaction timeout.
        timer_d: INVITE transaction completed timer.
        timer_e: Non-INVITE retransmit timer.
        timer_f: Non-INVITE transaction timeout.
        retransmit_count: Number of retransmits.
        last_msg: Last transmitted message.
        on_state_change: Callback for state changes.
        user_data: User data for callbacks.
    """
    method: SipMethod
    call_id: str
    from_tag: str
    to_tag: Optional[str] = None
    cseq: int = 1
    branch: str = ""
    state: TransactionState = TransactionState.NULL
    role: TransactionRole = TransactionRole.UAC
    remote_uri: str = ""
    local_uri: str = ""
    timeout: float = 32.0
    timer_a: float = 0.5
    timer_b: float = 64.0
    timer_d: float = 32.0
    timer_e: float = 0.5
    timer_f: float = 64.0
    retransmit_count: int = 0
    last_msg: Optional[bytes] = None
    on_state_change: Optional[Callable] = None
    user_data: Any = None

    def __post_init__(self):
        if not self.branch:
            import random
            self.branch = f"z9hG4bK{random.randint(1000000000, 9999999999)}"

    @property
    def is_invite(self) -> bool:
        """Check if this is an INVITE transaction."""
        return self.method == SipMethod.INVITE

    @property
    def key(self) -> str:
        """Get transaction key for lookup."""
        return f"{self.branch};{self.method.value}"

    @property
    def key2(self) -> str:
        """Get secondary key for merged request detection."""
        return f"{self.call_id};{self.cseq};{self.method.value}"

    def set_state(self, new_state: TransactionState) -> None:
        """Set transaction state and call callback."""
        old_state = self.state
        self.state = new_state
        if self.on_state_change and old_state != new_state:
            try:
                self.on_state_change(self, old_state, new_state)
            except Exception:
                pass

    def matches(self, msg: SipMessage) -> bool:
        """Check if message matches this transaction."""
        return False


@dataclass
class UacTransaction(Transaction):
    """UAC (client) transaction."""

    def __init__(self, **kwargs):
        kwargs['role'] = TransactionRole.UAC
        super().__init__(**kwargs)
        self.timer_a_handle: Optional[threading.Timer] = None
        self.timer_b_handle: Optional[threading.Timer] = None

    def matches(self, msg: SipMessage) -> bool:
        """Check if response matches this transaction."""
        if not msg.is_response:
            return False

        call_id = msg.get_call_id()
        if call_id and call_id != self.call_id:
            return False

        cseq, method = msg.get_cseq()
        if cseq != self.cseq:
            return False

        return True

    def start(self) -> None:
        """Start the transaction (send request)."""
        self.set_state(TransactionState.CALLING if self.is_invite else TransactionState.TRYING)

    def on_provisional(self, resp: SipMessage) -> None:
        """Handle provisional response (1xx)."""
        if self.state == TransactionState.CALLING:
            self.set_state(TransactionState.PROCEEDING)

    def on_success(self, resp: SipMessage) -> None:
        """Handle 2xx response (INVITE only)."""
        if self.is_invite:
            self.set_state(TransactionState.COMPLETED)
            self.to_tag = resp.get_to().tag
        else:
            self.set_state(TransactionState.TERMINATED)

    def on_redirect(self, resp: SipMessage) -> None:
        """Handle 3xx response."""
        self.set_state(TransactionState.COMPLETED)
        self.to_tag = resp.get_to().tag

    def on_error(self, resp: SipMessage) -> None:
        """Handle 4xx, 5xx, 6xx response."""
        self.set_state(TransactionState.TERMINATED)
        self.to_tag = resp.get_to().tag

    def retransmit(self) -> None:
        """Retransmit the last request."""
        self.retransmit_count += 1

    def timeout_expired(self) -> None:
        """Handle transaction timeout."""
        self.set_state(TransactionState.TERMINATED)

    def destroy(self) -> None:
        """Destroy the transaction."""
        if self.timer_a_handle:
            self.timer_a_handle.cancel()
            self.timer_a_handle = None
        if self.timer_b_handle:
            self.timer_b_handle.cancel()
            self.timer_b_handle = None
        self.set_state(TransactionState.DESTROYED)


@dataclass
class UasTransaction(Transaction):
    """UAS (server) transaction."""

    def __init__(self, **kwargs):
        kwargs['role'] = TransactionRole.UAS
        super().__init__(**kwargs)
        self.timer_d_handle: Optional[threading.Timer] = None
        self.timer_h_handle: Optional[threading.Timer] = None
        self.provisional_sent = False

    def matches(self, msg: SipMessage) -> bool:
        """Check if request matches this transaction."""
        if not msg.is_request:
            return False

        call_id = msg.get_call_id()
        if call_id and call_id != self.call_id:
            return False

        cseq, method = msg.get_cseq()
        if cseq != self.cseq:
            return False

        via = msg.get_via()
        if via and via.branch != self.branch:
            return False

        return True

    def start(self) -> None:
        """Start the transaction (receive request)."""
        self.set_state(TransactionState.TRYING)

    def send_provisional(self, resp: SipMessage) -> None:
        """Send provisional response (1xx)."""
        self.provisional_sent = True
        self.set_state(TransactionState.PROCEEDING)

    def send_success(self, resp: SipMessage) -> None:
        """Send 2xx response (INVITE only)."""
        self.set_state(TransactionState.COMPLETED)

    def send_error(self, resp: SipMessage) -> None:
        """Send error response."""
        self.set_state(TransactionState.COMPLETED)

    def on_ack(self, ack: SipMessage) -> None:
        """Handle ACK for INVITE."""
        if self.is_invite:
            self.set_state(TransactionState.CONFIRMED)

    def on_invite_resend(self, invite: SipMessage) -> None:
        """Handle retransmitted INVITE."""
        pass

    def destroy(self) -> None:
        """Destroy the transaction."""
        if self.timer_d_handle:
            self.timer_d_handle.cancel()
            self.timer_d_handle = None
        if self.timer_h_handle:
            self.timer_h_handle.cancel()
            self.timer_h_handle = None
        self.set_state(TransactionState.DESTROYED)


class TsxLayer:
    """
    Transaction layer manager.

    Manages all active transactions and routes incoming
    messages to the appropriate transaction.
    """

    def __init__(self):
        self._transactions: Dict[str, Transaction] = {}
        self._transactions2: Dict[str, Transaction] = {}
        self._lock = threading.Lock()
        self._tsx_count = 0
        self._on_incoming: Optional[Callable] = None

    @property
    def transaction_count(self) -> int:
        """Get number of active transactions."""
        return len(self._transactions)

    def create_uac(
        self,
        method: SipMethod,
        call_id: str,
        from_tag: str,
        local_uri: str,
        remote_uri: str,
        cseq: int = 1
    ) -> UacTransaction:
        """
        Create a UAC transaction.

        Args:
            method: SIP method.
            call_id: Call-ID.
            from_tag: From tag.
            local_uri: Local URI.
            remote_uri: Remote URI.
            cseq: CSeq number.

        Returns:
            UacTransaction instance.
        """
        tsx = UacTransaction(
            method=method,
            call_id=call_id,
            from_tag=from_tag,
            local_uri=local_uri,
            remote_uri=remote_uri,
            cseq=cseq
        )

        with self._lock:
            self._transactions[tsx.key] = tsx
            self._transactions2[tsx.key2] = tsx
            self._tsx_count += 1

        return tsx

    def create_uas(
        self,
        request: SipMessage,
        local_uri: str,
        remote_uri: str
    ) -> UasTransaction:
        """
        Create a UAS transaction from a request.

        Args:
            request: Incoming request.
            local_uri: Local URI.
            remote_uri: Remote URI.

        Returns:
            UasTransaction instance.
        """
        cseq, method_str = request.get_cseq()
        method = SipMethod(method_str) if method_str else SipMethod.INVITE

        via = request.get_via()
        branch = via.branch if via else ""

        from_hdr = request.get_from()
        to_hdr = request.get_to()

        tsx = UasTransaction(
            method=method,
            call_id=request.get_call_id() or "",
            from_tag=from_hdr.tag or "",
            to_tag=to_hdr.tag,
            cseq=cseq,
            branch=branch,
            local_uri=local_uri,
            remote_uri=remote_uri
        )

        with self._lock:
            self._transactions[tsx.key] = tsx
            self._transactions2[tsx.key2] = tsx
            self._tsx_count += 1

        return tsx

    def find_transaction(
        self,
        key: str,
        lock: bool = True
    ) -> Optional[Transaction]:
        """Find transaction by key."""
        with self._lock:
            return self._transactions.get(key)

    def find_transaction2(
        self,
        key: str,
        lock: bool = True
    ) -> Optional[Transaction]:
        """Find transaction by secondary key (for merged requests)."""
        with self._lock:
            return self._transactions2.get(key)

    def match_incoming(self, msg: SipMessage) -> Optional[Transaction]:
        """Match incoming message to transaction."""
        with self._lock:
            if msg.is_request:
                via = msg.get_via()
                if via:
                    key = f"{via.branch}"
                    if key in self._transactions:
                        tsx = self._transactions[key]
                        if tsx.matches(msg):
                            return tsx
            elif msg.is_response:
                call_id = msg.get_call_id()
                cseq, _ = msg.get_cseq()
                if call_id and cseq:
                    key2 = f"{call_id};{cseq}"
                    if key2 in self._transactions2:
                        tsx = self._transactions2[key2]
                        if tsx.matches(msg):
                            return tsx
        return None

    def handle_incoming(self, msg: SipMessage) -> Optional[Transaction]:
        """Handle incoming message and return matching transaction."""
        tsx = self.match_incoming(msg)
        if tsx and self._on_incoming:
            try:
                self._on_incoming(tsx, msg)
            except Exception:
                pass
        return tsx

    def set_on_incoming(self, callback: Callable) -> None:
        """Set callback for incoming messages."""
        self._on_incoming = callback

    def destroy_transaction(self, tsx: Transaction) -> None:
        """Remove transaction from layer."""
        with self._lock:
            self._transactions.pop(tsx.key, None)
            self._transactions2.pop(tsx.key2, None)
            self._tsx_count -= 1

    def get_stats(self) -> Dict[str, int]:
        """Get transaction layer statistics."""
        with self._lock:
            return {
                'transaction_count': len(self._transactions),
                'transaction_count2': len(self._transactions2)
            }

    def destroy(self) -> None:
        """Destroy all transactions and cleanup."""
        with self._lock:
            for tsx in list(self._transactions.values()):
                tsx.destroy()
            self._transactions.clear()
            self._transactions2.clear()
            self._tsx_count = 0


def create_tsx_layer() -> TsxLayer:
    """Create a new transaction layer."""
    return TsxLayer()
