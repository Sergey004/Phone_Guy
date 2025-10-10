#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import logging
import pjsua2 as pj
import threading
import queue
import asyncio
import os
from Libs.rtp_streamer import ByteStreamMediaPort  # Для TTS
from Libs.tts_adapter import TTSAdapter
# Use the local LLM adapter from Test_TTS folder
from Libs.llm_adapter import phoneguy_reply, reset_conversation_history

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S"
)

calls = []  # Global list to keep strong references to call objects

class MyAccount(pj.Account):
    def __init__(self, ep, tts_adapter, loop):
        super().__init__()
        self.ep = ep
        self.tts_adapter = tts_adapter
        self.loop = loop
        self.current_call = None

    def onRegState(self, prm):
        info = self.getInfo()
        logging.info(f"Account registration: {info.regIsActive} ({prm.code} {prm.reason})")

    async def immediate_voice_generation_and_answer(self, call):
        """МГНОВЕННЫЙ ответ на звонок с готовым голосом."""
        try:
            logging.info("⚡ МГНОВЕННЫЙ ответ на звонок - начинаем генерацию голоса!")
            
            # Сразу генерируем и отвечаем без задержки
            logging.info("🔍 Проверяем готовность TTS...")
            
            # Проверяем готовность TTS
            tts_ready = await self.tts_adapter.check_health()
            if not tts_ready:
                logging.warning("⚠️ TTS не готов, используем предварительно сгенерированный голос")
                await self.use_pre_generated_voice(call)
                return
            
            # Генерируем текст для ответа
            logging.info("🤖 Генерируем текст ответа...")
            greeting_prompt = "A person is calling you. Please greet them warmly and introduce yourself as an AI assistant. Ask how you can help them today."
            greeting_text = phoneguy_reply(greeting_prompt)
            logging.info(f"📝 Сгенерирован текст: '{greeting_text}'")
            
            # НЕМЕДЛЕННО создаем медиа-порт и генерируем голос
            logging.info("🔊 НЕМЕДЛЕННО создаем медиа-порт и генерируем голос...")
            
            # Создаем медиа-порт для TTS
            self.media_port = ByteStreamMediaPort(sample_rate=8000)
            self.media_port.register_with_conf(self.ep)
            
            if self.media_port.conf_port_id < 0:
                logging.error("❌ Не удалось создать медиа-порт")
                await self.use_pre_generated_voice(call)
                return
            
            logging.info(f"✅ Медиа-порт создан: ID={self.media_port.conf_port_id}")
            
            # МГНОВЕННО генерируем голос
            logging.info("🚀 МГНОВЕННО генерируем голос...")
            await self.tts_adapter.speak(greeting_text, self.media_port)
            
            # Проверяем результат
            pcm_length = len(getattr(self.media_port, 'pcm_data', b''))
            if pcm_length > 0:
                logging.info(f"✅ Голос сгенерирован: {pcm_length} байт")
                
                # Сразу сигнализируем о готовности
                self.media_ready.set()
                logging.info("✅ Голос готов, сигнализируем о готовности!")
                
                # НЕМЕДЛЕННО отвечаем на звонок
                if call.isActive():
                    prm = pj.CallOpParam()
                    prm.statusCode = 200
                    call.answer(prm)
                    logging.info("📞 Звонок принят мгновенно - голос готов!")
                else:
                    logging.warning("⚠️ Звонок стал неактивным")
            else:
                logging.warning("⚠️ Голос не сгенерировался, используем резервный вариант")
                await self.use_pre_generated_voice(call)
                
        except Exception as e:
            logging.error(f"❌ Ошибка мгновенной генерации: {e}")
            await self.use_pre_generated_voice(call)

    async def use_pre_generated_voice(self, call):
        """Использование предварительно сгенерированного голоса как резерв."""
        try:
            logging.info("📦 Используем предварительно сгенерированный голос...")
            
            # Проверяем, есть ли предварительно сгенерированные сэмплы
            if hasattr(self, 'pre_generated_samples') and self.pre_generated_samples:
                # Используем основное приветствие
                if 'main_greeting' in self.pre_generated_samples:
                    sample = self.pre_generated_samples['main_greeting']
                    self.media_port = sample['media_port']
                    self.media_ready.set()
                    logging.info("✅ Используем предварительно сгенерированное приветствие")
                else:
                    # Используем первый доступный сэмпл
                    first_sample = next(iter(self.pre_generated_samples.values()))
                    self.media_port = first_sample['media_port']
                    self.media_ready.set()
                    logging.info("✅ Используем предварительно сгенерированный сэмпл")
                
                # Отвечаем на звонок
                if call.isActive():
                    prm = pj.CallOpParam()
                    prm.statusCode = 200
                    call.answer(prm)
                    logging.info("📞 Звонок принят с предварительно сгенерированным голосом!")
                else:
                    logging.warning("⚠️ Звонок стал неактивным")
            else:
                logging.error("❌ Нет предварительно сгенерированных сэмплов!")
                # Отвечаем без голоса как последняя мера
                if call.isActive():
                    prm = pj.CallOpParam()
                    prm.statusCode = 200
                    call.answer(prm)
                    logging.warning("📞 Звонок принят без голоса (последняя мера)")
                    
        except Exception as e:
            logging.error(f"❌ Ошибка использования предварительного голоса: {e}")
            # Отвечаем без голоса
            if call.isActive():
                prm = pj.CallOpParam()
                prm.statusCode = 200
                call.answer(prm)
                logging.error("📞 Звонок принят без голоса из-за ошибки")

    async def generate_tts_in_background(self, text: str, call) -> bool:
        """Фоновая генерация TTS во время задержки."""
        try:
            logging.info("🚀 Фоновая генерация TTS начата...")
            logging.info(f"🚀 Текст для генерации: '{text[:50]}...'")
            
            # Создаем временный медиа-порт для фоновой генерации
            temp_media_port = ByteStreamMediaPort(sample_rate=8000)
            temp_media_port.register_with_conf(self.ep)
            
            if temp_media_port.conf_port_id < 0:
                logging.error("❌ Не удалось зарегистрировать временный TTS порт")
                return False
            
            logging.info(f"🚀 Временный TTS порт создан: ID={temp_media_port.conf_port_id}")
            
            # Генерируем голос асинхронно
            logging.info("🚀 Начинаем TTS синтез в фоне...")
            await self.tts_adapter.speak(text, temp_media_port)
            
            # Проверяем результат
            pcm_length = len(getattr(temp_media_port, 'pcm_data', b''))
            if pcm_length > 0:
                logging.info(f"✅ Фоновая генерация завершена: {pcm_length} байт PCM данных")
                
                # Сохраняем результат в атрибуте звонка для последующего использования
                call._pre_generated_audio = temp_media_port.pcm_data
                call._pre_generated_media_port = temp_media_port
                
                return True
            else:
                logging.warning("⚠️ Фоновая генерация завершилась без данных")
                return False
                
        except Exception as e:
            logging.error(f"❌ Ошибка в фоновой генерации TTS: {e}")
            import traceback
            logging.error(f"❌ TTS Background Traceback: {traceback.format_exc()}")
            return False

    def onIncomingCall(self, prm):
        call = MyCall(self, prm.callId, self.ep, tts_adapter=self.tts_adapter, loop=self.loop)
        calls.append(call)  # Keep strong reference to prevent GC
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"🎧 INCOMING CALL from {ci.remoteUri} - LLM+TTS voice generation will start!")
        
        # Немедленно запускаем генерацию голоса при входящем звонке
        logging.info("⚡ НЕМЕДЛЕННО запускаем генерацию голоса при входящем звонке!")
        self.loop.create_task(self.immediate_voice_generation_and_answer(call))

