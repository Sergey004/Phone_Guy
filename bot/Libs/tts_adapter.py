# bot/tts_adapter.py
import asyncio
import logging
import torch
import torchaudio
import numpy as np
import sys
import os

# Add project root to python path to allow importing rvc_py
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from rvc_py.rvc_infer import rvc_infer
except ImportError:
    # Try alternate import if running from different context
    sys.path.append(os.path.join(project_root, 'rvc_py'))
    from rvc_py.rvc_infer import rvc_infer
import rich.logging
from chatterbox.tts import ChatterboxTTS
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS
from .rtp_streamer import ByteStreamMediaPort
logging.getLogger('numba').setLevel(logging.WARNING)


logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class TTSAdapter:
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('TTS')
        tts_cfg = config.get('tts', {})
        self.engine = tts_cfg.get('engine', 'turbo')
        self.device = tts_cfg.get('device', 'cuda')
        self.language_id = tts_cfg.get('language_id')
        self.audio_prompt_path = tts_cfg.get('audio_prompt_path')
        self.sample_rate = 8000
        self._speak_lock = asyncio.Lock()
        self._model = None
        
        # RVC Configuration
        self.rvc_enabled = tts_cfg.get('rvc_enabled', False)
        self.rvc_model_path = tts_cfg.get('rvc_model_path')
        self.rvc_index_path = tts_cfg.get('rvc_index_path')
        self.rvc_f0_method = tts_cfg.get('rvc_f0_method', 'rmvpe')
        self.rvc_pitch_shift = tts_cfg.get('rvc_pitch_shift', 0)
        self.rvc_index_rate = tts_cfg.get('rvc_index_rate', 0.5)

    def _get_model(self):
        if self._model is not None:
            return self._model
        if self.engine.lower() == 'turbo':
            self._model = ChatterboxTurboTTS.from_pretrained(device=self.device)
        elif self.engine.lower() == 'multilingual':
            self._model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        else:
            self._model = ChatterboxTTS.from_pretrained(device=self.device)
        return self._model

    async def check_health(self, retries: int = 3, backoff: float = 1.0) -> bool:
        for attempt in range(1, retries + 1):
            try:
                model = await asyncio.get_event_loop().run_in_executor(None, self._get_model)
                if model is not None:
                    self.logger.info("TTS engine ready")
                    return True
            except Exception as e:
                self.logger.error(f"TTS health check failed (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    await asyncio.sleep(backoff * attempt)
        self.logger.error("All TTS health check attempts failed.")
        return False

    async def synthesize(self, text: str, voice: str = None, retries: int = 3) -> bytes:
        for attempt in range(1, retries + 1):
            self.logger.info(f"🎤 Начинаем синтез текста: '{text[:50]}...' ({attempt}/{retries})")
            try:
                model = await asyncio.get_event_loop().run_in_executor(None, self._get_model)
                if isinstance(model, ChatterboxMultilingualTTS) and self.language_id:
                    wav = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: model.generate(text, language_id=self.language_id, audio_prompt_path=self.audio_prompt_path)
                    )
                else:
                    wav = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: model.generate(text, audio_prompt_path=self.audio_prompt_path)
                    )
                sr = getattr(model, 'sr', 16000)
                if isinstance(wav, torch.Tensor):
                    wave = wav.detach().cpu().numpy()
                else:
                    wave = np.array(wav)
                
                # Apply RVC if enabled
                if self.rvc_enabled and self.rvc_model_path:
                     self.logger.info(f"🔄 Применяем RVC обработку: {self.rvc_model_path}")
                     try:
                         # Ensure waveform is 1D float32 for RVC/RMVPE
                         wave_np = np.asarray(wave)
                         if wave_np.ndim > 1:
                             wave_np = np.squeeze(wave_np)
                         if wave_np.ndim != 1:
                             wave_np = wave_np.reshape(-1)
                         wave_np = wave_np.astype(np.float32, copy=False)
                         wave, sr = await asyncio.get_event_loop().run_in_executor(
                             None,
                             lambda: rvc_infer(
                                 wave_np,
                                 sr,
                                 self.rvc_model_path,
                                 device=self.device,
                                 index_path=self.rvc_index_path,
                                 index_rate=self.rvc_index_rate,
                                 pitch_shift=self.rvc_pitch_shift,
                                 f0_method=self.rvc_f0_method
                             )
                         )
                     except Exception as e:
                         self.logger.error(f"⚠️ Ошибка RVC обработки: {e}", exc_info=True)
                         # Fallback to original audio if RVC fails
                
                # Convert back to torch tensor for resampling
                wave = torch.tensor(wave).float()

                if wave.dim() == 2 and wave.size(0) > 1:
                    wave = torch.mean(wave, dim=0, keepdim=True)
                elif wave.dim() == 1:
                    wave = wave.unsqueeze(0)
                if sr != self.sample_rate:
                    wave = torchaudio.functional.resample(wave, sr, self.sample_rate)
                wave = wave.squeeze(0)
                wave = torch.clamp(wave, -1.0, 1.0)
                int16 = (wave.numpy() * 32767.0).astype(np.int16)
                pcm = int16.tobytes()
                if len(pcm) == 0:
                    if attempt < retries:
                        continue
                    return b''
                self.logger.info(f"✅ Синтез успешно завершен: {len(pcm)} байт PCM данных")
                return pcm
            except Exception as e:
                self.logger.error(f"🎤 Ошибка синтеза на попытке {attempt}/{retries}: {e}", exc_info=True)
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                return b''

    async def speak(self, text: str, media_port: 'ByteStreamMediaPort', media_ready_event=None):
        async with self._speak_lock:
            self.logger.info(f"🎤 TTS speak: '{text[:50]}...'")
            self.logger.info(f"🎤 Media port: {type(media_port).__name__}")
            self.logger.info(f"🎤 Text length: {len(text)} characters, {len(text.split())} words")
            
            try:
                # Wait for TTS server response
                self.logger.info("🎤 Начинаем синтез речи...")
                pcm_data = await self.synthesize(text)
                
                self.logger.info(f"🎤 Получены PCM данные: {len(pcm_data)} байт")
                
                if not pcm_data:
                    self.logger.warning("🎤 Нет PCM данных от synthesize – отправляем тишину.")
                    return
                
                # Check if media_port is valid
                if media_port is None:
                    self.logger.error("🎤 Media port is None, cannot update playback data")
                    return
                
                self.logger.info("🎤 Обновляем данные воспроизведения в медиа-порту...")
                # Update media port only after successful synthesis
                media_port.update_playback_data(pcm_data)
                self.logger.info("✅ TTS PCM данные успешно обновлены в медиа-порту.")
                if media_ready_event:
                    media_ready_event.set()
                
            except Exception as e:
                self.logger.error(f"🎤 Ошибка TTS speak: {e}", exc_info=True)
                self.logger.error(f"🎤 Тип ошибки: {type(e).__name__}")
                self.logger.error(f"🎤 Детали ошибки: {str(e)}")
