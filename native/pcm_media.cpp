// pcm_media.cpp
#include "pcm_media.hpp"

const size_t PcmMedia::MAX_BUFFER_SIZE;

PcmMedia::PcmMedia(unsigned clockRate,
                   unsigned channelCount,
                   unsigned samplesPerFrame)
    : clockRate(clockRate),
      channelCount(channelCount),
      samplesPerFrame(samplesPerFrame),
      initialized(false) {
}

PcmMedia::~PcmMedia() {
    stop();
}

void PcmMedia::initialize() {
    if (initialized) return;
    
    // Endpoint must be in RUNNING state
    // Don't actually call createPort - just mark as ready
    // The actual port creation happens in start()
    initialized = true;
}

void PcmMedia::start() {
    if (!initialized) {
        initialize();
    }
    
    try {
        // Create audio format
        MediaFormatAudio fmt;
        fmt.type = PJMEDIA_TYPE_AUDIO;
        fmt.clockRate = clockRate;
        fmt.channelCount = channelCount;
        fmt.bitsPerSample = 16;
        fmt.frameTimeUsec = (samplesPerFrame * 1000000ULL) / clockRate;
        
        // Create port with proper name and format
        createPort("pcm_media", fmt);
        
        // Register with endpoint
        Endpoint::instance().mediaAdd(*this);
    } catch (const Error &err) {
        throw;
    }
}

void PcmMedia::stop() {
    if (!initialized) return;
    
    try {
        Endpoint::instance().mediaRemove(*this);
    } catch (const Error &err) {
        // Ignore errors during stop
    }
}

void PcmMedia::push(const int16_t* samples, size_t count) {
    if (!samples || count == 0) return;
    
    std::lock_guard<std::mutex> lock(mtx);
    
    // Check buffer size to prevent memory issues
    if (txBuffer.size() + count > MAX_BUFFER_SIZE) {
        // Drop old samples if buffer is full
        size_t dropCount = txBuffer.size() + count - MAX_BUFFER_SIZE;
        if (dropCount < txBuffer.size()) {
            txBuffer.erase(txBuffer.begin(), txBuffer.begin() + dropCount);
        } else {
            txBuffer.clear();
        }
    }
    
    txBuffer.insert(txBuffer.end(), samples, samples + count);
}

size_t PcmMedia::getReceiveBufferSize() const {
    std::lock_guard<std::mutex> lock(mtx);
    return rxBuffer.size();
}

// PJMEDIA requests audio frame to transmit
void PcmMedia::onFrameRequested(MediaFrame &frame) {
    std::lock_guard<std::mutex> lock(mtx);

    size_t needed_samples = samplesPerFrame * channelCount;
    size_t needed_bytes = needed_samples * sizeof(int16_t);

    frame.buf.resize(needed_bytes);
    frame.size = needed_bytes;
    frame.type = PJMEDIA_FRAME_TYPE_AUDIO;

    if (txBuffer.empty()) {
        // No data available - send silence
        memset(frame.buf.data(), 0, needed_bytes);
        return;
    }

    size_t available = txBuffer.size();
    size_t toCopy = std::min(needed_samples, available);
    size_t bytes_to_copy = toCopy * sizeof(int16_t);

    // Copy available samples
    if (toCopy > 0) {
        memcpy(frame.buf.data(), txBuffer.data(), bytes_to_copy);
        txBuffer.erase(txBuffer.begin(), txBuffer.begin() + toCopy);
    }

    // Pad with silence if needed
    if (toCopy < needed_samples) {
        size_t padding_bytes = (needed_samples - toCopy) * sizeof(int16_t);
        memset(frame.buf.data() + bytes_to_copy, 0, padding_bytes);
    }
}

// PJMEDIA has received audio frame
void PcmMedia::onFrameReceived(MediaFrame &frame) {
    if (frame.buf.empty() || frame.size == 0) {
        return;
    }

    // Only process audio frames
    if (frame.type != PJMEDIA_FRAME_TYPE_AUDIO) {
        return;
    }

    std::lock_guard<std::mutex> lock(mtx);

    // Convert buffer to int16_t samples
    int16_t* pcm = reinterpret_cast<int16_t*>(frame.buf.data());
    size_t samples = frame.size / sizeof(int16_t);

    // Check buffer size
    if (rxBuffer.size() + samples > MAX_BUFFER_SIZE) {
        // Drop old samples
        size_t dropCount = rxBuffer.size() + samples - MAX_BUFFER_SIZE;
        if (dropCount < rxBuffer.size()) {
            rxBuffer.erase(rxBuffer.begin(), rxBuffer.begin() + dropCount);
        } else {
            rxBuffer.clear();
        }
    }

    // Store received samples
    rxBuffer.insert(rxBuffer.end(), pcm, pcm + samples);
}