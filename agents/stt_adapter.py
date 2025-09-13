import asyncio
import logging
import struct

class STTAdapter:
    """
    Minimal STT scaffolding with real-time PCM feed (8kHz, mono, s16).
    - Segments stream by simple energy-based VAD.
    - For now, transcribe() is a stub; replace with provider call (e.g., Whisper API) later.
    """
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('STT')
        stt_cfg = config.get('stt', {})
        self.energy_threshold = int(stt_cfg.get('energy_threshold', 500))  # avg abs amplitude
        self.min_chunk_ms = int(stt_cfg.get('min_chunk_ms', 1500))
        self.silence_end_ms = int(stt_cfg.get('silence_end_ms', 600))
        self.sample_rate = 8000
        self.frame_ms = 20
        self._speech_active = False
        self._current = bytearray()
        self._current_ms = 0
        self._silence_ms = 0
        self.out_queue: asyncio.Queue[str] = asyncio.Queue()
        self._closed = False

    def close(self):
        self._closed = True

    def feed_pcm(self, frame: bytes):
        """
        Feed a 20ms frame (160 samples, s16le).
        """
        if self._closed:
            return
        # compute average absolute amplitude
        if not frame:
            return
        # Unpack as signed 16-bit little-endian
        try:
            samples = struct.unpack('<' + 'h' * (len(frame) // 2), frame)
        except Exception:
            return
        avg_abs = sum(abs(s) for s in samples) / max(1, len(samples))
        is_voice = avg_abs >= self.energy_threshold

        if is_voice:
            if not self._speech_active:
                # start of speech
                self._speech_active = True
                self._current.clear()
                self._current_ms = 0
                self._silence_ms = 0
            self._current.extend(frame)
            self._current_ms += self.frame_ms
            self._silence_ms = 0
        else:
            if self._speech_active:
                self._silence_ms += self.frame_ms
                self._current.extend(frame)
                self._current_ms += self.frame_ms
                # end of utterance
                if self._current_ms >= self.min_chunk_ms and self._silence_ms >= self.silence_end_ms:
                    payload = bytes(self._current)
                    # reset state
                    self._speech_active = False
                    self._current.clear()
                    self._current_ms = 0
                    self._silence_ms = 0
                    # fire transcription task (don't await here)
                    asyncio.create_task(self._transcribe_and_emit(payload))
            else:
                # remain idle
                pass

    async def _transcribe_and_emit(self, pcm_s16le_8k: bytes):
        try:
            text = await self.transcribe(pcm_s16le_8k)
            if text and text.strip():
                await self.out_queue.put(text.strip())
        except Exception as e:
            self.logger.error(f"STT transcribe failed: {e}", exc_info=True)

    async def transcribe(self, pcm_s16le_8k: bytes) -> str:
        """
        Stub transcription: returns a placeholder string with duration.
        Replace with provider integration (e.g., send HTTP to Whisper, Vosk, Azure).
        """
        dur = len(pcm_s16le_8k) / 2 / self.sample_rate
        self.logger.debug(f"Transcribing segment ~{dur:.2f}s ({len(pcm_s16le_8k)} bytes)")
        # Simulate network delay
        await asyncio.sleep(min(1.0, max(0.1, dur * 0.2)))
        return f"[распознано ~{dur:.1f}с аудио]"