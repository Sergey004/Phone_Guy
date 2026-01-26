"""
Simple TTS Adapter - Pure Python implementation
No PJSIP dependencies - works with Chatterbox TTS directly
"""

import asyncio
import logging
import numpy as np
import torch
import torchaudio
import audioop
from typing import Optional
from AI.audio.audio_playback_simple import SimpleAudioPlaybackPort

try:
    from chatterbox.tts import ChatterboxTTS
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from chatterbox.tts_turbo import ChatterboxTurboTTS
    CHATTERBOX_AVAILABLE = True
except ImportError:
    CHATTERBOX_AVAILABLE = False

try:
    from rvc_py.rvc_infer import rvc_infer
    RVC_AVAILABLE = True
except ImportError:
    RVC_AVAILABLE = False

logging.getLogger('numba').setLevel(logging.WARNING)
numba_logger = logging.getLogger('numba')
numba_logger.setLevel(logging.WARNING)
numba_logger.propagate = False


class SimpleTTSAdapter:
    """Simple TTS adapter without PJSIP dependencies."""
    
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('SimpleTTS')
        tts_cfg = config.get('tts', {})
        self.engine = tts_cfg.get('engine', 'turbo')
        self.device = tts_cfg.get('device', 'cuda')
        self.language_id = tts_cfg.get('language_id')
        self.sample_rate = 8000
        
        self._model = None
        
        # RVC Configuration
        self.rvc_enabled = tts_cfg.get('rvc_enabled', False)
        self.rvc_model_path = tts_cfg.get('rvc_model_path')
        self.rvc_index_path = tts_cfg.get('rvc_index_path')
        self.rvc_f0_method = tts_cfg.get('rvc_f0_method', 'rmvpe')
        self.rvc_pitch_shift = tts_cfg.get('rvc_pitch_shift', 0)
        self.rvc_index_rate = tts_cfg.get('rvc_index_rate', 0.5)
        
        # Audio playback port (simple version without PJSIP)
        self.playback_port = SimpleAudioPlaybackPort(
            sample_rate=self.sample_rate,
            frame_size_ms=20,
            logger=self.logger
        )
        
        self.logger.info(f"SimpleTTSAdapter initialized: engine={self.engine}, device={self.device}")
    
    def _get_model(self):
        if self._model is not None:
            return self._model
        
        if not CHATTERBOX_AVAILABLE:
            raise ImportError("Chatterbox TTS not available. Install with: pip install chatterbox")
        
        if self.engine.lower() == 'turbo':
            self._model = ChatterboxTurboTTS.from_pretrained(device=self.device)
        elif self.engine.lower() == 'multilingual':
            self._model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        else:
            self._model = ChatterboxTTS.from_pretrained(device=self.device)
        
        return self._model
    
    async def check_health(self, retries: int = 3, backoff: float = 1.0) -> bool:
        """Check if TTS engine is healthy."""
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
        """Synthesize speech from text."""
        for attempt in range(1, retries + 1):
            self.logger.info(f"🎤 Synthesizing: '{text[:50]}...' ({attempt}/{retries})")
            try:
                model = await asyncio.get_event_loop().run_in_executor(None, self._get_model)
                
                # Generate speech
                if isinstance(model, ChatterboxMultilingualTTS) and self.language_id:
                    wav = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: model.generate(text, language_id=self.language_id, audio_prompt_path=None)
                    )
                else:
                    wav = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: model.generate(text, audio_prompt_path=None)
                    )
                
                sr = getattr(model, 'sr', 16000)
                
                # Convert to numpy
                if isinstance(wav, torch.Tensor):
                    wave = wav.detach().cpu().numpy()
                else:
                    wave = np.array(wav)
                
                # Apply RVC if enabled
                if self.rvc_enabled and self.rvc_model_path and RVC_AVAILABLE:
                    self.logger.info(f"🔄 Applying RVC: {self.rvc_model_path}")
                    try:
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
                        self.logger.error(f"⚠️ RVC error: {e}", exc_info=True)
                
                # Convert back to torch for resampling
                wave = torch.tensor(wave).float()
                
                if wave.dim() == 2 and wave.size(0) > 1:
                    wave = torch.mean(wave, dim=0, keepdim=True)
                elif wave.dim() == 1:
                    wave = wave.unsqueeze(0)
                
                # Resample to 8000 Hz if needed
                if sr != self.sample_rate:
                    wave = torchaudio.functional.resample(wave, sr, self.sample_rate)
                
                wave = wave.squeeze(0)
                wave = torch.clamp(wave, -1.0, 1.0)
                
                # Convert to int16 PCM
                int16 = (wave.numpy() * 32767.0).astype(np.int16)
                pcm = int16.tobytes()
                
                if len(pcm) == 0:
                    if attempt < retries:
                        continue
                    return b''
                
                self.logger.info(f"✅ Synthesized: {len(pcm)} bytes PCM")
                return pcm
                
            except Exception as e:
                self.logger.error(f"🎤 Synthesis error (attempt {attempt}/{retries}): {e}", exc_info=True)
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                return b''
    
    def synthesize_sync(self, text: str, voice: str = None, retries: int = 3) -> bytes:
        """Synchronous version of synthesize for threading."""
        for attempt in range(1, retries + 1):
            self.logger.info(f"🎤 Synthesizing (sync): '{text[:50]}...' ({attempt}/{retries})")
            try:
                model = self._get_model()
                
                # Generate speech
                if isinstance(model, ChatterboxMultilingualTTS) and self.language_id:
                    wav = model.generate(text, language_id=self.language_id, audio_prompt_path=None)
                else:
                    wav = model.generate(text, audio_prompt_path=None)
                
                sr = getattr(model, 'sr', 16000)
                
                # Convert to numpy
                if isinstance(wav, torch.Tensor):
                    wave = wav.detach().cpu().numpy()
                else:
                    wave = np.array(wav)
                
                # Apply RVC if enabled
                if self.rvc_enabled and self.rvc_model_path and RVC_AVAILABLE:
                    self.logger.info(f"🔄 Applying RVC: {self.rvc_model_path}")
                    try:
                        wave_np = np.asarray(wave)
                        if wave_np.ndim > 1:
                            wave_np = np.squeeze(wave_np)
                        if wave_np.ndim != 1:
                            wave_np = wave_np.reshape(-1)
                        wave_np = wave_np.astype(np.float32, copy=False)
                        
                        wave, sr = rvc_infer(
                            wave_np,
                            sr,
                            self.rvc_model_path,
                            device=self.device,
                            index_path=self.rvc_index_path,
                            index_rate=self.rvc_index_rate,
                            pitch_shift=self.rvc_pitch_shift,
                            f0_method=self.rvc_f0_method
                        )
                    except Exception as e:
                        self.logger.error(f"⚠️ RVC error: {e}", exc_info=True)
                
                # Convert back to torch for resampling
                wave = torch.tensor(wave).float()
                
                if wave.dim() == 2 and wave.size(0) > 1:
                    wave = torch.mean(wave, dim=0, keepdim=True)
                elif wave.dim() == 1:
                    wave = wave.unsqueeze(0)
                
                # Resample to 8000 Hz if needed
                if sr != self.sample_rate:
                    wave = torchaudio.functional.resample(wave, sr, self.sample_rate)
                
                wave = wave.squeeze(0)
                wave = torch.clamp(wave, -1.0, 1.0)
                
                # Convert to int16 PCM
                int16 = (wave.numpy() * 32767.0).astype(np.int16)
                pcm = int16.tobytes()
                
                if len(pcm) == 0:
                    if attempt < retries:
                        import time
                        time.sleep(1.0 * attempt)
                        continue
                    return b''
                
                self.logger.info(f"✅ Synthesized: {len(pcm)} bytes PCM")
                return pcm
                
            except Exception as e:
                self.logger.error(f"🎤 Synthesis error (attempt {attempt}/{retries}): {e}", exc_info=True)
                if attempt < retries:
                    import time
                    time.sleep(1.0 * attempt)
                    continue
                return b''
    
    async def speak(self, text: str, media_port=None, media_ready_event=None):
        """Synthesize and speak text."""
        self.logger.info(f"🎤 Speaking: '{text[:50]}...'")
        
        try:
            # Synthesize
            pcm_data = await self.synthesize(text)
            
            if not pcm_data:
                self.logger.warning("No PCM data from synthesis")
                return
            
            # Convert to PCMA for SIP/RTP
            pcma_data = audioop.lin2alaw(pcm_data, 2)
            self.logger.info(f"✅ Converted to PCMA: {len(pcma_data)} bytes")
            
            # Update playback port
            if media_port:
                media_port.update_playback_data(pcma_data, validate=True)
                stats = media_port.get_stats()
                self.logger.info(f"📊 Duration: {stats['duration_seconds']:.2f}s")
            
            if media_ready_event:
                media_ready_event.set()
            
        except Exception as e:
            self.logger.error(f"🎤 Speak error: {e}", exc_info=True)
    
    def check_health_sync(self, retries: int = 3, backoff: float = 1.0) -> bool:
        """Synchronous version of check_health."""
        for attempt in range(1, retries + 1):
            try:
                model = self._get_model()
                if model is not None:
                    self.logger.info("TTS engine ready")
                    return True
            except Exception as e:
                self.logger.error(f"TTS health check failed (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    import time
                    time.sleep(backoff * attempt)
        self.logger.error("All TTS health check attempts failed.")
        return False
