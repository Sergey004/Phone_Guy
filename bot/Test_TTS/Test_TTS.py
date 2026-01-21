#!/usr/bin/env python3
"""
Test VoIP call with TTS - NO THREADING
Generate TTS beforehand to avoid Segmentation fault
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import logging
import queue
import pjsua2 as pj
from Libs.tts_adapter import TTSAdapter
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall
from Libs.wav_converter import ensure_pjsua_compatible
import wave
import numpy as np
import torch
import torchaudio


logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)
logging.getLogger('numba').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
calls = []  # Global list to keep strong references to call objects


class TTSCall(VoIPCall):
    """TTS call implementation with dynamic TTS."""
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.wav_file = None
        self.logger.info("TTSCall initialized")
    
    def set_tts_file(self, wav_file: str):
        """Set the TTS WAV file to play."""
        self.wav_file = wav_file
        self.logger.info(f"TTS file set: {wav_file}")

    def onCallState(self, prm):
        """Handle call state changes."""
        try:
            ci = self.getInfo()
            self.logger.info(f"Call state: {ci.stateText}")
            
            if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
                self.logger.info("Call is confirmed. Playing TTS audio...")
                self._play_tts_audio()
                    
            elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.logger.info("Call disconnected")
            
            # Call parent handler
            super().onCallState(prm)
            
        except Exception as e:
            self.logger.error(f"Error in onCallState: {e}", exc_info=True)
    
    def _play_tts_audio(self):
        """Play the pre-generated TTS audio file."""
        try:
            if not self.wav_file or not os.path.exists(self.wav_file):
                self.logger.error("TTS WAV file not found")
                return
            
            # Get audio media
            try:
                audio_media = self.getAudioMedia(0)
            except Exception:
                ci = self.getInfo()
                if not ci.media:
                    self.logger.error("No media found")
                    return
                
                for mi in ci.media:
                    if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                        audio_media = self.getAudioMedia(mi.index)
                        break
                else:
                    self.logger.error("No active audio media found")
                    return
            
            # Ensure WAV is compatible with PJSIP
            compatible_file = ensure_pjsua_compatible(self.wav_file, target_rate=8000)
            self.logger.info(f"Playing TTS audio: {compatible_file}")
            
            # Play audio file using VoIPCall method
            if self.play_audio_file(compatible_file, audio_media):
                # Calculate audio duration
                import soundfile as sf
                try:
                    data, sr = sf.read(compatible_file)
                    duration_seconds = len(data) / sr
                    self.logger.info(f"Audio duration: {duration_seconds:.2f} seconds")
                    
                    # Schedule hangup after playback
                    self.schedule_hangup(duration_seconds + 0.5)
                except Exception as e:
                    self.logger.error(f"Error calculating duration: {e}")
            
        except Exception as e:
            self.logger.error(f"Error playing TTS audio: {e}", exc_info=True)


class TTSAccount(VoIPAccount):
    """TTS account with dynamic LLM+TTS generation."""
    
    def __init__(self, ep, config=None, logger=None, **kwargs):
        super().__init__(ep, call_class=TTSCall, logger=logger, **kwargs)
        self.config = config or {}
        self.tts_queue = queue.Queue()
        self.current_tts_file = None
        
        self.logger.info("TTSAccount initialized with dynamic LLM+TTS")
    
    def onIncomingCall(self, prm):
        """Handle incoming call - answer immediately and generate dynamic response."""
        try:
            if not self.call_class:
                self.logger.warning("No call class set, ignoring incoming call")
                return
            
            # Create call instance
            call = self.call_class(
                self, 
                prm.callId, 
                **self.call_kwargs
            )
            self.current_call = call
            
            ci = call.getInfo()
            self.logger.info(f"Incoming call from {ci.remoteUri}")
            
            # Answer immediately
            self.logger.info("Answering call immediately...")
            answer_prm = pj.CallOpParam()
            answer_prm.statusCode = 200
            call.answer(answer_prm)
            self.logger.info("Call answered immediately")
            
            # Start TTS generation in background thread with PJSIP registration
            import threading
            thread = threading.Thread(
                target=self._generate_tts_background,
                args=(call,),
                daemon=True
            )
            thread.start()
            self.logger.info(f"TTS generation thread started: {thread.name}")
                
        except Exception as e:
            self.logger.error(f"Error handling incoming call: {e}", exc_info=True)
    
    def _generate_tts_background(self, call):
        """Generate TTS in background thread with PJSIP thread registration."""
        try:
            # Register thread with PJSIP BEFORE doing ANYTHING
            self.ep.libRegisterThread("tts_background_thread")
            
            self.logger.info("=" * 50)
            self.logger.info("ENTERING TTS GENERATION (BACKGROUND THREAD)")
            self.logger.info("=" * 50)
            
            # Import LLM adapter
            from Libs.llm_adapter import phoneguy_reply
            
            # Generate text using LLM
            self.logger.info("Generating text using LLM...")
            prompt = "Someone is calling you. Greet them warmly and introduce yourself. Ask them what they need from you in a polite manner."
            greeting_text = phoneguy_reply(prompt)
            self.logger.info(f"Generated text: '{greeting_text}'")
            
            # Generate TTS for this text
            self.logger.info("Generating TTS for dynamic text...")
            tts_file = f"tts_dynamic_{int(time.time())}.wav"
            
            if synthesize_tts_safe(self.config, greeting_text, tts_file):
                self.logger.info(f"Dynamic TTS ready: {tts_file}")
                call.set_tts_file(tts_file)
            else:
                self.logger.error("Failed to generate dynamic TTS")
                
        except Exception as e:
            self.logger.error(f"Error generating TTS in background thread: {e}", exc_info=True)


def synthesize_tts_safe(config, text: str, output_file: str) -> bool:
    """Generate TTS with safe RVC handling - NO THREADING."""
    try:
        logging.info("=" * 50)
        logging.info("GENERATING TTS (NO THREADING)")
        logging.info("=" * 50)
        
        tts = TTSAdapter(config, logging.getLogger("TTS"))
        
        # Check TTS health
        logging.info("Checking TTS health...")
        ok = tts.check_health_sync()
        if not ok:
            logging.error("TTS health check failed")
            return False
        
        logging.info(f"Generating TTS for: '{text}'")
        start_time = time.time()
        
        # Get model
        model = tts._get_model()
        
        # Generate TTS without RVC first
        if hasattr(model, 'language_id') and tts.language_id:
            wav = model.generate(text, language_id=tts.language_id, 
                               audio_prompt_path=tts.audio_prompt_path)
        else:
            wav = model.generate(text, audio_prompt_path=tts.audio_prompt_path)
        
        sr = getattr(model, 'sr', 16000)
        
        # Convert to numpy array safely
        if isinstance(wav, torch.Tensor):
            audio_data = wav.detach().cpu().numpy()
        else:
            audio_data = np.array(wav)
        
        # Ensure 1D array
        if audio_data.ndim > 1:
            audio_data = np.squeeze(audio_data)
        if audio_data.ndim != 1:
            audio_data = audio_data.reshape(-1)
        
        # Convert to float32
        audio_data = audio_data.astype(np.float32, copy=False)
        
        # Apply RVC if enabled - WITH SAFE HANDLING
        if tts.rvc_enabled and tts.rvc_model_path:
            logging.info(f"Applying RVC: {tts.rvc_model_path}")
            try:
                from rvc_py.rvc_infer import rvc_infer
                
                # Call RVC with proper error handling
                rvc_audio, rvc_sr = rvc_infer(
                    audio_data,
                    sr,
                    tts.rvc_model_path,
                    device=tts.device,
                    index_path=tts.rvc_index_path,
                    index_rate=tts.rvc_index_rate,
                    pitch_shift=tts.rvc_pitch_shift,
                    f0_method=tts.rvc_f0_method
                )
                
                # Validate RVC output
                if rvc_audio is None or len(rvc_audio) == 0:
                    logging.warning("RVC returned empty output, using original audio")
                else:
                    # Ensure RVC output is valid numpy array
                    if isinstance(rvc_audio, torch.Tensor):
                        rvc_audio = rvc_audio.detach().cpu().numpy()
                    if rvc_audio.ndim > 1:
                        rvc_audio = np.squeeze(rvc_audio)
                    if rvc_audio.ndim != 1:
                        rvc_audio = rvc_audio.reshape(-1)
                    rvc_audio = rvc_audio.astype(np.float32, copy=False)
                    
                    # Check for NaN or Inf
                    if np.isnan(rvc_audio).any() or np.isinf(rvc_audio).any():
                        logging.warning("RVC output contains NaN/Inf, using original audio")
                    else:
                        audio_data = rvc_audio
                        sr = rvc_sr
                        logging.info("RVC applied successfully")
            
            except Exception as e:
                logging.error(f"RVC processing error: {e}", exc_info=True)
                logging.warning("Using original audio without RVC")
        
        # Convert to torch tensor for resampling
        audio_tensor = torch.tensor(audio_data).float()
        
        # Ensure 1D tensor
        if audio_tensor.dim() == 2 and audio_tensor.size(0) > 1:
            audio_tensor = torch.mean(audio_tensor, dim=0, keepdim=True)
        elif audio_tensor.dim() == 1:
            audio_tensor = audio_tensor.unsqueeze(0)
        
        # Resample if needed
        if sr != tts.sample_rate:
            audio_tensor = torchaudio.functional.resample(audio_tensor, sr, tts.sample_rate)
        
        # Convert to int16 PCM
        audio_tensor = audio_tensor.squeeze(0)
        audio_tensor = torch.clamp(audio_tensor, -1.0, 1.0)
        
        # Check for NaN or Inf before conversion
        if torch.isnan(audio_tensor).any() or torch.isinf(audio_tensor).any():
            logging.warning("Waveform contains NaN/Inf, replacing with zeros")
            audio_tensor = torch.nan_to_num(audio_tensor, nan=0.0, posinf=1.0, neginf=-1.0)
        
        int16 = (audio_tensor.numpy() * 32767.0).astype(np.int16)
        pcm = int16.tobytes()
        
        if len(pcm) == 0:
            logging.error("Empty PCM data generated")
            return False
        
        # Save to WAV file
        with wave.open(output_file, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(pcm)
        
        generation_time = time.time() - start_time
        logging.info(f"TTS generated in {generation_time:.2f} seconds")
        logging.info(f"Saved TTS to {output_file} ({len(pcm)} bytes)")
        
        return True
        
    except Exception as e:
        logging.error(f"Error generating TTS: {e}", exc_info=True)
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        print(f"\nThis script tests:")
        print(f"  - TTS generation BEFORE call (no threading)")
        print(f"  - Safe RVC handling")
        print(f"  - No Segmentation fault")
        sys.exit(1)

    domain, user, passwd = sys.argv[1:4]
    
    # Create VoIP client
    config = {
        'sip': {
            'domain': domain,
            'username': user,
            'password': passwd,
            'local_addr': '192.168.1.181',
            'local_port': 5060
        },
        'server': {
            'answerDelay': 0.0,
            'silenceDuration': 2.0
        },
        'tts': {
            'engine': 'turbo',
            'device': 'cuda',
            'audio_prompt_path': '/home/user/Test_Phone/voices/PhoneGuy_FNAF1_01.wav',
            'rvc_enabled': True,
            'rvc_model_path': '/home/user/Test_Phone/models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth',
            'rvc_index_path': '/home/user/Test_Phone/models/RVC/PhoneGuyFNAF1/added_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index',
            'rvc_index_rate': 0.5,
            'rvc_f0_method': 'rmvpe'
        }
    }
    
    # Generate TTS BEFORE starting VoIP (NO THREADING!)
    tts_file = "tts_output.wav"
    greeting_text = "Hello! This is Phone Guy speaking. How can I help you today?"
    
    logging.info("Generating TTS BEFORE starting VoIP...")
    if not synthesize_tts_safe(config, greeting_text, tts_file):
        logging.error("Failed to generate TTS")
        sys.exit(1)
    
    logging.info(f"TTS ready: {tts_file}")
    
    # Now start VoIP
    bot = VoIPClient(config, logging.getLogger("VoIPClient"))
    
    if not bot.initialize():
        logging.error("Failed to initialize VoIP client")
        sys.exit(1)
    
    if not bot.start():
        logging.error("Failed to start VoIP client")
        sys.exit(1)

    logging.info("PJSUA2 started")

    # Create account
    if not bot.create_account(TTSAccount, config=config):
        logging.error("Failed to create account")
        sys.exit(1)

    # Make outgoing call if specified
    if len(sys.argv) > 4:
        target = sys.argv[4]
        call = bot.make_call(TTSCall, target)
        if call:
            calls.append(call)
            logging.info(f"Call initiated to {target}")

    logging.info("Ready. Waiting for calls...")
    logging.info("When call comes:")
    logging.info("  1. Will answer immediately")
    logging.info("  2. Will play pre-generated TTS audio")
    logging.info("  3. NO threading - NO Segmentation fault!")
    
    try:
        while True:
            bot.get_endpoint().libHandleEvents(10)
            
            # Process hangup queue for current call
            account = bot.get_account()
            if account:
                call = account.get_current_call()
                if call:
                    call.process_hangup_queue()
                    
    except KeyboardInterrupt:
        logging.info("\nShutting down...")
        try:
            for call in calls[:]:
                if call.isActive():
                    try:
                        call.hangup(pj.CallOpParam())
                        time.sleep(0.1)
                    except Exception as e:
                        logging.error(f"Error hanging up call: {e}")
            calls.clear()
            
            bot.destroy()
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")


if __name__ == "__main__":
    main()
