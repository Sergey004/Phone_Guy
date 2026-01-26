"""
audio.device - Physical Audio Device Support

Optional support for microphone/speaker using sounddevice.
These classes only work when physical audio devices are available.

Usage:
    # Check available devices
    from pjsip_python.audio.device import list_devices, get_default_devices
    
    # Capture from microphone
    capture = AudioCapture()
    audio = capture.read()  # AudioData
    
    # Play to speaker
    playback = AudioPlayback()
    playback.write(audio)
"""

import threading
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from . import AudioData, AudioFormat, AudioConfig, numpy_to_audio


class AudioDeviceType(IntEnum):
    """Audio device type."""
    INPUT = 1
    OUTPUT = 2
    FULL_DUPLEX = 3


@dataclass
class AudioDeviceInfo:
    """Audio device information."""
    index: int
    name: str
    device_type: AudioDeviceType
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    host_api: str

    @property
    def is_input(self) -> bool:
        return self.max_input_channels > 0

    @property
    def is_output(self) -> bool:
        return self.max_output_channels > 0


def list_devices() -> List[AudioDeviceInfo]:
    """
    List all available audio devices.

    Returns:
        List of AudioDeviceInfo objects
    """
    import sounddevice as sd

    devices = []
    for i, info in enumerate(sd.query_devices()):
        if isinstance(info, dict):
            dev_type = AudioDeviceType.FULL_DUPLEX
            if info.get('max_input_channels', 0) > 0 and info.get('max_output_channels', 0) == 0:
                dev_type = AudioDeviceType.INPUT
            elif info.get('max_input_channels', 0) == 0 and info.get('max_output_channels', 0) > 0:
                dev_type = AudioDeviceType.OUTPUT

            devices.append(AudioDeviceInfo(
                index=i,
                name=info.get('name', f'Device {i}'),
                device_type=dev_type,
                max_input_channels=info.get('max_input_channels', 0),
                max_output_channels=info.get('max_output_channels', 0),
                default_sample_rate=info.get('default_sample_rate', 8000.0),
                host_api=info.get('hostapi', 'Unknown')
            ))

    return devices


def list_input_devices() -> List[AudioDeviceInfo]:
    """List only input devices (microphones)."""
    return [d for d in list_devices() if d.is_input]


def list_output_devices() -> List[AudioDeviceInfo]:
    """List only output devices (speakers)."""
    return [d for d in list_devices() if d.is_output]


def get_default_devices() -> Dict[str, Optional[AudioDeviceInfo]]:
    """
    Get default input and output devices.

    Returns:
        Dict with 'input' and 'output' keys
    """
    import sounddevice as sd

    devices = list_devices()

    try:
        default_input = devices[sd.default.device[0]] if sd.default.device[0] >= 0 else None
    except (IndexError, TypeError):
        default_input = None

    try:
        default_output = devices[sd.default.device[1]] if sd.default.device[1] >= 0 else None
    except (IndexError, TypeError):
        default_output = None

    return {
        'input': default_input,
        'output': default_output
    }


