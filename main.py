import json
import logging
import os
import argparse
import threading
import time
import asyncio
import queue

from Sippy.VoIP import VoIPPhone, VoIPCall, CallState, InvalidStateError
from Sippy.VoIP.status import PhoneStatus

from agents.stt_adapter import STTAdapter
from agents.llm_adapter import LLMAdapter
from agents.tts_adapter import TTSAdapter

class VoIPBot:
    def __init__(self, config_path='config.json'):
        # Logging setup
        logging.basicConfig(level=logging.DEBUG if self._is_debug() else logging.INFO,
                            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            handlers=[logging.FileHandler('output.log'), logging.StreamHandler()])
        self.logger = logging.getLogger('VoIPBot')

        # Load config
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        # Initialize agents
        self.stt = STTAdapter(self.config, self.logger)
        self.llm = LLMAdapter(self.config, self.logger)
        self.tts = TTSAdapter(self.config, self.logger)

    async def check_health(self):
        return await self.tts.check_health()

    def start(self, call_type='incoming', target=None):
        if not asyncio.run(self.check_health()):
            self.logger.error("TTS server is not healthy. Aborting.")
            return
    
        sip_config = self.config.get('sip', {})
        rtp_config = self.config.get('rtp', {})
    
        self.phone = VoIPPhone(
            server=sip_config['domain'],  # Assuming domain is the SIP server
            port=sip_config.get('port', 5060),
            username=sip_config['username'],
            password=sip_config['password'],
            myIP=sip_config.get('myIP'),
            sipPort=sip_config.get('sipPort', 5060),
            rtpPortLow=rtp_config.get('rtp_port_min', 10000),
            rtpPortHigh=rtp_config.get('rtp_port_max', 20000),
            callCallback=self.handle_call_wrapper,
            register=True
        )
    
        # Removed self.phone.start() as it's now called in __init__ if register=True
    
        timeout = 30
        start_time = time.time()
        while self.phone.get_status() != PhoneStatus.REGISTERED and time.time() - start_time < timeout:
            time.sleep(1)
        if self.phone.get_status() != PhoneStatus.REGISTERED:
            self.logger.error("Failed to register phone after timeout.")
            self.phone.stop()
            return
    
        self.logger.info("Phone registered successfully.")
    
        if call_type == 'incoming':
            self.logger.info("Waiting for incoming call...")
            try:
                while True:
                    status = self.phone.get_status()
                    if status != PhoneStatus.REGISTERED:
                        self.logger.error("Phone is unregistered. Attempting to restart...")
                        self.phone.stop()
                        self.phone.start()  # Ensure this restarts registration
                        # Wait for re-registration
                        timeout = 30
                        start_time = time.time()
                        while self.phone.get_status() != PhoneStatus.REGISTERED and time.time() - start_time < timeout:
                            time.sleep(1)
                        if self.phone.get_status() != PhoneStatus.REGISTERED:
                            self.logger.critical("Failed to re-register after timeout. Exiting.")
                            break
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        elif call_type == 'outgoing':
            if not target:
                self.logger.error("Target URI required for outgoing calls.")
            else:
                call = self.phone.call(target)
                self.handle_call_wrapper(call)
                while call.state != CallState.ENDED:
                    time.sleep(1)
        self.phone.stop()

    def handle_call_wrapper(self, call):
        threading.Thread(target=self.handle_call, args=(call,)).start()

    def handle_call(self, call):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.async_handle(call))
        except Exception as e:
            self.logger.error(f"Error in handle_call: {e}")
        finally:
            loop.close()

    async def async_handle(self, call):
        try:
            if call.state == CallState.RINGING:
                call.answer()
            elif call.state == CallState.DIALING:
                while call.state == CallState.DIALING:
                    await asyncio.sleep(0.1)
                if call.state != CallState.ANSWERED:
                    return

            # Start reading thread
            running = [True]
            def read_loop():
                while running[0] and call.state == CallState.ANSWERED:
                    data = call.read_audio(320, blocking=True)
                    self.stt.feed_pcm(data)
                    time.sleep(0.02)
            read_thread = threading.Thread(target=read_loop)
            read_thread.start()

            # Initial greeting
            greeting = "Welcome to Freddy Fazbear's Pizza. How can I help you?"
            pcm = await self.tts.synthesize(greeting)
            call.write_audio(pcm)

            # Interactive loop
            while call.state == CallState.ANSWERED:
                try:
                    # Await sync queue.get with timeout
                    transcription = await asyncio.to_thread(self.stt.out_queue.get, timeout=30.0)
                    self.logger.info(f"Transcribed: {transcription}")

                    response = await self.llm.generate(transcription)
                    self.logger.info(f"LLM response: {response}")

                    pcm = await self.tts.synthesize(response)
                    call.write_audio(pcm)
                except queue.Empty:
                    self.logger.debug("No speech detected in timeout period.")
                except Exception as e:
                    self.logger.error(f"Error in call loop: {e}")
                    break

            running[0] = False
            read_thread.join()
            call.hangup()
        except InvalidStateError:
            pass
        except Exception as e:
            self.logger.error(f"Error in async_handle: {e}")

    def _is_debug(self) -> bool:
        v = os.getenv('DEBUG')
        return v is not None and v.lower() in ('true', '1', 't')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run VoIP client with agents.")
    parser.add_argument('--config', type=str, default='config.json', help='Path to config file.')
    parser.add_argument('--call-type', type=str, default='incoming', choices=['incoming', 'outgoing'], help='Call type.')
    parser.add_argument('--target', type=str, help='Target SIP URI for outgoing calls.')
    args = parser.parse_args()

    bot = VoIPBot(args.config)
    bot.start(args.call_type, args.target)
