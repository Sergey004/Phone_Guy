%module pcm_media

%{
#define SWIG_FILE_WITH_INIT
#include "pcm_media.hpp"
%}

// STL typemaps
%include <std_vector.i>
%include <std_string.i>
%include <stdint.i>

// Template instantiations
%template(ShortVector) std::vector<int16_t>;

// Explicit PcmMedia class wrapper (avoiding inheritance issues)
class PcmMedia {
public:
    PcmMedia(unsigned clockRate = 16000,
             unsigned channelCount = 1,
             unsigned samplesPerFrame = 160);
    
    ~PcmMedia();
    void initialize();
    void start();
    void stop();
    void push(const int16_t* samples, size_t count);
};

// Provide a Python wrapper class for better usability
%pythoncode %{
class PcmMediaWrapper:
    """Python wrapper for PcmMedia C++ class"""
    def __init__(self, clockRate=16000, channelCount=1, samplesPerFrame=160):
        self._obj = new_PcmMedia(clockRate, channelCount, samplesPerFrame)
    
    def start(self):
        """Start audio processing"""
        return PcmMedia_start(self._obj)
    
    def stop(self):
        """Stop audio processing"""
        return PcmMedia_stop(self._obj)
    
    def push(self, samples):
        """Push PCM samples"""
        if isinstance(samples, bytes):
            # Convert bytes to array of int16
            import array
            arr = array.array('h', samples)
            samples = arr
        return PcmMedia_push(self._obj, samples)
    
    def __del__(self):
        """Cleanup"""
        if hasattr(self, '_obj'):
            delete_PcmMedia(self._obj)

# Replace PcmMedia with the wrapper for normal use
PcmMedia = PcmMediaWrapper
%}
