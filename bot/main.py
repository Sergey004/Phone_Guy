# bot/main.py
import sys
import argparse
import time
import logging
import pjsua2 as pj
import rich.logging
import threading
import queue
import json
import os
from Libs.rtp_streamer import ByteStreamMediaPort
from Libs.stt_adapter import STTAdapter
from Libs.tts_adapter import TTSAdapter
from Libs.llm_adapter import phoneguy_reply
import asyncio

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class MyAccount(pj.Account):
    def __init__(self, ep, stt_adapter, tts_adapter):
        super().__init__()
        self.ep = ep
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter
        self.current_call = None

    def onRegState(self, prm):
        info = self.getInfo()
        logging.info(f"Account registration: {info.regIsActive} ({prm.code} {prm.reason})")

    def onIncomingCall(self, prm):
        call = MyCall(self, prm.callId, self.ep, stt_adapter=self.stt_adapter, tts_adapter=self.tts_adapter)
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"Incoming call from {ci.remoteUri}")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        call.answer(prm)

        
class SttFeederMediaPort(pj.AudioMediaPort):
    def __init__(self, stt_adapter):
        super().__init__()
        self.stt_adapter = stt_adapter

    def onFrameReceived(self, frame, channel):
        logging.debug(f"Received frame: size={frame.size}")
        self.stt_adapter.feed_pcm(bytes(frame.buf))

class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, stt_adapter=None, tts_adapter=None):
        super().__init__(acc, call_id)
        self.media_port = None
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter
        self.stt_feeder_port = None
        self.timer = None
        self.hangup_queue = queue.Queue()
        self.text_queue = queue.Queue()  # For STT -> LLM -> TTS pipeline

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}, last code: {ci.lastStatusCode}")
        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            logging.info("Call is confirmed. Starting STT/TTS processing.")
            # Start processing STT output
            asyncio.create_task(self.process_stt_tts_loop())
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")
            if self.media_port:
                self.media_port = None
            if self.timer:
                self.timer.cancel()
                self.timer = None

    async def process_stt_tts_loop(self):
        """Process STT output, pass to LLM, and feed TTS result to media port."""
        while self.isActive():
            try:
                text = await self.stt_adapter.out_queue.get()
                logging.info(f"STT output: {text}")
                # Pass to LLM
                llm_response = phoneguy_reply(text)
                logging.info(f"LLM response: {llm_response}")
                # Generate TTS and update media port
                await self.tts_adapter.speak(llm_response, self.media_port)
                self.text_queue.put_nowait(llm_response)
            except Exception as e:
                logging.error(f"Error in STT-TTS loop: {e}")
            await asyncio.sleep(0.1)

    def onCallMediaState(self, prm):
        logging.info("*** onCallMediaState ***")
        ci = self.getInfo()

        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and (mi.dir == pj.PJMEDIA_DIR_SENDRECV or mi.dir == pj.PJMEDIA_DIR_RECVONLY):
                audio_media = self.getMedia(mi.index)
                # Initialize media port with empty bytes (TTS will update)
                self.media_port = ByteStreamMediaPort(pcm_bytes=b'', sample_rate=8000)
                # Connect for playback
                self.media_port.startTransmit(audio_media)
                logging.info(f"Playback connected for media index {mi.index}")
                # Connect for recording
                self.stt_feeder_port = SttFeederMediaPort(self.stt_adapter)
                audio_media.startTransmit(self.stt_feeder_port)
                logging.info(f"Recording connected for media index {mi.index}")
                # Start timer to check playback completion
                self.timer = threading.Timer(0.5, self.check_playback_done)
                self.timer.start()

    def check_playback_done(self):
        try:
            if self.media_port and self.isActive() and self.media_port.is_playback_done():
                logging.info("Playback completed, checking for new TTS data")
            else:
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

        tcfg = pj.TransportConfig()
        tcfg.port = sip_cfg.get("local_port", 5060)
        tcfg.boundAddr = local_ip
        tcfg.publicAddr = local_ip
        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

        self.ep.codecSetPriority("*", 0)
        self.ep.codecSetPriority("PCMA/8000/1", 255)
        self.ep.codecSetPriority("PCMU/8000/1", 254)
        logging.info("Codecs set to PCMA/8000/1 (255), PCMU/8000/1 (254)")

        self.ep.libStart()
        logging.info("PJSUA2 started")

        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{sip_cfg['username']}@{sip_cfg['domain']}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_cfg['domain']}"
        acc_cfg.sipConfig.authCreds.append(pj.AuthCredInfo("digest", "*", sip_cfg['username'], 0, sip_cfg['password']))
        self.account = MyAccount(self.ep)
        self.account.create(acc_cfg)

        self.stt_adapter = STTAdapter(config, logging.getLogger("STT"))
        self.tts_adapter = TTSAdapter(config, logging.getLogger("TTS"))

    def destroy(self):
        logging.info("Cleaning up...")
        if self.account and self.account.current_call:
            try:
                call = self.account.current_call
                if call.isActive():
                    call.hangup(pj.CallOpParam())
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
    with open("config.json", "r") as f:
        config = json.load(f)

    bot = None
    try:
        bot = VoIPBot(config)
        logging.info("SIP client initialized. Press Ctrl+C to exit.")
        while True:
            time.sleep(0.1)
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