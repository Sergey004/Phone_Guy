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

// Typemap to handle Python bytes/bytearray for push() method
%typemap(in) (const int16_t* samples, size_t count) {
    if (PyBytes_Check($input)) {
        Py_ssize_t len = PyBytes_Size($input);
        if (len % sizeof(int16_t) != 0) {
            PyErr_SetString(PyExc_ValueError, "Bytes length must be multiple of 2 (int16_t size)");
            return NULL;
        }
        $1 = (int16_t*) PyBytes_AsString($input);
        $2 = len / sizeof(int16_t);
    } else if (PyByteArray_Check($input)) {
        Py_ssize_t len = PyByteArray_Size($input);
        if (len % sizeof(int16_t) != 0) {
            PyErr_SetString(PyExc_ValueError, "Bytes length must be multiple of 2 (int16_t size)");
            return NULL;
        }
        $1 = (int16_t*) PyByteArray_AsString($input);
        $2 = len / sizeof(int16_t);
    } else {
        PyErr_SetString(PyExc_TypeError, "Expected bytes or bytearray");
        return NULL;
    }
}

// PcmMedia class definition
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
    size_t getReceiveBufferSize() const;
};

// Python helper functions
%pythoncode %{
import array

def pcm_media_from_bytes(data, clock_rate=16000, channels=1, samples_per_frame=160):
    """
    Create PcmMedia from bytes and initialize it.
    
    Args:
        data: bytes object with PCM16 audio
        clock_rate: Sample rate in Hz
        channels: Number of channels
        samples_per_frame: Samples per frame
    
    Returns:
        PcmMedia instance
    """
    pcm = PcmMedia(clock_rate, channels, samples_per_frame)
    pcm.initialize()
    if data:
        pcm.push(data)
    return pcm
%}