class AudioCapture:
    """
    Audio capture from microphone.

    Captures audio from the default or specified input device.
    Uses a ring buffer for smooth capturing.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int = 8000,
        channels: int = 1,
        dtype=np.int16,
        chunk_size: int = 160
    ):
        """
        Initialize audio capture.

        Args:
            device_index: Device index (None for default)
            sample_rate: Sample rate (8000 for VoIP)
            channels: Number of channels (1 for mono)
            dtype: NumPy dtype for samples
            chunk_size: Samples per chunk (160 = 20ms at 8kHz)
        """
        import sounddevice as sd

        self._sample_rate = sample_rate
        self._channels = channels
        self._dtype = dtype
        self._chunk_size = chunk_size
        self._device_index = device_index
        self._stream: Optional[sd.InputStream] = None
        self._running = False
        self._lock = threading.Lock()

        self._buffer = np.zeros(chunk_size * 2, dtype=dtype)
        self._buffer_pos = 0

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def start(self) -> None:
        """Start capturing."""
        import sounddevice as sd

        if self._running:
            return

        self._stream = sd.InputStream(
            device=self._device_index,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype=self._dtype,
            blocksize=self._chunk_size,
            callback=self._callback
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        """Stop capturing."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False

    def _callback(self, indata, frames, time, status):
        """Internal callback for sounddevice."""
        with self._lock:
            self._buffer[self._buffer_pos:self._buffer_pos + frames] = indata[:, 0]
            self._buffer_pos = (self._buffer_pos + frames) % (self._chunk_size * 2)

    def read(self) -> AudioData:
        """
        Read audio chunk.

        Returns:
            AudioData with captured audio (20ms = 160 samples at 8kHz)
        """
        import sounddevice as sd

        if not self._running:
            self.start()

        chunk = np.zeros(self._chunk_size, dtype=self._dtype)
        with self._lock:
            for i in range(self._chunk_size):
                chunk[i] = self._buffer[(self._buffer_pos + i) % (self._chunk_size * 2)]

        return numpy_to_audio(chunk, self._sample_rate, self._channels)

    def read_all(self) -> AudioData:
        """
        Read all available audio in buffer.

        Returns:
            AudioData with all buffered audio
        """
        import sounddevice as sd

        if not self._running:
            self.start()

        with self._lock:
            available = (self._buffer_pos) % (self._chunk_size * 2)
            if available == 0:
                return numpy_to_audio(
                    np.zeros(self._chunk_size, dtype=self._dtype),
                    self._sample_rate,
                    self._channels
                )

            indices = [(self._buffer_pos - self._chunk_size + i) % (self._chunk_size * 2)
                      for i in range(self._chunk_size)]
            chunk = np.array([self._buffer[i] for i in indices], dtype=self._dtype)

        return numpy_to_audio(chunk, self._sample_rate, self._channels)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


class AudioPlayback:
    """
    Audio playback to speaker.

    Plays audio to the default or specified output device.
    Uses a queue for smooth playback.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int = 8000,
        channels: int = 1,
        dtype=np.int16,
        chunk_size: int = 160,
        buffer_chunks: int = 4
    ):
        """
        Initialize audio playback.

        Args:
            device_index: Device index (None for default)
            sample_rate: Sample rate (8000 for VoIP)
            channels: Number of channels (1 for mono)
            dtype: NumPy dtype for samples
            chunk_size: Samples per chunk
            buffer_chunks: Number of chunks in buffer
        """
        import sounddevice as sd

        self._sample_rate = sample_rate
        self._channels = channels
        self._dtype = dtype
        self._chunk_size = chunk_size
        self._device_index = device_index
        self._stream: Optional[sd.OutputStream] = None
        self._running = False
        self._lock = threading.Lock()

        self._buffer = np.zeros(chunk_size * buffer_chunks, dtype=dtype)
        self._buffer_pos = 0
        self._write_pos = 0

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def start(self) -> None:
        """Start playback."""
        import sounddevice as sd

        if self._running:
            return

        self._stream = sd.OutputStream(
            device=self._device_index,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype=self._dtype,
            blocksize=self._chunk_size,
            callback=self._callback
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        """Stop playback."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False
        self._buffer = np.zeros(self._chunk_size * 4, dtype=self._dtype)
        self._buffer_pos = 0
        self._write_pos = 0

    def _callback(self, outdata, frames, time, status):
        """Internal callback for sounddevice."""
        with self._lock:
            outdata[:, 0] = self._buffer[self._buffer_pos:self._buffer_pos + frames]
            self._buffer_pos = (self._buffer_pos + frames) % len(self._buffer)

    def write(self, audio: AudioData) -> None:
        """
        Write audio to playback buffer.

        Args:
            audio: AudioData to play
        """
        if not self._running:
            self.start()

        data = audio.to_numpy()
        if len(data) == 0:
            return

        with self._lock:
            for sample in data:
                self._buffer[self._write_pos] = sample
                self._write_pos = (self._write_pos + 1) % len(self._buffer)

    def write_chunk(self, chunk: np.ndarray) -> None:
        """
        Write raw numpy chunk.

        Args:
            chunk: NumPy array of samples
        """
        if not self._running:
            self.start()

        with self._lock:
            for i, sample in enumerate(chunk):
                self._buffer[self._write_pos] = sample
                self._write_pos = (self._write_pos + 1) % len(self._buffer)

    def drain(self) -> None:
        """Wait for buffer to empty."""
        import time
        while self._running and self._write_pos != self._buffer_pos:
            time.sleep(0.01)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


