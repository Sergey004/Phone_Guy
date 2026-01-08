"""Python wrapper for the PcmMedia C++ extension module"""

import pcm_media as _pcm_media


class PcmMedia:
    """Python wrapper for PcmMedia C++ class
    
    A wrapper around the native C++ PcmMedia class that provides
    a more Pythonic interface for audio processing.
    """
    
    def __init__(self, clockRate=16000, channelCount=1, samplesPerFrame=160):
        """Create a new PcmMedia instance
        
        Args:
            clockRate: Sample rate in Hz (default: 16000)
            channelCount: Number of audio channels (default: 1 for mono)
            samplesPerFrame: Samples per audio frame (default: 160)
        """
        self._obj = _pcm_media.new_PcmMedia(clockRate, channelCount, samplesPerFrame)
        self.clockRate = clockRate
        self.channelCount = channelCount
        self.samplesPerFrame = samplesPerFrame
    
    def start(self):
        """Start audio processing"""
        if not self._obj:
            raise RuntimeError("PcmMedia object has been deleted")
        return _pcm_media.PcmMedia_start(self._obj)
    
    def stop(self):
        """Stop audio processing"""
        if not self._obj:
            raise RuntimeError("PcmMedia object has been deleted")
        return _pcm_media.PcmMedia_stop(self._obj)
    
    def push(self, samples):
        """Push PCM audio samples
        
        Args:
            samples: Audio samples as bytes, bytearray, or array.array of int16
        """
        if not self._obj:
            raise RuntimeError("PcmMedia object has been deleted")
        
        if isinstance(samples, (bytes, bytearray)):
            # Convert bytes to array of int16
            import array
            arr = array.array('h', samples)
            samples = arr
        
        return _pcm_media.PcmMedia_push(self._obj, samples)
    
    def __del__(self):
        """Cleanup when the object is garbage collected"""
        if hasattr(self, '_obj') and self._obj:
            _pcm_media.delete_PcmMedia(self._obj)
            self._obj = None
    
    def __repr__(self):
        return f"PcmMedia(clockRate={self.clockRate}, channelCount={self.channelCount}, samplesPerFrame={self.samplesPerFrame})"


# Re-export the ShortVector for users who need it (if available)
try:
    ShortVector = _pcm_media.ShortVector
except AttributeError:
    # ShortVector might not be directly available, that's ok
    ShortVector = None

__all__ = ['PcmMedia']
if ShortVector is not None:
    __all__.append('ShortVector')
