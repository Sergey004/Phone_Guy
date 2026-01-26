"""
utils - Utility Functions

Helper utilities for audio processing:
- numpy <-> PCM conversion
- Audio resampling
"""

try:
    from .numpy_utils import (
        numpy_to_pcm16, pcm16_to_numpy,
        numpy_to_g711, g711_to_numpy,
        apply_gain, normalize_audio,
        float_to_pcm16, pcm16_to_float,
        audio_energy, trim_silence, create_silence
    )
except ImportError:
    pass

try:
    from .resample import (
        resample_audio, ResampleQuality,
        upsample, downsample,
        resample_to_8000, resample_to_16000,
        resample_to_44100, resample_to_48000
    )
except ImportError:
    pass

__all__ = [
    'numpy_to_pcm16', 'pcm16_to_numpy',
    'numpy_to_g711', 'g711_to_numpy',
    'apply_gain', 'normalize_audio',
    'float_to_pcm16', 'pcm16_to_float',
    'audio_energy', 'trim_silence', 'create_silence',
    'resample_audio', 'ResampleQuality',
    'upsample', 'downsample',
    'resample_to_8000', 'resample_to_16000',
    'resample_to_44100', 'resample_to_48000',
]
