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
import struct
import asyncio
from Libs.stt_adapter import STTAdapter
from Libs.tts_adapter import TTSAdapter
from Libs.llm_adapter import phoneguy_reply
from Libs.audio import AudioCapturePort, AudioPlaybackPort

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class MyAccount(pj.Account):
    def __init__(self, ep, stt_adapter, tts_adapter, loop):
        super().__init__()
        self.ep = ep
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter
        self.loop = loop
        self.current_call = None

    def onRegState(self, prm):
        info = self.getInfo()
        logging.info(f"Account registration: {info.regIsActive} ({prm.code} {prm.reason})")

    def onIncomingCall(self, prm):
        call = MyCall(self, prm.callId, stt_adapter=self.stt_adapter, tts_adapter=self.tts_adapter, loop=self.loop, ep=self.ep)
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"Incoming call from {ci.remoteUri}")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        call.answer(prm)

class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, stt_adapter=None, tts_adapter=None, loop=None, ep=None):
        super().__init__(acc, call_id)
        self.playback_port = None
        self.capture_port = None
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter
        self.loop = loop
        self.ep = ep
        self.timer = None
        self.hangup_queue = queue.Queue()
        self.text_queue = queue.Queue()
        self._capture_task = None
        self._stop_capture = False

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}, last code: {ci.lastStatusCode}")
        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            logging.info("Call is confirmed. Starting STT/TTS processing.")
            if self.loop:
                self.loop.create_task(self.process_stt_tts_loop())
                self.loop.create_task(self.process_audio_capture())
                self.loop.create_task(self.stt_adapter.consume_frame_queue())
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")
            if self.playback_port:
                self.playback_port = None
            if self.capture_port:
                self._stop_capture = True
            if self.timer:
                self.timer.cancel()
                self.timer = None
            try:
                self._stop_capture = True
                if self._capture_task:
                    self._capture_task.cancel()
                    self._capture_task = None
            except Exception as e:
                logging.warning(f"Error stopping audio capture: {e}")

    async def process_stt_tts_loop(self):
        """Process STT output, pass to LLM, and feed TTS result to media port."""
        while self.isActive():
            try:
                text = await self.stt_adapter.out_queue.get()
                logging.info(f"STT output: {text}")
                # Pass to LLM
                llm_response = phoneguy_reply(text)
                logging.info(f"LLM response: {llm_response}")
                # Generate TTS and update playback port
                await self.tts_adapter.speak(llm_response, self.playback_port)
                self.text_queue.put_nowait(llm_response)
            except Exception as e:
                logging.error(f"Error in STT-TTS loop: {e}")
            await asyncio.sleep(0.1)
    
    async def process_audio_capture(self):
        """Process captured audio frames and feed to STT adapter."""
        while not self._stop_capture and self.isActive():
            try:
                if self.capture_port:
                    frame = self.capture_port.get_frame(timeout=0.1)
                    if frame:
                        self.stt_adapter.enqueue_frame(frame)
            except Exception as e:
                logging.error(f"Error processing audio capture: {e}")
            await asyncio.sleep(0.02)

    def onCallMediaState(self, prm):
        logging.info("*** onCallMediaState ***")
        ci = self.getInfo()

        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and (mi.dir == pj.PJMEDIA_DIR_SENDRECV or mi.dir == pj.PJMEDIA_DIR_RECVONLY):
                audio_media = self.getMedia(mi.index)
                
                # Initialize playback port with AudioPlaybackPort (replaces ByteStreamMediaPort)
                self.playback_port = AudioPlaybackPort(pcm_bytes=b'', sample_rate=8000, logger=logging.getLogger("AudioPlayback"))
                if self.playback_port.register_with_conf(self.ep):
                    # Connect for playback
                    self.playback_port.startTransmit(audio_media)
                    logging.info(f"Playback connected for media index {mi.index}")
                else:
                    logging.error("Failed to register playback port")
                
                # Initialize capture port with AudioCapturePort (replaces AudioMediaRecorder)
                self.capture_port = AudioCapturePort(sample_rate=8000, logger=logging.getLogger("AudioCapture"))
                if self.capture_port.register_with_conf(self.ep):
                    # Connect for recording
                    audio_media.startTransmit(self.capture_port)
                    logging.info(f"Audio capture connected for media index {mi.index}")
                    
                    # Log capture statistics periodically
                    self.loop.create_task(self.log_capture_stats())
                else:
                    logging.error("Failed to register capture port")
    
    async def log_capture_stats(self):
        """Log capture statistics periodically."""
        while not self._stop_capture and self.isActive():
            try:
                if self.capture_port:
                    stats = self.capture_port.get_stats()
                    if stats['frames_captured'] > 0:
                        logging.info(f"Audio Capture Stats: Captured={stats['frames_captured']}, "
                                   f"Dropped={stats['frames_dropped']}, Errors={stats['errors']}, "
                                   f"Queue={stats['queue_size']}/{stats['queue_max_size']}")
                        # Reset stats periodically
                        self.capture_port.reset_stats()
            except Exception as e:
                logging.error(f"Error logging capture stats: {e}")
            await asyncio.sleep(30)  # Log every 30 seconds

class VoIPBot:
    def __init__(self, config):
        self.ep = pj.Endpoint()
        self.ep.libCreate()
        self.loop = asyncio.new_event_loop()
        def _run_loop(loop):
            asyncio.set_event_loop(loop)
            loop.run_forever()
        self.loop_thread = threading.Thread(target=_run_loop, args=(self.loop,), daemon=True)
        self.loop_thread.start()

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
        self.stt_adapter = STTAdapter(config, logging.getLogger("STT"))
        self.tts_adapter = TTSAdapter(config, logging.getLogger("TTS"))
        self.account = MyAccount(self.ep, self.stt_adapter, self.tts_adapter, self.loop)
        self.account.create(acc_cfg)
        try:
            fut = asyncio.run_coroutine_threadsafe(self.tts_adapter.check_health(), self.loop)
            ready = fut.result(timeout=15)
            if not ready:
                logging.warning("TTS engine not ready; audio responses may be skipped.")
        except Exception as e:
            logging.error(f"TTS health check error: {e}")

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
