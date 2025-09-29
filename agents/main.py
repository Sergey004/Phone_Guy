import sys
import argparse
import time
import logging
import wave
import pjsua2 as pj
import rich.logging

# Configure logging with rich
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

# Assuming RtpStreamerMediaPort is defined in rtp_streamer.py
from rtp_streamer import RtpStreamerMediaPort

class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, audio_file=None):
        pj.Call.__init__(self, acc, call_id)
        self.rtp_streamer_port: RtpStreamerMediaPort = None
        self.audio_player: pj.AudioMediaPlayer = None
        self.audio_file = audio_file

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}, last code: {ci.lastStatusCode}")
        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            logging.info("Call is confirmed. RTP streaming should be active.")
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")
            if self.rtp_streamer_port:
                self.rtp_streamer_port.save_to_wav("captured_audio.wav")
                self.rtp_streamer_port.destroy()
                self.rtp_streamer_port = None
            if self.audio_player:
                self.audio_player.destroy()
                self.audio_player = None

    def onCallMediaState(self, prm):
        logging.info("*** onCallMediaState ***")
        ci = self.getInfo()

        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and \
               (mi.dir == pj.PJMEDIA_DIR_RECVONLY or mi.dir == pj.PJMEDIA_DIR_SENDRECV):
                audio_media: pj.AudioMedia = self.getMedia(mi.index)
                media_conf: pj.ConfPortInfo = audio_media.getPortInfo()

                # Create and register the custom media port for capturing incoming audio
                self.rtp_streamer_port = RtpStreamerMediaPort()
                self.rtp_streamer_port.createPort("rtp_streamer_port", media_conf.format)

                # Connect capture device to RTP streamer (for incoming audio)
                pj.Endpoint.instance().audDevManager().getCaptureDevMedia().startTransmit(self.rtp_streamer_port)
                audio_media.startTransmit(self.rtp_streamer_port)
                logging.info(f"RTP streaming to RtpStreamerMediaPort started for media index {mi.index}")

                # Create and connect AudioMediaPlayer for playing WAV file
                if self.audio_file:
                    try:
                        self.audio_player = pj.AudioMediaPlayer()
                        self.audio_player.createPlayer(self.audio_file, 0)  # 0 means auto-detect format
                        self.audio_player.startTransmit(audio_media)
                        logging.info(f"AudioMediaPlayer started for file {self.audio_file} on media index {mi.index}")
                    except pj.Error as e:
                        logging.error(f"Failed to create AudioMediaPlayer for {self.audio_file}: {e}")
                        self.audio_player = None
                else:
                    logging.warning("No audio file specified, no audio will be played.")

class MyAccount(pj.Account):
    def __init__(self, acc_cfg):
        pj.Account.__init__(self)
        self.acc_cfg = acc_cfg

    def onRegState(self, prm):
        logging.info(f"Registration state: {prm.reason}, code: {prm.code}")
        if prm.code != 200:
            logging.error(f"Registration failed: {prm.reason}")
            raise RuntimeError(f"Failed to register SIP account: {prm.reason}")

class VoIPBot:
    def __init__(self, sip_username, sip_password, sip_domain, sip_server, clientip=None, audio_file=None):
        self.username = sip_username
        self.password = sip_password
        self.domain = sip_domain
        self.server = sip_server
        self.clientip = clientip
        self.audio_file = audio_file

        self.ep = pj.Endpoint()
        self.ep.libCreate()
        ep_cfg = pj.EpConfig()
        ep_cfg.logConfig.level = 6  # Increased log level for debugging
        ep_cfg.medConfig.sndRecLatency = 0
        ep_cfg.medConfig.sndPlayLatency = 0
        ep_cfg.medConfig.clockRate = 16000
        ep_cfg.medConfig.channelCount = 1
        ep_cfg.medConfig.noVad = True
        ep_cfg.medConfig.ilbcWasEnabled = False
        ep_cfg.medConfig.vidPreviewEnable = False
        ep_cfg.medConfig.enableIce = True
        ep_cfg.medConfig.enableTurn = True
        ep_cfg.medConfig.enableStun = True
        ep_cfg.uaConfig.threadCnt = 0
        self.ep.libInit(ep_cfg)

        # List available audio devices for debugging
        devices = self.ep.audDevManager().enumDev()
        logging.info(f"Available audio devices: {devices}")
        # Use default audio device (remove setNullDev for real audio)
        try:
            self.ep.audDevManager().setCaptureDev(0)
            self.ep.audDevManager().setPlaybackDev(0)
        except pj.Error as e:
            logging.warning(f"Failed to set audio devices: {e}, falling back to null device")
            self.ep.audDevManager().setNullDev()

        ts_cfg = pj.TransportConfig()
        ts_cfg.port = 5060
        if self.clientip:
            ts_cfg.public_addr = self.clientip
        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, ts_cfg)
        self.ep.libStart()

        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{self.username}@{self.domain}"
        acc_cfg.regConfig.registrarUri = f"sip:{self.server}"
        acc_cfg.sipConfig.authCreds.append(pj.AuthCredInfo("digest", "asterisk", self.username, 0, self.password))
        if self.clientip:
            acc_cfg.mediaConfig.transportConfig.bound_addr = self.clientip
        self.acc = MyAccount(acc_cfg)
        self.acc.create(acc_cfg)

        self.current_call = None

    def make_call(self, dest_uri):
        if self.current_call:
            logging.warning("Already in a call, disconnecting current call.")
            self.current_call.hangup()
            self.current_call = None

        logging.info(f"Making call to {dest_uri}")
        try:
            self.current_call = MyCall(self.acc, audio_file=self.audio_file)
            call_prm = pj.CallOpParam()
            call_prm.opt.audioCount = 1
            call_prm.opt.videoCount = 0
            self.current_call.makeCall(dest_uri, call_prm)
        except pj.Error as e:
            logging.error(f"Failed to make call: {e}")
            self.current_call = None
            raise

    def hangup_call(self):
        if self.current_call:
            logging.info("Hanging up current call.")
            call_prm = pj.CallOpParam()
            self.current_call.hangup(call_prm)
            self.current_call = None
        else:
            logging.info("No active call to hangup.")

    def destroy(self):
        if self.current_call:
            if self.current_call.rtp_streamer_port:
                self.current_call.rtp_streamer_port.save_to_wav("captured_audio.wav")
            self.hangup_call()
        time.sleep(1)
        self.ep.libDestroy()
        logging.info("SIP client destroyed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIP Client with RTP Streaming and Audio File Playback")
    parser.add_argument("-u", "--username", required=True, help="SIP Username")
    parser.add_argument("-p", "--password", required=True, help="SIP Password")
    parser.add_argument("-d", "--domain", required=True, help="SIP Domain")
    parser.add_argument("-s", "--server", required=True, help="SIP Server")
    parser.add_argument("--dest_uri", required=True, help="Destination URI for the call")
    parser.add_argument("--clientip", help="Client's public IP address for NAT traversal")
    parser.add_argument("--audio_file", required=True, help="Path to WAV audio file to play")
    args = parser.parse_args()

    bot = None
    try:
        bot = VoIPBot(args.username, args.password, args.domain, args.server, args.clientip, args.audio_file)
        logging.info("SIP client initialized. Press Ctrl+C to exit.")

        if args.dest_uri:
            bot.make_call(args.dest_uri)

        while True:
            time.sleep(1)

    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        if bot:
            bot.destroy()