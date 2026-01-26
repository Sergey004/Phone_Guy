"""
pjsip/sip_dialog.h - Dialog Management

SIP dialog state management according to RFC 3261.
Handles dialog creation, destruction, and in-dialog requests.
"""

import threading
import time
from typing import Optional, Dict, List, Callable, Any, Union
from enum import IntEnum, auto
from dataclasses import dataclass, field

from .sip_msg import SipMessage, SipMethod, SipHeader
from .sip_uri import SipUri
from .sip_transaction import Transaction, TsxLayer


class DialogState(IntEnum):
    """Dialog state constants (RFC 3261)."""
    NULL = 0
    EARLY = auto()
    CONFIRMED = auto()
    COMPLETED = auto()
    TERMINATED = auto()


@dataclass
class DialogRoute:
    """Dialog route set entry."""
    uri: str
    lr: bool = True
    weight: int = 0

    @classmethod
    def parse(cls, value: str) -> 'DialogRoute':
        """Parse Route header value."""
        route = cls()
        uri = SipUri.parse(value)
        route.uri = str(uri)
        route.lr = uri.lr
        return route

    def build(self) -> str:
        """Build Route header value."""
        return f"<{self.uri}>"


@dataclass
class Dialog:
    """
    SIP dialog representation.

    Attributes:
        call_id: Call-ID.
        local_tag: Local tag.
        remote_tag: Remote tag.
        local_uri: Local URI.
        remote_uri: Remote URI.
        local_target: Local target (Contact).
        remote_target: Remote target (Contact).
        route_set: Route set for requests.
        state: Current dialog state.
        dialog_id: Dialog identifier (call_id;from_tag;to_tag).
        local_cseq: Local CSeq.
        remote_cseq: Remote CSeq.
        secure: Whether dialog is secure (TLS).
        local_seq: Local sequence number.
        remote_seq: Remote sequence number.
        on_state_change: Callback for state changes.
        on_incoming_request: Callback for in-dialog requests.
        user_data: User data for callbacks.
    """
    call_id: str
    local_tag: str
    remote_tag: Optional[str] = None
    local_uri: str = ""
    remote_uri: str = ""
    local_target: str = ""
    remote_target: str = ""
    route_set: List[DialogRoute] = field(default_factory=list)
    state: DialogState = DialogState.NULL
    dialog_id: str = ""
    local_cseq: int = 0
    remote_cseq: int = 0
    secure: bool = False
    local_seq: int = 0
    remote_seq: int = 0
    on_state_change: Optional[Callable] = None
    on_incoming_request: Optional[Callable] = None
    user_data: Any = None

    def __post_init__(self):
        self._update_dialog_id()

    def _update_dialog_id(self) -> None:
        """Update dialog ID."""
        self.dialog_id = f"{self.call_id};{self.local_tag}"
        if self.remote_tag:
            self.dialog_id += f";{self.remote_tag}"

    @property
    def is_early(self) -> bool:
        """Check if dialog is in early state."""
        return self.state == DialogState.EARLY

    @property
    def is_confirmed(self) -> bool:
        """Check if dialog is confirmed."""
        return self.state == DialogState.CONFIRMED

    @property
    def is_terminated(self) -> bool:
        """Check if dialog is terminated."""
        return self.state in (DialogState.TERMINATED, DialogState.NULL)

    @property
    def is_outgoing(self) -> bool:
        """Check if dialog was created by UAC."""
        return self.local_cseq > 0 and self.remote_cseq == 0

    @property
    def local_seq(self) -> int:
        """Get local sequence number."""
        return self._local_seq

    @local_seq.setter
    def local_seq(self, value: int) -> None:
        """Set local sequence number."""
        self._local_seq = value
        self.local_cseq = value

    @property
    def remote_seq(self) -> int:
        """Get remote sequence number."""
        return self._remote_seq

    @remote_seq.setter
    def remote_seq(self, value: int) -> None:
        """Set remote sequence number."""
        self._remote_seq = value
        self.remote_cseq = value

    def set_state(self, new_state: DialogState) -> None:
        """Set dialog state and call callback."""
        old_state = self.state
        self.state = new_state
        if self.on_state_change and old_state != new_state:
            try:
                self.on_state_change(self, old_state, new_state)
            except Exception:
                pass

    def create_uac(
        call_id: str,
        local_tag: str,
        local_uri: str,
        remote_uri: str,
        remote_target: str,
        route_set: Optional[List[str]] = None
    ) -> 'Dialog':
        """
        Create a UAC dialog.

        Args:
            call_id: Call-ID.
            local_tag: Local tag.
            local_uri: Local URI.
            remote_uri: Remote URI.
            remote_target: Remote target (from Contact).
            route_set: Route set (list of Route headers).

        Returns:
            Dialog instance in EARLY state.
        """
        dialog = Dialog(
            call_id=call_id,
            local_tag=local_tag,
            local_uri=local_uri,
            remote_uri=remote_uri,
            remote_target=remote_target,
            local_seq=0,
            remote_seq=0,
            state=DialogState.EARLY
        )

        if route_set:
            dialog.route_set = [DialogRoute.parse(r) for r in route_set]

        dialog.local_cseq = 1

        return dialog

    def create_uas(
        request: SipMessage,
        local_uri: str,
        remote_uri: str,
        local_tag: str,
        remote_target: str
    ) -> 'Dialog':
        """
        Create a UAS dialog from a request.

        Args:
            request: Incoming request.
            local_uri: Local URI.
            remote_uri: Remote URI.
            local_tag: Local tag (generated).
            remote_target: Local target (our Contact).

        Returns:
            Dialog instance in EARLY state.
        """
        from_hdr = request.get_from()
        to_hdr = request.get_to()
        cseq, _ = request.get_cseq()

        dialog = Dialog(
            call_id=request.get_call_id() or "",
            local_tag=local_tag,
            remote_tag=from_hdr.tag,
            local_uri=local_uri,
            remote_uri=remote_uri,
            local_target=remote_target,
            remote_target=from_hdr.uri,
            local_seq=0,
            remote_seq=cseq,
            state=DialogState.EARLY
        )

        route_hdr = request.get_headers('Route')
        for hdr in route_hdr:
            dialog.route_set.append(DialogRoute.parse(hdr.value))

        dialog.local_cseq = 1

        return dialog

    def set_remote_tag(self, tag: str) -> None:
        """Set remote tag (called when 2xx response received)."""
        self.remote_tag = tag
        self._update_dialog_id()

    def set_remote_target(self, target: str) -> None:
        """Set remote target (from Contact header)."""
        self.remote_target = target

    def increment_local_cseq(self) -> int:
        """Increment local CSeq and return new value."""
        self.local_cseq += 1
        return self.local_cseq

    def verify_local_cseq(self, cseq: int) -> bool:
        """Verify remote CSeq is valid."""
        return cseq > self.remote_cseq

    def verify_remote_cseq(self, cseq: int) -> bool:
        """Verify remote CSeq is valid."""
        return cseq > self.remote_cseq

    def handle_incoming(self, request: SipMessage) -> bool:
        """
        Handle in-dialog request.

        Args:
            request: Incoming request.

        Returns:
            True if request was handled.
        """
        cseq, method_str = request.get_cseq()

        if not self.verify_remote_cseq(cseq):
            return False

        if self.on_incoming_request:
            try:
                self.on_incoming_request(self, method_str, request)
            except Exception:
                pass

        self.remote_cseq = cseq

        if method_str == "BYE":
            self.set_state(DialogState.TERMINATED)

        return True

    def create_request(
        self,
        method: Union[str, SipMethod],
        body: bytes = b"",
        content_type: Optional[str] = None
    ) -> SipMessage:
        """
        Create an in-dialog request.

        Args:
            method: SIP method.
            body: Message body.
            content_type: Content-Type header.

        Returns:
            SipMessage instance.
        """
        local_seq = self.increment_local_cseq()

        msg = SipMessage()
        msg._type = "request"
        msg.method = method
        msg._uri = self.remote_target if not self.route_set else self.route_set[0].uri
        msg._version = "SIP/2.0"

        via = SipViaHeader(branch=generate_branch())
        msg.set_via(via)

        from_hdr = SipFromHeader(uri=self.local_uri, tag=self.local_tag)
        msg.set_from(from_hdr)

        to_hdr = SipToHeader(uri=self.remote_uri, tag=self.remote_tag)
        msg.set_to(to_hdr)

        msg.set_call_id(self.call_id)
        msg.set_cseq(local_seq, method if isinstance(method, str) else method.value)

        contact = SipContactHeader(uri=self.local_target)
        msg.set_contact(contact)

        if self.route_set:
            route_headers = [r.build() for r in self.route_set]
            for hdr in reversed(route_headers):
                msg.add_header('Route', hdr)

        if body:
            msg.body = body
            if content_type:
                msg.set_content_type(content_type)
            msg.set_content_length(len(body))
        else:
            msg.set_content_length(0)

        return msg

    def create_response(self, status_code: int, reason: str) -> SipMessage:
        """
        Create in-dialog response.

        Args:
            status_code: Status code.
            reason: Reason phrase.

        Returns:
            SipMessage instance.
        """
        from .sip_msg import create_response
        return create_response(status_code, reason, None)

    def terminate(self, reason: str = "Dialog terminated") -> None:
        """Terminate the dialog."""
        self.set_state(DialogState.TERMINATED)


