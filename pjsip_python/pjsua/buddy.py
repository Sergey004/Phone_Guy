"""
pjsua/buddy.py - Presence Buddy

Presence subscription to buddies.
"""

from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import IntEnum, auto


class BuddyState(IntEnum):
    """Buddy states."""
    OFFLINE = 0
    ONLINE = auto()
    BUSY = auto()
    AWAY = auto()


@dataclass
class BuddyInfo:
    """Buddy information."""
    uri: str = ""
    display_name: str = ""
    status: BuddyState = BuddyState.OFFLINE
    note: str = ""
    subscribe_active: bool = False


class Buddy:
    """
    Presence buddy for subscription and monitoring.
    """

    def __init__(self):
        self._uri: str = ""
        self._display_name: str = ""
        self._state: BuddyState = BuddyState.OFFLINE
        self._note: str = ""
        self._subscribed: bool = False
        self._on_presence: Optional[Callable] = None

    @property
    def uri(self) -> str:
        """Get buddy URI."""
        return self._uri

    @property
    def state(self) -> BuddyState:
        """Get buddy presence state."""
        return self._state

    @property
    def info(self) -> BuddyInfo:
        """Get buddy info."""
        return BuddyInfo(
            uri=self._uri,
            display_name=self._display_name,
            status=self._state,
            note=self._note,
            subscribe_active=self._subscribed
        )

    def create(self, config: Dict[str, Any]) -> bool:
        """
        Create buddy from configuration.

        Args:
            config: Buddy configuration dict.

        Returns:
            True if created successfully.
        """
        self._uri = config.get('uri', '')
        self._display_name = config.get('display_name', '')
        return True

    def subscribe(self) -> bool:
        """
        Subscribe to buddy presence.

        Returns:
            True if subscribed successfully.
        """
        self._subscribed = True
        return True

    def unsubscribe(self) -> bool:
        """
        Unsubscribe from buddy presence.

        Returns:
            True if unsubscribed successfully.
        """
        self._subscribed = False
        return True

    def set_presence(self, status: BuddyState, note: str = "") -> None:
        """
        Update buddy presence (called by core).

        Args:
            status: New presence status.
            note: Status note.
        """
        self._state = status
        self._note = note
        if self._on_presence:
            try:
                self._on_presence(self, status, note)
            except Exception:
                pass

    def set_on_presence(self, callback: Callable) -> None:
        """Set callback for presence changes."""
        self._on_presence = callback


@dataclass
class BuddyConfig:
    """Buddy configuration."""
    uri: str = ""
    display_name: str = ""
    subscribe: bool = True


def create_buddy(config: Dict[str, Any]) -> Buddy:
    """Create buddy from config."""
    buddy = Buddy()
    buddy.create(config)
    return buddy
