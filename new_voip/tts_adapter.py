import asyncio
import logging
import torch
import torchaudio
import numpy as np
import sys
import os
import rich.logging

# Настройка путей
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from rvc_py.rvc_infer import rvc_infer
except ImportError:
    sys.path.append(os.path.join(project_root, 'rvc_py'))
    try:
        from rvc_py.rvc_infer import rvc_infer
    except ImportError as e:
        print(f"[TTS] RVC import failed: {e}")
        rvc_infer = None
else:
    print("[TTS] RVC module imported successfully")

from chatterbox.tts import ChatterboxTTS
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS

logging.getLogger('numba').setLevel(logging.ERROR)
logging.getLogger('numba.core.byteflow').setLevel(logging.ERROR)


class TTSAdapter:
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('TTS')
        
        tts_cfg = config.get('tts', {})
        self.engine = tts_cfg.get('engine', 'turbo')
        self.device = tts_cfg.get('device', 'cuda')
        self.language_id = tts_cfg.get('language_id')
        self.audio_prompt_path = tts_cfg.get('audio_prompt_path')
        self.cfg_weight = "0.3"
        
        self._speak_lock = asyncio.Lock()
        self._model = None
        
        # RVC Settings
        self.rvc_enabled = tts_cfg.get('rvc_enabled', False)
        self.rvc_model_path = tts_cfg.get('rvc_model_path')
        self.rvc_index_path = tts_cfg.get('rvc_index_path')
        self.rvc_f0_method = tts_cfg.get('rvc_f0_method', 'rmvpe')
        self.rvc_pitch_shift = tts_cfg.get('rvc_pitch_shift', 0)
        self.rvc_index_rate = tts_cfg.get('rvc_index_rate', 0.5)
        
        # Отключаем RVC если модуль не импортирован
        if rvc_infer is None:
            self.rvc_enabled = False
            self.logger.warning("RVC is disabled because rvc_infer module is not available")

    def _get_model(self):
        if self._model is not None:
            return self._model
        
        self.logger.info(f"Initializing TTS Model: {self.engine} on {self.device}")
        if self.engine.lower() == 'turbo':
            self._model = ChatterboxTurboTTS.from_pretrained(device=self.device)
        elif self.engine.lower() == 'multilingual':
            self._model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        else:
            self._model = ChatterboxTTS.from_pretrained(device=self.device)
        return self._model

    async def check_health(self) -> bool:
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._get_model)
            return True
        except Exception as e:
            self.logger.error(f"TTS health check failed: {e}")
            return False

    async def synthesize(self, text: str):
        """
        Возвращает кортеж: (PCM_BYTES, SAMPLE_RATE)
        """
        try:
            model = await asyncio.get_event_loop().run_in_executor(None, self._get_model)
            
            # 1. Генерация TTS (обычно 24k или 16k)
            def _generate():
                if isinstance(model, ChatterboxMultilingualTTS) and self.language_id:
                    return model.generate(text, language_id=self.language_id, audio_prompt_path=self.audio_prompt_path, cfg_weight=0.3)
                else:
                    return model.generate(text, audio_prompt_path=self.audio_prompt_path, cfg_weight=0.3)

            wav = await asyncio.get_event_loop().run_in_executor(None, _generate)
            sr = getattr(model, 'sr', 16000)
            
            if isinstance(wav, torch.Tensor):
                wave = wav.detach().cpu().numpy()
            else:
                wave = np.array(wav)
            
            # 2. RVC Обработка (Если включена)
            if self.rvc_enabled and self.rvc_model_path and rvc_infer:
                 try:
                     wave_np = np.asarray(wave)
                     if wave_np.ndim > 1: wave_np = np.squeeze(wave_np)
                     if wave_np.ndim != 1: wave_np = wave_np.reshape(-1)
                     wave_np = wave_np.astype(np.float32, copy=False)
                     
                     # Вызываем RVC
                     # RVC возвращает звук и НОВУЮ частоту (40000 или 48000)
                     rvc_result = await asyncio.get_event_loop().run_in_executor(
                         None,
                         lambda: rvc_infer(
                             wave_np, sr, self.rvc_model_path,
                             device=self.device, index_path=self.rvc_index_path,
                             index_rate=self.rvc_index_rate, pitch_shift=self.rvc_pitch_shift,
                             f0_method=self.rvc_f0_method
                         )
                     )
                     
                     # ЗАЩИТА ОТ РАЗНЫХ ВЕРСИЙ RVC
                     # Некоторые возвращают (audio, sr), некоторые (sr, audio)
                     if len(rvc_result) == 2:
                         val1, val2 = rvc_result
                         # Если первое число - это частота (int > 1000)
                         if isinstance(val1, int) and val1 > 1000:
                             sr = val1
                             wave = val2
                         # Если второе число - это частота
                         elif isinstance(val2, int) and val2 > 1000:
                             wave = val1
                             sr = val2
                             
                 except Exception as e:
                     self.logger.error(f"RVC Error (skipping): {e}", exc_info=True)

            # 3. Конвертация в PCM Int16
            if isinstance(wave, np.ndarray):
                wave = torch.from_numpy(wave)
            
            wave = wave.float()
            if wave.dim() == 2 and wave.size(0) > 1: wave = torch.mean(wave, dim=0, keepdim=True)
            elif wave.dim() == 1: wave = wave.unsqueeze(0)
            
            wave = wave.squeeze(0)
            wave = torch.clamp(wave, -1.0, 1.0)
            int16 = (wave.numpy() * 32767.0).astype(np.int16)
            
            return int16.tobytes(), sr

        except Exception as e:
            self.logger.error(f"Synthesis failed: {e}", exc_info=True)
            return b'', 16000

    async def speak(self, text: str, media_port):
        async with self._speak_lock:
            # Получаем байты И точную частоту (sr)
            pcm_data, sr = await self.synthesize(text)
            
            if not pcm_data:
                return

            if media_port is None:
                return
            
            # Передаем частоту (sr) в Bridge!
            self.logger.info(f"Sending audio to bridge: {len(pcm_data)} bytes at {sr} Hz")
            
            # Bridge сам сделает 48000 -> 8000 или 40000 -> 8000
            success = media_port.update_playback_data(pcm_data, sample_rate=sr, validate=True)
            
            if not success:
                self.logger.error("Failed to update bridge playback data")