class DialogSet:
    """
    Dialog set for managing multiple dialogs.

    Groups dialogs by Call-ID for easy lookup.
    """

    def __init__(self):
        self._dialogs: Dict[str, Dialog] = {}
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        """Get number of dialogs."""
        return len(self._dialogs)

    def add_dialog(self, dialog: Dialog) -> None:
        """Add a dialog to the set."""
        with self._lock:
            self._dialogs[dialog.dialog_id] = dialog

    def remove_dialog(self, dialog_id: str) -> Optional[Dialog]:
        """Remove a dialog from the set."""
        with self._lock:
            return self._dialogs.pop(dialog_id, None)

    def find_dialog(self, dialog_id: str) -> Optional[Dialog]:
        """Find dialog by ID."""
        with self._lock:
            return self._dialogs.get(dialog_id)

    def find_by_call_id(self, call_id: str) -> List[Dialog]:
        """Find all dialogs with given Call-ID."""
        with self._lock:
            return [d for d in self._dialogs.values() if d.call_id == call_id]

    def get_dialogs(self) -> List[Dialog]:
        """Get all dialogs."""
        with self._lock:
            return list(self._dialogs.values())

    def destroy(self) -> None:
        """Destroy all dialogs."""
        with self._lock:
            for dialog in list(self._dialogs.values()):
                dialog.terminate()
            self._dialogs.clear()


def generate_tag() -> str:
    """Generate a random tag."""
    import random
    return str(random.randint(1000000000, 9999999999))


from .sip_msg import SipViaHeader
from typing import Union