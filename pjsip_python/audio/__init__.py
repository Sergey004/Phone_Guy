"""
audio - In-Memory Audio Processing Layer

Audio processing for SIP/RTP without physical devices:
- Numpy array support (int16, float32)
- PyTorch Tensor support (optional)
- WAV file reading/writing
- MP3 via pydub (optional)
- G.711 codec integration
"""

import io
import wave
import numpy as np
from pathlib import Path
from typing import Optional, Union, Tuple, BinaryIO, TYPE_CHECKING
from dataclasses import dataclass
from enum import IntEnum

if TYPE_CHECKING:
    import torch


class AudioFormat(IntEnum):
    """Audio format constants."""
    UNKNOWN = 0
    PCM16 = 1
    FLOAT32 = 2
    G711_ALAW = 3
    G711_ULAW = 4


class AudioChannel(IntEnum):
    """Channel configuration."""
    MONO = 1
    STEREO = 2


@dataclass
class AudioInfo:
    """Audio file/stream information."""
    sample_rate: int
    channels: int
    duration: float
    format: AudioFormat
    num_samples: int
    
    @property
    def bytes_per_sample(self) -> int:
        if self.format == AudioFormat.PCM16:
            return 2
        elif self.format == AudioFormat.FLOAT32:
            return 4
        return 1


@dataclass  
class AudioConfig:
    """Audio processing configuration."""
    sample_rate: int = 8000
    channels: int = 1
    format: AudioFormat = AudioFormat.PCM16
    chunk_size: int = 160


class AudioData:
    """
    Unified audio data container supporting multiple formats.
    
    Supports:
    - Numpy arrays (int16, float32)
    - PyTorch Tensors (if available)
    - Raw bytes
    - G.711 encoded bytes
    """
    
    def __init__(
        self,
        data: Union[np.ndarray, bytes],
        sample_rate: int = 8000,
        channels: int = 1,
        format: AudioFormat = AudioFormat.PCM16
    ):
        self._data = data
        self._sample_rate = sample_rate
        self._channels = channels
        self._format = format
        
    @property
    def data(self) -> Union[np.ndarray, bytes]:
        """Get raw data."""
        return self._data
        
    @property
    def sample_rate(self) -> int:
        return self._sample_rate
    
    @property
    def channels(self) -> int:
        return self._channels
    
    @property
    def format(self) -> AudioFormat:
        return self._format
    
    @property
    def num_samples(self) -> int:
        """Get number of samples."""
        if isinstance(self._data, (np.ndarray, bytes)):
            if isinstance(self._data, bytes):
                return len(self._data) // (2 * self._channels) if self._format == AudioFormat.PCM16 else len(self._data) // (4 * self._channels)
            return len(self._data)
        return 0
    
    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        return self.num_samples / self._sample_rate
    
    def to_numpy(self, dtype=np.int16) -> np.ndarray:
        """Convert to numpy array."""
        if isinstance(self._data, np.ndarray):
            if self._format == AudioFormat.PCM16:
                return self._data.astype(dtype)
            elif self._format == AudioFormat.FLOAT32:
                return (self._data * 32767).astype(np.int16)
        elif isinstance(self._data, bytes):
            return np.frombuffer(self._data, dtype=np.int16)
        return np.array([], dtype=np.int16)
    
    def to_bytes(self, target_format: Optional[AudioFormat] = None) -> bytes:
        """Convert to bytes."""
        target = target_format or self._format
        
        if target == AudioFormat.PCM16:
            arr = self.to_numpy()
            return arr.tobytes()
        elif target == AudioFormat.FLOAT32:
            arr = self.to_numpy().astype(np.float32) / 32767.0
            return arr.tobytes()
        elif target in (AudioFormat.G711_ALAW, AudioFormat.G711_ULAW):
            from pjsip_python.pjmedia.codec import G711Codec
            codec = G711Codec(a_law=target == AudioFormat.G711_ALAW)
            pcm_bytes = self.to_numpy().tobytes()
            return codec.encode(pcm_bytes)
            
        return self._data if isinstance(self._data, bytes) else b''
    
    def resample(self, target_sr: int) -> 'AudioData':
        """Resample audio to new sample rate."""
        arr = self.to_numpy()
        if self._sample_rate != target_sr:
            try:
                from scipy import signal
                arr_float = arr.astype(np.float32) / 32767.0
                new_num = len(arr) * target_sr // self._sample_rate
                resampled = signal.resample(arr_float, new_num)
                arr_float = np.asarray(resampled, dtype=np.float32)
                arr = (arr_float * 32767).astype(np.int16)
            except Exception:
                pass
        return AudioData(arr, target_sr, self._channels, self._format)
    
    def to_mono(self) -> 'AudioData':
        """Convert to mono."""
        arr = self.to_numpy()
        if self._channels == 2:
            arr = arr.reshape(-1, 2).mean(axis=1).astype(np.int16)
        return AudioData(arr, self._sample_rate, 1, self._format)


def read_wav(file_path: Union[str, Path]) -> AudioData:
    """Read WAV file."""
    with wave.open(str(file_path), 'rb') as w:
        n_channels = w.getnchannels()
        sample_width = w.getsampwidth()
        framerate = w.getframerate()
        n_frames = w.getnframes()
        
        if sample_width == 2:
            fmt = AudioFormat.PCM16
            data = np.frombuffer(w.readframes(n_frames), dtype=np.int16)
        elif sample_width == 4:
            fmt = AudioFormat.FLOAT32
            data = np.frombuffer(w.readframes(n_frames), dtype=np.float32)
        else:
            raise ValueError(f"Unsupported sample width: {sample_width}")
            
    return AudioData(data, framerate, n_channels, fmt)


