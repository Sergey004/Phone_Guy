#!/usr/bin/env python3
"""
Test VoIP call with TTS using native PcmMedia
Direct PCM playback without WAV file - using native C++ module
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../../native'))
import time
import logging
import threading
import pjsua2 as pj
from Libs.tts_adapter import TTSAdapter
from Libs.llm_adapter import phoneguy_reply, reset_conversation_history
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall
import pcm_media


logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)
logging.getLogger('numba').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
calls = []  # Global list to keep strong references to call objects


class TTSCall(VoIPCall):
    """TTS call implementation using native PcmMedia for direct PCM playback."""
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, 
                 tts_adapter=None, silence_duration=2.0, **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.tts_adapter = tts_adapter
        self.silence_duration = silence_duration
        self.media_ready = threading.Event()
        self.pcm_data = None  # Store PCM data directly
        self.pcm_media = None  # Native PcmMedia instance
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
                    self._play_tts_pcm()
                else:
                    self.logger.warning("Timeout waiting for TTS")
                    
            elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.logger.info("Call disconnected")
                self._cleanup_pcm_media()
                self.media_ready.clear()
            
            # Call parent handler
            super().onCallState(prm)
            
        except Exception as e:
            self.logger.error(f"Error in onCallState: {e}", exc_info=True)
    
    def _play_tts_pcm(self):
        """Play TTS PCM data directly using native PcmMedia."""
        try:
            if not self.pcm_data:
                self.logger.error("No PCM data available")
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
            
            # Create native PcmMedia instance
            self.logger.info("Creating native PcmMedia...")
            self.pcm_media = pcm_media.PcmMedia(
                clockRate=8000,
                channelCount=1,
                samplesPerFrame=160
            )
            self.pcm_media.initialize()
            self.pcm_media.start()
            
            # Connect PcmMedia to audio_media
            self.pcm_media.startTransmit(audio_media)
            self.logger.info("PcmMedia connected to call")
            
            # Push PCM data
            self.logger.info(f"Pushing {len(self.pcm_data)} bytes of PCM data...")
            self.pcm_media.push(self.pcm_data)
            self.logger.info("PCM data pushed successfully")
            
            # Calculate duration and schedule hangup
            duration_seconds = len(self.pcm_data) / (8000 * 2)  # 8000 Hz, 16-bit (2 bytes)
            self.logger.info(f"Audio duration: {duration_seconds:.2f} seconds")
            self.schedule_hangup(duration_seconds + 0.5)
            
        except Exception as e:
            self.logger.error(f"Error playing TTS PCM: {e}", exc_info=True)
    
    def _cleanup_pcm_media(self):
        """Cleanup native PcmMedia resources."""
        try:
            if self.pcm_media:
                self.logger.info("Cleaning up PcmMedia...")
                self.pcm_media.stop()
                self.pcm_media = None
        except Exception as e:
            self.logger.error(f"Error cleaning up PcmMedia: {e}")


class TTSAccount(VoIPAccount):
    """TTS account implementation using native PcmMedia."""
    
    def __init__(self, ep, tts_adapter, config=None, logger=None, **kwargs):
        kwargs['tts_adapter'] = tts_adapter
        server_cfg = (config or {}).get('server', {})
        kwargs['silence_duration'] = server_cfg.get('silenceDuration', 2.0)
        
        super().__init__(ep, call_class=TTSCall, logger=logger, **kwargs)
        self.tts_adapter = tts_adapter
        self.config = config or {}
        
        self.answer_delay = server_cfg.get('answerDelay', 2.0)
        self.silence_duration = server_cfg.get('silenceDuration', 2.0)
        
        self.logger.info(f"TTSAccount: answer_delay={self.answer_delay}s, silence_duration={self.silence_duration}s")
    
    def onIncomingCall(self, prm):
        """Handle incoming call - answer immediately and start TTS generation."""
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
        """Generate TTS in background thread and store PCM data directly."""
        try:
            self.logger.info("=" * 50)
            self.logger.info("ENTERING TTS generation (background thread)")
            self.logger.info("=" * 50)
            
            # Check TTS readiness
            self.logger.info("Checking TTS health...")
            tts_ready = self.tts_adapter.check_health_sync()
            self.logger.info(f"TTS health check result: {tts_ready}")
            
            if not tts_ready:
                self.logger.warning("TTS server unavailable")
                return

            # Use static greeting text (no LLM for now)
            self.logger.info("Using static greeting text...")
            greeting_text = "Hello! This is Phone Guy speaking. How can I help you today?"
            self.logger.info(f"Greeting text: '{greeting_text}'")

            # Generate TTS audio
            self.logger.info("Generating TTS voice...")
            start_time = time.time()
            
            # Use synchronous synthesize method
            pcm_data = self.tts_adapter.synthesize_sync(greeting_text)
            
            generation_time = time.time() - start_time
            self.logger.info(f"TTS generated in {generation_time:.2f} seconds")
            
            if not pcm_data:
                self.logger.error("Failed to generate TTS audio")
                return
            
            self.logger.info(f"TTS ready: {len(pcm_data)} bytes")
            
            # Store PCM data directly (no WAV file!)
            call.pcm_data = pcm_data
            call.media_ready.set()
            self.logger.info("TTS generation completed! Media ready event set.")
            
        except Exception as e:
            self.logger.error(f"Error generating TTS: {e}", exc_info=True)


def main():
    """Main entry point."""
    if "--tts-only" in sys.argv:
        # Test TTS only
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
        logging.info(f"Generated {len(pcm)} bytes of PCM data")
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
    logging.info("  3. Will play TTS via native PcmMedia (no WAV file)")
    
    try:
        while True:
            time.sleep(0.1)
            
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
            reset_conversation_history()
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")


if __name__ == "__main__":
    main()