"""Python wrapper for the PcmMedia C++ extension module"""

import os
import sys
import ctypes

# Ensure this directory is in sys.path so we can import pcm_media.so
_native_dir = os.path.dirname(os.path.abspath(__file__))
if _native_dir not in sys.path:
    sys.path.insert(0, _native_dir)

# Setup library paths for PJSUA2 dependencies
def _preload_libraries():
    """Preload PJSUA2 libraries before importing the extension"""
    # Try multiple ways to find the library directory
    import os
    
    # Method 1: Relative to this file
    native_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(native_dir)
    
    # Method 2: If native_dir doesn't look right, try relative to current working directory
    if not os.path.exists(os.path.join(native_dir, "pcm_media.cpython-311-x86_64-linux-gnu.so")):
        # Try to find from working directory
        alt_native = os.path.join(os.getcwd(), "native")
        if os.path.exists(os.path.join(alt_native, "pcm_media.cpython-311-x86_64-linux-gnu.so")):
            native_dir = alt_native
            parent_dir = os.path.dirname(native_dir)
    
    # Library search paths
    lib_paths = [
        os.path.join(parent_dir, "pjproject", "pjlib", "lib"),
        os.path.join(parent_dir, "pjproject", "pjmedia", "lib"),
        os.path.join(parent_dir, "pjproject", "pjsip", "lib"),
        os.path.join(parent_dir, "pjproject", "pjnath", "lib"),
        os.path.join(parent_dir, "pjproject", "pjlib-util", "lib"),
    ]
    
    # Libraries to preload in order
    libraries_to_load = [
        ("libpj.so.2", "pjlib"),
        ("libpjlib-util.so.2", "pjlib-util"),
        ("libpjnath.so.2", "pjnath"),
        ("libpjmedia.so.2", "pjmedia"),
        ("libpjmedia-codec.so.2", "pjmedia-codec"),
        ("libpjmedia-audiodev.so.2", "pjmedia-audiodev"),
        ("libpjsua.so.2", "pjsua"),
        ("libpjsua2.so.2", "pjsua2"),
    ]
    
    for lib_name, lib_label in libraries_to_load:
        for lib_path in lib_paths:
            full_path = os.path.join(lib_path, lib_name)
            if os.path.exists(full_path):
                try:
                    ctypes.CDLL(full_path, mode=ctypes.RTLD_GLOBAL)
                    # Successfully loaded
                except Exception as e:
                    # Silently continue if library loading fails
                    pass
                break

# Preload libraries
_preload_libraries()

# Now import the compiled module
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