def read_wav_from_bytes(data: bytes) -> AudioData:
    """Read WAV from bytes."""
    with wave.open(io.BytesIO(data), 'rb') as w:
        return read_wav_impl(w)


def read_wav_impl(w: wave.Wave_read) -> AudioData:
    """Read WAV from wave object."""
    n_channels = w.getnchannels()
    sample_width = w.getsampwidth()
    framerate = w.getframerate()
    n_frames = w.getnframes()
    
    raw_data = w.readframes(n_frames)
    
    if sample_width == 2:
        fmt = AudioFormat.PCM16
        arr = np.frombuffer(raw_data, dtype=np.int16)
    elif sample_width == 4:
        fmt = AudioFormat.FLOAT32
        arr = np.frombuffer(raw_data, dtype=np.float32)
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")
        
    return AudioData(arr, framerate, n_channels, fmt)


def write_wav(file_path: Union[str, Path], audio: AudioData) -> None:
    """Write WAV file."""
    arr = audio.to_numpy()
    
    with wave.open(str(file_path), 'wb') as w:
        w.setnchannels(audio.channels)
        w.setsampwidth(2)  # Always 16-bit for compatibility
        w.setframerate(audio.sample_rate)
        w.writeframes(arr.tobytes())


def write_wav_to_bytes(audio: AudioData) -> bytes:
    """Write WAV to bytes."""
    arr = audio.to_numpy()
    buffer = io.BytesIO()
    
    with wave.open(buffer, 'wb') as w:
        w.setnchannels(audio.channels)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes(arr.tobytes())
        
    return buffer.getvalue()


def read_mp3(file_path: Union[str, Path]) -> AudioData:
    """Read MP3 file (requires pydub)."""
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ImportError("pydub required for MP3: pip install pydub")
    
    audio = AudioSegment.from_mp3(str(file_path))
    audio = audio.set_frame_rate(8000)
    audio = audio.set_channels(1)
    
    samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
    return AudioData(samples, 8000, 1, AudioFormat.PCM16)


def read_mp3_from_bytes(data: bytes) -> AudioData:
    """Read MP3 from bytes."""
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ImportError("pydub required for MP3")
    
    audio = AudioSegment.from_mp3(io.BytesIO(data))
    audio = audio.set_frame_rate(8000)
    audio = audio.set_channels(1)
    
    samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
    return AudioData(samples, 8000, 1, AudioFormat.PCM16)


def numpy_to_audio(
    data: np.ndarray,
    sample_rate: int = 8000,
    channels: int = 1
) -> AudioData:
    """Create AudioData from numpy array."""
    if data.dtype == np.float32 or data.dtype == np.float64:
        fmt = AudioFormat.FLOAT32
    else:
        fmt = AudioFormat.PCM16
        
    if channels > 1:
        data = data.reshape(-1, channels)
        
    return AudioData(data, sample_rate, channels, fmt)


def audio_to_numpy(audio: AudioData) -> np.ndarray:
    """Extract numpy array from AudioData."""
    return audio.to_numpy()


def tensor_to_audio(
    data: 'torch.Tensor',
    sample_rate: int = 8000,
    channels: int = 1
) -> AudioData:
    """Create AudioData from PyTorch tensor."""
    arr = data.detach().cpu().numpy()
    return numpy_to_audio(arr, sample_rate, channels)


def audio_to_tensor(audio: AudioData) -> 'torch.Tensor':
    """Extract PyTorch tensor from AudioData."""
    import torch
    arr = audio.to_numpy().astype(np.float32) / 32767.0
    return torch.from_numpy(arr)


def create_silence(duration: float, sample_rate: int = 8000) -> AudioData:
    """Create silence audio."""
    num_samples = int(duration * sample_rate)
    data = np.zeros(num_samples, dtype=np.int16)
    return AudioData(data, sample_rate, 1, AudioFormat.PCM16)


def create_tone(
    frequency: float,
    duration: float,
    sample_rate: int = 8000,
    amplitude: float = 0.5
) -> AudioData:
    """Create sine wave tone."""
    t = np.linspace(0, duration, int(duration * sample_rate), dtype=np.float32)
    data = (np.sin(2 * np.pi * frequency * t) * 32767 * amplitude).astype(np.int16)
    return AudioData(data, sample_rate, 1, AudioFormat.PCM16)


__all__ = [
    'AudioFormat', 'AudioChannel', 'AudioInfo', 'AudioConfig', 'AudioData',
    'read_wav', 'write_wav', 'read_wav_from_bytes', 'write_wav_to_bytes',
    'read_mp3', 'read_mp3_from_bytes',
    'numpy_to_audio', 'audio_to_numpy',
    'tensor_to_audio', 'audio_to_tensor',
    'create_silence', 'create_tone',
]

try:
    from .device import (
        AudioDeviceType, AudioDeviceInfo,
        list_devices, list_input_devices, list_output_devices, get_default_devices,
        AudioCapture, AudioPlayback, FullDuplexStream,
        check_audio_devices
    )
    __all__.extend([
        'AudioDeviceType', 'AudioDeviceInfo',
        'list_devices', 'list_input_devices', 'list_output_devices', 'get_default_devices',
        'AudioCapture', 'AudioPlayback', 'FullDuplexStream',
        'check_audio_devices'
    ])
except ImportError:
    pass
