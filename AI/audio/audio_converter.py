"""
Audio Converter
Utility functions for audio format conversion and resampling.
"""

import numpy as np
import logging
from scipy import signal
from typing import Optional, Tuple
from .audio_format_handler import AudioFormatHandler, AudioFormat

class AudioConverter:
    """
    Provides audio conversion utilities including resampling and format conversion.
    """
    
    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)
        self.format_handler = AudioFormatHandler(self.logger)
    
    def resample_pcm16(self, 
                       pcm_data: bytes, 
                       from_rate: int, 
                       to_rate: int) -> Tuple[bytes, bool]:
        """
        Resample PCM-16 audio from one sample rate to another.
        
        Args:
            pcm_data: PCM-16 audio bytes
            from_rate: Source sample rate
            to_rate: Target sample rate
            
        Returns:
            Tuple of (resampled_pcm16_data, success)
        """
        if from_rate == to_rate:
            return pcm_data, True
        
        try:
            # Convert bytes to numpy array
            samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Calculate number of samples for target rate
            n_out = int(round(len(samples) * to_rate / from_rate))
            
            # Resample using scipy
            resampled = signal.resample(samples, n_out)
            
            # Convert back to int16
            resampled_i16 = np.clip(resampled, -1.0, 1.0)
            resampled_i16 = (resampled_i16 * 32767.0).astype(np.int16)
            
            result = resampled_i16.tobytes()
            self.logger.debug(f"Resampled {len(pcm_data)} bytes from {from_rate}Hz to {to_rate}Hz: {len(result)} bytes")
            return result, True
            
        except Exception as e:
            self.logger.error(f"Error resampling audio: {e}", exc_info=True)
            return pcm_data, False  # Return original on error
    
    def convert_to_target_format(self,
                                  audio_data: bytes,
                                  input_format: Optional[AudioFormat] = None,
                                  input_sample_rate: int = 8000,
                                  target_sample_rate: int = 8000) -> Tuple[bytes, bool]:
        """
        Convert audio to target format and sample rate.
        
        Args:
            audio_data: Input audio bytes
            input_format: Input audio format (auto-detected if None)
            input_sample_rate: Input sample rate
            target_sample_rate: Target sample rate
            
        Returns:
            Tuple of (converted_pcm16_data, success)
        """
        try:
            # Convert to PCM-16 first
            pcm16_data, detected_format = self.format_handler.convert_to_pcm16(
                audio_data,
                input_format=input_format,
                sample_rate=input_sample_rate
            )
            
            # Resample if needed
            if input_sample_rate != target_sample_rate:
                pcm16_data, success = self.resample_pcm16(
                    pcm16_data,
                    input_sample_rate,
                    target_sample_rate
                )
                if not success:
                    self.logger.warning("Resampling failed, using original PCM-16")
            
            return pcm16_data, True
            
        except Exception as e:
            self.logger.error(f"Error converting audio format: {e}", exc_info=True)
            # Return silence as fallback
            return self._generate_silence(len(audio_data)), False
    
    def _generate_silence(self, num_bytes: int) -> bytes:
        """Generate silence of specified length in PCM-16 format"""
        silence_samples = num_bytes // 2
        silence = np.zeros(silence_samples, dtype=np.int16)
        return silence.tobytes()
    
    def mix_audio(self, audio1: bytes, audio2: bytes) -> bytes:
        """
        Mix two audio streams together.
        
        Args:
            audio1: First PCM-16 audio stream
            audio2: Second PCM-16 audio stream
            
        Returns:
            Mixed PCM-16 audio
        """
        try:
            # Ensure both are the same length
            min_len = min(len(audio1), len(audio2))
            
            if min_len == 0:
                return audio1 if len(audio1) > 0 else audio2
            
            # Convert to numpy arrays
            arr1 = np.frombuffer(audio1[:min_len], dtype=np.int16)
            arr2 = np.frombuffer(audio2[:min_len], dtype=np.int16)
            
            # Mix and clip
            mixed = np.clip(arr1.astype(np.int32) + arr2.astype(np.int32), -32768, 32767).astype(np.int16)
            
            # Add remaining audio from longer stream
            result = mixed.tobytes()
            if len(audio1) > min_len:
                result += audio1[min_len:]
            elif len(audio2) > min_len:
                result += audio2[min_len:]
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error mixing audio: {e}")
            return audio1 if audio1 else audio2
    
    def apply_gain(self, audio_data: bytes, gain_db: float) -> bytes:
        """
        Apply gain to audio in decibels.
        
        Args:
            audio_data: PCM-16 audio bytes
            gain_db: Gain in decibels (positive = louder, negative = quieter)
            
        Returns:
            Audio with gain applied
        """
        try:
            # Convert dB to linear scale
            gain_linear = 10 ** (gain_db / 20.0)
            
            # Convert to numpy array
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            
            # Apply gain
            samples = np.clip(samples * gain_linear, -32768, 32767).astype(np.int16)
            
            return samples.tobytes()
            
        except Exception as e:
            self.logger.error(f"Error applying gain: {e}")
            return audio_data
    
    def fade_in(self, audio_data: bytes, duration_ms: float, sample_rate: int = 8000) -> bytes:
        """
        Apply fade-in to audio.
        
        Args:
            audio_data: PCM-16 audio bytes
            duration_ms: Fade duration in milliseconds
            sample_rate: Sample rate
            
        Returns:
            Audio with fade-in applied
        """
        try:
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            fade_samples = int(duration_ms * sample_rate / 1000)
            
            if fade_samples >= len(samples):
                fade_samples = len(samples)
            
            # Create fade curve
            fade_curve = np.linspace(0, 1, fade_samples)
            
            # Apply fade
            samples[:fade_samples] *= fade_curve
            
            return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
            
        except Exception as e:
            self.logger.error(f"Error applying fade-in: {e}")
            return audio_data
    
    def fade_out(self, audio_data: bytes, duration_ms: float, sample_rate: int = 8000) -> bytes:
        """
        Apply fade-out to audio.
        
        Args:
            audio_data: PCM-16 audio bytes
            duration_ms: Fade duration in milliseconds
            sample_rate: Sample rate
            
        Returns:
            Audio with fade-out applied
        """
        try:
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            fade_samples = int(duration_ms * sample_rate / 1000)
            
            if fade_samples >= len(samples):
                fade_samples = len(samples)
            
            # Create fade curve
            fade_curve = np.linspace(1, 0, fade_samples)
            
            # Apply fade
            samples[-fade_samples:] *= fade_curve
            
            return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
            
        except Exception as e:
            self.logger.error(f"Error applying fade-out: {e}")
            return audio_data
