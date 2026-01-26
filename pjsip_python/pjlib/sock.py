"""
pj/sock.h - Socket Abstraction

Portable socket interface for IPv4/IPv6 with
support for UDP and TCP sockets.
"""

import socket
import struct
from typing import Optional, Tuple, List, Any
from enum import IntEnum


class AddressFamily(IntEnum):
    """Address family constants."""
    INET = socket.AF_INET
    INET6 = socket.AF_INET6
    UNIX = socket.AF_UNIX


class SocketType(IntEnum):
    """Socket type constants."""
    STREAM = socket.SOCK_STREAM
    DATAGRAM = socket.SOCK_DGRAM
    RAW = socket.SOCK_RAW


class IPPProto(IntEnum):
    """IP protocol constants."""
    IP = socket.IPPROTO_IP
    UDP = socket.IPPROTO_UDP
    TCP = socket.IPPROTO_TCP


class Socket:
    """
    Portable socket wrapper.

    Provides a consistent interface across platforms for
    IPv4/IPv6 UDP and TCP sockets.
    """

    def __init__(
        self,
        family: AddressFamily = AddressFamily.INET,
        type: SocketType = SocketType.DATAGRAM,
        proto: IPPProto = IPPProto.IP
    ):
        self._sock: Optional[socket.socket] = None
        self._family = family
        self._type = type
        self._proto = proto
        self._closed = False

    @property
    def fd(self) -> Optional[int]:
        """Get file descriptor."""
        return self._sock.fileno() if self._sock else None

    @property
    def family(self) -> AddressFamily:
        """Get address family."""
        return self._family

    @property
    def type(self) -> SocketType:
        """Get socket type."""
        return self._type

    @property
    def proto(self) -> IPPProto:
        """Get protocol."""
        return self._proto

    @property
    def closed(self) -> bool:
        """Check if socket is closed."""
        return self._closed

    def socket(self) -> 'Socket':
        """Create a new socket."""
        self._sock = socket.socket(self._family, self._type, self._proto)
        return self

    def create_socket(
        self,
        family: AddressFamily = AddressFamily.INET,
        type: SocketType = SocketType.DATAGRAM,
        proto: IPPProto = IPPProto.IP
    ) -> 'Socket':
        """Create a new socket with specified parameters."""
        self._family = family
        self._type = type
        self._proto = proto
        return self.socket()

    def bind(self, addr: Tuple[str, int]) -> 'Socket':
        """
        Bind socket to address.

        Args:
            addr: Tuple of (host, port)

        Returns:
            Self for chaining.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.bind(addr)
        return self

    def connect(self, addr: Tuple[str, int]) -> 'Socket':
        """
        Connect to remote address.

        Args:
            addr: Tuple of (host, port)

        Returns:
            Self for chaining.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.connect(addr)
        return self

    def listen(self, backlog: int = 5) -> 'Socket':
        """
        Listen for connections (TCP).

        Args:
            backlog: Maximum queue length.

        Returns:
            Self for chaining.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.listen(backlog)
        return self

    def accept(self) -> Tuple['Socket', Tuple[str, int]]:
        """
        Accept a connection (TCP).

        Returns:
            Tuple of (new Socket, client_address).
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        client_sock, client_addr = self._sock.accept()
        sock = Socket(self._family, self._type, self._proto)
        sock._sock = client_sock
        return sock, client_addr

    def sendto(self, data: bytes, addr: Tuple[str, int]) -> int:
        """
        Send data to address.

        Args:
            data: Bytes to send.
            addr: Destination address.

        Returns:
            Number of bytes sent.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        return self._sock.sendto(data, addr)

    def recvfrom(self, bufsize: int = 4096) -> Tuple[bytes, Tuple[str, int]]:
        """
        Receive data from socket.

        Args:
            bufsize: Maximum receive buffer size.

        Returns:
            Tuple of (data, sender_address).
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        return self._sock.recvfrom(bufsize)

    def send(self, data: bytes) -> int:
        """
        Send data (connected socket).

        Args:
            data: Bytes to send.

        Returns:
            Number of bytes sent.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        return self._sock.send(data)

    def recv(self, bufsize: int = 4096) -> bytes:
        """
        Receive data (connected socket).

        Args:
            bufsize: Maximum receive buffer size.

        Returns:
            Received data.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        return self._sock.recv(bufsize)

    def sendall(self, data: bytes) -> None:
        """
        Send all data (connected socket).

        Args:
            data: Bytes to send.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.sendall(data)

    def settimeout(self, timeout: Optional[float]) -> 'Socket':
        """
        Set socket timeout.

        Args:
            timeout: Timeout in seconds, None for blocking.

        Returns:
            Self for chaining.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.settimeout(timeout)
        return self

    def setblocking(self, blocking: bool) -> 'Socket':
        """
        Set blocking mode.

        Args:
            blocking: True for blocking, False for non-blocking.

        Returns:
            Self for chaining.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.setblocking(blocking)
        return self

    def setsockopt(self, level: int, optname: int, value: Any) -> 'Socket':
        """
        Set socket option.

        Args:
            level: Option level (e.g., socket.SOL_SOCKET).
            optname: Option name.
            value: Option value.

        Returns:
            Self for chaining.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.setsockopt(level, optname, value)
        return self

    def getsockopt(self, level: int, optname: int) -> Any:
        """
        Get socket option.

        Args:
            level: Option level.
            optname: Option name.

        Returns:
            Option value.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        return self._sock.getsockopt(level, optname)

    def getsockname(self) -> Tuple[str, int]:
        """
        Get local socket address.

        Returns:
            Tuple of (host, port).
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        return self._sock.getsockname()

    def getpeername(self) -> Tuple[str, int]:
        """
        Get remote socket address.

        Returns:
            Tuple of (host, port).
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        return self._sock.getpeername()

    def getservbyname(self, servicename: str, proto: str = 'udp') -> int:
        """
        Get port number by service name.

        Args:
            servicename: Service name (e.g., 'sip').
            proto: Protocol ('udp' or 'tcp').

        Returns:
            Port number.
        """
        return socket.getservbyname(servicename, proto)

    def gethostbyname(self, hostname: str) -> str:
        """
        Resolve hostname to IP address.

        Args:
            hostname: Hostname to resolve.

        Returns:
            IP address string.
        """
        return socket.gethostbyname(hostname)

    def gethostbyaddr(self, ip_addr: str) -> Tuple[str, List[str], List[str]]:
        """
        Resolve IP address to hostname.

        Args:
            ip_addr: IP address string.

        Returns:
            Tuple of (hostname, aliases, ip_addresses).
        """
        return socket.gethostbyaddr(ip_addr)

    def shutdown(self, how: int) -> 'Socket':
        """
        Shutdown socket.

        Args:
            how: SHUT_RD, SHUT_WR, or SHUT_RDWR.

        Returns:
            Self for chaining.
        """
        if not self._sock:
            raise RuntimeError("Socket not created")
        self._sock.shutdown(how)
        return self

    def close(self) -> None:
        """
        Close socket.
        """
        if self._sock and not self._closed:
            try:
                self._sock.close()
            except Exception:
                pass
            self._closed = True
            self._sock = None

    def __enter__(self) -> 'Socket':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Destructor."""
        self.close()


