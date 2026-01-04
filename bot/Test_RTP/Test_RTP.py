#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import logging
import pjsua2 as pj
import threading
import queue
from Libs.wav_converter import ensure_pjsua_compatible

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)


class MyAccount(pj.Account):
    def __init__(self, ep):
        super().__init__()
        self.ep = ep
        self.current_call = None

    def onRegState(self, prm):
        info = self.getInfo()
        logging.info(f"Account registration: {info.regIsActive} ({prm.code} {prm.reason})")

    def onIncomingCall(self, prm):
        call = MyCall(self, prm.callId, self.ep, wav_file="output_phone.wav")
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"Incoming call from {ci.remoteUri}")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        call.answer(prm)


class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, ep=None, wav_file="output.wav"):
        super().__init__(acc, call_id)
        self.playback_port = None
        self.capture_port = None
        self.recorder = None
        self.ep = ep
        self.wav_file = wav_file
        self.timer = None
        self.hangup_queue = queue.Queue()  # Queue for hangup commands

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}")
        if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")
            if self.recorder:
                try:
                    logging.info("Recording saved to captured_audio.wav")
                except Exception as e:
                    logging.error(f"Error with recording: {e}")
                self.recorder = None
            if self.playback_port:
                self.playback_port = None
            if self.capture_port:
                self.capture_port = None
            if self.timer:
                self.timer.cancel()
                self.timer = None

    def onCallMediaState(self, prm):
        logging.info("Entering onCallMediaState")
        ci = self.getInfo()
        
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                logging.info("Audio active, setting up media")
                
                # Check if already set up to prevent duplicate setup
                if self.playback_port is not None:
                    logging.info("Playback port already exists, skipping setup")
                    return
                
                try:
                    audio_media = self.getAudioMedia(mi.index)
                    logging.info(f"Got audio media, port ID: {audio_media.getPortId()}")
                    
                    # Convert WAV to PCM16/mono/8000Hz
                    compatible_file = ensure_pjsua_compatible(self.wav_file, target_rate=8000)
                    logging.info(f"Using audio file: {compatible_file}")
                    
                    # Use AudioMediaPlayer for playback (standard PJSIP approach)
                    self.playback_port = pj.AudioMediaPlayer()
                    try:
                        self.playback_port.createPlayer(compatible_file, 0)
                        logging.info("✓ AudioMediaPlayer created successfully")
                        
                        # Connect for playback (player -> audio_media)
                        self.playback_port.startTransmit(audio_media)
                        logging.info("✓ Playback transmission started")
                        
                        # Verify connection
                        logging.info(f"  Audio media port ID: {audio_media.getPortId()}")
                        logging.info(f"  Playback media port ID: {self.playback_port.getPortId()}")
                        
                        # Calculate audio file duration
                        import soundfile as sf
                        data, sr = sf.read(compatible_file)
                        duration_seconds = len(data) / sr
                        logging.info(f"  Audio duration: {duration_seconds:.2f} seconds")
                        
                        # Start timer to stop playback after file ends
                        self.timer = threading.Timer(duration_seconds + 0.5, self.check_playback_done)
                        self.timer.start()
                    except Exception as e:
                        logging.error(f"Failed to create AudioMediaPlayer: {e}")
                        self.playback_port = None
                    
                    # Create recorder for capturing audio
                    self.recorder = pj.AudioMediaRecorder()
                    self.recorder.createRecorder("captured_audio.wav")
                    audio_media.startTransmit(self.recorder)
                    logging.info("✓ Recording enabled")
                    
                except Exception as e:
                    logging.error(f"Error in onCallMediaState: {e}")
                    import traceback
                    traceback.print_exc()
                    try:
                        # Fallback to simple recorder
                        self.recorder = pj.AudioMediaRecorder()
                        self.recorder.createRecorder("captured_audio.wav")
                        audio_media.startTransmit(self.recorder)
                        logging.info("✓ Fallback recording enabled")
                    except Exception as fallback_e:
                        logging.error(f"Failed fallback recorder: {fallback_e}")

    def check_playback_done(self):
        try:
            # Stop playback and disconnect
            if self.playback_port:
                logging.info("Stopping playback...")
                self.playback_port.stopTransmit()
                self.playback_port = None
            
            # Queue hangup
            self.timer = None  # Don't reschedule
            logging.info("Playback timer expired, queuing hangup")
            self.hangup_queue.put(True)  # Signal hangup
        except Exception as e:
            logging.error(f"Error in check_playback_done: {e}")
            if self.timer:
                self.timer.cancel()
                self.timer = None


