"""
pjnath/stun.h - STUN Client

STUN (Session Traversal Utilities for NAT) client implementation.
Used for NAT detection and obtaining mapped addresses.
"""

import socket
import random
import struct
import time
from typing import Optional, Dict, Any, Tuple, List
from enum import IntEnum
from dataclasses import dataclass


class StunMethod(IntEnum):
    """STUN methods."""
    BINDING = 0x0001
    SHARED_SECRET = 0x0002


class StunClass(IntEnum):
    """STUN message class."""
    REQUEST = 0x0000
    INDICATION = 0x0010
    SUCCESS_RESPONSE = 0x0100
    ERROR_RESPONSE = 0x0110


class StunAttribute(IntEnum):
    """STUN attributes."""
    MAPPED_ADDRESS = 0x0001
    RESPONSE_ADDRESS = 0x0002
    CHANGE_REQUEST = 0x0003
    SOURCE_ADDRESS = 0x0004
    CHANGED_ADDRESS = 0x0005
    USERNAME = 0x0006
    PASSWORD = 0x0007
    MESSAGE_INTEGRITY = 0x0008
    ERROR_CODE = 0x0009
    UNKNOWN_ATTRIBUTES = 0x000A
    REALM = 0x0014
    NONCE = 0x0015
    XOR_MAPPED_ADDRESS = 0x0020
    SOFTWARE = 0x8022
    ALTERNATE_SERVER = 0x8023
    FINGERPRINT = 0x8028


class NatType(IntEnum):
    """NAT type classification."""
    UNKNOWN = 0
    OPEN_INTERNET = 1
    BLOCKED = 2
    FULL_CONE = 3
    RESTRICTED_CONE = 4
    PORT_RESTRICTED_CONE = 5
    SYMMETRIC = 6


@dataclass
class StunMessage:
    """STUN message representation."""
    method: int = 0
    class_: int = 0
    transaction_id: bytes = b""
    attributes: Dict[int, bytes] = None

    def __post_init__(self):
        if self.attributes is None:
            self.attributes = {}

    @property
    def type(self) -> int:
        """Get message type."""
        return (self.class_ << 4) | (self.method & 0x0F) | ((self.method & 0x0070) << 2)

    def build(self) -> bytes:
        """Build STUN message to bytes."""
        data = bytearray(20)
        data[0:2] = struct.pack('!H', self.type)
        data[2:4] = struct.pack('!H', len(self.attributes) * 4 + 8)
        data[4:20] = self.transaction_id

        for attr_type, attr_value in self.attributes.items():
            attr_data = bytearray()
            attr_data.extend(struct.pack('!H', attr_type))
            attr_data.extend(struct.pack('!H', len(attr_value)))
            attr_data.extend(attr_value)
            if len(attr_value) % 4 != 0:
                attr_data.extend(b'\x00' * (4 - len(attr_value) % 4))
            data.extend(attr_data)

        return bytes(data)

    @classmethod
    def parse(cls, data: bytes) -> 'StunMessage':
        """Parse STUN message from bytes."""
        msg = cls()
        if len(data) < 20:
            return msg

        msg_type = struct.unpack('!H', data[0:2])[0]
        msg.method = (msg_type & 0x000F) | ((msg_type & 0x0070) << 2)
        msg.class_ = (msg_type & 0x0010) | ((msg_type & 0x0100) >> 2)
        msg.transaction_id = data[4:20]

        offset = 20
        while offset < len(data):
            attr_type = struct.unpack('!H', data[offset:offset+2])[0]
            attr_len = struct.unpack('!H', data[offset+2:offset+4])[0]
            offset += 4
            attr_value = data[offset:offset+attr_len]
            msg.attributes[attr_type] = attr_value
            offset += attr_len
            if attr_len % 4 != 0:
                offset += (4 - attr_len % 4)

        return msg

    @classmethod
    def create_binding_request(cls, transaction_id: Optional[bytes] = None) -> 'StunMessage':
        """Create STUN Binding request."""
        msg = cls()
        msg.method = StunMethod.BINDING
        msg.class_ = StunClass.REQUEST
        msg.transaction_id = transaction_id or random.randbytes(16)
        return msg

    def get_mapped_address(self) -> Optional[Tuple[str, int]]:
        """Get mapped address from message."""
        if StunAttribute.MAPPED_ADDRESS in self.attributes:
            data = self.attributes[StunAttribute.MAPPED_ADDRESS]
            if len(data) >= 8:
                family = data[1]
                port = struct.unpack('!H', data[2:4])[0]
                if family == 1:
                    addr = socket.inet_ntoa(data[4:8])
                    return (addr, port)
        if StunAttribute.XOR_MAPPED_ADDRESS in self.attributes:
            data = self.attributes[StunAttribute.XOR_MAPPED_ADDRESS]
            if len(data) >= 8:
                family = data[1]
                port = struct.unpack('!H', data[2:4])[0] ^ 0x2112
                if family == 1:
                    addr = socket.inet_ntoa(
                        struct.pack('!I', struct.unpack('!I', data[4:8])[0] ^ 0x2112A442)
                    )
                    return (addr, port)
        return None


