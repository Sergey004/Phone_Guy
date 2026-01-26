"""
pjsip/sip_endpoint.h - SIP Endpoint

Core SIP endpoint that manages all SIP layers and provides
the main event loop for the stack.
"""

import threading
import time
from typing import Optional, Dict, List, Callable, Any, Tuple
from dataclasses import dataclass, field

from ..pjlib.sock import Socket
from ..pjlib.timer import TimerHeap
from ..pjlib.pool import Pool, create_pool
from .sip_msg import SipMessage, SipHeader
from .sip_transaction import Transaction, TsxLayer, TransactionState
from .sip_dialog import Dialog, DialogSet, DialogState
from .sip_transport import Transport, TransportManager, TransportType, TransportConfig


class Module:
    """
    Base module class.

    Modules register with the endpoint to receive events
    and extend the functionality of the SIP stack.
    """

    def __init__(self, name: str):
        self._name = name
        self._priority = 0
        self._endpoint: Optional['SipEndpoint'] = None
        self._enabled = True

    @property
    def name(self) -> str:
        """Get module name."""
        return self._name

    @property
    def priority(self) -> int:
        """Get module priority."""
        return self._priority

    @property
    def endpoint(self) -> Optional['SipEndpoint']:
        """Get endpoint."""
        return self._endpoint

    @property
    def enabled(self) -> bool:
        """Check if module is enabled."""
        return self._enabled

    def load(self, endpt: 'SipEndpoint') -> int:
        """Load module (called when registering with endpoint)."""
        self._endpoint = endpt
        return 0

    def unload(self) -> int:
        """Unload module."""
        self._endpoint = None
        return 0

    def on_rx_request(self, request: SipMessage) -> int:
        """Handle incoming request."""
        return 0

    def on_rx_response(self, response: SipMessage) -> int:
        """Handle incoming response."""
        return 0

    def on_tx_request(self, request: SipMessage, transport: Transport) -> int:
        """Handle outgoing request."""
        return 0

    def on_tx_response(self, response: SipMessage, transport: Transport) -> int:
        """Handle outgoing response."""
        return 0

    def on_tsx_state(self, tsx: Transaction, event: Any) -> int:
        """Handle transaction state change."""
        return 0

    def on_dlg_state(self, dlg: Dialog, event: Any) -> int:
        """Handle dialog state change."""
        return 0


class CoreModule(Module):
    """Core module for endpoint event handling."""

    def __init__(self):
        super().__init__("pjsip_core")
        self._priority = 0

    def load(self, endpt: 'SipEndpoint') -> int:
        """Load core module."""
        return super().load(endpt)


class EndpointConfig:
    """Endpoint configuration."""

    def __init__(self):
        self.name: str = "pjsip_python"
        self.user_agent: str = "pjsip_python/1.0"
        self.max_timer_count: int = 16
        # Media
        self.media_thread_count: int = 1
        self.ioqueue_size: int = 0
        # Thread settings
        self.use_separate_worker_thread: bool = False
        self.main_thread_only: bool = False


