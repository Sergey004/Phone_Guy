#!/usr/bin/env python3
"""
Test VoIP call with answer delay and silence initialization
Tests the new delay and silence features for TTS preparation
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import logging
import pjsua2 as pj
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall
from Libs.audio import AudioPlaybackPort
from Libs.wav_converter import ensure_pjsua_compatible

logging.basicConfig(
    level="DEBUG",
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)


class TestAccount(VoIPAccount):
    """Test account with delay and silence support."""
    
    def __init__(self, ep, wav_file="output.wav", config=None, **kwargs):
        super().__init__(ep, call_class=TestCall, logger=logging.getLogger("TestAccount"), **kwargs)
        self.wav_file = wav_file
        self.config = config or {}
        
        # Get settings from config
        server_cfg = self.config.get('server', {})
        self.answer_delay = server_cfg.get('answerDelay', 5.0)
        self.silence_duration = server_cfg.get('silenceDuration', 2.0)
        
        self.logger.info(f"TestAccount: answer_delay={self.answer_delay}s, silence_duration={self.silence_duration}s")
    
    def onIncomingCall(self, prm):
        """
        Called when incoming call is received.
        Implements delay to simulate human answering.
        """
        try:
            if not self.call_class:
                self.logger.warning("No call class set, ignoring incoming call")
                return
            
            # Create call instance with silence duration
            call = self.call_class(
                self, 
                prm.callId, 
                wav_file=self.wav_file,
                silence_duration=self.silence_duration,
                **self.call_kwargs
            )
            self.current_call = call
            
            ci = call.getInfo()
            self.logger.info(f"Incoming call from {ci.remoteUri}")
            
            # Call custom handler if set
            if self.incoming_call_handler:
                self.incoming_call_handler(call, prm)
            else:
                # Answer with delay to simulate human
                if self.answer_delay > 0:
                    # Schedule delayed answer
                    import threading
                    def delayed_answer():
                        import time
                        time.sleep(self.answer_delay)
                        try:
                            # Register thread with PJSIP before calling its functions
                            self.ep.libRegisterThread("delayed_answer_thread")
                            
                            answer_prm = pj.CallOpParam()
                            answer_prm.statusCode = 200
                            call.answer(answer_prm)
                            self.logger.info("Call answered after delay")
                        except Exception as e:
                            self.logger.error(f"Error answering call after delay: {e}")
                    
                    thread = threading.Thread(target=delayed_answer, daemon=True)
                    thread.start()
                    self.logger.info(f"Scheduled answer in {self.answer_delay} seconds")
                else:
                    # Answer immediately
                    self._answer_call(call, prm)
                
        except Exception as e:
            self.logger.error(f"Error handling incoming call: {e}", exc_info=True)


class TestCall(VoIPCall):
    """Test call with audio playback."""
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, 
                 wav_file="output.wav", silence_duration=2.0, **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.wav_file = wav_file
        self.silence_duration = silence_duration
        self.logger.info(f"TestCall initialized")
    
    def onCallState(self, prm):
        """Handle call state changes."""
        try:
            ci = self.getInfo()
            self.logger.info(f"Call state: {ci.stateText}, last code: {ci.lastStatusCode}")
            
            if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
                self.logger.info("Call is confirmed. Playing audio file...")
                self._play_audio_file()
                    
            elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.logger.info("Call disconnected")
            
            # Call parent handler
            super().onCallState(prm)
            
        except Exception as e:
            self.logger.error(f"Error in onCallState: {e}", exc_info=True)
    
    def _play_audio_file(self):
        """Play the audio file."""
        try:
            # Get audio media
            ci = self.getInfo()
            if not ci.media:
                self.logger.error("No media found")
                return
            
            for mi in ci.media:
                if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    audio_media = self.getAudioMedia(mi.index)
                    
                    # Convert WAV to PCM16/mono/8000Hz
                    compatible_file = ensure_pjsua_compatible(self.wav_file, target_rate=8000)
                    self.logger.info(f"Using audio file: {compatible_file}")
                    
                    # Play audio file
                    if self.play_audio_file(compatible_file, audio_media):
                        # Calculate audio duration
                        import soundfile as sf
                        data, sr = sf.read(compatible_file)
                        duration_seconds = len(data) / sr
                        self.logger.info(f"Audio duration: {duration_seconds:.2f} seconds")
                        
                        # Schedule hangup after playback
                        self.schedule_hangup(duration_seconds + 0.5)
                    break
            
        except Exception as e:
            self.logger.error(f"Error playing audio file: {e}", exc_info=True)


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        print(f"\nThis script tests:")
        print(f"  - Answer delay (configurable in config.json)")
        print(f"  - Silence initialization before playback")
        print(f"  - Smooth transition from silence to audio")
        sys.exit(1)
    
    domain, user, passwd = sys.argv[1:4]
    
    # Check audio file
    wav_file = "/home/user/Test_Phone/bot/Test_RTP/output_phone.wav"
    if not os.path.exists(wav_file):
        logging.error(f"ERROR: {wav_file} not found!")
        sys.exit(1)
    
    logging.info(f"Found {wav_file} ({os.path.getsize(wav_file)} bytes)")
    
    # Load config for delay and silence settings
    config = {
        'sip': {
            'domain': domain,
            'username': user,
            'password': passwd,
            'local_addr': '192.168.1.181',
            'local_port': 5060
        },
        'server': {
            'answerDelay': 20.0,      # 2 seconds delay before answering
            'silenceDuration': 2.0   # 2 seconds of silence
        }
    }
    
    logging.info(f"Config: answerDelay={config['server']['answerDelay']}s, silenceDuration={config['server']['silenceDuration']}s")
    
    # Create VoIP client
    bot = VoIPClient(config, logging.getLogger("VoIPClient"))
    
    # Initialize and start
    if not bot.initialize():
        logging.error("Failed to initialize VoIP client")
        sys.exit(1)
    
    if not bot.start():
        logging.error("Failed to start VoIP client")
        sys.exit(1)
    
    logging.info("PJSUA2 started")
    
    # Create account
    if not bot.create_account(TestAccount, wav_file=wav_file, config=config):
        logging.error("Failed to create account")
        sys.exit(1)
    
    # Make outgoing call if specified
    if len(sys.argv) > 4:
        target = sys.argv[4]
        call = bot.make_call(TestCall, target, wav_file=wav_file)
        if call:
            logging.info(f"Call initiated to {target}")
    
    logging.info("Ready. Waiting for calls...")
    logging.info("When call comes:")
    logging.info("  1. Will wait for answerDelay seconds before answering (simulates human)")
    logging.info("  2. Will play the audio file immediately after answering")
    
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
        bot.destroy()


if __name__ == "__main__":
    main()