class StunClient:
    """
    STUN client for NAT detection and mapped address discovery.
    """

    DEFAULT_STUN_SERVER = "stun.l.google.com"
    DEFAULT_STUN_PORT = 19302

    def __init__(
        self,
        server: str = "stun.l.google.com",
        port: int = 19302,
        timeout: float = 2.0
    ):
        """
        Initialize STUN client.

        Args:
            server: STUN server hostname.
            port: STUN server port.
            timeout: Request timeout in seconds.
        """
        self._server = server
        self._port = port
        self._timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._mapped_addr: Optional[Tuple[str, int]] = None
        self._nat_type = NatType.UNKNOWN

    def _create_socket(self) -> bool:
        """Create UDP socket."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(self._timeout)
            self._sock.bind(('0.0.0.0', 0))
            return True
        except Exception:
            return False

    def get_mapped_address(self, local_ip: str = "0.0.0.0") -> Optional[Tuple[str, int]]:
        """
        Get mapped address using STUN.

        Args:
            local_ip: Local IP to report.

        Returns:
            Tuple of (mapped_ip, mapped_port) or None.
        """
        if not self._create_socket():
            return None

        try:
            server_addr = (self._server, self._port)
            request = StunMessage.create_binding_request()
            self._sock.sendto(request.build(), server_addr)

            data, addr = self._sock.recvfrom(1024)
            response = StunMessage.parse(data)

            mapped = response.get_mapped_address()
            if mapped:
                self._mapped_addr = mapped
            return mapped

        except Exception:
            return None

    def detect_nat_type(self, local_ip: str = "0.0.0.0") -> NatType:
        """
        Detect NAT type.

        This is a simplified implementation that tests basic
        connectivity scenarios.

        Args:
            local_ip: Local IP address.

        Returns:
            Detected NAT type.
        """
        if not self._create_socket():
            return NatType.BLOCKED

        try:
            primary_mapped = self.get_mapped_address(local_ip)
            if not primary_mapped:
                self._nat_type = NatType.BLOCKED
                return self._nat_type

            if primary_mapped[0] == local_ip:
                self._nat_type = NatType.OPEN_INTERNET
                return self._nat_type

            self._nat_type = NatType.FULL_CONE
            return self._nat_type

        except Exception:
            self._nat_type = NatType.UNKNOWN
            return self._nat_type

    def close(self) -> None:
        """Close the STUN client."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    @property
    def mapped_address(self) -> Optional[Tuple[str, int]]:
        """Get last known mapped address."""
        return self._mapped_addr

    @property
    def nat_type(self) -> NatType:
        """Get detected NAT type."""
        return self._nat_type


def detect_nat_type(local_ip: str = "0.0.0.0") -> Tuple[NatType, Optional[Tuple[str, int]]]:
    """
    Simple NAT type detection.

    Args:
        local_ip: Local IP to report.

    Returns:
        Tuple of (nat_type, mapped_address).
    """
    client = StunClient()
    nat_type = client.detect_nat_type(local_ip)
    mapped_addr = client.mapped_address
    client.close()
    return nat_type, mapped_addr


def get_mapped_address(
    local_ip: str = "0.0.0.0",
    stun_server: str = "stun.l.google.com",
    stun_port: int = 19302
) -> Optional[Tuple[str, int]]:
    """
    Get mapped address from STUN server.

    Args:
        local_ip: Local IP to report.
        stun_server: STUN server hostname.
        stun_port: STUN server port.

    Returns:
        Tuple of (mapped_ip, mapped_port) or None.
    """
    client = StunClient(stun_server, stun_port)
    mapped = client.get_mapped_address(local_ip)
    client.close()
    return mapped
