"""
utils/numpy_utils.py - numpy <-> PCM Conversion

Utilities for converting between numpy arrays and PCM audio.
"""

import numpy as np
from typing import Union, Optional


def numpy_to_pcm16(audio: np.ndarray) -> bytes:
    """
    Convert numpy array to PCM int16 bytes.

    Args:
        audio: Input array (any dtype/conversion applied).

    Returns:
        PCM bytes (int16).
    """
    if audio.dtype != np.int16:
        audio = audio.astype(np.int16)
    return audio.tobytes()


def pcm16_to_numpy(pcm_bytes: bytes) -> np.ndarray:
    """
    Convert PCM int16 bytes to numpy array.

    Args:
        pcm_bytes: PCM int16 bytes.

    Returns:
        Numpy array (int16).
    """
    return np.frombuffer(pcm_bytes, dtype=np.int16)


def numpy_to_g711(audio: np.ndarray, a_law: bool = True) -> np.ndarray:
    """
    Convert numpy PCM float/int to G.711 bytes.

    Args:
        audio: Input numpy array (float -1.0 to 1.0 or int16).
        a_law: Use A-law if True, u-law if False.

    Returns:
        G.711 encoded array (uint8).
    """
    import audioop

    if audio.dtype == np.float32 or audio.dtype == np.float64:
        audio = np.clip(audio, -1.0, 1.0)
        audio = (audio * 32767).astype(np.int16)

    pcm_bytes = audio.tobytes()
    bias_pcm = audioop.bias(pcm_bytes, 2, -32768)
    int8_pcm = audioop.lin2lin(bias_pcm, 2, 1)
    
    if a_law:
        g711_bytes = audioop.lin2alaw(int8_pcm, 1)
    else:
        g711_bytes = audioop.lin2ulaw(int8_pcm, 1)

    return np.frombuffer(g711_bytes, dtype=np.uint8)


def g711_to_numpy(g711_bytes: bytes, a_law: bool = True) -> np.ndarray:
    """
    Convert G.711 bytes to numpy PCM int16.

    Args:
        g711_bytes: G.711 encoded bytes.
        a_law: Use A-law if True, u-law if False.

    Returns:
        Numpy array (int16).
    """
    import audioop

    if a_law:
        pcm_bytes = audioop.alaw2lin(g711_bytes, 2)
    else:
        pcm_bytes = audioop.ulaw2lin(g711_bytes, 2)

    return np.frombuffer(pcm_bytes, dtype=np.int16)


def apply_gain(audio: np.ndarray, gain_db: float) -> np.ndarray:
    """
    Apply gain to audio.

    Args:
        audio: Input numpy array.
        gain_db: Gain in dB.

    Returns:
        Gain-adjusted array.
    """
    factor = 10 ** (gain_db / 20)
    return audio * factor


def normalize_audio(audio: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    """
    Normalize audio to target peak level.

    Args:
        audio: Input numpy array.
        target_peak: Target peak level (0.0 to 1.0).

    Returns:
        Normalized array.
    """
    if len(audio) == 0:
        return audio

    max_val = np.max(np.abs(audio))
    if max_val == 0:
        return audio

    factor = target_peak / max_val
    return audio * factor


def remove_dc_offset(audio: np.ndarray) -> np.ndarray:
    """
    Remove DC offset from audio.

    Args:
        audio: Input numpy array.

    Returns:
        DC-offset removed array.
    """
    return audio - np.mean(audio)


def float_to_pcm16(audio: np.ndarray) -> np.ndarray:
    """
    Convert float audio (-1.0 to 1.0) to int16.

    Args:
        audio: Float audio array.

    Returns:
        Int16 audio array.
    """
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767).astype(np.int16)


def pcm16_to_float(audio: np.ndarray) -> np.ndarray:
    """
    Convert int16 audio to float (-1.0 to 1.0).

    Args:
        audio: Int16 audio array.

    Returns:
        Float audio array.
    """
    return audio.astype(np.float32) / 32767.0


def mix_audio(audio1: np.ndarray, audio2: np.ndarray) -> np.ndarray:
    """
    Mix two audio arrays.

    Args:
        audio1: First audio array.
        audio2: Second audio array.

    Returns:
        Mixed audio array.
    """
    min_len = min(len(audio1), len(audio2))
    mixed = np.zeros(min_len, dtype=np.float32)
    mixed[:min_len] = audio1[:min_len].astype(np.float32) / 32767.0
    mixed[:min_len] += audio2[:min_len].astype(np.float32) / 32767.0
    mixed = np.clip(mixed, -1.0, 1.0)
    return (mixed * 32767).astype(np.int16)


def audio_energy(audio: np.ndarray) -> float:
    """
    Calculate RMS energy of audio.

    Args:
        audio: Input audio array.

    Returns:
        RMS energy value.
    """
    if len(audio) == 0:
        return 0.0
    return np.sqrt(np.mean(audio.astype(np.float32) ** 2))


def silence_detection(audio: np.ndarray, threshold_db: float = -40.0) -> np.ndarray:
    """
    Detect silent frames.

    Args:
        audio: Input audio array.
        threshold_db: Silence threshold in dB.

    Returns:
        Boolean array where True indicates silence.
    """
    threshold = 10 ** (threshold_db / 20) * 32767
    return np.abs(audio.astype(np.int32)) < threshold


def trim_silence(audio: np.ndarray, threshold_db: float = -40.0) -> np.ndarray:
    """
    Trim leading and trailing silence.

    Args:
        audio: Input audio array.
        threshold_db: Silence threshold in dB.

    Returns:
        Trimmed audio array.
    """
    is_silent = silence_detection(audio, threshold_db)

    if not np.any(~is_silent):
        return audio

    start = np.argmax(~is_silent)
    end = len(audio) - np.argmax(~is_silent[::-1])

    return audio[start:end]


def create_silence(duration_ms: int, sample_rate: int = 8000) -> np.ndarray:
    """
    Create silence audio.

    Args:
        duration_ms: Duration in milliseconds.
        sample_rate: Sample rate.

    Returns:
        Silence audio array.
    """
    num_samples = int(sample_rate * duration_ms / 1000)
    return np.zeros(num_samples, dtype=np.int16)
