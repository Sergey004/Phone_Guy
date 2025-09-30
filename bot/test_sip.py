#!/usr/bin/env python3
import sys
import time
import logging
import pjsua2 as pj
from rtp_streamer import RtpStreamerMediaPort
from wav_converter import ensure_pjsua_compatible

logging.basicConfig(
    level=logging.INFO,
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
        call = MyCall(self, prm.callId, self.ep, wav_file="output.wav")
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"Incoming call from {ci.remoteUri}")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        call.answer(prm)


class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, ep=None, wav_file="output.wav"):
        super().__init__(acc, call_id)
        self.rtp_port = None
        self.ep = ep
        self.recorder = None  # Fallback recorder, if needed
        self.wav_file = wav_file

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}")
        if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")
            # Save recording on disconnect
            if self.rtp_port:
                self.rtp_port.save_to_wav("captured_audio.wav")

    def onCallMediaState(self, prm):
        logging.info("Entering onCallMediaState")
        ci = self.getInfo()
        
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                logging.info("Audio active, setting up media")
                
                try:
                    # Get call's audio media (port ID should be 1)
                    audio_media = self.getAudioMedia(mi.index)
                    logging.info(f"Got audio media, port ID: {audio_media.getPortId()}")
                    
                    # Convert WAV to PJSUA2-compatible format (PCM16, mono, 8000Hz)
                    compatible_file = ensure_pjsua_compatible(self.wav_file, target_rate=8000)
                    logging.info(f"Using audio file: {compatible_file}")
                    
                    # Use custom port for both playback and recording
                    self.rtp_port = RtpStreamerMediaPort(compatible_file)
                    logging.info("RTP port created")
                    
                    # KEY FIX: Register the custom port to the conference bridge
                    self.rtp_port.createPort("rtp_streamer")
                    logging.info(f"Custom port registered with ID: {self.rtp_port.getPortId()}")
                    
                    # Connect bidirectional:
                    # - Custom port transmits to call (playback)
                    self.rtp_port.startTransmit(audio_media)
                    logging.info("✓ Playback enabled via RTP port")
                    
                    # - Call transmits to custom port (recording)
                    audio_media.startTransmit(self.rtp_port)
                    logging.info("✓ Recording enabled via RTP port")                    
                except Exception as e:
                    logging.error(f"Error in onCallMediaState: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Fallback: Use built-in recorder if custom fails
                    try:
                        self.recorder = pj.AudioMediaRecorder()
                        self.recorder.createRecorder("captured_audio.wav")
                        audio_media.startTransmit(self.recorder)
                        logging.info("✓ Fallback recording enabled via AudioMediaRecorder")
                    except Exception as fallback_e:
                        logging.error(f"Failed fallback recorder: {fallback_e}")


class VoIPBot:
    def __init__(self, sip_domain, sip_user, sip_pass, local_ip="192,168.1.181"):
        self.ep = pj.Endpoint()
        self.ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.uaConfig.threadCnt = 1
        ep_cfg.logConfig.level = 4  # Reduced logging
        self.ep.libInit(ep_cfg)
        
        # KEY FIX: Use null sound device for headless/server-side operation
        self.ep.audDevManager().setNullDev()
        logging.info("Null sound device set (no hardware audio needed)")

        # Transport
        tcfg = pj.TransportConfig()
        tcfg.port = 5060
        tcfg.boundAddr = local_ip
        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

        self.ep.libStart()
        logging.info("PJSUA2 started")

        # Account
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{sip_user}@{sip_domain}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_domain}"
        cred = pj.AuthCredInfo("digest", "*", sip_user, 0, sip_pass)
        acc_cfg.sipConfig.authCreds.append(cred)

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
            call = self.account.current_call
            
            # Save recording if exists
            if call.rtp_port:
                try:
                    call.rtp_port.save_to_wav("captured_audio.wav")
                    logging.info("Recording saved")
                except Exception as e:
                    logging.error(f"Error saving recording: {e}")
            
            # Clean resources
            if call.rtp_port:
                try:
                    del call.rtp_port
                except:
                    pass
            
            if call.recorder:
                try:
                    del call.recorder
                except:
                    pass

        self.ep.libDestroy()
        logging.info("Destroyed")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        sys.exit(1)

    domain, user, passwd = sys.argv[1:4]
    
    # Check file existence
    import os
    if not os.path.exists("output.wav"):
        logging.error("ERROR: output.wav not found!")
        sys.exit(1)
    
    logging.info(f"Found output.wav ({os.path.getsize('output.wav')} bytes)")
    logging.info("Audio will be auto-converted to PJSUA2 format if needed")
    
    bot = VoIPBot(domain, user, passwd)

    if len(sys.argv) > 4:
        target = sys.argv[4]
        bot.make_call(target)

    logging.info("Ready. Waiting for calls...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("\nShutting down...")
        bot.destroy()