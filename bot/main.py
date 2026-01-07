# bot/main.py
import sys
import argparse
import time
import logging
import rich.logging
import threading
import queue
import json
import os
import asyncio
import pjsua2 as pj
from Libs.stt_adapter import STTAdapter
from Libs.tts_adapter import TTSAdapter
from Libs.llm_adapter import phoneguy_reply
from Libs.audio import AudioCapturePort, AudioPlaybackPort
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)


class MainAccount(VoIPAccount):
    """Main account with STT/TTS support."""
    
    def __init__(self, ep, stt_adapter, tts_adapter, loop, config=None, logger=None, **kwargs):
        super().__init__(ep, call_class=MainCall, logger=logger, **kwargs)
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter
        self.loop = loop
        self.config = config or {}
        
        # Get settings from config
        server_cfg = self.config.get('server', {})
        self.answer_delay = server_cfg.get('answerDelay', 2.0)
        self.silence_duration = server_cfg.get('silenceDuration', 2.0)
        
        self.logger.info(f"MainAccount initialized with answer_delay={self.answer_delay}s, silence_duration={self.silence_duration}s")
    
    def onIncomingCall(self, prm):
        """
        Called when incoming call is received.
        Implements delay to simulate real human answering.
        """
        try:
            if not self.call_class:
                self.logger.warning("No call class set, ignoring incoming call")
                return
            
            # Create call instance with silence duration
            call = self.call_class(
                self, 
                prm.callId, 
                stt_adapter=self.stt_adapter,
                tts_adapter=self.tts_adapter,
                loop=self.loop,
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
                # Default behavior: answer with delay to simulate human
                if self.answer_delay > 0 and self.loop:
                    # Schedule delayed answer using asyncio
                    asyncio.run_coroutine_threadsafe(
                        self._delayed_answer(call), 
                        self.loop
                    )
                else:
                    # Answer immediately
                    self._answer_call(call, prm)
                
        except Exception as e:
            self.logger.error(f"Error handling incoming call: {e}", exc_info=True)
    
    async def _delayed_answer(self, call):
        """
        Delayed answer using asyncio to simulate human answering.
        """
        try:
            self.logger.info(f"Waiting {self.answer_delay} seconds before answering...")
            await asyncio.sleep(self.answer_delay)
            
            # Answer the call
            answer_prm = pj.CallOpParam()
            answer_prm.statusCode = 200
            call.answer(answer_prm)
            self.logger.info("Call answered")
            
        except Exception as e:
            self.logger.error(f"Error in delayed answer: {e}", exc_info=True)


class MainCall(VoIPCall):
    """Main call with STT/TTS processing."""
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, 
                 stt_adapter=None, tts_adapter=None, loop=None, 
                 silence_duration=2.0, **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.playback_port = None
        self.capture_port = None
        self.stt_adapter = stt_adapter
        self.tts_adapter = tts_adapter
        self.loop = loop
        self.silence_duration = silence_duration
        self.text_queue = queue.Queue()
        self._capture_task = None
        self._stop_capture = False

    def onCallState(self, prm):
        """Handle call state changes."""
        try:
            ci = self.getInfo()
            self.logger.info(f"Call state: {ci.stateText}, last code: {ci.lastStatusCode}")
            
            if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
                self.logger.info("Call is confirmed. Starting STT/TTS processing.")
                
                # Initialize playback port with silence
                if self.playback_port:
                    silence = self.playback_port.generate_silence(self.silence_duration)
                    self.playback_port.update_playback_data(silence, validate=False)
                    self.logger.info(f"Playback port initialized with {self.silence_duration}s of silence")
                
                if self.loop:
                    self.loop.create_task(self.process_stt_tts_loop())
                    self.loop.create_task(self.process_audio_capture())
                    self.loop.create_task(self.stt_adapter.consume_frame_queue())
            elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.logger.info("Call disconnected")
                if self.playback_port:
                    self.playback_port = None
                if self.capture_port:
                    self._stop_capture = True
                try:
                    self._stop_capture = True
                    if self._capture_task:
                        self._capture_task.cancel()
                        self._capture_task = None
                except Exception as e:
                    self.logger.warning(f"Error stopping audio capture: {e}")
            
            # Call parent handler
            super().onCallState(prm)
            
        except Exception as e:
            self.logger.error(f"Error in onCallState: {e}")

    def _setup_audio_media(self, media_info):
        """Setup audio media with STT/TTS ports."""
        try:
            audio_media = self.getAudioMedia(media_info.index)
            self.logger.info(f"Got audio media, port ID: {audio_media.getPortId()}")
            
            # Check if already set up
            if self.playback_port is not None:
                self.logger.info("Audio already set up")
                return
            
            # Initialize playback port
            self.playback_port = AudioPlaybackPort(
                pcm_bytes=b'', 
                sample_rate=8000, 
                logger=self.logger.getChild("AudioPlayback")
            )
            if self.playback_port.register_with_conf(self.getAccount().ep):
                self.playback_port.startTransmit(audio_media)
                self.logger.info(f"Playback connected for media index {media_info.index}")
            else:
                self.logger.error("Failed to register playback port")
            
            # Initialize capture port
            self.capture_port = AudioCapturePort(
                sample_rate=8000, 
                logger=self.logger.getChild("AudioCapture")
            )
            if self.capture_port.register_with_conf(self.getAccount().ep):
                audio_media.startTransmit(self.capture_port)
                self.logger.info(f"Audio capture connected for media index {media_info.index}")
                self.loop.create_task(self.log_capture_stats())
            else:
                self.logger.error("Failed to register capture port")
                
        except Exception as e:
            self.logger.error(f"Error setting up audio media: {e}", exc_info=True)

    async def process_stt_tts_loop(self):
        """Process STT output, pass to LLM, and feed TTS result to media port."""
        while self.isActive():
            try:
                text = await self.stt_adapter.out_queue.get()
                self.logger.info(f"STT output: {text}")
                
                # Pass to LLM
                llm_response = phoneguy_reply(text)
                self.logger.info(f"LLM response: {llm_response}")
                
                # Generate TTS and update playback port
                await self.tts_adapter.speak(llm_response, self.playback_port)
                self.text_queue.put_nowait(llm_response)
            except Exception as e:
                self.logger.error(f"Error in STT-TTS loop: {e}")
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
                self.logger.error(f"Error processing audio capture: {e}")
            await asyncio.sleep(0.02)

    async def log_capture_stats(self):
        """Log capture statistics periodically."""
        while not self._stop_capture and self.isActive():
            try:
                if self.capture_port:
                    stats = self.capture_port.get_stats()
                    if stats['frames_captured'] > 0:
                        self.logger.info(
                            f"Audio Capture Stats: Captured={stats['frames_captured']}, "
                            f"Dropped={stats['frames_dropped']}, Errors={stats['errors']}, "
                            f"Queue={stats['queue_size']}/{stats['queue_max_size']}"
                        )
                        self.capture_port.reset_stats()
            except Exception as e:
                self.logger.error(f"Error logging capture stats: {e}")
            await asyncio.sleep(30)


def main():
    """Main entry point."""
    with open("config.json", "r") as f:
        config = json.load(f)

    # Create asyncio event loop
    loop = asyncio.new_event_loop()
    def _run_loop(loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()
    loop_thread = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    loop_thread.start()

    # Initialize adapters
    stt_adapter = STTAdapter(config, logging.getLogger("STT"))
    tts_adapter = TTSAdapter(config, logging.getLogger("TTS"))

    # Create VoIP client
    bot = VoIPClient(config, logging.getLogger("VoIPClient"))
    
    if not bot.initialize():
        logging.error("Failed to initialize VoIP client")
        sys.exit(1)
    
    if not bot.start():
        logging.error("Failed to start VoIP client")
        sys.exit(1)

    logging.info("PJSUA2 started")

    # Create account
    if not bot.create_account(
        MainAccount, 
        stt_adapter=stt_adapter, 
        tts_adapter=tts_adapter, 
        loop=loop,
        config=config
    ):
        logging.error("Failed to create account")
        sys.exit(1)

    # Check TTS health
    try:
        fut = asyncio.run_coroutine_threadsafe(tts_adapter.check_health(), loop)
        ready = fut.result(timeout=15)
        if not ready:
            logging.warning("TTS engine not ready; audio responses may be skipped.")
    except Exception as e:
        logging.error(f"TTS health check error: {e}")

    logging.info("SIP client initialized. Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(0.1)
            
            # Process hangup queue for current call
            account = bot.get_account()
            if account:
                call = account.get_current_call()
                if call:
                    call.process_hangup_queue()
                    
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        logging.info("Cleaning up...")
        if bot:
            bot.destroy()


if __name__ == "__main__":
    main()
