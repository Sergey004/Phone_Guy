"""
pjlib - Foundation Layer

Portable foundation library providing platform abstraction:
- Socket abstraction (pj/sock.h)
- Async I/O queue (pj/ioqueue.h)
- Timer management (pj/timer.h)
- Memory pool (pj/pool.h)
- Threading and synchronization (pj/lock.h, pj/thread.h)
"""

from .sock import Socket, SockAddr, get_local_ip, get_local_hostname
from .ioqueue import IoQueue, IoKey, IoQueueWorker
from .timer import TimerHeap, TimerEntry, Timer, create_timer_heap, create_timer
from .pool import Pool, PoolImpl, create_pool
from .lock import Mutex, Event, Semaphore, RWMutex, Lock
from .thread import Thread, ThreadPool, create_thread, get_current_thread_name

__all__ = [
    'Socket', 'SockAddr', 'get_local_ip', 'get_local_hostname',
    'IoQueue', 'IoKey', 'IoQueueWorker',
    'TimerHeap', 'TimerEntry', 'Timer', 'create_timer_heap', 'create_timer',
    'Pool', 'PoolImpl', 'create_pool',
    'Mutex', 'Event', 'Semaphore', 'RWMutex', 'Lock',
    'Thread', 'ThreadPool', 'create_thread', 'get_current_thread_name',
]
