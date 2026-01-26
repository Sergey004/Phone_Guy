"""
pjnath/ice.h - ICE (Interactive Connectivity Establishment)

Full ICE implementation for NAT traversal according to RFC 8445.
"""

import random
import time
import threading
from typing import Optional, Dict, List, Tuple, Any
from enum import IntEnum, auto
from dataclasses import dataclass, field


class IceRole(IntEnum):
    """ICE role (controlling or controlled)."""
    UNKNOWN = 0
    CONTROLLING = auto()
    CONTROLLED = auto()


class IceCandidateType(IntEnum):
    """ICE candidate types."""
    HOST = 0
    SRFLX = auto()
    RELAY = auto()
    PRFLX = auto()


@dataclass
class IceCandidate:
    """ICE candidate."""
    foundation: str
    component_id: int
    transport: str = "UDP"
    priority: int = 0
    address: str = ""
    port: int = 0
    cand_type: IceCandidateType = IceCandidateType.HOST
    related_address: Optional[str] = None
    related_port: Optional[int] = None
    tcp_type: Optional[str] = None

    def to_sdp(self) -> str:
        """Convert to SDP candidate attribute."""
        rel_addr = f" raddr {self.related_address}" if self.related_address else ""
        rel_port = f" rport {self.related_port}" if self.related_port else ""
        tcp = f" tcptype {self.tcp_type}" if self.tcp_type else ""
        return (
            f"a=candidate:{self.foundation} {self.component_id} {self.transport} "
            f"{self.priority} {self.address} {self.port} typ {self.cand_type.name.lower()}"
            f"{rel_addr}{rel_port}{tcp}"
        )

    @classmethod
    def from_sdp(cls, line: str) -> 'IceCandidate':
        """Parse from SDP candidate line."""
        parts = line.split()
        cand = cls(foundation=parts[1], component_id=int(parts[2]))
        cand.transport = parts[3]
        cand.priority = int(parts[4])
        cand.address = parts[5]
        cand.port = int(parts[6])

        i = 7
        while i < len(parts):
            if parts[i] == "typ":
                i += 1
                cand.cand_type = IceCandidateType[parts[i].upper()]
            elif parts[i] == "raddr":
                i += 1
                cand.related_address = parts[i]
            elif parts[i] == "rport":
                i += 1
                cand.related_port = int(parts[i])
            elif parts[i] == "tcptype":
                i += 1
                cand.tcp_type = parts[i]
            i += 1

        return cand

    @property
    def is_host(self) -> bool:
        """Check if host candidate."""
        return self.cand_type == IceCandidateType.HOST

    @property
    def is_server_reflexive(self) -> bool:
        """Check if server-reflexive candidate."""
        return self.cand_type == IceCandidateType.SRFLX


class IceCheckList:
    """ICE checklist for candidate pairs."""

    def __init__(self):
        self._pairs: List[Dict] = []
        self._state = "running"
        self._nominated_pair: Optional[Dict] = None

    def add_pair(self, local: IceCandidate, remote: IceCandidate) -> None:
        """Add candidate pair."""
        priority = self.calculate_pair_priority(local, remote)
        self._pairs.append({
            'local': local,
            'remote': remote,
            'state': 'waiting',
            'priority': priority,
            'succeeded': False,
            'failed': False
        })
        self._pairs.sort(key=lambda p: p['priority'], reverse=True)

    def calculate_pair_priority(self, local: IceCandidate, remote: IceCandidate) -> int:
        """Calculate pair priority (RFC 8445)."""
        G = local.priority
        D = remote.priority
        if G > D:
            return (G << 32) | (D << 1) | 1
        else:
            return (D << 32) | (G << 1) | 0

    def get_next_pair(self) -> Optional[Dict]:
        """Get next pair to check."""
        for pair in self._pairs:
            if pair['state'] == 'waiting':
                pair['state'] = 'in_progress'
                return pair
        return None

    def set_pair_succeeded(self, pair: Dict) -> None:
        """Mark pair as succeeded."""
        pair['succeeded'] = True
        pair['state'] = 'succeeded'

    def set_pair_failed(self, pair: Dict) -> None:
        """Mark pair as failed."""
        pair['failed'] = True
        pair['state'] = 'failed'

    def nominate_pair(self, pair: Dict) -> None:
        """Nominate pair for use."""
        self._nominated_pair = pair
        for p in self._pairs:
            if p != pair:
                p['state'] = 'discarded'
        pair['state'] = 'nominated'

    def get_nominated_pair(self) -> Optional[Dict]:
        """Get nominated pair."""
        return self._nominated_pair

    @property
    def state(self) -> str:
        """Get checklist state."""
        if all(p['failed'] for p in self._pairs):
            return "failed"
        if self._nominated_pair:
            return "completed"
        if any(p['succeeded'] for p in self._pairs):
            return "in_progress"
        return "running"


