"""
Native C++ extensions for PhoneGuy Bot.
Includes PCM Media port for PJSUA2.
"""

import array
import sys
import os

# Import the low-level C/C++ module
from . import _pcm_media


class PcmMedia:
    """
    PCM Audio Media Port for PJSUA2
    
    This class allows you to send and receive PCM16 audio streams
    through PJSUA2.
    
    Parameters:
        clockRate (int): Sample rate in Hz (default 16000)
        channelCount (int): Number of channels (default 1 = mono)
        samplesPerFrame (int): Samples per frame (default 160)
    """
    
    def __init__(self, clockRate=16000, channelCount=1, samplesPerFrame=160):
        """Initialize with audio parameters"""
        self._obj = _pcm_media.new_PcmMedia(clockRate, channelCount, samplesPerFrame)
    
    def __del__(self):
        """Cleanup"""
        if hasattr(self, '_obj'):
            try:
                _pcm_media.delete_PcmMedia(self._obj)
            except:
                pass
    
    def initialize(self):
        """Initialize the audio port"""
        try:
            _pcm_media.PcmMedia_initialize(self._obj)
        except Exception as e:
            # Log but don't crash
            import logging
            logging.warning(f"PCM Media initialize: {e}")
    
    def start(self):
        """Start the audio port"""
        try:
            _pcm_media.PcmMedia_start(self._obj)
        except Exception as e:
            # Log but don't crash
            import logging
            logging.warning(f"PCM Media start: {e}")
    
    def stop(self):
        """Stop the audio port"""
        try:
            _pcm_media.PcmMedia_stop(self._obj)
        except Exception as e:
            # Log but don't crash
            import logging
            logging.warning(f"PCM Media stop: {e}")
    
    def push(self, audio_data):
        """Push audio samples to transmit buffer"""
        if isinstance(audio_data, (bytes, bytearray)):
            # Convert to proper format if needed
            _pcm_media.PcmMedia_push(self._obj, audio_data)
        else:
            raise TypeError("Expected bytes or bytearray")
    
    def getReceiveBufferSize(self):
        """Get size of receive buffer"""
        return _pcm_media.PcmMedia_getReceiveBufferSize(self._obj)
    
    def push_samples(self, samples):
        """
        Push audio samples to the transmit buffer
        
        Parameters:
            samples: array of samples (bytes, bytearray, or array.array of int16)
        """
        if isinstance(samples, (bytes, bytearray)):
            self.push(samples)
        elif isinstance(samples, array.array):
            if samples.typecode != 'h':
                raise TypeError("Expected int16 array (typecode 'h')")
            self.push(samples.tobytes())
        else:
            raise TypeError("Expected bytes, bytearray, or array.array of int16")
    
    def __repr__(self):
        return f"<PcmMedia at {id(self)}>"
    
    def __enter__(self):
        """Context manager entry"""
        self.initialize()
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        try:
            self.stop()
        except:
            pass
        return False


def create_pcm_media(clock_rate=16000, channels=1, samples_per_frame=160):
    """
    Create and initialize a PcmMedia instance
    
    Parameters:
        clock_rate: Sample rate in Hz
        channels: Number of channels
        samples_per_frame: Samples per frame
    
    Returns:
        Initialized PcmMedia instance
    """
    pcm = PcmMedia(clock_rate, channels, samples_per_frame)
    pcm.initialize()
    return pcm


__all__ = ['PcmMedia', 'create_pcm_media', '_pcm_media']
