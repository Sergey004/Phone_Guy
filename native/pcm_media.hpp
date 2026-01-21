// pcm_media.hpp
#pragma once
#include "../pjproject/pjsip/include/pjsua2.hpp"
#include <vector>
#include <mutex>
#include <cstring>

using namespace pj;

/**
 * Custom audio media port for PCM audio I/O.
 * Designed according to PJSUA2 API documentation.
 * Allows sending/receiving PCM16 audio streams.
 */
class PcmMedia : public AudioMediaPort {
public:
    /**
     * Constructor with audio format parameters
     * @param clockRate Sample rate (default 16000 Hz)
     * @param channelCount Number of channels (default 1 = mono)
     * @param samplesPerFrame Samples per frame (default 160)
     */
    PcmMedia(unsigned clockRate = 16000,
             unsigned channelCount = 1,
             unsigned samplesPerFrame = 160);
    
    /**
     * Virtual destructor
     */
    virtual ~PcmMedia();
    
    /**
     * Initialize the media port.
     * Must be called after Endpoint::instance().libCreate()
     */
    void initialize();
    
    /**
     * Register port with endpoint for media processing
     */
    void start();
    
    /**
     * Unregister port from endpoint
     */
    void stop();

    /**
     * Push PCM16 audio samples to transmit buffer
     * @param samples Array of int16_t samples
     * @param count Number of samples
     */
    void push(const int16_t* samples, size_t count);

    /**
     * Get number of samples in receive buffer
     */
    size_t getReceiveBufferSize() const;

protected:
    /**
     * Called when PJMEDIA needs audio to transmit
     */
    virtual void onFrameRequested(MediaFrame &frame) override;
    
    /**
     * Called when PJMEDIA has received audio
     */
    virtual void onFrameReceived(MediaFrame &frame) override;

private:
    unsigned clockRate;
    unsigned channelCount;
    unsigned samplesPerFrame;
    bool initialized;

    // Transmit buffer (to be sent to network)
    std::vector<int16_t> txBuffer;
    
    // Receive buffer (received from network)
    std::vector<int16_t> rxBuffer;
    
    // Synchronization
    mutable std::mutex mtx;
    
    // Max buffer size to prevent memory issues
    static const size_t MAX_BUFFER_SIZE = 320000; // ~10 seconds at 16kHz
};