"""
Audio Format Handler
Handles conversion between different audio formats (PCMA, PCMU, PCM-16)
and validates audio data to prevent PJSIP crashes.
"""

import numpy as np
import logging
from enum import Enum
from typing import Optional, Tuple

class AudioFormat(Enum):
    """Supported audio formats"""
    PCM_16 = "PCM_16"
    PCMA = "PCMA"  # G.711 A-law
    PCMU = "PCMU"  # G.711 µ-law

class AudioFormatHandler:
    """
    Handles audio format conversion and validation.
    Prevents crashes by ensuring all audio is in the correct format.
    """
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger.getChild('AudioFormatHandler')
        self._pcma_lookup_table = self._build_pcma_table()
        self._pcmu_lookup_table = self._build_pcmu_table()
        
    def _build_pcma_table(self) -> np.ndarray:
        """Build A-law decoding table"""
        table = np.zeros(256, dtype=np.int16)
        for i in range(256):
            table[i] = self._alaw_to_pcm16(i)
        return table
    
    def _build_pcmu_table(self) -> np.ndarray:
        """Build µ-law decoding table"""
        table = np.zeros(256, dtype=np.int16)
        for i in range(256):
            table[i] = self._ulaw_to_pcm16(i)
        return table
    
    @staticmethod
    def _alaw_to_pcm16(byte_val: int) -> int:
        """Convert A-law byte to 16-bit PCM"""
        # Sign bit
        sign = (byte_val & 0x80) >> 7
        # Exponent
        exponent = (byte_val & 0x70) >> 4
        # Mantissa
        mantissa = byte_val & 0x0F
        
        if exponent == 0:
            sample = mantissa << 4
        else:
            sample = (mantissa + 16) << (exponent + 3)
        
        # Apply sign
        if sign:
            sample = -sample
        
        # Scale to 16-bit range
        sample = sample << 3
        return np.clip(sample, -32768, 32767)
    
    @staticmethod
    def _ulaw_to_pcm16(byte_val: int) -> int:
        """Convert µ-law byte to 16-bit PCM"""
        # Complement bit
        byte_val = ~byte_val & 0xFF
        # Sign bit
        sign = (byte_val & 0x80) >> 7
        # Exponent
        exponent = (byte_val & 0x70) >> 4
        # Mantissa
        mantissa = byte_val & 0x0F
        
        if exponent == 0:
            sample = mantissa << 3
        else:
            sample = (mantissa + 33) << (exponent + 2)
        
        # Apply sign and bias
        if sign:
            sample = -sample
        sample -= 33
        
        # Scale to 16-bit range
        sample = sample << 2
        return np.clip(sample, -32768, 32767)
    
    def detect_format(self, audio_data: bytes, sample_rate: int) -> AudioFormat:
        """
        Detect audio format from data characteristics.
        Returns PCM_16 by default if format cannot be determined.
        """
        if len(audio_data) < 2:
            return AudioFormat.PCM_16
        
        # Check byte range to guess format
        byte_values = np.frombuffer(audio_data[:100], dtype=np.uint8)
        
        # PCMA/PCMU values are typically in 0-255 range
        # PCM-16 values can be any byte when viewed as bytes
        
        # Simple heuristic: if most bytes are in 0-255 and show patterns
        # typical of compressed audio, it might be PCMA/PCMU
        unique_bytes = len(np.unique(byte_values))
        
        if unique_bytes <= 256:
            # Likely compressed format
            # Check for A-law or µ-law patterns
            if np.mean(byte_values) < 128:
                return AudioFormat.PCMU
            else:
                return AudioFormat.PCMA
        
        # Default to PCM-16
        return AudioFormat.PCM_16
    
    def convert_to_pcm16(self, audio_data: bytes, 
                        input_format: Optional[AudioFormat] = None,
                        sample_rate: int = 8000) -> Tuple[bytes, AudioFormat]:
        """
        Convert audio data to PCM-16 format.
        
        Args:
            audio_data: Input audio bytes
            input_format: Input format (auto-detected if None)
            sample_rate: Sample rate in Hz
            
        Returns:
            Tuple of (pcm16_data, detected_format)
        """
        if not audio_data:
            self.logger.warning("Empty audio data received")
            return b'', AudioFormat.PCM_16
        
        try:
            # Detect format if not provided
            if input_format is None:
                input_format = self.detect_format(audio_data, sample_rate)
                self.logger.debug(f"Auto-detected format: {input_format.value}")
            
            # Already in PCM-16
            if input_format == AudioFormat.PCM_16:
                self.logger.debug("Audio already in PCM-16 format")
                return audio_data, AudioFormat.PCM_16
            
            # Convert from PCMA
            elif input_format == AudioFormat.PCMA:
                self.logger.debug("Converting from PCMA to PCM-16")
                byte_array = np.frombuffer(audio_data, dtype=np.uint8)
                pcm16 = self._pcma_lookup_table[byte_array]
                return pcm16.tobytes(), AudioFormat.PCM_16
            
            # Convert from PCMU
            elif input_format == AudioFormat.PCMU:
                self.logger.debug("Converting from PCMU to PCM-16")
                byte_array = np.frombuffer(audio_data, dtype=np.uint8)
                pcm16 = self._pcmu_lookup_table[byte_array]
                return pcm16.tobytes(), AudioFormat.PCM_16
            
            else:
                self.logger.error(f"Unknown audio format: {input_format}")
                # Return silence as fallback
                return self._generate_silence(len(audio_data)), AudioFormat.PCM_16
                
        except Exception as e:
            self.logger.error(f"Error converting audio format: {e}", exc_info=True)
            # Return silence as fallback to prevent crashes
            return self._generate_silence(len(audio_data)), AudioFormat.PCM_16
    
    def _generate_silence(self, num_bytes: int) -> bytes:
        """Generate silence of specified length in PCM-16 format"""
        silence_samples = num_bytes // 2
        silence = np.zeros(silence_samples, dtype=np.int16)
        return silence.tobytes()
    
    def validate_pcm16(self, audio_data: bytes) -> bool:
        """
        Validate that audio data is valid PCM-16.
        
        Args:
            audio_data: Audio bytes to validate
            
        Returns:
            True if valid, False otherwise
        """
        if len(audio_data) % 2 != 0:
            self.logger.warning(f"PCM-16 data length not even: {len(audio_data)}")
            return False
        
        try:
            # Try to interpret as int16
            samples = np.frombuffer(audio_data, dtype=np.int16)
            # Check for reasonable range
            if np.any(np.abs(samples) > 32768):
                self.logger.warning("PCM-16 samples out of valid range")
                return False
            return True
        except Exception as e:
            self.logger.error(f"PCM-16 validation failed: {e}")
            return False
    
    def normalize_pcm16(self, audio_data: bytes, target_level: float = 0.8) -> bytes:
        """
        Normalize PCM-16 audio to target level.
        
        Args:
            audio_data: PCM-16 audio bytes
            target_level: Target peak level (0.0 to 1.0)
            
        Returns:
            Normalized PCM-16 bytes
        """
        try:
            samples = np.frombuffer(audio_data, dtype=np.int16)
            current_peak = np.max(np.abs(samples))
            
            if current_peak == 0:
                return audio_data
            
            scale_factor = (32767 * target_level) / current_peak
            normalized = np.clip(samples * scale_factor, -32768, 32767).astype(np.int16)
            
            return normalized.tobytes()
        except Exception as e:
            self.logger.error(f"Error normalizing audio: {e}")
            return audio_data
