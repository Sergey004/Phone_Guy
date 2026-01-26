"""
pjnath/turn.h - TURN Client

TURN (Traversal Using Relays around NAT) client implementation.
Used for relay candidates when direct connectivity fails.
"""

import socket
import random
import struct
import time
from typing import Optional, Dict, Any, Tuple, List
from enum import IntEnum
from dataclasses import dataclass


class TurnMethod(IntEnum):
    """TURN methods."""
    ALLOCATE = 0x0003
    REFRESH = 0x0004
    SEND = 0x0006
    DATA_INDICATION = 0x0007
    CREATE_PERMISSION = 0x0008
    CHANNEL_BIND = 0x0009


class TurnChannel:
    """TURN channel for data relay."""

    def __init__(self, channel_number: int, peer_addr: Tuple[str, int]):
        self._channel_number = channel_number
        self._peer_addr = peer_addr
        self._allocated = time.time()

    @property
    def channel_number(self) -> int:
        """Get channel number."""
        return self._channel_number

    @property
    def peer_addr(self) -> Tuple[str, int]:
        """Get peer address."""
        return self._peer_addr


class TurnClient:
    """
    TURN client for relay candidate allocation.

    Allocates a relayed address on TURN server and
    relays data through it.
    """

    def __init__(
        self,
        server: str = "turn.example.com",
        port: int = 3478,
        username: Optional[str] = None,
        password: Optional[str] = None,
        realm: Optional[str] = None
    ):
        """
        Initialize TURN client.

        Args:
            server: TURN server hostname.
            port: TURN server port.
            username: Authentication username.
            password: Authentication password.
            realm: Authentication realm.
        """
        self._server = server
        self._port = port
        self._username = username
        self._password = password
        self._realm = realm or "turn"
        self._sock: Optional[socket.socket] = None
        self._relayed_addr: Optional[Tuple[str, int]] = None
        self._mapped_addr: Optional[Tuple[str, int]] = None
        self._transaction_id: bytes = b""
        self._channels: Dict[int, TurnChannel] = {}
        self._next_channel = 0x4000

    @property
    def relayed_address(self) -> Optional[Tuple[str, int]]:
        """Get allocated relayed address."""
        return self._relayed_addr

    def _create_socket(self) -> bool:
        """Create UDP socket."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(5.0)
            self._sock.bind(('0.0.0.0', 0))
            return True
        except Exception:
            return False

    def allocate(
        self,
        client_addr: Optional[Tuple[str, int]] = None
    ) -> Optional[Tuple[str, int]]:
        """
        Allocate relayed address on TURN server.

        Args:
            client_addr: Client address to use.

        Returns:
            Tuple of (relayed_ip, relayed_port) or None.
        """
        if not self._create_socket():
            return None

        self._transaction_id = random.randbytes(12)
        msg = bytearray()
        msg.extend(struct.pack('!HH', 0x0001, TurnMethod.ALLOCATE))
        msg.extend(struct.pack('!H', 0))  # Length (will update)
        msg.extend(self._transaction_id)

        attrs = bytearray()

        requested_transport = struct.pack('!HI', 0x0019, 17)
        attrs.extend(requested_transport)

        even_port = struct.pack('!HI', 0x0018, 0)
        attrs.extend(even_port)

        msg[4:6] = struct.pack('!H', len(attrs))
        msg.extend(attrs)

        try:
            self._sock.sendto(msg, (self._server, self._port))
            data, addr = self._sock.recvfrom(1024)

            if len(data) >= 20:
                msg_type, method, length, trans_id = struct.unpack('!HHH12s', data[:20])
                if method == TurnMethod.ALLOCATE | 0x0100:
                    self._relayed_addr = addr
                    return addr

        except Exception:
            pass

        return None

    def create_permission(self, peer_addr: Tuple[str, int]) -> bool:
        """
        Create permission for peer.

        Args:
            peer_addr: Peer address (ip, port).

        Returns:
            True if successful.
        """
        if not self._sock or not self._relayed_addr:
            return False

        msg = bytearray()
        msg.extend(struct.pack('!HH', 0x0001, TurnMethod.CREATE_PERMISSION))
        msg.extend(struct.pack('!H', 0))
        msg.extend(self._transaction_id)

        attrs = bytearray()
        peer_addr_data = struct.pack('!H', 0x000C) + struct.pack('!H', 4)
        peer_addr_data += socket.inet_aton(peer_addr[0])
        peer_addr_data += struct.pack('!H', peer_addr[1])
        attrs.extend(peer_addr_data)

        msg[4:6] = struct.pack('!H', len(attrs))
        msg.extend(attrs)

        try:
            self._sock.sendto(msg, (self._server, self._port))
            data, _ = self._sock.recvfrom(1024)
            return True
        except Exception:
            return False

    def channel_bind(self, peer_addr: Tuple[str, int]) -> Optional[int]:
        """
        Bind channel to peer.

        Args:
            peer_addr: Peer address.

        Returns:
            Channel number or None.
        """
        if not self._sock:
            return None

        channel = self._next_channel
        self._next_channel += 1
        if self._next_channel > 0x7FFF:
            self._next_channel = 0x4000

        msg = bytearray()
        msg.extend(struct.pack('!HH', 0x0001, TurnMethod.CHANNEL_BIND))
        msg.extend(struct.pack('!H', 0))
        msg.extend(self._transaction_id)

        attrs = bytearray()

        channel_data = struct.pack('!HI', 0x000C, channel)
        attrs.extend(channel_data)

        peer_addr_data = struct.pack('!H', 0x000C) + struct.pack('!H', 4)
        peer_addr_data += socket.inet_aton(peer_addr[0])
        peer_addr_data += struct.pack('!H', peer_addr[1])
        attrs.extend(peer_addr_data)

        msg[4:6] = struct.pack('!H', len(attrs))
        msg.extend(attrs)

        try:
            self._sock.sendto(msg, (self._server, self._port))
            data, _ = self._sock.recvfrom(1024)
            self._channels[channel] = TurnChannel(channel, peer_addr)
            return channel
        except Exception:
            return None

    def send_data(self, data: bytes, peer_addr: Tuple[str, int]) -> int:
        """
        Send data through TURN server to peer.

        Args:
            data: Data to send.
            peer_addr: Destination address.

        Returns:
            Number of bytes sent.
        """
        if not self._sock:
            return 0

        try:
            msg = bytearray()
            channel = self._get_channel(peer_addr)
            if channel:
                msg.extend(struct.pack('!H', channel))
                msg.extend(struct.pack('!H', len(data)))
                msg.extend(data)
                self._sock.sendto(msg, (self._server, self._port))
                return len(data)
            else:
                send_ind = bytearray()
                send_ind.extend(struct.pack('!HH', 0x0011, TurnMethod.SEND))
                send_ind.extend(struct.pack('!H', 0))
                send_ind.extend(self._transaction_id)

                attrs = bytearray()

                peer_addr_data = struct.pack('!H', 0x000C) + struct.pack('!H', 4)
                peer_addr_data += socket.inet_aton(peer_addr[0])
                peer_addr_data += struct.pack('!H', peer_addr[1])
                attrs.extend(peer_addr_data)

                data_attr = struct.pack('!HI', 0x0013, len(data)) + data
                attrs.extend(data_attr)

                send_ind[4:6] = struct.pack('!H', len(attrs))
                send_ind.extend(attrs)

                self._sock.sendto(send_ind, (self._server, self._port))
                return len(data)

        except Exception:
            return 0

    def _get_channel(self, peer_addr: Tuple[str, int]) -> Optional[int]:
        """Get channel number for peer."""
        for channel, turn_ch in self._channels.items():
            if turn_ch.peer_addr == peer_addr:
                return channel
        return None

    def receive_data(self, buffer_size: int = 4096) -> Optional[Tuple[bytes, Tuple[str, int]]]:
        """
        Receive data from TURN server.

        Returns:
            Tuple of (data, peer_addr) or None.
        """
        if not self._sock:
            return None

        try:
            data, addr = self._sock.recvfrom(buffer_size)
            if len(data) >= 4:
                channel = struct.unpack('!H', data[0:2])[0]
                if 0x4000 <= channel <= 0x7FFF:
                    turn_ch = self._channels.get(channel)
                    if turn_ch:
                        return (data[4:], turn_ch.peer_addr)
                elif channel == 0:
                    if data[2:4] == struct.pack('!H', TurnMethod.DATA_INDICATION):
                        pass
            return (data, addr)
        except Exception:
            return None

    def refresh(self, lifetime: int = 600) -> bool:
        """
        Refresh allocation.

        Args:
            lifetime: Desired lifetime in seconds.

        Returns:
            True if successful.
        """
        if not self._sock:
            return False

        msg = bytearray()
        msg.extend(struct.pack('!HH', 0x0001, TurnMethod.REFRESH))
        msg.extend(struct.pack('!H', 0))
        msg.extend(self._transaction_id)

        attrs = bytearray()
        lifetime_data = struct.pack('!HI', 0x000D, lifetime)
        attrs.extend(lifetime_data)

        msg[4:6] = struct.pack('!H', len(attrs))
        msg.extend(attrs)

        try:
            self._sock.sendto(msg, (self._server, self._port))
            data, _ = self._sock.recvfrom(1024)
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close TURN client."""
        self.refresh(lifetime=0)
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


