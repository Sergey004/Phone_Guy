"""
utils/resample.py - Audio Resampling

Audio resampling utilities using scipy.
"""

import numpy as np
from typing import Optional
from enum import Enum


class ResampleQuality(Enum):
    """Resampling quality levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def resample_audio(
    audio: np.ndarray,
    from_sr: int,
    to_sr: int,
    quality: ResampleQuality = ResampleQuality.MEDIUM
) -> np.ndarray:
    """
    Resample audio to new sample rate.

    Args:
        audio: Input numpy array.
        from_sr: Original sample rate.
        to_sr: Target sample rate.
        quality: Resampling quality.

    Returns:
        Resampled audio array.
    """
    if from_sr == to_sr:
        return audio

    try:
        from scipy import signal
        factor = to_sr / from_sr

        if quality == ResampleQuality.LOW:
            num_taps = 8
        elif quality == ResampleQuality.HIGH:
            num_taps = 64
        else:
            num_taps = 16

        if factor > 1:
            resampled = signal.resample_poly(audio, to_sr, from_sr, num_taps)
        else:
            resampled = signal.decimate(audio, int(1 / factor), num_taps)

        return resampled.astype(audio.dtype)

    except ImportError:
        ratio = to_sr / from_sr
        new_len = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(audio.dtype)


def upsample(audio: np.ndarray, factor: int) -> np.ndarray:
    """
    Upsample audio by integer factor.

    Args:
        audio: Input audio array.
        factor: Upsampling factor.

    Returns:
        Upsampled audio array.
    """
    return resample_audio(audio, 1, factor)


def downsample(audio: np.ndarray, factor: int) -> np.ndarray:
    """
    Downsample audio by integer factor.

    Args:
        audio: Input audio array.
        factor: Downsampling factor.

    Returns:
        Downsampled audio array.
    """
    return resample_audio(audio, factor, 1)


def resample_to_8000(audio: np.ndarray, from_sr: int) -> np.ndarray:
    """
    Resample audio to 8000 Hz.

    Args:
        audio: Input audio array.
        from_sr: Original sample rate.

    Returns:
        Resampled audio at 8000 Hz.
    """
    return resample_audio(audio, from_sr, 8000)


def resample_to_16000(audio: np.ndarray, from_sr: int) -> np.ndarray:
    """
    Resample audio to 16000 Hz.

    Args:
        audio: Input audio array.
        from_sr: Original sample rate.

    Returns:
        Resampled audio at 16000 Hz.
    """
    return resample_audio(audio, from_sr, 16000)


def resample_to_44100(audio: np.ndarray, from_sr: int) -> np.ndarray:
    """
    Resample audio to 44100 Hz.

    Args:
        audio: Input audio array.
        from_sr: Original sample rate.

    Returns:
        Resampled audio at 44100 Hz.
    """
    return resample_audio(audio, from_sr, 44100)


def resample_to_48000(audio: np.ndarray, from_sr: int) -> np.ndarray:
    """
    Resample audio to 48000 Hz.

    Args:
        audio: Input audio array.
        from_sr: Original sample rate.

    Returns:
        Resampled audio at 48000 Hz.
    """
    return resample_audio(audio, from_sr, 48000)
