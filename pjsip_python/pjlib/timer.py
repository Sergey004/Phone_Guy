"""
pj/timer.h - Timer Management

Timer heap implementation for scheduling callbacks
to be executed after specified time intervals.
"""

import heapq
import threading
import time
from typing import Callable, Optional, Any, Dict, List
from dataclasses import dataclass, field
from enum import IntEnum


class TimerState(IntEnum):
    """Timer state constants."""
    IDLE = 0
    RUNNING = 1
    CANCELLED = 2


@dataclass(order=True)
class TimerEntry:
    """
    Timer entry for scheduling.

    Attributes:
        expire_time: Absolute time when timer expires.
        id: Unique timer ID.
        callback: Function to call when timer expires.
        user_data: User data to pass to callback.
        repeat: Repeat interval in seconds (0 for one-shot).
        state: Current timer state.
    """
    expire_time: float
    id: int = field(init=False, compare=False)
    callback: Callable = field(init=False, compare=False)
    user_data: Any = field(init=False, compare=False)
    repeat: float = field(init=False, compare=False)
    state: int = field(init=False, compare=False)

    def __post_init__(self):
        self.id = 0
        self.callback = lambda: None
        self.user_data = None
        self.repeat = 0.0
        self.state = TimerState.IDLE


class TimerHeap:
    """
    Timer heap for scheduling timeouts.

    Implements a priority queue based on expire_time,
    providing O(log n) scheduling and O(1) peek.
    """

    def __init__(self):
        self._heap: List[TimerEntry] = []
        self._lock = threading.Lock()
        self._next_id = 1

    def create_entry(
        self,
        callback: Callable,
        delay: float,
        user_data: Any = None,
        repeat: float = 0.0
    ) -> TimerEntry:
        """
        Create a timer entry without scheduling it.

        Args:
            callback: Function to call when timer expires.
            delay: Delay in seconds from now.
            user_data: User data to pass to callback.
            repeat: Repeat interval in seconds (0 for one-shot).

        Returns:
            TimerEntry instance.
        """
        entry = TimerEntry(
            expire_time=time.monotonic() + delay
        )
        entry.id = self._next_id
        self._next_id += 1
        entry.callback = callback
        entry.user_data = user_data
        entry.repeat = repeat
        entry.state = TimerState.IDLE
        return entry

    def schedule(self, entry: TimerEntry) -> bool:
        """
        Schedule a timer entry.

        Args:
            entry: TimerEntry to schedule.

        Returns:
            True if scheduled, False if already running or cancelled.
        """
        with self._lock:
            if entry.state != TimerState.IDLE:
                return False
            entry.state = TimerState.RUNNING
            heapq.heappush(self._heap, entry)
            return True

    def schedule_unique(
        self,
        id: int,
        callback: Callable,
        delay: float,
        user_data: Any = None,
        repeat: float = 0.0
    ) -> TimerEntry:
        """
        Schedule a timer, cancelling any existing timer with same ID.

        Args:
            id: Timer ID for uniqueness.
            callback: Function to call when timer expires.
            delay: Delay in seconds from now.
            user_data: User data to pass to callback.
            repeat: Repeat interval in seconds.

        Returns:
            Scheduled TimerEntry.
        """
        self.cancel_by_id(id)
        entry = self.create_entry(callback, delay, user_data, repeat)
        entry.id = id
        self.schedule(entry)
        return entry

    def cancel(self, entry: TimerEntry) -> bool:
        """
        Cancel a scheduled timer entry.

        Args:
            entry: TimerEntry to cancel.

        Returns:
            True if cancelled, False if not running.
        """
        with self._lock:
            if entry.state != TimerState.RUNNING:
                return False
            entry.state = TimerState.CANCELLED
            return True

    def cancel_by_id(self, id: int) -> bool:
        """
        Cancel a timer by its ID.

        Args:
            id: Timer ID.

        Returns:
            True if cancelled, False if not found.
        """
        with self._lock:
            for entry in self._heap:
                if entry.id == id:
                    if entry.state == TimerState.RUNNING:
                        entry.state = TimerState.CANCELLED
                        return True
            return False

    def poll(self, now: float) -> List[TimerEntry]:
        """
        Get and remove all expired timers.

        Args:
            now: Current time to compare against.

        Returns:
            List of expired TimerEntry instances.
        """
        expired = []
        with self._lock:
            while self._heap:
                if self._heap[0].expire_time > now:
                    break
                entry = heapq.heappop(self._heap)
                if entry.state == TimerState.RUNNING:
                    expired.append(entry)
                    if entry.repeat > 0:
                        entry.expire_time = now + entry.repeat
                        heapq.heappush(self._heap, entry)
                    else:
                        entry.state = TimerState.IDLE
        return expired

    def poll_once(self, now: float) -> Optional[TimerEntry]:
        """
        Get and remove the next expired timer.

        Args:
            now: Current time to compare against.

        Returns:
            Next expired TimerEntry or None.
        """
        with self._lock:
            if not self._heap:
                return None
            if self._heap[0].expire_time > now:
                return None
            entry = heapq.heappop(self._heap)
            if entry.state != TimerState.RUNNING:
                return None
            if entry.repeat > 0:
                entry.expire_time = now + entry.repeat
                heapq.heappush(self._heap, entry)
            else:
                entry.state = TimerState.IDLE
            return entry

    def peek(self) -> Optional[TimerEntry]:
        """
        Get the next timer without removing it.

        Returns:
            Next TimerEntry or None if heap is empty.
        """
        with self._lock:
            if not self._heap:
                return None
            return self._heap[0]

    def next_expire_time(self) -> Optional[float]:
        """
        Get the next expiration time.

        Returns:
            Time of next expiration or None.
        """
        entry = self.peek()
        return entry.expire_time if entry else None

    def next_expire_delay(self) -> float:
        """
        Get the delay until next expiration.

        Returns:
            Delay in seconds (float), negative if expired.
        """
        entry = self.peek()
        if not entry:
            return -1.0
        return max(0, entry.expire_time - time.monotonic())

    def count(self) -> int:
        """Get the number of scheduled timers."""
        with self._lock:
            return len(self._heap)

    def count_active(self) -> int:
        """Get the number of running (not cancelled) timers."""
        with self._lock:
            return sum(1 for e in self._heap if e.state == TimerState.RUNNING)

    def heap(self) -> List[TimerEntry]:
        """
        Get a copy of the internal heap.

        Returns:
            Copy of the timer heap.
        """
        with self._lock:
            return list(self._heap)

    def destroy(self) -> None:
        """Destroy the timer heap and cancel all timers."""
        with self._lock:
            for entry in self._heap:
                entry.state = TimerState.CANCELLED
            self._heap.clear()