class TurnAllocation:
    """TURN allocation wrapper."""

    def __init__(
        self,
        server: str = "turn.example.com",
        port: int = 3478
    ):
        self._client = TurnClient(server, port)

    @property
    def relayed_address(self) -> Optional[Tuple[str, int]]:
        """Get relayed address."""
        return self._client.relayed_address

    def allocate(self) -> bool:
        """Allocate relayed address."""
        return self._client.allocate() is not None

    def add_permission(self, peer_addr: Tuple[str, int]) -> bool:
        """Add permission for peer."""
        return self._client.create_permission(peer_addr)

    def bind_channel(self, peer_addr: Tuple[str, int]) -> Optional[int]:
        """Bind channel to peer."""
        return self._client.channel_bind(peer_addr)

    def send(self, data: bytes, peer_addr: Tuple[str, int]) -> int:
        """Send data to peer."""
        return self._client.send_data(data, peer_addr)

    def receive(self) -> Optional[Tuple[bytes, Tuple[str, int]]]:
        """Receive data from peer."""
        return self._client.receive_data()

    def destroy(self) -> None:
        """Destroy allocation."""
        self._client.close()


def create_turn_client(
    server: str = "turn.example.com",
    port: int = 3478,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> TurnClient:
    """Create TURN client."""
    return TurnClient(server, port, username, password)
