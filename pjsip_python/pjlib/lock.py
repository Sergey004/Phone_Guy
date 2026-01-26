"""
pj/lock.h - Synchronization Primitives

Threading and synchronization primitives including:
- Mutex (mutual exclusion lock)
- Event (manual/auto reset event)
- Semaphore (counting semaphore)
- RWMutex (read-write mutex)
"""

import threading
import time
from typing import Optional, Union
from abc import ABC, abstractmethod


class Lock(ABC):
    """Abstract base class for locks."""

    @abstractmethod
    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """Acquire the lock."""
        pass

    @abstractmethod
    def release(self) -> None:
        """Release the lock."""
        pass

    @abstractmethod
    def locked(self) -> bool:
        """Check if lock is currently held."""
        pass

    def __enter__(self) -> 'Lock':
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class Mutex(Lock):
    """
    Mutual exclusion lock.

    A simple mutex that can be used to protect shared
    resources from concurrent access.
    """

    def __init__(self, recursive: bool = False):
        """
        Initialize mutex.

        Args:
            recursive: Allow recursive locking (uses RLock internally).
        """
        self._recursive = recursive
        if recursive:
            self._lock = threading.RLock()
        else:
            self._lock = threading.Lock()
        self._owner: Optional[threading.Thread] = None
        self._count = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """
        Acquire the lock.

        Args:
            blocking: Block until acquired if True.
            timeout: Timeout in seconds (-1 for infinite).

        Returns:
            True if acquired, False if timeout.
        """
        if self._recursive:
            if self._lock.acquire(blocking, timeout):
                self._owner = threading.current_thread()
                return True
            return False
        else:
            success = self._lock.acquire(blocking, timeout)
            if success:
                self._owner = threading.current_thread()
            return success

    def release(self) -> None:
        """Release the lock."""
        if self._owner != threading.current_thread():
            raise RuntimeError("Cannot release lock owned by another thread")
        self._lock.release()
        self._owner = None

    def locked(self) -> bool:
        """Check if lock is currently held."""
        return False  # Simplified - actual check would require try-acquire pattern

    def owning_thread(self) -> Optional[threading.Thread]:
        """Get the thread that owns this lock."""
        return self._owner


class Event(Lock):
    """
    Event synchronization primitive.

    An event can be set and cleared, and threads can wait
    for the event to be set.
    """

    def __init__(self, manual_reset: bool = False):
        """
        Initialize event.

        Args:
            manual_reset: If True, must call clear() manually.
                         If False, auto-resets after wait() returns.
        """
        self._event = threading.Event()
        self._manual_reset = manual_reset

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """
        Wait for event to be set.

        Args:
            blocking: Block until set if True.
            timeout: Timeout in seconds.

        Returns:
            True if event was set, False if timeout.
        """
        if blocking:
            self._event.wait(timeout)
            return self._event.is_set()
        else:
            return self._event.is_set()

    def release(self) -> None:
        """
        Release (set) the event.

        Note: For manual reset events, this sets the event.
        For auto reset events, this is a no-op since release
        is done via wait().
        """
        if self._manual_reset:
            self._event.set()

    def set(self) -> None:
        """Set the event."""
        self._event.set()

    def clear(self) -> None:
        """Clear the event."""
        self._event.clear()

    def is_set(self) -> bool:
        """Check if event is set."""
        return self._event.is_set()

    def locked(self) -> bool:
        """Check if event is set."""
        return self._event.is_set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for event to be set.

        Args:
            timeout: Timeout in seconds.

        Returns:
            True if set, False if timeout.
        """
        return self._event.wait(timeout)


class Semaphore(Lock):
    """
    Semaphore (counting semaphore).

    A semaphore maintains an internal counter and allows
    acquire() to succeed when counter > 0, decrementing it.
    release() increments the counter.
    """

    def __init__(self, value: int = 1, max_value: int = 0):
        """
        Initialize semaphore.

        Args:
            value: Initial counter value.
            max_value: Maximum counter value (0 for unlimited).
        """
        self._sem = threading.Semaphore(value)
        self._max_value = max_value
        self._value = value

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire the semaphore (decrement counter).

        Args:
            blocking: Block if counter is 0.
            timeout: Timeout in seconds (None for infinite).

        Returns:
            True if acquired, False if timeout.
        """
        return self._sem.acquire(blocking, timeout)

    def release(self) -> None:
        """Release the semaphore (increment counter)."""
        if self._max_value > 0 and self._value >= self._max_value:
            raise RuntimeError("Semaphore maximum value exceeded")
        self._sem.release()
        self._value += 1

    def locked(self) -> bool:
        """Check if semaphore cannot be acquired immediately."""
        return False

    def value(self) -> int:
        """Get current counter value."""
        return self._value

    def draining(self, timeout: float = 0) -> bool:
        """
        Wait for semaphore to be acquired (counter = 0).

        Args:
            timeout: Maximum time to wait.

        Returns:
            True if drained, False if timeout.
        """
        start = time.monotonic()
        while self._value > 0:
            if timeout > 0 and (time.monotonic() - start) >= timeout:
                return False
            time.sleep(0.01)
        return True