class Timer:
    """
    High-level timer interface.

    Wrapper around TimerHeap for simple one-shot and
    repeating timers.
    """

    def __init__(self, heap: Optional[TimerHeap] = None):
        """
        Initialize timer.

        Args:
            heap: Optional TimerHeap to use (creates new if None).
        """
        self._heap = heap if heap is not None else TimerHeap()
        self._entry: Optional[TimerEntry] = None
        self._lock = threading.Lock()

    @property
    def heap(self) -> TimerHeap:
        """Get the underlying timer heap."""
        return self._heap

    def schedule(
        self,
        callback: Callable,
        delay: float,
        repeat: float = 0.0
    ) -> bool:
        """
        Schedule a callback.

        Args:
            callback: Function to call.
            delay: Delay in seconds.
            repeat: Repeat interval (0 for one-shot).

        Returns:
            True if scheduled, False if already running.
        """
        with self._lock:
            if self._entry and self._entry.state == TimerState.RUNNING:
                return False
            self._entry = self._heap.create_entry(callback, delay, None, repeat)
            self._heap.schedule(self._entry)
            return True

    def cancel(self) -> bool:
        """
        Cancel the scheduled callback.

        Returns:
            True if cancelled, False if not running.
        """
        with self._lock:
            if not self._entry:
                return False
            result = self._heap.cancel(self._entry)
            self._entry = None
            return result

    def running(self) -> bool:
        """Check if timer is running."""
        with self._lock:
            return (
                self._entry is not None and
                self._entry.state == TimerState.RUNNING
            )

    def destroy(self) -> None:
        """Destroy the timer."""
        self.cancel()
        self._heap.destroy()


def create_timer_heap() -> TimerHeap:
    """Create a new timer heap."""
    return TimerHeap()


def create_timer(heap: Optional[TimerHeap] = None) -> Timer:
    """Create a new timer."""
    return Timer(heap)
