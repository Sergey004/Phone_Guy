"""
pj/thread.h - Threading

Thread creation and management utilities.
"""

import threading
import time
from typing import Optional, Callable, Any, List, Dict
from dataclasses import dataclass
from enum import IntEnum


class ThreadPriority(IntEnum):
    """Thread priority constants (platform-dependent)."""
    LOWEST = 0
    BELOW_NORMAL = 1
    NORMAL = 2
    ABOVE_NORMAL = 3
    HIGHEST = 4


@dataclass
class ThreadDesc:
    """Thread description for creation."""
    name: str = "thread"
    priority: int = ThreadPriority.NORMAL
    stack_size: int = 0
    detached: bool = False


class Thread:
    """
    Thread wrapper with enhanced functionality.

    Provides a consistent interface for thread creation
    with additional features like naming and priority.
    """

    _thread_counter = 0
    _thread_lock = threading.Lock()

    def __init__(
        self,
        target: Optional[Callable] = None,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        daemon: bool = False
    ):
        """
        Initialize thread.

        Args:
            target: Function to run in thread.
            args: Positional arguments for target.
            kwargs: Keyword arguments for target.
            name: Thread name (auto-generated if None).
            daemon: Daemon thread flag.
        """
        Thread._thread_lock.acquire()
        if name is None:
            Thread._thread_counter += 1
            name = f"thread-{Thread._thread_counter}"
        Thread._thread_lock.release()

        self._target = target
        self._args = args
        self._kwargs = kwargs if kwargs else {}
        self._name = name
        self._daemon = daemon
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._finished = False
        self._result: Any = None
        self._exception: Optional[Exception] = None

    @property
    def name(self) -> str:
        """Get thread name."""
        return self._name

    @property
    def ident(self) -> Optional[int]:
        """Get thread identifier."""
        return self._thread.ident if self._thread else None

    @property
    def alive(self) -> bool:
        """Check if thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def daemon(self) -> bool:
        """Get daemon flag."""
        return self._daemon

    @daemon.setter
    def daemon(self, value: bool) -> None:
        """Set daemon flag (must be set before start)."""
        self._daemon = value
        if self._thread:
            self._thread.daemon = value

    def start(self) -> 'Thread':
        """
        Start the thread.

        Returns:
            Self for chaining.
        """
        if self._started:
            raise RuntimeError("Thread already started")

        self._started = True
        self._thread = threading.Thread(
            target=self._run_wrapper,
            name=self._name,
            daemon=self._daemon
        )
        self._thread.start()
        return self

    def _run_wrapper(self) -> None:
        """Wrapper to capture result/exception."""
        try:
            if self._target:
                self._result = self._target(*self._args, **self._kwargs)
        except Exception as e:
            self._exception = e
        finally:
            self._finished = True

    def run(self) -> None:
        """
        Run the target function directly.

        Override this method for subclassing.
        """
        if self._target:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for thread to complete.

        Args:
            timeout: Timeout in seconds.

        Returns:
            True if completed, False if timeout.
        """
        if not self._thread:
            return True

        self._thread.join(timeout)
        return not self._thread.is_alive()

    def is_alive(self) -> bool:
        """Check if thread is alive."""
        return self.alive

    def get_result(self) -> Any:
        """
        Get the result of the thread.

        Returns:
            Thread return value or None.
        """
        return self._result

    def get_exception(self) -> Optional[Exception]:
        """
        Get exception from thread.

        Returns:
            Exception if raised, None otherwise.
        """
        return self._exception

    def detach(self) -> None:
        """Detach thread (run in background)."""
        if self._thread and self._thread.is_alive():
            pass

    @classmethod
    def sleep(cls, seconds: float) -> None:
        """
        Sleep for specified seconds.

        Args:
            seconds: Sleep duration.
        """
        time.sleep(seconds)

    @classmethod
    def current_thread(cls) -> threading.Thread:
        """Get current thread."""
        return threading.current_thread()

    @classmethod
    def active_count(cls) -> int:
        """Get number of active threads."""
        return threading.active_count()

    @classmethod
    def enumerate(cls) -> List[threading.Thread]:
        """Get list of all active threads."""
        return threading.enumerate()


def create_thread(
    target: Callable,
    args: tuple = (),
    kwargs: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    daemon: bool = False
) -> Thread:
    """
    Create a new thread.

    Args:
        target: Function to run.
        args: Positional arguments.
        kwargs: Keyword arguments.
        name: Thread name.
        daemon: Daemon flag.

    Returns:
        Thread instance.
    """
    return Thread(target, args, kwargs, name, daemon)


def create_worker_thread(
    callback: Callable[[Any], Any],
    name: Optional[str] = None
) -> Thread:
    """
    Create a worker thread that calls a callback.

    Args:
        callback: Function to call in thread.
        name: Thread name.

    Returns:
        Thread instance.
    """
    return Thread(target=callback, name=name)


class ThreadPool:
    """
    Simple thread pool for executing tasks.

    Maintains a fixed number of worker threads and
    distributes tasks among them.
    """

    def __init__(self, num_threads: int = 4):
        """
        Initialize thread pool.

        Args:
            num_threads: Number of worker threads.
        """
        self._num_threads = num_threads
        self._threads: List[Thread] = []
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the thread pool."""
        self._running = True

    def stop(self) -> None:
        """Stop the thread pool."""
        self._running = False

    def submit(self, task: Callable, *args, **kwargs) -> None:
        """
        Submit a task for execution.

        Args:
            task: Function to execute.
            *args, **kwargs: Function arguments.
        """
        if not self._running:
            return
        thread = Thread(target=task, args=args, kwargs=kwargs)
        thread.start()


def get_current_thread_name() -> str:
    """Get current thread name."""
    return threading.current_thread().name


def is_main_thread() -> bool:
    """Check if current thread is main thread."""
    return threading.current_thread() is threading.main_thread()
