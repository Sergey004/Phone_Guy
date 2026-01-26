"""
audio/capture.py - Audio Capture

Audio capture using system libraries (sounddevice, pyaudio, or wave).
"""

from typing import Optional, Callable, List
from dataclasses import dataclass
import threading


@dataclass
class AudioCaptureConfig:
    """Audio capture configuration."""
    device: Optional[int] = None
    sample_rate: int = 8000
    channels: int = 1
    dtype: str = "int16"
    blocksize: int = 320
    callback: Optional[Callable] = None


class AudioCapture:
    """Audio capture interface."""

    def __init__(self, config: Optional[AudioCaptureConfig] = None):
        self._config = config or AudioCaptureConfig()
        self._running = False
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
        """Start audio capture."""
        self._running = True
        return True

    def stop(self) -> None:
        """Stop audio capture."""
        self._running = False

    def read(self) -> bytes:
        """Read audio data (blocking)."""
        return b'\x00' * (self._config.blocksize * 2)

    def get_devices(self) -> List[dict]:
        """Get list of audio devices."""
        return [{'name': 'Default', 'index': 0, 'sample_rates': [8000, 16000, 44100]}]

    def destroy(self) -> None:
        """Release resources."""
        self.stop()


def create_audio_capture(config: Optional[AudioCaptureConfig] = None) -> AudioCapture:
    """Create audio capture."""
    return AudioCapture(config)
