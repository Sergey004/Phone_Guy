# bot/stt_adapter.py
import asyncio
import logging
import struct
import rich.logging
import tempfile
import wave
import numpy as np
from scipy import signal
from faster_whisper import WhisperModel
import queue

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class STTAdapter:
    def __init__(self, config: dict, logger: logging.Logger, media_port=None):
        self.config = config
        self.logger = logger.getChild('STT')
        self.media_port = media_port  # Reference to AudioCapturePort
        stt_cfg = config.get('stt', {})
        self.energy_threshold = int(stt_cfg.get('energy_threshold', 500))
        self.min_chunk_ms = int(stt_cfg.get('min_chunk_ms', 1500))
        self.silence_end_ms = int(stt_cfg.get('silence_end_ms', 600))
        self.sample_rate = 8000
        self.target_sample_rate = int(stt_cfg.get('target_sample_rate', 16000))
        self.frame_ms = 20
        self._speech_active = False
        self._current = bytearray()
        self._current_np = []
        self._current_ms = 0
        self._silence_ms = 0
        self.out_queue: asyncio.Queue[str] = asyncio.Queue()
        self._closed = False
        self._frame_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=256)
        model_size = stt_cfg.get('model', 'base')
        self.device = stt_cfg.get('device', 'cpu')
        self.compute_type = stt_cfg.get('compute_type', 'int8' if self.device == 'cpu' else 'float16')
        self.language = stt_cfg.get('language', None)
        self.translate = bool(stt_cfg.get('translate', True))
        self.beam_size = int(stt_cfg.get('beam_size', 5))
        n_threads = stt_cfg.get('n_threads')
        self.cpu_threads = int(n_threads) if n_threads is not None else 1
        self.whisper_model = WhisperModel(model_size, device=self.device, compute_type=self.compute_type, num_workers=self.cpu_threads)

        # Start processing media port chunks if provided
        if media_port:
            asyncio.create_task(self.process_media_port_chunks())

    def enqueue_frame(self, frame_bytes: bytes):
        try:
            if not self._closed and frame_bytes:
                self._frame_queue.put_nowait(frame_bytes)
        except queue.Full:
            pass

    async def consume_frame_queue(self):
        while not self._closed:
            try:
                frame = await asyncio.get_event_loop().run_in_executor(None, self._frame_queue.get)
                if frame:
                    self.feed_pcm(frame)
            except Exception as e:
                self.logger.error(f"Error consuming frame queue: {e}", exc_info=True)
            await asyncio.sleep(0.0)
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
            x = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            self.feed_numpy(x)
            self._current.extend(frame)
        except Exception as e:
            self.logger.error(f"Error processing PCM frame: {e}", exc_info=True)

    def feed_numpy(self, x: np.ndarray):
        if self._closed or x is None or x.size == 0:
            return
        try:
            avg_abs_i16 = float(np.mean(np.abs(x)) * 32768.0)
            is_voice = avg_abs_i16 >= self.energy_threshold

            if is_voice:
                if not self._speech_active:
                    self._speech_active = True
                    self._current_np.clear()
                    self._current.clear()
                    self._current_ms = 0
                    self._silence_ms = 0
                self._current_np.append(x)
                self._current_ms += self.frame_ms
                self._silence_ms = 0
            else:
                if self._speech_active:
                    self._silence_ms += self.frame_ms
                    self._current_np.append(x)
                    self._current_ms += self.frame_ms
                    if self._current_ms >= self.min_chunk_ms and self._silence_ms >= self.silence_end_ms:
                        payload_np = np.concatenate(self._current_np) if len(self._current_np) > 0 else np.array([], dtype=np.float32)
                        self._speech_active = False
                        self._current_np.clear()
                        self._current.clear()
                        self._current_ms = 0
                        self._silence_ms = 0
                        asyncio.create_task(self._transcribe_and_emit_numpy(payload_np, self.sample_rate))
        except Exception as e:
            self.logger.error(f"Error processing numpy frame: {e}", exc_info=True)

    async def _transcribe_and_emit(self, pcm_s16le_8k: bytes):
        try:
            text = await self.transcribe(pcm_s16le_8k)
            if text and text.strip():
                await self.out_queue.put(text.strip())
        except Exception as e:
            self.logger.error(f"STT transcribe failed: {e}", exc_info=True)

    async def _transcribe_and_emit_numpy(self, wav: np.ndarray, sr: int):
        try:
            text = await self.transcribe_numpy(wav, sr)
            if text and text.strip():
                await self.out_queue.put(text.strip())
        except Exception as e:
            self.logger.error(f"STT transcribe (numpy) failed: {e}", exc_info=True)

    async def transcribe(self, pcm_s16le_8k: bytes) -> str:
        try:
            def write_and_transcribe():
                wav = np.frombuffer(pcm_s16le_8k, dtype=np.int16).astype(np.float32) / 32768.0
                sr = self.sample_rate
                if self.target_sample_rate and self.target_sample_rate != sr:
                    n_out = int(round(len(wav) * self.target_sample_rate / sr))
                    wav = signal.resample(wav, n_out)
                    sr = self.target_sample_rate
                wav_i16 = np.clip(wav, -1.0, 1.0)
                wav_i16 = (wav_i16 * 32767.0).astype(np.int16)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    with wave.open(tmp.name, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sr)
                        wf.writeframes(wav_i16.tobytes())
                    segments, _ = self.whisper_model.transcribe(tmp.name, beam_size=self.beam_size, language=self.language or None, vad_filter=False, task=("translate" if self.translate else "transcribe"))
                    return " ".join(getattr(s, "text", "") for s in segments).strip()
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, write_and_transcribe)
        except Exception as e:
            self.logger.error(f"Whisper.cpp transcription failed: {e}", exc_info=True)
            return ""

    async def transcribe_numpy(self, wav: np.ndarray, sample_rate: int) -> str:
        try:
            def write_and_transcribe_np():
                x = np.asarray(wav)
                if x.ndim > 1:
                    x = np.squeeze(x)
                if x.ndim != 1:
                    x = x.reshape(-1)
                x = x.astype(np.float32, copy=False)
                sr = int(sample_rate)
                if self.target_sample_rate and self.target_sample_rate != sr:
                    n_out = int(round(len(x) * self.target_sample_rate / sr))
                    x = signal.resample(x, n_out)
                    sr = self.target_sample_rate
                xi16 = np.clip(x, -1.0, 1.0)
                xi16 = (xi16 * 32767.0).astype(np.int16)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    with wave.open(tmp.name, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sr)
                        wf.writeframes(xi16.tobytes())
                    segments, _ = self.whisper_model.transcribe(tmp.name, beam_size=self.beam_size, language=self.language or None, vad_filter=False, task=("translate" if self.translate else "transcribe"))
                    return " ".join(getattr(s, "text", "") for s in segments).strip()
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, write_and_transcribe_np)
        except Exception as e:
            self.logger.error(f"Whisper.cpp transcription failed (numpy): {e}", exc_info=True)
            return ""
