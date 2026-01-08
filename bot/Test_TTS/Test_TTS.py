#!/usr/bin/env python3
"""
Test VoIP call with TTS
Uses threading for TTS generation (no asyncio) - similar to Test_Delay_Silence.py
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import logging
import threading
import pjsua2 as pj
from Libs.tts_adapter import TTSAdapter
from Libs.llm_adapter import phoneguy_reply, reset_conversation_history
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall
from Libs.wav_converter import ensure_pjsua_compatible
import wave


logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)
logging.getLogger('numba').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
calls = []  # Global list to keep strong references to call objects


class TTSCall(VoIPCall):
    """TTS call implementation with voice generation using threading."""
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, 
                 tts_adapter=None, silence_duration=2.0, **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.tts_adapter = tts_adapter
        self.silence_duration = silence_duration
        self.media_ready = threading.Event()  # threading.Event, not asyncio.Event!
        self.tts_wav_file = None  # Store path to generated WAV file
        self.greeting_text = None  # Store greeting text
        self.logger.info(f"TTSCall initialized with silence_duration={silence_duration}s")

    def onCallState(self, prm):
        """Handle call state changes."""
        try:
            ci = self.getInfo()
            self.logger.info(f"Call state: {ci.stateText}")
            
            if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
                self.logger.info("Call CONFIRMED! Waiting for TTS...")
                # Wait for TTS to be ready
                if self.media_ready.wait(timeout=30):
                    self.logger.info("TTS is ready! Playing audio...")
                    self._play_tts_audio()
                else:
                    self.logger.warning("Timeout waiting for TTS")
                    
            elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.logger.info("Call disconnected")
                self.media_ready.clear()
            
            # Call parent handler
            super().onCallState(prm)
            
        except Exception as e:
            self.logger.error(f"Error in onCallState: {e}", exc_info=True)
    
    def _play_tts_audio(self):
        """Play the generated TTS audio file."""
        try:
            if not self.tts_wav_file:
                self.logger.error("No TTS WAV file available")
                return
            
            # Get audio media (try first active media)
            try:
                audio_media = self.getAudioMedia(0)
            except Exception:
                # Fallback: try to get any media
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
            compatible_file = ensure_pjsua_compatible(self.tts_wav_file, target_rate=8000)
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
    """TTS account implementation using threading (no asyncio)."""
    
    def __init__(self, ep, tts_adapter, config=None, logger=None, **kwargs):
        # Pass tts_adapter and silence_duration to call class
        kwargs['tts_adapter'] = tts_adapter
        server_cfg = (config or {}).get('server', {})
        kwargs['silence_duration'] = server_cfg.get('silenceDuration', 2.0)
        
        super().__init__(ep, call_class=TTSCall, logger=logger, **kwargs)
        self.tts_adapter = tts_adapter
        self.config = config or {}
        
        # Get settings from config
        self.answer_delay = server_cfg.get('answerDelay', 2.0)
        self.silence_duration = server_cfg.get('silenceDuration', 2.0)
        
        self.logger.info(f"TTSAccount: answer_delay={self.answer_delay}s, silence_duration={self.silence_duration}s")
    
    def onIncomingCall(self, prm):
        """
        Called when incoming call is received.
        Answers immediately and starts TTS generation in background thread.
        """
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
            
            # Answer the call immediately
            self.logger.info("Answering call immediately...")
            answer_prm = pj.CallOpParam()
            answer_prm.statusCode = 200
            call.answer(answer_prm)
            self.logger.info("Call answered immediately")
            
            # Start TTS generation in background thread
            self.logger.info("Starting TTS generation in background thread...")
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
        """Generate TTS in background thread (synchronous, no asyncio)."""
        try:
            self.logger.info("=" * 50)
            self.logger.info("ENTERING TTS generation (background thread)")
            self.logger.info("=" * 50)
            
            # Check TTS readiness (synchronous)
            self.logger.info("Checking TTS health...")
            tts_ready = self.tts_adapter.check_health_sync()
            self.logger.info(f"TTS health check result: {tts_ready}")
            
            if not tts_ready:
                self.logger.warning("TTS server unavailable")
                return

            # Use static greeting text (no LLM generation)
            self.logger.info("Using static greeting text...")
            greeting_text = "Hello! This is Phone Guy speaking. How can I help you today?"
            self.logger.info(f"Greeting text: '{greeting_text}'")

            # Generate TTS audio (synchronous)
            self.logger.info("Generating TTS voice...")
            import time
            start_time = time.time()
            
            # Use synchronous synthesize method
            pcm_data = self.tts_adapter.synthesize_sync(greeting_text)
            
            generation_time = time.time() - start_time
            self.logger.info(f"TTS generated in {generation_time:.2f} seconds")
            
            if not pcm_data:
                self.logger.error("Failed to generate TTS audio")
                return
            
            self.logger.info(f"TTS ready: {len(pcm_data)} bytes")
            
            # Save PCM to temporary WAV file
            temp_wav = "temp_tts_playback.wav"
            with wave.open(temp_wav, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(pcm_data)
            
            self.logger.info(f"Saved TTS to {temp_wav}")
            
            # Store WAV file path and set event
            call.tts_wav_file = temp_wav
            call.greeting_text = greeting_text
            call.media_ready.set()
            self.logger.info("TTS generation completed! Media ready event set.")
            
        except Exception as e:
            self.logger.error(f"Error generating TTS: {e}", exc_info=True)


def main():
    """Main entry point."""
    if "--tts-only" in sys.argv:
        # Test TTS only (synchronous, no threading)
        config = {
            "tts": {
                "engine": "turbo",
                "device": "cuda",
                "audio_prompt_path": "voices/PhoneGuy_FNAF1_01.wav",
                "rvc_enabled": True,
                "rvc_model_path": "models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth",
                "rvc_index_path": "models/RVC/PhoneGuyFNAF1/added_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index",
                "rvc_index_rate": 0.5,
                "rvc_f0_method": "rmvpe"
            }
        }
        tts = TTSAdapter(config, logging.getLogger("TTS"))
        ok = tts.check_health_sync()
        if not ok:
            logging.error("TTS health check failed")
            return
        text = "Hello, this is a test of the voice."
        pcm = tts.synthesize_sync(text)
        if not pcm:
            logging.error("No PCM data generated")
            return
        with wave.open("output.wav", "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(pcm)
        logging.info("Wrote output.wav")
        sys.exit(0)
    
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain] [--tts-only]")
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
            'answerDelay': 0.0,      # Answer immediately
            'silenceDuration': 2.0   # 2 seconds of silence
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
    
    bot = VoIPClient(config, logging.getLogger("VoIPClient"))
    
    if not bot.initialize():
        logging.error("Failed to initialize VoIP client")
        sys.exit(1)
    
    if not bot.start():
        logging.error("Failed to start VoIP client")
        sys.exit(1)

    logging.info("PJSUA2 started")

    # Initialize TTS
    tts_adapter = TTSAdapter(config, logging.getLogger("TTS"))
    ready = tts_adapter.check_health_sync()
    if not ready:
        logging.warning("TTS engine not ready; audio responses may be skipped.")

    # Create account
    if not bot.create_account(TTSAccount, tts_adapter=tts_adapter, config=config):
        logging.error("Failed to create account")
        sys.exit(1)

    # Make outgoing call if specified
    if len(sys.argv) > 4:
        target = sys.argv[4]
        call = bot.make_call(TTSCall, target, tts_adapter=tts_adapter)
        if call:
            calls.append(call)
            logging.info(f"Call initiated to {target}")

    logging.info("Ready. Waiting for calls (LLM+TTS test on incoming)...")
    logging.info("When call comes:")
    logging.info("  1. Will answer immediately")
    logging.info("  2. Will generate TTS in background thread")
    logging.info("  3. Will play TTS when ready")
    
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
            # Hang up all calls
            for call in calls[:]:
                if call.isActive():
                    try:
                        call.hangup(pj.CallOpParam())
                        time.sleep(0.1)
                    except Exception as e:
                        logging.error(f"Error hanging up call: {e}")
            calls.clear()
            
            bot.destroy()
            reset_conversation_history()
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")


if __name__ == "__main__":
   main()
