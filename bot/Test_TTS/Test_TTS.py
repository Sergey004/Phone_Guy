#!/usr/bin/env python3
"""
Test VoIP call with TTS
Uses new VoIP library for SIP functionality
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import asyncio
import logging
import pjsua2 as pj
from Libs.tts_adapter import TTSAdapter
from Libs.llm_adapter import phoneguy_reply, reset_conversation_history
from Libs.audio import AudioPlaybackPort
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall
import wave

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)

calls = []  # Global list to keep strong references to call objects


class TTSCall(VoIPCall):
    """TTS call implementation with voice generation."""
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, 
                 tts_adapter=None, loop=None, **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.tts_adapter = tts_adapter
        self.loop = loop
        self.media_ready = asyncio.Event()

    def onCallState(self, prm):
        """Handle call state changes."""
        try:
            ci = self.getInfo()
            self.logger.info(f"Call state: {ci.stateText}")
            
            if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
                self.logger.info("Call CONFIRMED! Setting up media...")
                self.media_ready.set()
                self.logger.info("Media ready event set")
            elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.logger.info("Call disconnected")
                self.media_ready.clear()
            
            # Call parent handler
            super().onCallState(prm)
            
        except Exception as e:
            self.logger.error(f"Error in onCallState: {e}")

    def onCallMediaState(self, prm):
        """Handle media state changes."""
        try:
            self.logger.info("ENTERING onCallMediaState")
            ci = self.getInfo()
            self.logger.info(f"Media state info: media count={len(ci.media)}")
            
            if not ci.media:
                self.logger.warning("No media found in call info")
                return
            
            for i, mi in enumerate(ci.media):
                self.logger.info(f"Media {i}: type={mi.type}, status={mi.status}")
                
                if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    self.logger.info("Audio media is ACTIVE - signaling media ready!")
                    self.media_ready.set()
                    break
            
            self.logger.info("EXITING onCallMediaState")
            
        except Exception as e:
            self.logger.error(f"Error in onCallMediaState: {e}")


class TTSAccount(VoIPAccount):
    """TTS account implementation."""
    
    def __init__(self, ep, tts_adapter, loop, logger=None, **kwargs):
        super().__init__(ep, call_class=TTSCall, logger=logger, **kwargs)
        self.tts_adapter = tts_adapter
        self.loop = loop
        self.pre_generated_samples = {}

    def onIncomingCall(self, prm):
        """Handle incoming call."""
        try:
            call = TTSCall(self, prm.callId, tts_adapter=self.tts_adapter, loop=self.loop)
            calls.append(call)
            self.current_call = call
            
            ci = call.getInfo()
            self.logger.info(f"INCOMING CALL from {ci.remoteUri}")
            
            # Answer immediately
            self.logger.info("Answering call...")
            answer_prm = pj.CallOpParam()
            answer_prm.statusCode = 200
            call.answer(answer_prm)
            self.logger.info("Call answered")
            
            # Start voice generation
            self.loop.create_task(self.handle_call_after_answer(call))
            
        except Exception as e:
            self.logger.error(f"Error handling incoming call: {e}")

    async def handle_call_after_answer(self, call):
        """Handle call after answer."""
        try:
            # Check TTS readiness
            tts_ready = await self.tts_adapter.check_health()
            if not tts_ready:
                self.logger.warning("TTS server unavailable, using pre-generated samples")
                await self.use_pre_generated_voice(call)
                return

            # Generate greeting text
            self.logger.info("Generating greeting text...")
            greeting_prompt = "A person is calling you. Please greet them warmly and introduce yourself as an AI assistant. Ask how you can help them today."
            greeting_text = phoneguy_reply(greeting_prompt)
            self.logger.info(f"Generated text: '{greeting_text}'")

            # Create media port for TTS
            media_port = AudioPlaybackPort(sample_rate=8000, logger=self.logger.getChild("AudioPlayback"))
            if not media_port.register_with_conf(self.getAccount().ep):
                self.logger.error("Failed to create media port")
                await self.use_pre_generated_voice(call)
                return

            self.logger.info(f"Media port created: ID={media_port.conf_port_id}")

            # Generate and play voice
            self.logger.info("Generating voice...")
            try:
                await self.tts_adapter.speak(greeting_text, media_port)
                self.logger.info("Voice generated and playing")
                self.logger.info("Waiting for media stream...")
                try:
                    await asyncio.wait_for(call.media_ready.wait(), timeout=10)
                    self.logger.info("Media stream ready!")
                except asyncio.TimeoutError:
                    self.logger.error("Timeout waiting for media stream")
                    return
            except Exception as e:
                self.logger.error(f"Error generating voice: {e}")
                await self.use_pre_generated_voice(call)
                return

            # Connect media port to audio stream
            try:
                try:
                    audio_media = call.getAudioMedia(0)
                except Exception:
                    audio_media = call.getMedia(0)
                media_port.startTransmit(audio_media)
                self.logger.info("Media port connected to audio stream")
            except Exception as e:
                self.logger.error(f"Error connecting media port: {e}")
                # Fallback
                try:
                    pcm = await self.tts_adapter.synthesize(greeting_text)
                    if pcm:
                        temp_wav = "temp_tts_fallback.wav"
                        with wave.open(temp_wav, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(8000)
                            wf.writeframes(pcm)
                        player = pj.AudioMediaPlayer()
                        player.createPlayer(temp_wav, 0)
                        player.startTransmit(audio_media)
                        self.logger.info("Fallback AudioMediaPlayer started")
                except Exception as pe:
                    self.logger.error(f"Fallback playback failed: {pe}")
                    await self.use_pre_generated_voice(call)
                return
            
            # Wait for playback to finish
            greeting_duration = len(greeting_text.split()) * 0.5 + 2
            self.logger.info(f"Waiting {greeting_duration:.1f} seconds for greeting...")
            await asyncio.sleep(greeting_duration)

            # Hang up after greeting
            if call.isActive():
                self.logger.info("Hanging up after greeting...")
                prm = pj.CallOpParam()
                prm.statusCode = pj.PJSIP_SC_OK
                call.hangup(prm)
                self.logger.info("Call completed")
                
        except Exception as e:
            self.logger.error(f"Error handling call: {e}")
            if call.isActive():
                prm = pj.CallOpParam()
                prm.statusCode = pj.PJSIP_SC_INTERNAL_SERVER_ERROR
                call.hangup(prm)

    async def use_pre_generated_voice(self, call):
        """Use pre-generated voice as fallback."""
        try:
            self.logger.info("Using pre-generated voice...")
            
            if not self.pre_generated_samples:
                self.logger.error("No pre-generated samples available!")
                return
            
            # Select best sample
            best_sample = None
            if 'main_greeting' in self.pre_generated_samples:
                best_sample = self.pre_generated_samples['main_greeting']
                self.logger.info("Using main pre-generated greeting")
            else:
                best_sample = max(self.pre_generated_samples.values(), key=lambda x: x.get('length', 0))
                self.logger.info(f"Using pre-generated sample: {best_sample.get('length', 0)} bytes")
            
            if not best_sample or not best_sample.get('pcm_data'):
                self.logger.error("Selected sample is empty or corrupted")
                return
            
            # Create media port
            media_port = AudioPlaybackPort(sample_rate=8000, logger=self.logger.getChild("AudioPlayback"))
            if not media_port.register_with_conf(self.getAccount().ep):
                self.logger.error("Failed to create media port for pre-generated voice")
                return
            
            # Load PCM data
            media_port.update_playback_data(best_sample['pcm_data'])
            self.logger.info(f"PCM data loaded: {len(best_sample['pcm_data'])} bytes")
            
            # Connect to audio stream
            try:
                audio_media = call.getAudioMedia(-1)
                media_port.startTransmit(audio_media)
                self.logger.info("Media port connected to audio stream")
                
                # Wait for playback
                greeting_duration = len(best_sample['text'].split()) * 0.5 + 2
                self.logger.info(f"Waiting {greeting_duration:.1f} seconds for greeting...")
                await asyncio.sleep(greeting_duration)
                
            except Exception as e:
                self.logger.error(f"Error connecting media port: {e}")
                return
                
        except Exception as e:
            self.logger.error(f"Error using pre-generated voice: {e}")


def main():
    """Main entry point."""
    if "--tts-only" in sys.argv:
        async def tts_only():
            config = {
                "tts": {
                    "engine": "turbo",
                    "device": "cpu",
                    "audio_prompt_path": "voices/PhoneGuy_FNAF1_01.wav",
                    "rvc_enabled": True,
                    "rvc_model_path": "models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth",
                    "rvc_index_path": "models/RVC/PhoneGuyFNAF1/added_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index",
                    "rvc_index_rate": 0.5,
                    "rvc_f0_method": "rmvpe"
                }
            }
            tts = TTSAdapter(config, logging.getLogger("TTS"))
            ok = await tts.check_health()
            if not ok:
                logging.error("TTS health check failed")
                return
            text = "Hello, this is a test of the voice."
            pcm = await tts.synthesize(text)
            if not pcm:
                logging.error("No PCM data generated")
                return
            with wave.open("output.wav", "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(pcm)
            logging.info("Wrote output.wav")
        asyncio.run(tts_only())
        sys.exit(0)
    
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain] [--tts-only]")
        sys.exit(1)

    domain, user, passwd = sys.argv[1:4]
    
    # Create asyncio event loop
    loop = asyncio.get_event_loop()
    
    # Create VoIP client
    config = {
        'sip': {
            'domain': domain,
            'username': user,
            'password': passwd,
            'local_addr': '192.168.1.181',
            'local_port': 5060
        },
        'tts': {
            'engine': 'turbo',
            'device': 'cpu',
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
    if not loop.run_until_complete(tts_adapter.check_health()):
        logging.error("TTS server unavailable. Calls may proceed without audio.")

    # Create account
    if not bot.create_account(TTSAccount, tts_adapter=tts_adapter, loop=loop):
        logging.error("Failed to create account")
        sys.exit(1)

    # Make outgoing call if specified
    if len(sys.argv) > 4:
        target = sys.argv[4]
        call = bot.make_call(TTSCall, target, tts_adapter=tts_adapter, loop=loop)
        if call:
            calls.append(call)
            logging.info(f"Call initiated to {target}")

    logging.info("Ready. Waiting for calls (LLM+TTS test on incoming)...")
    
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("\nShutting down...")
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            
            # Hang up all calls
            for call in calls[:]:
                if call.isActive():
                    try:
                        call.hangup(pj.CallOpParam())
                        time.sleep(0.1)
                    except Exception as e:
                        logging.error(f"Error hanging up call: {e}")
            calls.clear()
            
            # Cleanup account
            account = bot.get_account()
            if account and hasattr(account, 'pre_generated_samples'):
                logging.info(f"Cleaning up {len(account.pre_generated_samples)} pre-generated samples")
                account.pre_generated_samples.clear()
            
            bot.destroy()
            reset_conversation_history()
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")


if __name__ == "__main__":
    main()
