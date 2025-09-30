#!/usr/bin/env python3
import sys
import time
import logging
import pjsua2 as pj
import threading
import queue
import asyncio
import soundfile as sf
import os
from rtp_streamer import ByteStreamMediaPort
from stt_adapter import STTAdapter
from tts_adapter import TTSAdapter
from llm_adapter import phoneguy_reply, reset_conversation_history

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)

class SttFeederMediaPort(pj.AudioMediaPort):
    def __init__(self, stt_adapter):
        super().__init__()
        self.stt_adapter = stt_adapter
        self.conf_port_id = -1

    def onFrameReceived(self, frame, channel):
        logging.debug(f"Received frame: size={frame.size}")
        self.stt_adapter.feed_pcm(bytes(frame.buf))

    def register_with_conf(self, ep):
        try:
            self.createPort("stt_feeder_port")
            self.conf_port_id = self.getPortId()
            logging.info(f"Registered SttFeederMediaPort with conf port ID: {self.conf_port_id}")
        except Exception as e:
            logging.error(f"Error registering SttFeederMediaPort: {e}")
            self.conf_port_id = -1

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
        call = MyCall(self, prm.callId, self.ep, stt_adapter=self.stt_adapter, tts_adapter=self.tts_adapter, loop=self.loop)
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"Incoming call from {ci.remoteUri}")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        call.answer(prm)

