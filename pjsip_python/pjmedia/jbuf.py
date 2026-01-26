"""
pjmedia/jbuf.h - Jitter Buffer

Adaptive jitter buffer for smooth audio playback.
Includes packet loss concealment (PLC).
"""

import time
import threading
import collections
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class JitterBufferFrame:
    """Frame in jitter buffer."""
    data: bytes
    timestamp: int
    seq: int
    arrival_time: float


class JitterBuffer:
    """
    Adaptive jitter buffer.

    Manages incoming RTP packets and delivers them
    at regular intervals for smooth playback.
    """

    def __init__(
        self,
        min_delay_ms: int = 60,
        max_delay_ms: int = 200,
        max_size: int = 100,
        ptime_ms: int = 20
    ):
        """
        Initialize jitter buffer.

        Args:
            min_delay_ms: Minimum delay in milliseconds.
            max_delay_ms: Maximum delay in milliseconds.
            max_size: Maximum buffer size in frames.
            ptime_ms: Packet time in milliseconds.
        """
        self._min_delay = min_delay_ms
        self._max_delay = max_delay_ms
        self._max_size = max_size
        self._ptime_ms = ptime_ms
        self._clock_rate = 8000

        self._buffer: collections.deque = collections.deque()
        self._seq = 0
        self._base_seq = 0
        self._timestamp = 0
        self._received = 0
        self._lost = 0
        self._discarded = 0
        self._min_jitter = 0
        self._max_jitter = 0
        self._avg_jitter = 0
        self._level = 0
        self._lock = threading.Lock()
        self._running = False
        self._last_play_time = 0.0

    @property
    def delay_ms(self) -> int:
        """Get current delay in milliseconds."""
        return min(self._max_delay, max(self._min_delay, int(self._level * 1000 / 8)))

    def set_clock_rate(self, rate: int) -> None:
        """Set clock rate (samples per second)."""
        self._clock_rate = rate

    def put(self, frame: JitterBufferFrame) -> bool:
        """
        Put frame into buffer.

        Args:
            frame: Frame to add.

        Returns:
            True if added successfully.
        """
        with self._lock:
            if len(self._buffer) >= self._max_size:
                self._discarded += 1
                return False

            self._received += 1
            self._buffer.append(frame)
            self._update_level()
            return True

    def get(self) -> Optional[JitterBufferFrame]:
        """
        Get frame for playback.

        Returns:
            Frame for playback or None if buffer empty.
        """
        now = time.time()
        with self._lock:
            if not self._buffer:
                return None

            min_delay = self._min_delay / 1000.0
            target_delay = self.delay_ms / 1000.0

            elapsed = now - self._last_play_time
            if elapsed < (self._ptime_ms / 1000.0) * 0.5:
                return None

            self._last_play_time = now
            frame = self._buffer.popleft()
            self._update_level()
            return frame

    def _update_level(self) -> None:
        """Update buffer level (for adaptive delay)."""
        level = len(self._buffer)
        self._level = self._level * 0.99 + level * 0.01

    def set_fixed_delay(self, delay_ms: int) -> None:
        """Set fixed delay (disable adaptation)."""
        self._level = delay_ms * 8

    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics."""
        with self._lock:
            return {
                'min_delay_ms': self._min_delay,
                'max_delay_ms': self._max_delay,
                'current_delay_ms': self.delay_ms,
                'current_level': self._level,
                'buffer_size': len(self._buffer),
                'received': self._received,
                'lost': self._lost,
                'discarded': self._discarded,
                'min_jitter': self._min_jitter,
                'max_jitter': self._max_jitter,
                'avg_jitter': self._avg_jitter
            }

    def reset(self) -> None:
        """Reset buffer."""
        with self._lock:
            self._buffer.clear()
            self._received = 0
            self._lost = 0
            self._discarded = 0
            self._level = 0
            self._min_jitter = 0
            self._max_jitter = 0
            self._avg_jitter = 0

    def get_concealment(self, num_samples: int = 160) -> bytes:
        """
        Generate concealment samples for packet loss.

        Args:
            num_samples: Number of samples to generate.

        Returns:
            Concealment audio data.
        """
        import array
        import random

        last = getattr(self, '_last_conceal', [0] * 10)
        output = array.array('h')

        for i in range(num_samples // 2):
            if i < len(last):
                val = last[i] // 2 + random.randint(-100, 100)
            else:
                val = random.randint(-100, 100)
            val = max(-32768, min(32767, val))
            output.append(val)
            last.append(val)

        self._last_conceal = last[-10:]
        return output.tobytes()


class Plc:
    """Packet Loss Concealment (simple implementation)."""

    def __init__(self, sample_rate: int = 8000):
        self._sample_rate = sample_rate
        self._last_frame: Optional[bytes] = None
        self._pitch_period = 0
        self._concealed = False

    def concealment(self, good_frame: Optional[bytes] = None) -> bytes:
        """
        Generate concealment for missing frame.

        Args:
            good_frame: Last good frame (for pitch-based concealment).

        Returns:
            Concealed frame bytes.
        """
        import array
        import random
        import math

        if good_frame:
            self._last_frame = good_frame

        output = array.array('h')
        num_samples = self._sample_rate * 20 // 1000

        if self._last_frame and not self._concealed:
            pcm = array.array('h', self._last_frame)
            if len(pcm) >= 2:
                max_corr = 0
                best_period = 80
                min_period = 20
                max_period = 120

                for period in range(min_period, max_period):
                    corr = 0
                    for i in range(len(pcm) - period):
                        corr += pcm[i] * pcm[i + period]
                    if corr > max_corr:
                        max_corr = corr
                        best_period = period

                self._pitch_period = best_period
                self._concealed = True

                for i in range(num_samples):
                    idx = (self._pitch_period + i) % len(pcm)
                    val = int(pcm[idx] * 0.9)
                    output.append(max(-32768, min(32767, val)))
        else:
            for _ in range(num_samples):
                val = random.randint(-200, 200)
                output.append(max(-32768, min(32767, val)))

        return output.tobytes()

    def reset(self) -> None:
        """Reset PLC state."""
        self._last_frame = None
        self._pitch_period = 0
        self._concealed = False


def create_jitter_buffer(
    min_delay_ms: int = 60,
    max_delay_ms: int = 200,
    max_size: int = 100
) -> JitterBuffer:
    """Create jitter buffer."""
    return JitterBuffer(min_delay_ms, max_delay_ms, max_size)


def create_plc(sample_rate: int = 8000) -> Plc:
    """Create PLC instance."""
    return Plc(sample_rate)