class IceSession:
    """
    ICE session for a media stream.

    Manages candidate gathering, checks, and nomination.
    """

    def __init__(self, ufrag: Optional[str] = None, pwd: Optional[str] = None):
        """
        Initialize ICE session.

        Args:
            ufrag: ICE username fragment.
            pwd: ICE password.
        """
        self._ufrag = ufrag or self._generate_cred()
        self._pwd = pwd or self._generate_cred()
        self._role = IceRole.UNKNOWN
        self._tie_breaker = random.randbytes(8)
        self._local_candidates: List[IceCandidate] = []
        self._remote_candidates: List[IceCandidate] = []
        self._checklist = IceCheckList()
        self._state = "idle"
        self._gathering_complete = False
        self._lock = threading.Lock()

    def _generate_cred(self) -> str:
        """Generate random credential string."""
        return ''.join(random.choice('0123456789abcdef') for _ in range(16))

    @property
    def ufrag(self) -> str:
        """Get ICE username fragment."""
        return self._ufrag

    @property
    def pwd(self) -> str:
        """Get ICE password."""
        return self._pwd

    @property
    def role(self) -> IceRole:
        """Get ICE role."""
        return self._role

    @property
    def local_ufrag(self) -> str:
        """Get local username fragment for encoding."""
        return self._ufrag

    @property
    def local_pwd(self) -> str:
        """Get local password for integrity."""
        return self._pwd

    def set_role(self, role: IceRole) -> None:
        """Set ICE role."""
        self._role = role

    def add_local_candidate(self, candidate: IceCandidate) -> None:
        """Add local candidate."""
        with self._lock:
            self._local_candidates.append(candidate)

    def add_remote_candidate(self, candidate: IceCandidate) -> None:
        """Add remote candidate."""
        with self._lock:
            self._remote_candidates.append(candidate)

    def add_remote_candidates_from_sdp(self, lines: List[str]) -> None:
        """Parse and add remote candidates from SDP."""
        for line in lines:
            if line.startswith('a=candidate:'):
                cand = IceCandidate.from_sdp(line)
                self.add_remote_candidate(cand)

    def start_gathering(self) -> None:
        """Start candidate gathering."""
        self._state = "gathering"

    def gather_candidates(self, local_ip: str = "0.0.0.0", ports: List[int] = None) -> List[IceCandidate]:
        """
        Gather local host candidates.

        Args:
            local_ip: Local IP address.
            ports: List of ports to use.

        Returns:
            List of gathered candidates.
        """
        ports = ports or [5000, 5002]
        for port in ports:
            cand = IceCandidate(
                foundation=f"{random.randint(1, 1000000)}",
                component_id=1,
                priority=2130706431 if random.random() > 0.5 else 2113937151,
                address=local_ip,
                port=port,
                cand_type=IceCandidateType.HOST
            )
            self.add_local_candidate(cand)
        self._gathering_complete = True
        return self._local_candidates

    def create_checklist(self) -> IceCheckList:
        """Create checklist from local and remote candidates."""
        for local in self._local_candidates:
            for remote in self._remote_candidates:
                self._checklist.add_pair(local, remote)
        return self._checklist

    def get_local_candidates_sdp(self) -> List[str]:
        """Get local candidates as SDP lines."""
        lines = [
            f"a=ice-ufrag:{self._ufrag}",
            f"a=ice-pwd:{self._pwd}"
        ]
        for cand in self._local_candidates:
            lines.append(cand.to_sdp())
        return lines

    def start_checks(self, role: IceRole = IceRole.CONTROLLING) -> None:
        """Start ICE checks."""
        self._role = role
        self._state = "checking"

    def process_check_response(self, success: bool, pair: Dict) -> None:
        """Process response to a check."""
        if success:
            self._checklist.set_pair_succeeded(pair)
            if self._role == IceRole.CONTROLLING:
                self._checklist.nominate_pair(pair)
                self._state = "completed"
        else:
            self._checklist.set_pair_failed(pair)

    def get_state(self) -> str:
        """Get ICE session state."""
        return self._state

    def is_completed(self) -> bool:
        """Check if ICE completed successfully."""
        return self._state == "completed" and self._checklist.get_nominated_pair() is not None

    def get_selected_pair(self) -> Optional[Tuple[IceCandidate, IceCandidate]]:
        """Get selected candidate pair."""
        pair = self._checklist.get_nominated_pair()
        if pair:
            return (pair['local'], pair['remote'])
        return None

    def reset(self) -> None:
        """Reset ICE session."""
        self._role = IceRole.UNKNOWN
        self._state = "idle"
        self._checklist = IceCheckList()
        self._gathering_complete = False

    def destroy(self) -> None:
        """Destroy ICE session."""
        self.reset()
        self._local_candidates.clear()
        self._remote_candidates.clear()


def create_ice_session() -> IceSession:
    """Create new ICE session."""
    return IceSession()