class SockAddr:
    """
    Socket address container.

    Provides a structured way to store and manipulate
    socket addresses for both IPv4 and IPv6.
    """

    def __init__(
        self,
        addr: Optional[Tuple[str, int]] = None,
        family: AddressFamily = AddressFamily.INET
    ):
        self._family = family
        self._addr = ('0.0.0.0', 0)
        if addr:
            self._addr = addr

    @property
    def family(self) -> AddressFamily:
        """Get address family."""
        return self._family

    @property
    def host(self) -> str:
        """Get host address."""
        return self._addr[0]

    @property
    def port(self) -> int:
        """Get port number."""
        return self._addr[1]

    @host.setter
    def host(self, value: str) -> None:
        """Set host address."""
        self._addr = (value, self._addr[1])

    @port.setter
    def port(self, value: int) -> None:
        """Set port number."""
        self._addr = (self._addr[0], value)

    def to_tuple(self) -> Tuple[str, int]:
        """Convert to tuple."""
        return self._addr

    @classmethod
    def from_string(cls, addr_str: str, default_port: int = 0) -> 'SockAddr':
        """
        Create from string like "192.168.1.1:5060".

        Args:
            addr_str: Address string.
            default_port: Default port if not specified.

        Returns:
            SockAddr instance.
        """
        if ':' in addr_str:
            host, port_str = addr_str.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                port = default_port
        else:
            host = addr_str
            port = default_port

        family = AddressFamily.INET6 if ':' in host else AddressFamily.INET
        return cls((host, port), family)


def get_local_ip(exclude_loopback: bool = True) -> str:
    """
    Get the local IP address of this machine.

    Args:
        exclude_loopback: Exclude 127.0.0.1 if True.

    Returns:
        Local IP address string.
    """
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


def create_socket_pair(
    type: SocketType = SocketType.DATAGRAM
) -> Tuple[Socket, Socket]:
    """
    Create a pair of connected sockets.

    Args:
        type: Socket type (DATAGRAM for UDP-like, STREAM for TCP-like).

    Returns:
        Tuple of (socket1, socket2).
    """
    sock1 = Socket()
    sock2 = Socket()
    s1, s2 = socket.socketpair()
    sock1._sock = s1
    sock2._sock = s2
    return sock1, sock2