class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, ep=None, tts_adapter=None, loop=None):
        super().__init__(acc, call_id)
        self.ep = ep
        self.loop = loop
        self.media_port = None  # ByteStreamMediaPort for TTS
        self.timer = None
        self.hangup_queue = queue.Queue()
        self.tts_adapter = tts_adapter
        self.media_ready = asyncio.Event()

    async def wait_for_media_and_start(self):
        """Wait for media ready and trigger LLM+TTS test."""
        logging.info("🎤 ENTERING wait_for_media_and_start()")
        
        # Add timeout and alternative trigger mechanism
        max_wait_time = 10  # seconds
        check_interval = 0.5  # seconds
        elapsed_time = 0
        
        logging.info(f"⏳ Waiting for media ready (max {max_wait_time}s)...")
        
        while elapsed_time < max_wait_time:
            if self.media_ready.is_set():
                logging.info("✅ Media ready event received!")
                break
                
            # Check if media is already available
            try:
                ci = self.getInfo()
                for mi in ci.media:
                    if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                        logging.info("🎵 Found active audio media - triggering setup directly!")
                        # Set up media immediately if found active
                        self.onCallMediaState(None)  # Force media setup
                        if self.media_ready.is_set():
                            break
                        elapsed_time = max_wait_time  # Force exit after manual setup
                        break
            except Exception as e:
                logging.warning(f"⚠️ Error checking media during wait: {e}")
            
            await asyncio.sleep(check_interval)
            elapsed_time += check_interval
            logging.debug(f"⏳ Still waiting for media... {elapsed_time:.1f}s elapsed")
        
        if not self.media_ready.is_set():
            logging.error(f"❌ Media ready timeout after {max_wait_time}s - proceeding with fallback")
            # Try to set up media anyway as fallback
            try:
                self.onCallMediaState(None)
            except Exception as e:
                logging.error(f"❌ Fallback media setup failed: {e}")
                prm = pj.CallOpParam()
                prm.statusCode = pj.PJSIP_SC_INTERNAL_SERVER_ERROR
                self.hangup(prm)
                return
            
        logging.info("🎤 Media ready, starting LLM+TTS voice generation")
        
        # Validate media port is still available
        if not self.media_port:
            logging.error("❌ TTS media port is None")
            prm = pj.CallOpParam()
            prm.statusCode = pj.PJSIP_SC_INTERNAL_SERVER_ERROR
            self.hangup(prm)
            return
            
        if self.media_port.conf_port_id < 0:
            logging.error(f"❌ TTS media port ID invalid: {self.media_port.conf_port_id}")
            prm = pj.CallOpParam()
            prm.statusCode = pj.PJSIP_SC_INTERNAL_SERVER_ERROR
            self.hangup(prm)
            return
            
        logging.info(f"✅ TTS media port validated: ID={self.media_port.conf_port_id}")
        
        # Direct connect: TTS port → call media
        try:
            audio_media = self.getAudioMedia(-1)
            logging.info(f"Connecting TTS port (ID={self.media_port.conf_port_id}) to audio media (ID={audio_media.getPortId()})")
            
            # Use the audio media port ID directly (more reliable approach)
            audio_port_id = audio_media.getPortId()
            if audio_port_id < 0:
                logging.error("Invalid audio media port ID")
                raise RuntimeError("Audio media port invalid")
                
            # Connect TTS port to audio media
            self.media_port.startTransmit(audio_media)
            logging.info("Direct transmit: TTS port → audio media")
            
        except Exception as e:
            logging.error(f"Failed to connect TTS port to audio media: {e}")
            prm = pj.CallOpParam()
            prm.statusCode = pj.PJSIP_SC_INTERNAL_SERVER_ERROR
            self.hangup(prm)
            return
        
        # Generate voice response using LLM+TTS
        logging.info("🤖 GENERATING VOICE RESPONSE via LLM+TTS for incoming call...")
        
        # Generate greeting message for the caller using LLM
        greeting_prompt = "A person is calling you. Please greet them warmly and introduce yourself as an AI assistant. Ask how you can help them today."
        greeting_text = phoneguy_reply(greeting_prompt)
        logging.info(f"🗣️ LLM generated GREETING: '{greeting_text}'")
        
        # TTS synthesize and play the greeting to the caller
        try:
            logging.info("🔊 CONVERTING LLM greeting to speech for caller...")
            logging.info(f"🎵 TTS Media Port Status: conf_port_id={self.media_port.conf_port_id}, position={self.media_port.position}")
            logging.info(f"🎵 TTS Adapter Status: {self.tts_adapter}")
            logging.info(f"🎵 TTS Config: {getattr(self.tts_adapter, 'base_url', 'unknown')}")
            
            # Детальное логирование процесса TTS
            logging.info("🎵 Начинаем TTS синтез...")
            await self.tts_adapter.speak(greeting_text, self.media_port)
            
            # Проверяем результат после TTS
            pcm_data_length = len(getattr(self.media_port, 'pcm_data', b''))
            logging.info(f"🎵 После TTS: PCM данные = {pcm_data_length} байт")
            
            if pcm_data_length > 0:
                logging.info("✅ TTS voice GREETING completed successfully!")
                logging.info(f"🎵 Final TTS Media Port Status: position={self.media_port.position}/{pcm_data_length}")
            else:
                logging.warning("⚠️ TTS завершился, но PCM данные пустые!")
                
        except Exception as e:
            logging.error(f"❌ TTS voice greeting failed: {e}")
            logging.error(f"❌ TTS Error Details: {type(e).__name__}: {str(e)}")
            import traceback
            logging.error(f"❌ TTS Traceback: {traceback.format_exc()}")
        
        # Keep call alive for interaction (extended duration for potential conversation)
        greeting_duration = len(greeting_text.split()) * 0.5 + 5  # Calculate greeting duration + buffer
        logging.info(f"⏳ Keeping call alive for {greeting_duration:.1f} seconds after voice greeting...")
        await asyncio.sleep(greeting_duration)
        
        # For now, hang up after the greeting (future: add interactive conversation)
        if self.isActive():
            logging.info("📞 Hanging up call after LLM+TTS voice greeting...")
            prm = pj.CallOpParam()
            prm.statusCode = pj.PJSIP_SC_OK
            self.hangup(prm)
            logging.info("✅ Call completed successfully with LLM+TTS VOICE GENERATION!")

    async def log_media_stats(self):
        """Log media stats periodically."""
        while self.isActive():
            try:
                ci = self.getInfo()
                for mi in ci.media:
                    if mi.type == pj.PJMEDIA_TYPE_AUDIO:
                        try:
                            rx = mi.rxLevel if hasattr(mi, 'rxLevel') else 'N/A'
                            tx = mi.txLevel if hasattr(mi, 'txLevel') else 'N/A'
                        except AttributeError:
                            rx = tx = 'N/A'
                        logging.debug(f"Media stats: index={mi.index}, status={mi.status}, rx={rx}, tx={tx}")
                await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"Media stats error: {e}")
                break

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"📞 Call state: {ci.stateText}, last status: {ci.lastStatusCode}, reason: {ci.lastReason}")
        
        if ci.state == pj.PJSIP_INV_STATE_CALLING:
            logging.info("📞 Call state: CALLING")
        elif ci.state == pj.PJSIP_INV_STATE_INCOMING:
            logging.info("📞 Call state: INCOMING")
        elif ci.state == pj.PJSIP_INV_STATE_EARLY:
            logging.info("📞 Call state: EARLY")
        elif ci.state == pj.PJSIP_INV_STATE_CONNECTING:
            logging.info("📞 Call state: CONNECTING")
        elif ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            logging.info("🎉 Call CONFIRMED! Setting up media and voice generation...")
            try:
                # Start the voice generation process
                future = asyncio.run_coroutine_threadsafe(self.wait_for_media_and_start(), self.loop)
                logging.info("✅ Voice generation coroutine scheduled successfully")
                
                # Also start media stats logging
                asyncio.run_coroutine_threadsafe(self.log_media_stats(), self.loop)
                logging.info("✅ Media stats coroutine scheduled successfully")
                
            except Exception as e:
                logging.error(f"❌ Failed to schedule voice generation: {e}")
                # Try to hang up the call if we can't proceed
                try:
                    prm = pj.CallOpParam()
                    prm.statusCode = pj.PJSIP_SC_INTERNAL_SERVER_ERROR
                    self.hangup(prm)
                except Exception as hangup_e:
                    logging.error(f"❌ Failed to hang up call after error: {hangup_e}")
                    
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("📞 Call disconnected")
            if self.media_port:
                self.media_port = None
            if self.timer:
                self.timer.cancel()
                self.timer = None
        else:
            logging.info(f"📞 Call state: {ci.stateText} (unhandled state)")

    def onCallMediaState(self, prm):
        logging.info("🎵 ENTERING onCallMediaState")
        ci = self.getInfo()
        logging.info(f"🎵 Media state info: media count={len(ci.media)}")
        
        if not ci.media:
            logging.warning("🎵 No media found in call info")
            return
            
        for i, mi in enumerate(ci.media):
            logging.info(f"🎵 Media {i}: type={mi.type}, status={mi.status}, index={mi.index}")
            
            if mi.type == pj.PJMEDIA_TYPE_AUDIO:
                logging.info(f"🎵 Audio media {i} found with status={mi.status}")
                
                if mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    logging.info("🎵 Audio media is ACTIVE - proceeding with setup!")
                    try:
                        logging.info(f"🎵 Getting audio media for index {mi.index}...")
                        audio_media = self.getAudioMedia(mi.index)
                        audio_port_id = audio_media.getPortId()
                        logging.info(f"🎵 Got audio media, port ID: {audio_port_id}")
                        
                        if audio_port_id < 0:
                            logging.error(f"❌ Invalid audio media port ID: {audio_port_id}")
                            continue
                            
                        # Setup TTS port only
                        logging.info("🎵 Creating ByteStreamMediaPort for TTS...")
                        self.media_port = ByteStreamMediaPort(sample_rate=8000)
                        logging.info("🎵 ByteStreamMediaPort created, now registering with conference...")
                        
                        # Try to register with better error handling
                        try:
                            self.media_port.register_with_conf(self.ep)
                            logging.info(f"🎵 TTS port registered, conf port ID: {self.media_port.conf_port_id}")
                            
                            # Validate TTS port registration
                            if self.media_port.conf_port_id < 0:
                                logging.error(f"❌ TTS port registration failed, ID: {self.media_port.conf_port_id}")
                                raise RuntimeError("TTS port registration failed")
                            
                            logging.info("✅ TTS port successfully created and registered!")
                            logging.info("🎵 Setting media_ready event to trigger voice generation...")
                            self.media_ready.set()  # Signal ready
                            logging.info("✅ Media ready event set - voice generation should start now!")
                            
                            # Break after successful setup of first active audio media
                            break
                            
                        except Exception as reg_e:
                            logging.error(f"❌ TTS port registration failed: {reg_e}")
                            # Don't clean up here - let the calling code handle it
                            raise  # Re-raise to be handled by caller
                            
                    except Exception as e:
                        logging.error(f"❌ Error in media setup for media {i}: {e}")
                        # Only clean up if we're not in fallback mode
                        if self.media_port and "fallback" not in str(e).lower():
                            self.media_port = None
                        logging.error(f"❌ Media setup failed for media {i}, trying next if available...")
                        # Re-raise to be handled by caller
                        raise
                        
                elif mi.status == pj.PJSUA_CALL_MEDIA_NONE:
                    logging.info(f"🎵 Audio media {i} status: NONE (not active yet)")
                elif mi.status == pj.PJSUA_CALL_MEDIA_LOCAL_HOLD:
                    logging.info(f"🎵 Audio media {i} status: LOCAL_HOLD")
                elif mi.status == pj.PJSUA_CALL_MEDIA_REMOTE_HOLD:
                    logging.info(f"🎵 Audio media {i} status: REMOTE_HOLD")
                else:
                    logging.info(f"🎵 Audio media {i} status: {mi.status} (other)")
            else:
                logging.info(f"🎵 Media {i} is not audio (type: {mi.type})")
        
        logging.info("🎵 EXITING onCallMediaState")

