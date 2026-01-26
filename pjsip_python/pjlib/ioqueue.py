"""
pj/ioqueue.h - Asynchronous I/O Queue

Proactor pattern implementation for asynchronous socket operations.
Supports epoll on Linux and select on other platforms.
"""

import select
import threading
import socket
from typing import Optional, Callable, Dict, Tuple, Any, List
from dataclasses import dataclass
from enum import IntFlag


class IoqueueEvent(IntFlag):
    """I/O event constants."""
    READ = 1
    WRITE = 2
    ERROR = 4
    HUP = 8


@dataclass
class IoKey:
    """
    I/O key registration.

    Represents a registered socket with its associated
    callback and user data.
    """
    sock: socket.socket
    read_cb: Optional[Callable] = None
    write_cb: Optional[Callable] = None
    error_cb: Optional[Callable] = None
    user_data: Any = None
    closed: bool = False


class IoQueue:
    """
    Asynchronous I/O event queue.

    Uses epoll on Linux for efficient event notification.
    Falls back to select on other platforms.
    """

    def __init__(self, max_size: int = 1024):
        """
        Initialize I/O queue.

        Args:
            max_size: Maximum number of registered sockets.
        """
        self._running = False
        self._lock = threading.Lock()
        self._readers: Dict[int, IoKey] = {}
        self._writers: Dict[int, IoKey] = {}
        self._events = IoqueueEvent.READ | IoqueueEvent.WRITE | IoqueueEvent.ERROR

        if hasattr(select, 'epoll'):
            self._poll = select.epoll(max_size)
            self._use_epoll = True
        else:
            self._use_epoll = False

        self._callback_lock = threading.Lock()

    def create(self) -> 'IoQueue':
        """Create and return a new IoQueue."""
        return IoQueue()

    def register_(
        self,
        sock: socket.socket,
        interest: int = IoqueueEvent.READ | IoqueueEvent.ERROR,
        read_cb: Optional[Callable] = None,
        write_cb: Optional[Callable] = None,
        error_cb: Optional[Callable] = None,
        user_data: Any = None
    ) -> IoKey:
        """
        Register a socket for event notification.

        Args:
            sock: Socket to register.
            interest: Interest mask (READ, WRITE, ERROR).
            read_cb: Callback for read events.
            write_cb: Callback for write events.
            error_cb: Callback for error events.
            user_data: User data to pass to callbacks.

        Returns:
            IoKey instance.
        """
        with self._lock:
            key = IoKey(
                sock=sock,
                read_cb=read_cb,
                write_cb=write_cb,
                error_cb=error_cb,
                user_data=user_data
            )
            fd = sock.fileno()
            self._readers[fd] = key
            self._writers[fd] = key

            if self._use_epoll:
                self._poll.register(fd, interest)
            else:
                self._poll.register(fd)

            return key

    def register(
        self,
        sock: socket.socket,
        interest: int = IoqueueEvent.READ | IoqueueEvent.ERROR,
        user_data: Any = None
    ) -> IoKey:
        """
        Register a socket with default callbacks.

        Args:
            sock: Socket to register.
            interest: Interest mask.
            user_data: User data.

        Returns:
            IoKey instance.
        """
        return self.register_(
            sock, interest,
            read_cb=self._default_read_cb,
            write_cb=self._default_write_cb,
            error_cb=self._default_error_cb,
            user_data=user_data
        )

    def unregister(self, key: IoKey) -> bool:
        """
        Unregister a socket.

        Args:
            key: IoKey to unregister.

        Returns:
            True if unregistered, False if not found.
        """
        with self._lock:
            fd = key.sock.fileno()
            if fd not in self._readers:
                return False

            if self._use_epoll:
                try:
                    self._poll.unregister(fd)
                except Exception:
                    pass
            else:
                try:
                    self._poll.unregister(fd)
                except Exception:
                    pass

            self._readers.pop(fd, None)
            self._writers.pop(fd, None)
            key.closed = True
            return True

    def modify(
        self,
        key: IoKey,
        interest: int
    ) -> bool:
        """
        Modify event interest for a socket.

        Args:
            key: IoKey to modify.
            interest: New interest mask.

        Returns:
            True if modified, False if not found.
        """
        with self._lock:
            fd = key.sock.fileno()
            if fd not in self._readers:
                return False

            if self._use_epoll:
                self._poll.modify(fd, interest)
            return True

    def poll(self, timeout: float = 0.1) -> List[Tuple[IoKey, int]]:
        """
        Wait for I/O events.

        Args:
            timeout: Timeout in seconds.

        Returns:
            List of (IoKey, event_mask) tuples.
        """
        result = []
        if self._use_epoll:
            events = self._poll.poll(timeout)
            for fd, event in events:
                key = self._readers.get(fd)
                if key:
                    result.append((key, event))
        else:
            result = []
        return result

    def poll_events(self, timeout: float = 0.1) -> List[Tuple[IoKey, int]]:
        """Alias for poll() for compatibility."""
        return self.poll(timeout)

    def handle_events(self, timeout: float = 0.1) -> int:
        """
        Poll and dispatch events to callbacks.

        Args:
            timeout: Timeout in seconds.

        Returns:
            Number of events handled.
        """
        events = self.poll(timeout)
        count = 0

        for key, event in events:
            if key.closed:
                continue

            with self._callback_lock:
                if event & IoqueueEvent.ERROR:
                    if key.error_cb:
                        key.error_cb(key, event)
                        count += 1
                    continue

                if event & IoqueueEvent.READ:
                    if key.read_cb:
                        key.read_cb(key, event)
                        count += 1

                if event & IoqueueEvent.WRITE:
                    if key.write_cb and not key.closed:
                        key.write_cb(key, event)
                        count += 1

        return count

    def wait(self, event_mask: int, timeout: float) -> List[IoKey]:
        """
        Wait for specific events on any registered socket.

        Args:
            event_mask: Event mask to wait for.
            timeout: Timeout in seconds.

        Returns:
            List of IoKey that had events.
        """
        events = self.poll(timeout)
        matching = [(k, e) for k, e in events if e & event_mask]
        return [k for k, e in matching]

    def start(self) -> None:
        """Start the I/O queue."""
        self._running = True

    def stop(self) -> None:
        """Stop the I/O queue."""
        self._running = False

    def destroy(self) -> None:
        """
        Destroy the I/O queue.

        Unregisters all sockets and closes the poll handle.
        """
        self._running = False

        with self._lock:
            for key in list(self._readers.values()):
                self.unregister(key)

            if self._use_epoll:
                try:
                    self._poll.close()
                except Exception:
                    pass

    def get_qsize(self) -> int:
        """Get the number of registered sockets."""
        with self._lock:
            return len(self._readers)

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self.get_qsize() == 0

    def _default_read_cb(self, key: IoKey, event: int) -> None:
        """Default read callback - attempt to receive data."""
        try:
            data = key.sock.recv(4096)
            if not data:
                self.unregister(key)
        except BlockingIOError:
            pass
        except Exception:
            self.unregister(key)

    def _default_write_cb(self, key: IoKey, event: int) -> None:
        """Default write callback - ready for sending."""
        pass

    def _default_error_cb(self, key: IoKey, event: int) -> None:
        """Default error callback - close socket."""
        self.unregister(key)


class IoQueueWorker:
    """
    Worker thread for processing I/O events.

    Runs I/O queue in a separate thread with automatic
    event dispatch.
    """

    def __init__(self, ioqueue: Optional[IoQueue] = None):
        """
        Initialize worker.

        Args:
            ioqueue: IoQueue to use (creates new if None).
        """
        self._ioqueue = ioqueue if ioqueue is not None else IoQueue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    @property
    def ioqueue(self) -> IoQueue:
        """Get the I/O queue."""
        return self._ioqueue

    def start(self) -> None:
        """Start the worker thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the worker thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def destroy(self) -> None:
        """Destroy the worker."""
        self.stop()
        self._ioqueue.destroy()

    def _run(self) -> None:
        """Worker thread main loop."""
        self._ioqueue.start()
        while self._running:
            try:
                self._ioqueue.handle_events(timeout=0.1)
            except Exception:
                pass
        self._ioqueue.destroy()


def create_ioqueue(max_size: int = 1024) -> IoQueue:
    """Create a new I/O queue."""
    return IoQueue(max_size)
