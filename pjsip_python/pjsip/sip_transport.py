"""
pjsip/sip_transport.h - Transport Layer

SIP transport layer implementation for UDP and TCP.
Provides reliable message delivery and transport management.
"""

import socket
import threading
import time
import select
from typing import Optional, Dict, List, Callable, Tuple, Any
from enum import IntEnum, auto
from dataclasses import dataclass, field

from ..pjlib.sock import Socket, AddressFamily
from .sip_msg import SipMessage
from ..pjlib.timer import TimerHeap, TimerEntry


class TransportType(IntEnum):
    """Transport type constants."""
    NONE = 0
    UDP = auto()
    TCP = auto()
    TLS = auto()


@dataclass
class TransportConfig:
    """Transport configuration."""
    local_host: str = "0.0.0.0"
    local_port: int = 5060
    public_host: Optional[str] = None
    public_port: int = 0
    bound_host: Optional[str] = None
    bound_port: int = 0
    async_cnt: int = 1
    use_source_ip: bool = False
    use_specific_source: bool = False
    reuse_socket: bool = True
    qos_type: int = 0
    qos_dscp: int = 0
    qos_socket_val: int = 0


class Transport:
    """
    Base transport class.

    Provides common functionality for all transport types.
    """

    def __init__(self, config: TransportConfig):
        self._config = config
        self._sock: Optional[Socket] = None
        self._local_addr: Tuple[str, int] = ("", 0)
        self._local_host = config.local_host
        self._local_port = config.local_port
        self._remote_addr: Tuple[str, int] = ("", 0)
        self._running = False
        self._closing = False
        self._ref_count = 0
        self._lock = threading.Lock()
        self._ioqueue = None
        self._on_received: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None
        self._rx_count = 0
        self._tx_count = 0
        self._rx_bytes = 0
        self._tx_bytes = 0

    @property
    def type(self) -> TransportType:
        """Get transport type."""
        return TransportType.NONE

    @property
    def local_addr(self) -> Tuple[str, int]:
        """Get local address."""
        return self._local_addr

    @property
    def remote_addr(self) -> Tuple[str, int]:
        """Get remote address."""
        return self._remote_addr

    @property
    def is_running(self) -> bool:
        """Check if transport is running."""
        return self._running

    @property
    def ref_count(self) -> int:
        """Get reference count."""
        return self._ref_count

    def add_ref(self) -> None:
        """Increment reference count."""
        with self._lock:
            self._ref_count += 1

    def dec_ref(self) -> None:
        """Decrement reference count."""
        with self._lock:
            self._ref_count -= 1
            if self._ref_count <= 0:
                self._destroy()

    def start(self) -> bool:
        """
        Start the transport.

        Returns:
            True if started successfully.
        """
        return False

    def send(self, msg: SipMessage, addr: Tuple[str, int]) -> bool:
        """
        Send SIP message.

        Args:
            msg: SIP message to send.
            addr: Destination address.

        Returns:
            True if sent successfully.
        """
        return False

    def send_raw(self, data: bytes, addr: Tuple[str, int]) -> bool:
        """
        Send raw data.

        Args:
            data: Raw data to send.
            addr: Destination address.

        Returns:
            True if sent successfully.
        """
        return False

    def handle_input(self, data: bytes, addr: Tuple[str, int]) -> None:
        """
        Handle incoming data.

        Args:
            data: Raw data received.
            addr: Source address.
        """
        print(f"DEBUG: handle_input received {len(data)} bytes from {addr}")
        if len(data) > 50:
            print(f"DEBUG: First 100 bytes: {data[:100]}")
        msg = SipMessage.parse(data)
        if msg:
            print(f"DEBUG: Parsed msg status={msg.status_code}, body_len={len(msg.body) if msg.body else 0}")
        if msg and self._on_received:
            try:
                self._on_received(msg, addr)
            except Exception:
                pass

        with self._lock:
            self._rx_count += 1
            self._rx_bytes += len(data)

    def set_on_received(self, callback: Optional[Callable]) -> None:
        """Set callback for received messages."""
        self._on_received = callback

    def set_on_state_change(self, callback: Callable) -> None:
        """Set callback for state changes."""
        self._on_state_change = callback

    def get_info(self) -> str:
        """Get transport info string."""
        return f"{self._local_host}:{self._local_port}"

    def get_stats(self) -> Dict[str, int]:
        """Get transport statistics."""
        return {
            'rx_count': self._rx_count,
            'tx_count': self._tx_count,
            'rx_bytes': self._rx_bytes,
            'tx_bytes': self._tx_bytes
        }

    def close(self) -> None:
        """Start closing the transport."""
        self._closing = True

    def _destroy(self) -> None:
        """Destroy the transport."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def destroy(self) -> None:
        """Fully destroy the transport."""
        with self._lock:
            self._destroy()


class UdpTransport(Transport):
    """UDP transport implementation."""

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        self._type = TransportType.UDP
        self._timer: Optional[TimerHeap] = None
        self._timer_entry: Optional[TimerEntry] = None

    @property
    def type(self) -> TransportType:
        """Get transport type."""
        return TransportType.UDP

    def start(self) -> bool:
        """
        Start the UDP transport.

        Returns:
            True if started successfully.
        """
        try:
            self._sock = Socket()
            self._sock.create_socket(AddressFamily.INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            if self._config.local_host is not None:
                self._sock.bind((self._config.local_host, self._config.local_port))

            self._local_addr = self._sock.getsockname()
            self._local_host, self._local_port = self._local_addr
            self._running = True

            threading.Thread(target=self.receive_loop, daemon=True).start()

            return True

        except Exception:
            return False

    def send(self, msg: SipMessage, addr: Tuple[str, int]) -> bool:
        """
        Send SIP message over UDP.

        Args:
            msg: SIP message to send.
            addr: Destination address.

        Returns:
            True if sent successfully.
        """
        if not self._running or not self._sock:
            return False

        try:
            data = msg.build()
            return self.send_raw(data, addr)
        except Exception:
            return False

    def send_raw(self, data: bytes, addr: Tuple[str, int]) -> bool:
        """
        Send raw data over UDP.

        Args:
            data: Raw data to send.
            addr: Destination address.

        Returns:
            True if sent successfully.
        """
        if not self._running or not self._sock:
            return False

        try:
            sent = self._sock.sendto(data, addr)
            with self._lock:
                self._tx_count += 1
                self._tx_bytes += sent
            return True
        except Exception:
            return False

    def receive_loop(self) -> None:
        """Main receive loop (run in thread)."""
        import socket as sock_module
        import sys

        while self._running and self._sock:
            try:
                real_sock = self._sock._sock
                if real_sock is None:
                    time.sleep(0.01)
                    continue
                    
                if hasattr(sock_module, 'epoll'):
                    poll = select.epoll()
                    poll.register(real_sock.fileno(), select.EPOLLIN)
                    events = poll.poll(0.1)
                    for fd, event in events:
                        if event & select.EPOLLIN:
                            data, addr = real_sock.recvfrom(65535)
                            if data:
                                self.handle_input(data, addr)
                else:
                    r, _, _ = select.select([real_sock], [], [], 0.1)
                    if r:
                        data, addr = real_sock.recvfrom(65535)
                        if data:
                            self.handle_input(data, addr)
            except Exception:
                pass

    def set_read_enabled(self, enabled: bool) -> None:
        """Enable/disable reading."""
        pass

    def destroy(self) -> None:
        """Destroy the UDP transport."""
        if self._timer_entry:
            self._timer.cancel(self._timer_entry)
        super().destroy()


class TcpTransport(Transport):
    """TCP transport implementation."""

    def __init__(self, config: TransportConfig):
        super().__init__(config)
        self._type = TransportType.TCP
        self._listener: Optional[Socket] = None
        self._connections: Dict[str, Socket] = {}
        self._lock_connections = threading.Lock()

    @property
    def type(self) -> TransportType:
        """Get transport type."""
        return TransportType.TCP

    def start(self, listener: bool = True) -> bool:
        """
        Start the TCP transport.

        Args:
            listener: Whether to start a listening socket.

        Returns:
            True if started successfully.
        """
        try:
            self._sock = Socket()
            self._sock.create_socket(AddressFamily.INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            if listener:
                self._sock.bind((self._config.local_host, self._config.local_port))
                self._sock.listen(5)
            else:
                self._sock.connect((self._config.local_host, self._config.local_port))

            self._local_addr = self._sock.getsockname()
            self._local_host, self._local_port = self._local_addr
            self._running = True

            return True

        except Exception:
            return False

    def connect(self, addr: Tuple[str, int]) -> bool:
        """
        Connect to remote address.

        Args:
            addr: Remote address.

        Returns:
            True if connected successfully.
        """
        try:
            self._sock.connect(addr)
            self._remote_addr = addr
            return True
        except Exception:
            return False

    def send(self, msg: SipMessage, addr: Tuple[str, int]) -> bool:
        """
        Send SIP message.

        Args:
            msg: SIP message to send.
            addr: Destination address (not used for connected sockets).

        Returns:
            True if sent successfully.
        """
        if not self._running or not self._sock:
            return False

        try:
            data = msg.build()
            return self.send_raw(data, addr)
        except Exception:
            return False

    def send_raw(self, data: bytes, addr: Tuple[str, int]) -> bool:
        """
        Send raw data.

        Args:
            data: Raw data to send.
            addr: Destination address.

        Returns:
            True if sent successfully.
        """
        if not self._running or not self._sock:
            return False

        try:
            self._sock.sendall(data)
            with self._lock:
                self._tx_count += 1
                self._tx_bytes += len(data)
            return True
        except Exception:
            return False

    def destroy(self) -> None:
        """Destroy the TCP transport."""
        with self._lock_connections:
            for conn in list(self._connections.values()):
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
        super().destroy()


class TransportManager:
    """
    Transport manager.

    Manages multiple transports and provides transport
    selection based on various criteria.
    """

    def __init__(self):
        self._transports: Dict[TransportType, List[Transport]] = {
            TransportType.UDP: [],
            TransportType.TCP: [],
            TransportType.TLS: []
        }
        self._lock = threading.Lock()
        self._next_udp_port = 0

    def create_transport(
        self,
        type: TransportType,
        config: Optional[TransportConfig] = None
    ) -> Optional[Transport]:
        """
        Create a new transport.

        Args:
            type: Transport type.
            config: Transport configuration.

        Returns:
            Transport instance or None if creation failed.
        """
        if config is None:
            config = TransportConfig()

        transport = None

        if type == TransportType.UDP:
            transport = UdpTransport(config)
        elif type == TransportType.TCP:
            transport = TcpTransport(config)
        elif type == TransportType.TLS:
            return None

        if transport:
            with self._lock:
                self._transports[type].append(transport)

        return transport

    def add_transport(self, transport: Transport) -> None:
        """Add an existing transport."""
        with self._lock:
            t = transport.type
            if t not in self._transports:
                self._transports[t] = []
            self._transports[t].append(transport)

    def get_transport(
        self,
        type: TransportType = TransportType.UDP
    ) -> Optional[Transport]:
        """Get a transport of the specified type."""
        with self._lock:
            transports = self._transports.get(type, [])
            return transports[0] if transports else None

    def get_transports(self, type: TransportType) -> List[Transport]:
        """Get all transports of the specified type."""
        with self._lock:
            return list(self._transports.get(type, []))

    def find_transport(
        self,
        local_addr: Tuple[str, int]
    ) -> Optional[Transport]:
        """Find transport by local address."""
        with self._lock:
            for transports in self._transports.values():
                for t in transports:
                    if t.local_addr == local_addr:
                        return t
        return None

    def remove_transport(self, transport: Transport) -> bool:
        """Remove a transport."""
        with self._lock:
            t = transport.type
            if t in self._transports:
                try:
                    self._transports[t].remove(transport)
                    transport.destroy()
                    return True
                except ValueError:
                    pass
        return False

    def shutdown(self) -> None:
        """Shutdown all transports."""
        with self._lock:
            for transports in self._transports.values():
                for t in transports:
                    t.destroy()
                transports.clear()

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """Get statistics for all transports."""
        result = {}
        with self._lock:
            for type, transports in self._transports.items():
                stats = {}
                for t in transports:
                    type_name = type.name
                    if type_name in stats:
                        stats[type_name]['count'] += 1
                        for k, v in t.get_stats().items():
                            stats[type_name][k] = stats[type_name].get(k, 0) + v
                    else:
                        stats[type_name] = t.get_stats()
                        stats[type_name]['count'] = 1
                result.update(stats)
        return result


def create_transport_manager() -> TransportManager:
    """Create a new transport manager."""
    return TransportManager()
