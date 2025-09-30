# bot/stt_adapter.py
import asyncio
import logging
import struct
from langchain_community.utilities.nvidia_riva import RivaASR
import rich.logging

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class STTAdapter:
    def __init__(self, config: dict, logger: logging.Logger, media_port=None):
        self.config = config
        self.logger = logger.getChild('STT')
        self.media_port = media_port  # Reference to ByteStreamMediaPort
        stt_cfg = config.get('stt', {})
        self.energy_threshold = int(stt_cfg.get('energy_threshold', 500))
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
        
        self.riva_asr = RivaASR(
            audio_channel_count=1,
            profanity_filter=stt_cfg.get('profanity_filter', True),
            enable_automatic_punctuation=stt_cfg.get('enable_automatic_punctuation', True)
        )

        # Start processing media port chunks if provided
        if media_port:
            asyncio.create_task(self.process_media_port_chunks())

    async def process_media_port_chunks(self):
        """Process PCM chunks from media port's record_queue."""
        while not self._closed:
            try:
                chunk = await asyncio.get_event_loop().run_in_executor(None, self.media_port.get_next_record_chunk)
                if chunk:
                    self.feed_pcm(chunk)
                else:
                    await asyncio.sleep(0.02)  # Avoid tight loop
            except Exception as e:
                self.logger.error(f"Error processing media port chunk: {e}", exc_info=True)

    def close(self):
        self._closed = True

    def feed_pcm(self, frame: bytes):
        if self._closed or not frame:
            return
        try:
            samples = struct.unpack('<' + 'h' * (len(frame) // 2), frame)
            avg_abs = sum(abs(s) for s in samples) / max(1, len(samples))
            is_voice = avg_abs >= self.energy_threshold

            if is_voice:
                if not self._speech_active:
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
                    if self._current_ms >= self.min_chunk_ms and self._silence_ms >= self.silence_end_ms:
                        payload = bytes(self._current)
                        self._speech_active = False
                        self._current.clear()
                        self._current_ms = 0
                        self._silence_ms = 0
                        asyncio.create_task(self._transcribe_and_emit(payload))
        except Exception as e:
            self.logger.error(f"Error processing PCM frame: {e}", exc_info=True)

    async def _transcribe_and_emit(self, pcm_s16le_8k: bytes):
        try:
            text = await self.transcribe(pcm_s16le_8k)
            if text and text.strip():
                await self.out_queue.put(text.strip())
        except Exception as e:
            self.logger.error(f"STT transcribe failed: {e}", exc_info=True)

    async def transcribe(self, pcm_s16le_8k: bytes) -> str:
        self.logger.debug(f"Transcribing segment ({len(pcm_s16le_8k)} bytes) using Riva ASR")
        try:
            text = await self.riva_asr.ainvoke(pcm_s16le_8k)
            return text
        except Exception as e:
            self.logger.error(f"Riva ASR transcription failed: {e}", exc_info=True)
            return ""