class VoIPBot:
    def __init__(self, sip_domain, sip_user, sip_pass, local_ip="192.168.1.181"):
        logging.info(f"Starting LLM+TTS VoIPBot for {sip_user}@{sip_domain}")
        self.ep = pj.Endpoint()
        self.account = None

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

        # Config for TTS
        config = {
            "tts": {"api_key": "your_super_secret_api_key", "base_url": "http://localhost:8000/v1"}
        }
        self.tts_adapter = TTSAdapter(config, logging.getLogger("TTS"))

        loop = asyncio.get_event_loop()
        if not loop.run_until_complete(self.tts_adapter.check_health()):
            logging.error("TTS server unavailable. Calls may proceed without audio.")

        # Account (no STT)
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f"sip:{sip_user}@{sip_domain}"
        acc_cfg.regConfig.registrarUri = f"sip:{sip_domain}"
        acc_cfg.sipConfig.authCreds.append(pj.AuthCredInfo("digest", "*", sip_user, 0, sip_pass))
        self.account = MyAccount(self.ep, self.tts_adapter, loop)
        self.account.create(acc_cfg)
        
        # Предварительная генерация голосовых сэмплов
        logging.info("🎯 Запускаем предварительную генерацию голосовых сэмплов...")
        loop.create_task(self.pre_generate_voice_samples())

    def make_call(self, uri):
        call = MyCall(self.account, ep=self.ep, tts_adapter=self.tts_adapter, loop=self.account.loop)
        calls.append(call)  # Keep strong reference
        prm = pj.CallOpParam(True)
        call.makeCall(uri, prm)
        self.account.current_call = call

    async def pre_generate_voice_samples(self):
        """Предварительная генерация голосовых сэмплов для ускорения ответа на звонки."""
        try:
            logging.info("🎯 Начинаем предварительную генерацию голосовых сэмпров...")
            
            # Проверяем готовность TTS сервера
            if not await self.tts_adapter.check_health():
                logging.error("❌ TTS сервер не готов для предварительной генерации")
                return
            
            # Генерируем несколько стандартных фраз заранее
            sample_texts = [
                "Hello! This is your AI assistant. How can I help you today?",
                "Hi there! Welcome to our service. What can I do for you?",
                "Good day! I'm here to assist you. Please go ahead with your question.",
                "Hello and welcome! I'm ready to help you with anything you need.",
                "Hi! Thank you for calling. I'm your AI assistant, how may I assist you?"
            ]
            
            self.pre_generated_samples = {}
            
            for i, text in enumerate(sample_texts):
                try:
                    logging.info(f"🎯 Генерируем сэмпл {i+1}/{len(sample_texts)}: '{text[:50]}...'")
                    
                    # Создаем временный медиа-порт для генерации
                    temp_port = ByteStreamMediaPort(sample_rate=8000)
                    temp_port.register_with_conf(self.ep)
                    
                    if temp_port.conf_port_id < 0:
                        logging.error(f"❌ Не удалось создать медиа-порт для сэмпла {i+1}")
                        continue
                    
                    # Генерируем голос
                    await self.tts_adapter.speak(text, temp_port)
                    
                    # Сохраняем результат
                    pcm_data = getattr(temp_port, 'pcm_data', b'')
                    if len(pcm_data) > 0:
                        self.pre_generated_samples[f"sample_{i}"] = {
                            'text': text,
                            'pcm_data': pcm_data,
                            'media_port': temp_port,
                            'length': len(pcm_data)
                        }
                        logging.info(f"✅ Сэмпл {i+1} готов: {len(pcm_data)} байт")
                    else:
                        logging.warning(f"⚠️ Сэмпл {i+1} пустой")
                        
                except Exception as e:
                    logging.error(f"❌ Ошибка при генерации сэмпла {i+1}: {e}")
                    continue
            
            # Генерируем основное приветствие для входящих звонков
            logging.info("🎯 Генерируем основное приветствие для входящих звонков...")
            main_greeting = "A person is calling you. Please greet them warmly and introduce yourself as an AI assistant. Ask how you can help them today."
            
            main_text = phoneguy_reply(main_greeting)
            logging.info(f"🎯 Основное приветствие: '{main_text}'")
            
            # Создаем порт для основного приветствия
            main_port = ByteStreamMediaPort(sample_rate=8000)
            main_port.register_with_conf(self.ep)
            
            if main_port.conf_port_id >= 0:
                await self.tts_adapter.speak(main_text, main_port)
                pcm_main = getattr(main_port, 'pcm_data', b'')
                
                if len(pcm_main) > 0:
                    self.pre_generated_samples['main_greeting'] = {
                        'text': main_text,
                        'pcm_data': pcm_main,
                        'media_port': main_port,
                        'length': len(pcm_main)
                    }
                    logging.info(f"✅ Основное приветствие готово: {len(pcm_main)} байт")
                else:
                    logging.warning("⚠️ Основное приветствие пустое")
            else:
                logging.error("❌ Не удалось создать порт для основного приветствия")
            
            total_samples = len(self.pre_generated_samples)
            total_size = sum(sample['length'] for sample in self.pre_generated_samples.values())
            
            logging.info(f"🎯 Предварительная генерация завершена!")
            logging.info(f"🎯 Сгенерировано сэмплов: {total_samples}")
            logging.info(f"🎯 Общий размер данных: {total_size} байт")
            logging.info(f"🎯 Система готова к быстрому ответу на звонки!")
            
        except Exception as e:
            logging.error(f"❌ Ошибка в предварительной генерации: {e}")
            import traceback
            logging.error(f"❌ Pre-generation Traceback: {traceback.format_exc()}")

    def destroy(self):
        logging.info("Cleaning up...")
        global calls
        try:
            # Hang up all active calls
            for call in calls[:]:
                if call.isActive():
                    try:
                        call.hangup(pj.CallOpParam())
                        logging.info(f"Hung up call {call.getId()}")
                        time.sleep(0.1)
                    except Exception as e:
                        logging.error(f"Error hanging up call {call.getId()}: {e}")
            calls.clear()
            
            # Clean up pre-generated samples
            if hasattr(self, 'pre_generated_samples'):
                logging.info(f"🧹 Очищаем {len(self.pre_generated_samples)} предварительно сгенерированных сэмплов")
                for key, sample in self.pre_generated_samples.items():
                    if 'media_port' in sample and sample['media_port']:
                        try:
                            # Clean up media ports if needed
                            sample['media_port'] = None
                        except Exception as e:
                            logging.warning(f"⚠️ Ошибка при очистке сэмпла {key}: {e}")
                self.pre_generated_samples.clear()
            
            # Delete account
            if self.account:
                self.account.delete()
                self.account = None
                logging.info("Account deleted")
                time.sleep(0.1)
            # Destroy endpoint
            self.ep.libDestroy()
            logging.info("PJSUA2 endpoint destroyed")
            reset_conversation_history()
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain]")
        sys.exit(1)

    domain, user, passwd = sys.argv[1:4]
    
    bot = VoIPBot(domain, user, passwd)

    if len(sys.argv) > 4:
        target = sys.argv[4]
        bot.make_call(target)

    logging.info("Ready. Waiting for calls (LLM+TTS test on incoming)...")
    
    try:
        loop = asyncio.get_event_loop()
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("\nShutting down...")
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            bot.destroy()
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")