class VoIPBot:
    def __init__(self, sip_domain, sip_user, sip_pass, local_ip="192.168.1.181"):
        self.ep = pj.Endpoint()
        self.ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.uaConfig.threadCnt = 1
        ep_cfg.uaConfig.maxCalls = 4
        ep_cfg.logConfig.level = 3  # 0=None, 1=Error, 2=Warning, 3=Info, 4=Debug, 5=Trace
        ep_cfg.medConfig.sndClockRate = 8000
        ep_cfg.medConfig.channelCount = 1
        ep_cfg.medConfig.audioFramePtime = 20
        ep_cfg.medConfig.noVad = True
        self.ep.libInit(ep_cfg)
        
        self.ep.audDevManager().setNullDev()
        logging.info("Null sound device set (no hardware audio needed)")

        # Transport
        tcfg = pj.TransportConfig()
        tcfg.port = 5060
        tcfg.boundAddr = local_ip
        tcfg.publicAddr = local_ip
        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

        # Codec settings
        self.ep.codecSetPriority("*", 0)  # Disable all codecs
        self.ep.codecSetPriority("PCMA/8000/1", 255)  # Primary: PCMA
        self.ep.codecSetPriority("PCMU/8000/1", 254)  # Fallback: PCMU
        logging.info("Codecs set to PCMA/8000/1 (255), PCMU/8000/1 (254)")

        self.ep.libStart()
        logging.info("PJSUA2 started")

        # Account
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{sip_user}@{sip_domain}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_domain}"
        acc_cfg.sipConfig.authCreds.append(pj.AuthCredInfo("digest", "*", sip_user, 0, sip_pass))
        self.account = MyAccount(self.ep)
        self.account.create(acc_cfg)

    def make_call(self, uri):
        call = MyCall(self.account, ep=self.ep)
        prm = pj.CallOpParam(True)
        call.makeCall(uri, prm)
        self.account.current_call = call

    def destroy(self):
        logging.info("Cleaning up...")
        
        if self.account and self.account.current_call:
            try:
                call = self.account.current_call
                if call.isActive():
                    call.hangup(pj.CallOpParam())
                # Recording is automatically saved by AudioMediaRecorder
                if call.recorder:
                    logging.info("Recording saved to captured_audio.wav")
                self.account.current_call = None
            except Exception as e:
                logging.error(f"Error cleaning up call: {e}")

        try:
            if self.account:
                # Unregister account instead of delete
                self.account.setRegistration(False)
                time.sleep(0.5)  # Wait for unregistration
                self.account = None
        except Exception as e:
            logging.error(f"Error unregistering account: {e}")

        try:
            self.ep.libDestroy()
            logging.info("Destroyed")
        except Exception as e:
            logging.error(f"Error destroying endpoint: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        sys.exit(1)

    domain, user, passwd = sys.argv[1:4]
    
    import os
    wav_file = "/home/user/Test_Phone/bot/Test_RTP/output_phone.wav"
    if not os.path.exists(wav_file):
        logging.error(f"ERROR: {wav_file} not found!")
        sys.exit(1)
    
    logging.info(f"Found {wav_file} ({os.path.getsize(wav_file)} bytes)")
    logging.info("Audio will be auto-converted to PJSUA2 format if needed")
    
    bot = VoIPBot(domain, user, passwd)

    if len(sys.argv) > 4:
        target = sys.argv[4]
        bot.make_call(target)

    logging.info("Ready. Waiting for calls...")
    
    try:
        while True:
            time.sleep(0.1)  # Reduced sleep for faster queue processing
            # Process hangup queue for current call
            if bot.account and bot.account.current_call:
                call = bot.account.current_call
                try:
                    if not call.hangup_queue.empty():
                        call.hangup_queue.get_nowait()  # Consume signal
                        if call.isActive():
                            logging.info("Processing queued hangup")
                            prm = pj.CallOpParam()
                            prm.statusCode = pj.PJSIP_SC_OK
                            call.hangup(prm)
                except Exception as e:
                    logging.error(f"Error processing hangup queue: {e}")
    except KeyboardInterrupt:
        logging.info("\nShutting down...")
        bot.destroy()
