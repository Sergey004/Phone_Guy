#!/usr/bin/env python3
import sys
import argparse
import time
import logging
import wave
import pjsua2 as pj
import rich.logging
import threading
import queue
import json
import os
from rtp_streamer import RtpStreamerMediaPort
from Adapters.stt_adapter import STTAdapter
from Adapters.tts_adapter import TTSAdapter
from Adapters.llm_adapter import phoneguy_reply
from wav_converter import ensure_pjsua_compatible

# Configure logging with rich
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class SttFeederMediaPort(pj.AudioMediaPort):
    def __init__(self, stt_adapter):
        super().__init__()
        self.stt_adapter = stt_adapter

    def onFrameReceived(self, frame, channel):
        logging.debug(f"Received frame: size={frame.size}")
        self.stt_adapter.feed_pcm(bytes(frame.buf))

class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, audio_file=None, stt_adapter=None, tts_adapter=None):
        super().__init__(acc, call_id)
        self.rtp_streamer_port = None
        self.audio_player = None
        self.audio_file = audio_file
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter
        self.stt_feeder_port = None
        self.timer = None
        self.hangup_queue = queue.Queue()
        self.playback_queue = queue.Queue()
        self.recording_file = "captured_audio.wav"
        self.tts_file = "tts_output.wav"

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}, last code: {ci.lastStatusCode}")
        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            logging.info("Call is confirmed. RTP streaming should be active.")
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")
            if self.rtp_streamer_port:
                self.rtp_streamer_port.save_to_wav(self.recording_file)
                self.rtp_streamer_port.destroy()
                self.rtp_streamer_port = None
            if self.audio_player:
                self.audio_player.destroy()
                self.audio_player = None
            if self.timer:
                self.timer.cancel()
                self.timer = None
            # Process STT/TTS after disconnect if needed
            self.process_stt_tts()

    def process_stt_tts(self):
        # STT is real-time, but if needed, wait for last segment
        text = phoneguy_reply("Example text from STT")  # Replace with actual STT text from queue
        pcm_data = self.tts_adapter.synthesize(text)
        if pcm_data:
            # Save PCM to temp WAV for playback
            with wave.open(self.tts_file, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(pcm_data)
            # Queue for playback
            self.playback_queue.put(self.tts_file)

    def onCallMediaState(self, prm):
        logging.info("*** onCallMediaState ***")
        ci = self.getInfo()

        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and (mi.dir == pj.PJMEDIA_DIR_SENDRECV or mi.dir == pj.PJMEDIA_DIR_RECVONLY):
                audio_media = self.getMedia(mi.index)
                media_conf = audio_media.getPortInfo()

                # Create and register the custom media port for capturing incoming audio
                self.stt_feeder_port = SttFeederMediaPort(self.stt_adapter)
                # Assuming createPort is fixed or not needed if not using custom port for other things
                # Connect incoming audio to STT feeder
                audio_media.startTransmit(self.stt_feeder_port)
                logging.info(f"Incoming audio connected to STT feeder for media index {mi.index}")

                # Create and connect AudioMediaPlayer for playing WAV file
                if self.audio_file:
                    try:
                        self.audio_player = pj.AudioMediaPlayer()
                        compatible_file = ensure_pjsua_compatible(self.audio_file, target_rate=8000)
                        self.audio_player.createPlayer(compatible_file, 0)  # 0 means auto-detect format
                        self.audio_player.startTransmit(audio_media)
                        logging.info(f"AudioMediaPlayer started for file {self.audio_file} on media index {mi.index}")
                    except pj.Error as e:
                        logging.error(f"Failed to create AudioMediaPlayer for {self.audio_file}: {e}")
                        self.audio_player = None
                else:
                    logging.warning("No audio file specified, no audio will be played.")

                # Start timer to check playback completion
                self.timer = threading.Timer(0.5, self.check_playback_done)
                self.timer.start()

    def check_playback_done(self):
        try:
            if self.rtp_port and self.isActive() and self.rtp_port.is_playback_done():
                logging.info("Playback completed, queuing hangup")
                self.hangup_queue.put(True)
            else:
                # Reschedule timer
                self.timer = threading.Timer(0.5, self.check_playback_done)
                self.timer.start()
        except Exception as e:
            logging.error(f"Error in check_playback_done: {e}")
            if self.timer:
                self.timer.cancel()
                self.timer = None


class VoIPBot:
    def __init__(self, config):
        self.ep = pj.Endpoint()
        self.ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.uaConfig.threadCnt = 1
        ep_cfg.uaConfig.maxCalls = 4
        ep_cfg.logConfig.level = 5
        ep_cfg.medConfig.sndClockRate = 8000
        ep_cfg.medConfig.channelCount = 1
        ep_cfg.medConfig.audioFramePtime = 20
        ep_cfg.medConfig.noVad = True
        self.ep.libInit(ep_cfg)
        
        self.ep.audDevManager().setNullDev()
        logging.info("Null sound device set (no hardware audio needed)")

        sip_cfg = config["sip"]
        local_ip = sip_cfg.get("local_addr", "192.168.1.181")

        # Transport
        tcfg = pj.TransportConfig()
        tcfg.port = sip_cfg.get("local_port", 5060)
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
        acc_cfg.idUri = f"sip:{sip_cfg['username']}@{sip_cfg['domain']}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_cfg['domain']}"
        acc_cfg.sipConfig.authCreds.append(pj.AuthCredInfo("digest", "*", sip_cfg['username'], 0, sip_cfg['password']))
        self.account = MyAccount(self.ep)
        self.account.create(acc_cfg)

        # STT and TTS adapters
        self.stt_adapter = STTAdapter(config, logging.getLogger("STT"))
        self.tts_adapter = TTSAdapter(config, logging.getLogger("TTS"))

    def destroy(self):
        logging.info("Cleaning up...")
        
        if self.account and self.account.current_call:
            try:
                call = self.account.current_call
                if call.isActive():
                    call.hangup(pj.CallOpParam())
                if call.rtp_streamer_port:
                    try:
                        call.rtp_streamer_port.save_to_wav("captured_audio.wav")
                        logging.info("Recording saved")
                    except Exception as e:
                        logging.error(f"Error saving recording: {e}")
                    call.rtp_streamer_port = None
                self.account.current_call = None
            except Exception as e:
                logging.error(f"Error cleaning up call: {e}")

        try:
            if self.account:
                self.account.delete()
                self.account = None
        except Exception as e:
            logging.error(f"Error deleting account: {e}")

        try:
            self.ep.libDestroy()
            logging.info("Destroyed")
        except Exception as e:
            logging.error(f"Error destroying endpoint: {e}")

if __name__ == "__main__":
    # Load config
    with open("config.json", "r") as f:
        config = json.load(f)

    bot = None
    try:
        bot = VoIPBot(config)
        logging.info("SIP client initialized. Press Ctrl+C to exit.")

        # Main loop for queue processing
        while True:
            time.sleep(0.1)
            # Process hangup queue for current call
            if bot.account and bot.account.current_call:
                call = bot.account.current_call
                try:
                    if not call.hangup_queue.empty():
                        call.hangup_queue.get_nowait()
                        if call.isActive():
                            logging.info("Processing queued hangup")
                            prm = pj.CallOpParam()
                            prm.statusCode = pj.PJSIP_SC_OK
                            call.hangup(prm)
                except Exception as e:
                    logging.error(f"Error processing hangup queue: {e}")

    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        if bot:
            bot.destroy()