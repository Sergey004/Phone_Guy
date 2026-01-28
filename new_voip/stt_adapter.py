import asyncio
import logging
import rich.logging
import tempfile
import wave
import numpy as np
from scipy import signal
from faster_whisper import WhisperModel
import queue

# Настройка логгера, если он еще не настроен
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class STTAdapter:
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('STT')
        
        # Настройки VAD и буферизации
        stt_cfg = config.get('stt', {})
        self.energy_threshold = int(stt_cfg.get('energy_threshold', 500))
        self.min_chunk_ms = int(stt_cfg.get('min_chunk_ms', 1500))
        self.silence_end_ms = int(stt_cfg.get('silence_end_ms', 600))
        
        # Параметры аудио
        self.sample_rate = 8000 # Входящий от RTP (после декодирования G.711)
        self.target_sample_rate = int(stt_cfg.get('target_sample_rate', 16000)) # Для Whisper
        self.frame_ms = 20
        
        # Состояние VAD
        self._speech_active = False
        self._current = bytearray()
        self._current_np = []
        self._current_ms = 0
        self._silence_ms = 0
        
        # Очереди
        self.out_queue: asyncio.Queue[str] = asyncio.Queue() # Сюда кладем текст
        self._frame_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=512) # Входящий PCM
        self._closed = False
        
        # Инициализация Whisper
        model_size = stt_cfg.get('model', 'base')
        self.device = stt_cfg.get('device', 'cpu')
        self.compute_type = stt_cfg.get('compute_type', 'int8' if self.device == 'cpu' else 'float16')
        self.language = stt_cfg.get('language', None)
        self.translate = bool(stt_cfg.get('translate', False))
        self.beam_size = int(stt_cfg.get('beam_size', 5))
        
        self.logger.info(f"Loading Whisper model '{model_size}' on {self.device}...")
        self.whisper_model = WhisperModel(
            model_size, 
            device=self.device, 
            compute_type=self.compute_type, 
            num_workers=int(stt_cfg.get('n_threads', 1))
        )
        self.logger.info("Whisper loaded.")

    def enqueue_frame(self, frame_bytes: bytes):
        """
        Метод вызывается из RTPProtocol.
        Принимает декодированный PCM16 (bytes).
        """
        try:
            if not self._closed and frame_bytes:
                self._frame_queue.put_nowait(frame_bytes)
        except queue.Full:
            pass # Если не успеваем обрабатывать, дропаем пакеты (real-time)

    async def consume_frame_queue(self):
        """
        Фоновая задача: забирает сырые байты из очереди и скармливает VAD.
        Запускается один раз при старте.
        """
        self.logger.info("STT Frame Consumer started")
        while not self._closed:
            try:
                # Используем run_in_executor для блокирующего get, чтобы не вешать loop
                frame = await asyncio.get_event_loop().run_in_executor(None, self._frame_queue.get)
                if frame:
                    self.feed_pcm(frame)
            except Exception as e:
                self.logger.error(f"Error consuming frame queue: {e}", exc_info=True)
            
            # Даем дышать циклу
            await asyncio.sleep(0.0)

    def close(self):
        self._closed = True

    def feed_pcm(self, frame: bytes):
        """Конвертирует bytes -> float32 numpy и передает в VAD"""
        if self._closed or not frame:
            return
        try:
            # RTP отдает int16, Whisper любит float32 [-1.0, 1.0]
            x = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            self.feed_numpy(x)
        except Exception as e:
            self.logger.error(f"Error processing PCM frame: {e}", exc_info=True)

    def feed_numpy(self, x: np.ndarray):
        """Логика VAD (Voice Activity Detection)"""
        if self._closed or x is None or x.size == 0:
            return
        try:
            # Считаем энергию
            avg_abs_i16 = float(np.mean(np.abs(x)) * 32768.0)
            is_voice = avg_abs_i16 >= self.energy_threshold

            if is_voice:
                if not self._speech_active:
                    self._speech_active = True
                    self._current_np.clear()
                    self._current_ms = 0
                    self._silence_ms = 0
                    # self.logger.debug("VAD: Speech started")
                
                self._current_np.append(x)
                self._current_ms += self.frame_ms
                self._silence_ms = 0
            else:
                if self._speech_active:
                    self._silence_ms += self.frame_ms
                    self._current_np.append(x)
                    self._current_ms += self.frame_ms
                    
                    # Если тишина длится достаточно долго - считаем фразу законченной
                    if self._current_ms >= self.min_chunk_ms and self._silence_ms >= self.silence_end_ms:
                        # self.logger.debug("VAD: Speech ended, transcribing...")
                        payload_np = np.concatenate(self._current_np) if len(self._current_np) > 0 else np.array([], dtype=np.float32)
                        
                        # Сброс состояния
                        self._speech_active = False
                        self._current_np.clear()
                        self._current_ms = 0
                        self._silence_ms = 0
                        
                        # Отправляем на распознавание
                        asyncio.create_task(self._transcribe_and_emit_numpy(payload_np, self.sample_rate))
        except Exception as e:
            self.logger.error(f"Error processing numpy frame: {e}", exc_info=True)

    async def _transcribe_and_emit_numpy(self, wav: np.ndarray, sr: int):
        try:
            text = await self.transcribe_numpy(wav, sr)
            if text and text.strip():
                # self.logger.info(f"STT Recognized: {text}")
                await self.out_queue.put(text.strip())
        except Exception as e:
            self.logger.error(f"STT transcribe (numpy) failed: {e}", exc_info=True)

    async def transcribe_numpy(self, wav: np.ndarray, sample_rate: int) -> str:
        """Обертка над whisper для запуска в треде"""
        try:
            def write_and_transcribe_np():
                # Подготовка аудио
                x = np.asarray(wav)
                if x.ndim > 1: x = np.squeeze(x)
                x = x.astype(np.float32, copy=False)
                
                # Ресемплинг если нужно (8000 -> 16000)
                sr = int(sample_rate)
                if self.target_sample_rate and self.target_sample_rate != sr:
                    n_out = int(round(len(x) * self.target_sample_rate / sr))
                    x = signal.resample(x, n_out)
                    sr = self.target_sample_rate
                
                # Обратно в int16 для сохранения во временный файл (Whisper.cpp / API часто любят файлы)
                # Хотя faster-whisper может принимать ndarray напрямую, сохранение в файл 
                # часто надежнее работает с разными версиями библиотек.
                xi16 = np.clip(x, -1.0, 1.0)
                xi16 = (xi16 * 32767.0).astype(np.int16)
                
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    with wave.open(tmp.name, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sr)
                        wf.writeframes(xi16.tobytes())
                    
                    segments, _ = self.whisper_model.transcribe(
                        tmp.name, 
                        beam_size=self.beam_size, 
                        language=self.language or None, 
                        vad_filter=False, 
                        task=("translate" if self.translate else "transcribe")
                    )
                    return " ".join(getattr(s, "text", "") for s in segments).strip()
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, write_and_transcribe_np)
        except Exception as e:
            self.logger.error(f"Whisper transcription failed: {e}", exc_info=True)
            return ""