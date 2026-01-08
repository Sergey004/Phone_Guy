// pcm_media.hpp
#pragma once
#include "../pjproject/pjsip/include/pjsua2.hpp"
#include <vector>
#include <mutex>

using namespace pj;

class PcmMedia : public AudioMediaPort {
public:
    PcmMedia(unsigned clockRate = 16000,
             unsigned channelCount = 1,
             unsigned samplesPerFrame = 160)
        : clockRate(clockRate),
          channelCount(channelCount),
          samplesPerFrame(samplesPerFrame),
          initialized(false) {
        // Defer initialization to a separate init() call
        // This avoids requiring Endpoint at construction time
    }
    
    void initialize() {
        if (initialized) return;
        
        MediaFormatAudio fmt;
        fmt.type = PJMEDIA_TYPE_AUDIO;
        fmt.clockRate = clockRate;
        fmt.channelCount = channelCount;
        fmt.bitsPerSample = 16;
        fmt.frameTimeUsec = (samplesPerFrame * 1000000ULL) / clockRate;
        createPort("pcm_media", fmt);
        initialized = true;
    }

    void start();
    void stop();

    // пуш PCM в звонок
    void push(const int16_t* samples, size_t count);

protected:
    virtual void onFrameRequested(MediaFrame &frame) override;
    virtual void onFrameReceived(MediaFrame &frame) override;

private:
    unsigned clockRate;
    unsigned channelCount;
    unsigned samplesPerFrame;
    bool initialized;

    std::vector<int16_t> txBuffer;
    std::mutex mtx;
};