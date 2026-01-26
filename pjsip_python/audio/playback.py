"""
audio/playback.py - Audio Playback

Audio playback using system libraries (sounddevice, pyaudio, or wave).
"""

from typing import Optional, Callable, List
from dataclasses import dataclass
import threading
import queue


@dataclass
class AudioPlaybackConfig:
    """Audio playback configuration."""
    device: Optional[int] = None
    sample_rate: int = 8000
    channels: int = 1
    dtype: str = "int16"
    blocksize: int = 320
    callback: Optional[Callable] = None


class AudioPlayback:
    """Audio playback interface."""

    def __init__(self, config: Optional[AudioPlaybackConfig] = None):
        self._config = config or AudioPlaybackConfig()
        self._running = False
        self._queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    @property
    def sample_rate(self) -> int:
        """Get sample rate."""
        return self._config.sample_rate

    @property
    def channels(self) -> int:
        """Get number of channels."""
        return self._config.channels

    def start(self) -> bool:
        """Start audio playback."""
        self._running = True
        return True

    def stop(self) -> None:
        """Stop audio playback."""
        self._running = False

    def write(self, data: bytes) -> int:
        """Write audio data for playback."""
        self._queue.put(data)
        return len(data)

    def get_devices(self) -> List[dict]:
        """Get list of audio devices."""
        return [{'name': 'Default', 'index': 0, 'sample_rates': [8000, 16000, 44100]}]

    def drain(self) -> None:
        """Wait for playback to complete."""
        pass

    def destroy(self) -> None:
        """Release resources."""
        self.stop()


def create_audio_playback(config: Optional[AudioPlaybackConfig] = None) -> AudioPlayback:
    """Create audio playback."""
    return AudioPlayback(config)
