// pcm_media.cpp
#include "pcm_media.hpp"
#include <cstring>

void PcmMedia::start() {
    Endpoint::instance().mediaAdd(*this);
}

void PcmMedia::stop() {
    Endpoint::instance().mediaRemove(*this);
}

void PcmMedia::push(const int16_t* samples, size_t count) {
    std::lock_guard<std::mutex> lock(mtx);
    txBuffer.insert(txBuffer.end(), samples, samples + count);
}

// PJMEDIA → МЫ (приём звука)
void PcmMedia::onFrameReceived(MediaFrame &frame) {
    if (frame.buf.empty() || frame.size == 0)
        return;

    int16_t* pcm = reinterpret_cast<int16_t*>(frame.buf.data());
    size_t samples = frame.size / sizeof(int16_t);

    // 👉 ТУТ:
    // pcm = сырой звук звонка
    // samples = количество семплов
    // формат: PCM16 mono

    // например: STT / запись / DSP
}

// МЫ → PJMEDIA (отдаём звук)
void PcmMedia::onFrameRequested(MediaFrame &frame) {
    std::lock_guard<std::mutex> lock(mtx);

    size_t needed_samples = samplesPerFrame * channelCount;
    size_t available = txBuffer.size();

    size_t toCopy = std::min(needed_samples, available);
    size_t needed_bytes = needed_samples * sizeof(int16_t);

    frame.buf.resize(needed_bytes);

    if (toCopy > 0) {
        memcpy(frame.buf.data(), txBuffer.data(), toCopy * sizeof(int16_t));
        txBuffer.erase(txBuffer.begin(), txBuffer.begin() + toCopy);
        frame.size = toCopy * sizeof(int16_t);
    } else {
        memset(frame.buf.data(), 0, needed_bytes);
        frame.size = needed_bytes;
    }
}