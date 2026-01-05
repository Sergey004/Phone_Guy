#!/usr/bin/env python3
"""
Test VoIP call with audio file playback
Uses new VoIP library for SIP functionality
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import logging
import pjsua2 as pj
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall
from Libs.wav_converter import ensure_pjsua_compatible

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)


class TestCall(VoIPCall):
    """Test call implementation with audio file playback."""
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, wav_file="output.wav", **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.wav_file = wav_file
    
    def _setup_audio_media(self, media_info):
        """Setup audio media with file playback."""
        try:
            audio_media = self.getAudioMedia(media_info.index)
            self.logger.info(f"Got audio media, port ID: {audio_media.getPortId()}")
            
            # Check if already set up
            if self.playback_port is not None:
                self.logger.info("Playback already set up")
                return
            
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
            
        except Exception as e:
            self.logger.error(f"Error setting up audio media: {e}", exc_info=True)


class TestAccount(VoIPAccount):
    """Test account implementation."""
    
    def __init__(self, ep, wav_file="output_phone.wav", **kwargs):
        super().__init__(ep, call_class=TestCall, **kwargs)
        self.wav_file = wav_file


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        sys.exit(1)
    
    domain, user, passwd = sys.argv[1:4]
    
    # Check audio file
    wav_file = "/home/user/Test_Phone/bot/Test_RTP/output_phone.wav"
    if not os.path.exists(wav_file):
        logging.error(f"ERROR: {wav_file} not found!")
        sys.exit(1)
    
    logging.info(f"Found {wav_file} ({os.path.getsize(wav_file)} bytes)")
    logging.info("Audio will be auto-converted to PJSUA2 format if needed")
    
    # Create VoIP client
    config = {
        'sip': {
            'domain': domain,
            'username': user,
            'password': passwd,
            'local_addr': '192.168.1.181',
            'local_port': 5060
        }
    }
    
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
    if not bot.create_account(TestAccount, wav_file=wav_file):
        logging.error("Failed to create account")
        sys.exit(1)
    
    # Make outgoing call if specified
    if len(sys.argv) > 4:
        target = sys.argv[4]
        call = bot.make_call(TestCall, target, wav_file=wav_file)
        if call:
            logging.info(f"Call initiated to {target}")
    
    logging.info("Ready. Waiting for calls...")
    
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