class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, ep=None, stt_adapter=None, tts_adapter=None, loop=None):
        super().__init__(acc, call_id)
        self.ep = ep
        self.loop = loop
        self.media_port = None
        self.stt_feeder_port = None
        self.timer = None
        self.hangup_queue = queue.Queue()
        self.text_queue = queue.Queue()
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"Call state: {ci.stateText}")
        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            logging.info("Call is confirmed. Starting initial greeting and STT/TTS processing.")
            asyncio.run_coroutine_threadsafe(self.send_initial_greeting(), self.loop)
            asyncio.run_coroutine_threadsafe(self.process_stt_tts_loop(), self.loop)
            asyncio.run_coroutine_threadsafe(self.log_media_stats(), self.loop)
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("Call disconnected")
            reset_conversation_history()
            if self.media_port and self.media_port.conf_port_id >= 0:
                try:
                    pj.Endpoint.instance().conf_disconnect(self.media_port.conf_port_id, 0)
                    logging.info(f"Disconnected media port {self.media_port.conf_port_id} from conference")
                except Exception as e:
                    logging.error(f"Error disconnecting media port: {e}")
            if self.stt_feeder_port and self.stt_feeder_port.conf_port_id >= 0:
                try:
                    pj.Endpoint.instance().conf_disconnect(0, self.stt_feeder_port.conf_port_id)
                    logging.info(f"Disconnected STT feeder port {self.stt_feeder_port.conf_port_id} from conference")
                except Exception as e:
                    logging.error(f"Error disconnecting STT feeder port: {e}")
            if self.timer:
                self.timer.cancel()
                self.timer = None

    async def send_initial_greeting(self):
        """Generate and play a Phone Guy-style greeting when the call is answered."""
        try:
            # Check TTS server health
            if not await self.tts_adapter.check_health():
                logging.warning("TTS server unavailable, using fallback greeting")
                # Fallback to pre-recorded WAV
                fallback_wav = "fallback_greeting.wav"
                if os.path.exists(fallback_wav):
                    with open(fallback_wav, "rb") as f:
                        pcm_data = f.read()
                    self.media_port.update_playback_data(pcm_data)
                    logging.info("Played fallback greeting from WAV")
                    self.text_queue.put_nowait("Hello, welcome to the call!")
                else:
                    logging.error("Fallback greeting WAV not found")
                    self.text_queue.put_nowait("Hello, welcome to the call!")
                return

            greeting_text = phoneguy_reply("Say a welcoming greeting as if answering a phone call.")
            if not greeting_text or greeting_text.strip() == "":
                logging.error("LLM returned empty greeting, using default")
                greeting_text = "Hello, uh, welcome to the call! This is your, um, friendly Phone Guy speaking."
                self.text_queue.put_nowait(greeting_text)
            else:
                logging.info(f"Generated greeting: {greeting_text}")
                self.text_queue.put_nowait(greeting_text)
            
            await self.tts_adapter.speak(greeting_text, self.media_port)
            logging.info("Initial greeting sent to TTS")
        except Exception as e:
            logging.error(f"Error generating or playing initial greeting: {e}")

    async def process_stt_tts_loop(self):
        """Process STT output, pass to LLM, and feed TTS result to media port."""
        while self.isActive():
            try:
                text = await self.stt_adapter.out_queue.get()
                logging.info(f"STT output: {text}")
                llm_response = phoneguy_reply(text)
                if not llm_response or llm_response.strip() == "":
                    logging.error("LLM returned empty response, using default")
                    llm_response = "Uh, I didn’t catch that. Could you, um, repeat it?"
                logging.info(f"LLM response: {llm_response}")
                await self.tts_adapter.speak(llm_response, self.media_port)
                self.text_queue.put_nowait(llm_response)
            except Exception as e:
                logging.error(f"Error in STT-TTS loop: {e}")
            await asyncio.sleep(0.1)

    async def log_media_stats(self):
        """Periodically log media port status to debug audio flow."""
        while self.isActive():
            try:
                # Log port IDs and connection status
                if self.media_port and self.media_port.conf_port_id >= 0:
                    logging.debug(f"ByteStreamMediaPort active, port ID: {self.media_port.conf_port_id}")
                if self.stt_feeder_port and self.stt_feeder_port.conf_port_id >= 0:
                    logging.debug(f"SttFeederMediaPort active, port ID: {self.stt_feeder_port.conf_port_id}")
                # Log call media info
                ci = self.getInfo()
                for mi in ci.media:
                    if mi.type == pj.PJMEDIA_TYPE_AUDIO:
                        logging.debug(f"Call media: index={mi.index}, status={mi.status}")
            except Exception as e:
                logging.error(f"Error logging media port status: {e}")
            await asyncio.sleep(2.0)

    def onCallMediaState(self, prm):
        logging.info("Entering onCallMediaState")
        ci = self.getInfo()
        
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                logging.info("Audio active, setting up media")
                try:
                    audio_media = self.getAudioMedia(mi.index)
                    audio_port_id = audio_media.getPortId()
                    logging.info(f"Got audio media, port ID: {audio_port_id}")
                    
                    # Initialize and register ByteStreamMediaPort
                    self.media_port = ByteStreamMediaPort(pcm_bytes=b'', sample_rate=8000)
                    self.media_port.register_with_conf(self.ep)
                    if self.media_port.conf_port_id < 0:
                        raise Exception("Failed to register ByteStreamMediaPort with conference bridge")
                    
                    # Initialize and register SttFeederMediaPort
                    self.stt_feeder_port = SttFeederMediaPort(self.stt_adapter)
                    self.stt_feeder_port.register_with_conf(self.ep)
                    if self.stt_feeder_port.conf_port_id < 0:
                        raise Exception("Failed to register SttFeederMediaPort with conference bridge")
                    
                    # Connect ports using conference bridge
                    # Playback: media_port -> audio_media
                    pj.Endpoint.instance().conf_connect(self.media_port.conf_port_id, audio_port_id)
                    # Recording: audio_media -> stt_feeder_port
                    pj.Endpoint.instance().conf_connect(audio_port_id, self.stt_feeder_port.conf_port_id)
                    
                    logging.info(f"Connected media_port ({self.media_port.conf_port_id}) -> audio_media ({audio_port_id})")
                    logging.info(f"Connected audio_media ({audio_port_id}) -> stt_feeder_port ({self.stt_feeder_port.conf_port_id})")
                    
                    # Log PJSUA2 media state
                    logging.debug(f"Call media state: index={mi.index}, status={mi.status}")
                    
                    self.timer = threading.Timer(0.5, self.check_playback_done)
                    self.timer.start()
                except Exception as e:
                    logging.error(f"Error in onCallMediaState: {e}")
                    import traceback
                    traceback.print_exc()

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
    def __init__(self, sip_domain, sip_user, sip_pass, local_ip="192.168.1.181"):
        self.ep = pj.Endpoint()
        self.ep.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.uaConfig.threadCnt = 1
        ep_cfg.uaConfig.maxCalls = 4
        ep_cfg.logConfig.level = 6  # High verbosity for media debugging
        ep_cfg.medConfig.sndClockRate = 8000
        ep_cfg.medConfig.channelCount = 1
        ep_cfg.medConfig.audioFramePtime = 20
        ep_cfg.medConfig.noVad = True
        self.ep.libInit(ep_cfg)
        
        self.ep.audDevManager().setNullDev()
        logging.info("Null sound device set (no hardware audio needed)")

        tcfg = pj.TransportConfig()
        tcfg.port = 5060
        tcfg.boundAddr = local_ip
        tcfg.publicAddr = local_ip
        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

        self.ep.codecSetPriority("*", 0)
        self.ep.codecSetPriority("PCMA/8000/1", 255)
        self.ep.codecSetPriority("PCMU/8000/1", 254)
        logging.info("Codecs set to PCMA/8000/1 (255), PCMU/8000/1 (254)")

        self.ep.libStart()
        logging.info("PJSUA2 started")

        config = {
            "sip": {"username": sip_user, "domain": sip_domain, "password": sip_pass, "local_addr": local_ip},
            "stt": {"energy_threshold": 500, "min_chunk_ms": 1500, "silence_end_ms": 600},
            "tts": {"api_key": "your_super_secret_api_key", "base_url": "http://localhost:8000/v1"}
        }
        self.stt_adapter = STTAdapter(config, logging.getLogger("STT"))
        self.tts_adapter = TTSAdapter(config, logging.getLogger("TTS"))

        # Check TTS server health
        loop = asyncio.get_event_loop()
        if not loop.run_until_complete(self.tts_adapter.check_health()):
            logging.error("TTS server is unavailable. Calls may proceed without audio.")
        
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{sip_user}@{sip_domain}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_domain}"
        acc_cfg.sipConfig.authCreds.append(pj.AuthCredInfo("digest", "*", sip_user, 0, sip_pass))
        self.account = MyAccount(self.ep, self.stt_adapter, self.tts_adapter, loop)
        self.account.create(acc_cfg)

    def make_call(self, uri):
        call = MyCall(self.account, ep=self.ep, stt_adapter=self.stt_adapter, tts_adapter=self.tts_adapter, loop=self.account.loop)
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
        reset_conversation_history()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        sys.exit(1)

    domain, user, passwd = sys.argv[1:4]
    
    bot = VoIPBot(domain, user, passwd)

    if len(sys.argv) > 4:
        target = sys.argv[4]
        bot.make_call(target)

    logging.info("Ready. Waiting for calls...")
    
    try:
        loop = asyncio.get_event_loop()
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("\nShutting down...")
        bot.destroy()