@dataclass
class SipEndpoint:
    """
    SIP endpoint.

    The core object of the SIP stack that manages:
    - Transport layer
    - Transaction layer
    - Dialog layer
    - Timer management
    - Memory pools
    - Event loop
    """

    name: str = "pjsip_python"
    user_agent: str = "pjsip_python/1.0"
    tsx_layer: Optional[TsxLayer] = None
    dialog_set: Optional[DialogSet] = None
    transport_mgr: Optional[TransportManager] = None
    timer_heap: Optional[TimerHeap] = None
    pool: Optional[Pool] = None
    modules: List[Module] = field(default_factory=list)
    ioqueue: Optional[Any] = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    on_rx_msg: Optional[Callable] = None

    def __post_init__(self):
        self.tsx_layer = TsxLayer()
        self.dialog_set = DialogSet()
        self.transport_mgr = TransportManager()
        self.timer_heap = TimerHeap()
        self.pool = Pool("endpoint", 4096, 1024, 0)

    @classmethod
    def create(cls, config: Optional[EndpointConfig] = None) -> 'SipEndpoint':
        """
        Create and initialize the endpoint.

        Args:
            config: Optional endpoint configuration.

        Returns:
            SipEndpoint instance.
        """
        endpt = cls()

        if config:
            endpt.name = config.name
            endpt.user_agent = config.user_agent

        return endpt

    def create_pool(self, name: str, size: int = 1000) -> Pool:
        """
        Create a memory pool from the endpoint.

        Args:
            name: Pool name.
            size: Initial size.

        Returns:
            Pool instance.
        """
        return create_pool(name, size, size // 2)

    def register_module(self, module: Module) -> int:
        """
        Register a module with the endpoint.

        Args:
            module: Module to register.

        Returns:
            0 on success, error code otherwise.
        """
        with self.lock:
            if module.endpoint is not None:
                return -1

            result = module.load(self)
            if result == 0:
                self.modules.append(module)
                self.modules.sort(key=lambda m: m.priority)

            return result

    def unregister_module(self, module: Module) -> int:
        """
        Unregister a module.

        Args:
            module: Module to unregister.

        Returns:
            0 on success.
        """
        with self.lock:
            if module in self.modules:
                self.modules.remove(module)
                module.unload()
            return 0

    def create_transport(
        self,
        type: TransportType,
        config: Optional[TransportConfig] = None
    ) -> Optional[Transport]:
        """
        Create a transport.

        Args:
            type: Transport type.
            config: Optional transport configuration.

        Returns:
            Transport instance or None.
        """
        if config is None:
            config = TransportConfig()

        transport = self.transport_mgr.create_transport(type, config)
        if transport:
            transport.add_ref()
            transport.set_on_received(self._on_rx_msg)

        return transport

    def create_timer(self):
        """Create a timer from the endpoint."""
        return self.timer_heap

    def handle_events(self, timeout: float = 0.1) -> int:
        """
        Process pending events.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            Number of events processed.
        """
        count = 0

        now = time.monotonic()
        expired = self.timer_heap.poll(now)

        for entry in expired:
            try:
                if entry.callback:
                    entry.callback(entry.user_data)
                count += 1
            except Exception:
                pass

        return count

    def process_rx_data(self, data: bytes, addr: Tuple[str, int]) -> None:
        """
        Process raw received data.

        Args:
            data: Raw data.
            addr: Source address.
        """
        msg = SipMessage.parse(data)
        if not msg:
            return

        self._on_rx_msg(msg, addr)

    def _on_rx_msg(self, msg: SipMessage, addr: Tuple[str, int]) -> None:
        """Internal message handler."""
        with self.lock:
            modules = list(self.modules)

        if msg.is_request:
            for module in modules:
                if not module.enabled:
                    continue
                try:
                    if module.on_rx_request(msg) != 0:
                        return
                except Exception:
                    pass

            tsx = self.tsx_layer.handle_incoming(msg)

            if not tsx:
                if msg.method_str == "INVITE":
                    pass
                elif msg.method_str == "ACK":
                    pass
                elif msg.method_str == "BYE":
                    pass
                elif msg.method_str == "CANCEL":
                    pass
                elif msg.method_str == "REGISTER":
                    pass

        else:
            for module in modules:
                if not module.enabled:
                    continue
                try:
                    if module.on_rx_response(msg) != 0:
                        return
                except Exception:
                    pass

            self.tsx_layer.handle_incoming(msg)

        if self.on_rx_msg:
            try:
                self.on_rx_msg(msg, addr)
            except Exception:
                pass

    def destroy(self) -> None:
        """Destroy the endpoint and all resources."""
        self.running = False

        for module in list(self.modules):
            self.unregister_module(module)

        self.transport_mgr.shutdown()

        if self.tsx_layer:
            self.tsx_layer.destroy()

        if self.dialog_set:
            self.dialog_set.destroy()

        if self.timer_heap:
            self.timer_heap.destroy()

        if self.pool:
            self.pool.destroy()

    def get_stats(self) -> Dict[str, Any]:
        """Get endpoint statistics."""
        return {
            'name': self.name,
            'transaction_count': self.tsx_layer.transaction_count if self.tsx_layer else 0,
            'dialog_count': self.dialog_set.count if self.dialog_set else 0,
            'transport_stats': self.transport_mgr.get_stats() if self.transport_mgr else {},
            'timer_count': self.timer_heap.count() if self.timer_heap else 0
        }