class FullDuplexStream:
    """
    Full-duplex audio stream (simultaneous capture and playback).

    Useful for real-time voice communication with echo cancellation.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int = 8000,
        channels: int = 1,
        dtype=np.int16,
        chunk_size: int = 160
    ):
        """
        Initialize full-duplex stream.

        Args:
            device_index: Device index (None for default)
            sample_rate: Sample rate
            channels: Number of channels
            dtype: NumPy dtype
            chunk_size: Samples per chunk
        """
        import sounddevice as sd

        self._sample_rate = sample_rate
        self._channels = channels
        self._dtype = dtype
        self._chunk_size = chunk_size
        self._device_index = device_index
        self._stream: Optional[sd.Stream] = None
        self._running = False

        self._input_buffer = np.zeros(chunk_size, dtype=dtype)
        self._output_buffer = np.zeros(chunk_size, dtype=dtype)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def start(self) -> None:
        """Start the stream."""
        import sounddevice as sd

        if self._running:
            return

        self._stream = sd.Stream(
            device=self._device_index,
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype=self._dtype,
            blocksize=self._chunk_size,
            callback=self._callback
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        """Stop the stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False

    def _callback(self, indata, outdata, frames, time, status):
        """Internal callback."""
        self._input_buffer[:] = indata[:, 0]
        self._process(indata[:, 0], outdata[:, 0])

    def _process(self, input_data: np.ndarray, output_data: np.ndarray) -> None:
        """
        Process audio. Override this for custom processing.

        Args:
            input_data: Input samples from microphone
            output_data: Output samples to speaker
        """
        output_data[:] = input_data

    def read(self) -> AudioData:
        """
        Read latest captured audio.

        Returns:
            AudioData with captured audio
        """
        return numpy_to_audio(
            self._input_buffer.copy(),
            self._sample_rate,
            self._channels
        )

    def write(self, audio: AudioData) -> None:
        """
        Queue audio for playback.

        Args:
            audio: AudioData to play
        """
        data = audio.to_numpy()
        if len(data) >= self._chunk_size:
            self._output_buffer[:] = data[:self._chunk_size]

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


def check_audio_devices() -> Dict[str, Any]:
    """
    Check if audio devices are available.

    Returns:
        Dict with device status information
    """
    try:
        import sounddevice as sd
        sd.check_input_settings()
        sd.check_output_settings()
        devices = list_devices()
        defaults = get_default_devices()
        return {
            'available': True,
            'input_devices': len([d for d in devices if d.is_input]),
            'output_devices': len([d for d in devices if d.is_output]),
            'default_input': defaults['input'].name if defaults['input'] else None,
            'default_output': defaults['output'].name if defaults['output'] else None
        }
    except ImportError:
        return {
            'available': False,
            'error': 'sounddevice not installed. Run: pip install sounddevice'
        }
    except Exception as e:
        return {
            'available': False,
            'error': str(e)
        }


__all__ = [
    'AudioDeviceType', 'AudioDeviceInfo',
    'list_devices', 'list_input_devices', 'list_output_devices', 'get_default_devices',
    'AudioCapture', 'AudioPlayback', 'FullDuplexStream',
    'check_audio_devices'
]
