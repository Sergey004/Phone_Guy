"""
pj/pool.h - Memory Pool

Memory pool allocation for efficient memory management.
Uses arena-style allocation to reduce system calls.
"""

import threading
from typing import Optional, List, Any, Dict
from dataclasses import dataclass


@dataclass
class Block:
    """Memory block descriptor."""
    start: int
    end: int
    size: int
    used: bool = False


class Pool:
    """
    Memory pool for efficient allocations.

    Implements an arena-based memory pool where memory
    is allocated in large blocks and sub-allocated from
    those blocks.
    """

    def __init__(
        self,
        name: str = "pool",
        initial_size: int = 1000,
        increment_size: int = 1000,
        max_size: int = 0
    ):
        """
        Initialize memory pool.

        Args:
            name: Pool name (for debugging).
            initial_size: Initial block size in bytes.
            increment_size: Size increment for new blocks.
            max_size: Maximum pool size (0 for unlimited).
        """
        self._name = name
        self._block_size = initial_size
        self._increment = increment_size
        self._max_size = max_size
        self._blocks: List[bytearray] = []
        self._allocations: Dict[int, Any] = {}
        self._lock = threading.Lock()
        self._total_used = 0

    @property
    def name(self) -> str:
        """Get pool name."""
        return self._name

    @property
    def used_size(self) -> int:
        """Get total used memory."""
        return self._total_used

    @property
    def max_size(self) -> int:
        """Get maximum pool size."""
        return self._max_size

    def allocate(self, size: int) -> Optional[bytearray]:
        """
        Allocate memory from the pool.

        Args:
            size: Number of bytes to allocate.

        Returns:
            bytearray of requested size or None if failed.
        """
        if size <= 0:
            return None

        with self._lock:
            if self._max_size > 0:
                if self._total_used + size > self._max_size:
                    return None

            for i, block in enumerate(self._blocks):
                if len(block) - len(self._allocations.get(i, b'')) >= size:
                    if i not in self._allocations:
                        self._allocations[i] = b''
                    offset = len(self._allocations[i])
                    if offset + size <= len(block):
                        alloc = bytearray(block[offset:offset + size])
                        self._allocations[i] += bytes(alloc)
                        self._total_used += size
                        return alloc

            new_size = max(size, self._block_size)
            try:
                block = bytearray(new_size)
                self._blocks.append(block)
                idx = len(self._blocks) - 1
                self._allocations[idx] = bytes(size)
                self._total_used += size
                return bytearray(block[:size])
            except MemoryError:
                return None

    def allocate_int(self, size: int) -> Optional[int]:
        """
        Allocate memory and return pointer (address).

        Args:
            size: Number of bytes to allocate.

        Returns:
            Memory address (int) or None if failed.
        """
        mem = self.allocate(size)
        if mem:
            return id(mem)
        return None

    def allocate_clear(self, size: int) -> bytearray:
        """
        Allocate and zero-initialize memory.

        Args:
            size: Number of bytes to allocate.

        Returns:
            Zero-initialized bytearray.
        """
        data = self.allocate(size)
        if data:
            for i in range(len(data)):
                data[i] = 0
        return data

    def release(self, mem: bytearray) -> bool:
        """
        Release allocated memory.

        Note: For simple pools, this is a no-op as memory
        is only reclaimed when the pool is destroyed.

        Args:
            mem: Memory to release.

        Returns:
            True if released, False if not found.
        """
        with self._lock:
            for idx, block in enumerate(self._blocks):
                block_start = id(block)
                mem_start = id(mem)
                if block_start == mem_start:
                    self._total_used -= len(mem)
                    return True
            return False

    def reset(self) -> None:
        """
        Reset the pool.

        Frees all allocations and resets block sizes to initial.
        """
        with self._lock:
            self._blocks.clear()
            self._allocations.clear()
            self._total_used = 0
            self._block_size = max(self._block_size, 1000)

    def get_capacity(self) -> int:
        """Get total capacity of all blocks."""
        with self._lock:
            return sum(len(b) for b in self._blocks)

    def get_available(self) -> int:
        """Get available (free) memory."""
        return self.get_capacity() - self._used_size

    def get_stats(self) -> Dict[str, int]:
        """
        Get pool statistics.

        Returns:
            Dictionary with pool statistics.
        """
        with self._lock:
            return {
                'name': self._name,
                'total_capacity': self.get_capacity(),
                'used': self._total_used,
                'available': self.get_available(),
                'block_count': len(self._blocks),
                'max_size': self._max_size
            }

    def resize(self, mem: bytearray, new_size: int) -> Optional[bytearray]:
        """
        Resize allocated memory.

        Note: For simple pools, this allocates new memory
        and copies the data.

        Args:
            mem: Memory to resize.
            new_size: New size in bytes.

        Returns:
            Resized memory or None if failed.
        """
        if new_size <= 0:
            self.release(mem)
            return None

        new_mem = self.allocate(new_size)
        if not new_mem:
            return None

        copy_len = min(len(mem), new_size)
        new_mem[:copy_len] = mem[:copy_len]
        self.release(mem)

        return new_mem

    def create_subpool(self, name: str, size: int) -> 'Pool':
        """
        Create a sub-pool from this pool.

        Args:
            name: Sub-pool name.
            size: Initial block size.

        Returns:
            New Pool instance.
        """
        sub = Pool(name, size, self._increment, self._max_size)
        return sub

    def destroy(self) -> None:
        """Destroy the pool and free all memory."""
        with self._lock:
            self._blocks.clear()
            self._allocations.clear()
            self._total_used = 0


class PoolImpl(Pool):
    """Alias for Pool for PJSIP compatibility."""
    pass


def create_pool(
    name: str = "pool",
    initial_size: int = 1000,
    increment: int = 1000,
    max_size: int = 0
) -> Pool:
    """
    Create a new memory pool.

    Args:
        name: Pool name.
        initial_size: Initial block size.
        increment: Increment for new blocks.
        max_size: Maximum size (0 for unlimited).

    Returns:
        Pool instance.
    """
    return Pool(name, initial_size, increment, max_size)