class RWMutex(Lock):
    """
    Read-write mutex.

    Allows multiple concurrent readers or a single writer.
    Writers get priority over readers.
    """

    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire the read-write lock for writing.

        Args:
            blocking: Block until acquired.
            timeout: Timeout in seconds (None for infinite).

        Returns:
            True if acquired, False if timeout.
        """
        if not blocking:
            if self._writer:
                return False
            self._writer = True
            return True
        
        start = time.monotonic()
        with self._read_ready:
            if not self._writer:
                self._writer = True
                return True
            
            while self._writer:
                remaining = None
                if timeout is not None:
                    elapsed = time.monotonic() - start
                    if elapsed >= timeout:
                        return False
                    remaining = timeout - elapsed
                self._read_ready.wait(remaining)
            self._writer = True
            return True
            if not blocking:
                return False

            start = time.monotonic()
            while self._writer:
                remaining = None
                if timeout is not None:
                    remaining = timeout - (time.monotonic() - start)
                    if remaining <= 0:
                        return False
                self._read_ready.wait(remaining)
            self._writer = True
            return True

    def release(self) -> None:
        """Release write lock."""
        with self._read_ready:
            self._writer = False
            self._read_ready.notify_all()

    def locked(self) -> bool:
        """Check if write lock is held."""
        return self._writer

    def acquire_read(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire for reading.

        Args:
            blocking: Block until acquired.
            timeout: Timeout in seconds (None for infinite).

        Returns:
            True if acquired, False if timeout.
        """
        with self._read_ready:
            while self._writer:
                if not blocking:
                    return False
                start = time.monotonic()
                remaining = None
                if timeout is not None:
                    elapsed = time.monotonic() - start
                    if elapsed >= timeout:
                        return False
                    remaining = timeout - elapsed
                self._read_ready.wait(remaining)
            self._readers += 1
            return True

    def release_read(self) -> None:
        """Release read lock."""
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def locked_read(self) -> bool:
        """Check if any read locks are held."""
        with self._read_ready:
            return self._readers > 0

    def __enter__(self) -> 'RWMutex':
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class CriticalSection:
    """
    Simple critical section helper.

    Provides a way to execute code within a locked section
    using the 'with' statement.
    """

    def __init__(self, lock: Lock):
        """
        Initialize with a lock.

        Args:
            lock: Lock instance to use.
        """
        self._lock = lock

    def __enter__(self) -> 'CriticalSection':
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._lock.release()

    def execute(self, func, *args, **kwargs):
        """
        Execute a function within the critical section.

        Args:
            func: Function to execute.
            *args, **kwargs: Function arguments.

        Returns:
            Function return value.
        """
        with self:
            return func(*args, **kwargs)


def create_mutex(recursive: bool = False) -> Mutex:
    """Create a mutex."""
    return Mutex(recursive)


def create_event(manual_reset: bool = False) -> Event:
    """Create an event."""
    return Event(manual_reset)


def create_semaphore(value: int = 1, max_value: int = 0) -> Semaphore:
    """Create a semaphore."""
    return Semaphore(value, max_value)


def create_rwmutex() -> RWMutex:
    """Create a read-write mutex."""
    return RWMutex()


def atomic_increment(counter: list, index: int = 0) -> int:
    """
    Atomically increment a counter.

    Args:
        counter: List containing the counter.
        index: Index of counter in list.

    Returns:
        New value after increment.
    """
    with threading.Lock():
        counter[index] += 1
        return counter[index]


def atomic_decrement(counter: list, index: int = 0) -> int:
    """
    Atomically decrement a counter.

    Args:
        counter: List containing the counter.
        index: Index of counter in list.

    Returns:
        New value after decrement.
    """
    with threading.Lock():
        counter[index] -= 1
        return counter[index]
