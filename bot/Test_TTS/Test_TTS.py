#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import time
import asyncio
import logging
import pjsua2 as pj
from Libs.audio import AudioPlaybackPort  # Для TTS
from Libs.tts_adapter import TTSAdapter
from Libs.llm_adapter import phoneguy_reply, reset_conversation_history
import wave

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
        self.pre_generated_samples = {}

    def onRegState(self, prm):
        info = self.getInfo()
        logging.info(f"Account registration: {info.regIsActive} ({prm.code} {prm.reason})")

    def onIncomingCall(self, prm):
        """Упрощённая логика приёма входящего звонка."""
        call = MyCall(self, prm.callId, self.ep, tts_adapter=self.tts_adapter, loop=self.loop)
        calls.append(call)  # Keep strong reference to prevent GC
        self.current_call = call
        ci = call.getInfo()
        logging.info(f"🎧 INCOMING CALL from {ci.remoteUri}")
        
        # Немедленно отвечаем на звонок для минимизации задержки
        logging.info("📞 Немедленно отвечаем на звонок...")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        call.answer(prm)
        logging.info("✅ Звонок принят")
        
        # Запускаем генерацию голоса после ответа на звонок
        self.loop.create_task(self.handle_call_after_answer(call))

    async def handle_call_after_answer(self, call):
        """Обработка звонка после ответа."""
        try:
            # Проверяем готовность TTS сервера
            tts_ready = await self.tts_adapter.check_health()
            if not tts_ready:
                logging.warning("⚠️ TTS сервер недоступен, используем предварительные сэмплы")
                await self.use_pre_generated_voice(call)
                return

            # Генерируем текст приветствия
            logging.info("🤖 Генерируем текст приветствия...")
            greeting_prompt = "A person is calling you. Please greet them warmly and introduce yourself as an AI assistant. Ask how you can help them today."
            greeting_text = phoneguy_reply(greeting_prompt)
            logging.info(f"📝 Сгенерирован текст: '{greeting_text}'")

            # Создаем медиа-порт для TTS
            media_port = AudioPlaybackPort(sample_rate=8000, logger=logging.getLogger("AudioPlayback"))
            if not media_port.register_with_conf(self.ep):
                logging.error("❌ Не удалось создать медиа-порт")
                await self.use_pre_generated_voice(call)
                return

            logging.info(f"✅ Медиа-порт создан: ID={media_port.conf_port_id}")

            # Генерируем и воспроизводим голос
            logging.info("🔊 Генерируем голос...")
            try:
                await self.tts_adapter.speak(greeting_text, media_port)
                logging.info("✅ Голос сгенерирован и воспроизводится")
                logging.info("⏳ Ожидаем готовности медиапотока...")
                try:
                    await asyncio.wait_for(call.media_ready.wait(), timeout=10)
                    logging.info("✅ Медиапоток готов!")
                except asyncio.TimeoutError:
                    logging.error("❌ Таймаут ожидания медиапотока")
                    return
            except Exception as e:
                logging.error(f"❌ Ошибка генерации голоса: {e}")
                await self.use_pre_generated_voice(call)
                return

            # Подключаем медиа-порт к аудио потоку звонка
            try:
                try:
                    audio_media = call.getAudioMedia(0)
                except Exception:
                    audio_media = call.getMedia(0)
                media_port.startTransmit(audio_media)
                logging.info("✅ Медиа-порт подключен к аудио потоку")
            except Exception as e:
                logging.error(f"❌ Ошибка подключения медиа-порта: {e}")
                # Fallback: синтезируем PCM и проигрываем через AudioMediaPlayer
                try:
                    pcm = await self.tts_adapter.synthesize(greeting_text)
                    if pcm:
                        temp_wav = "temp_tts_fallback.wav"
                        with wave.open(temp_wav, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(8000)
                            wf.writeframes(pcm)
                        player = pj.AudioMediaPlayer()
                        player.createPlayer(temp_wav, 0)
                        player.startTransmit(audio_media)
                        logging.info("✅ Fallback AudioMediaPlayer запущен")
                except Exception as pe:
                    logging.error(f"❌ Fallback проигрывание не удалось: {pe}")
                    await self.use_pre_generated_voice(call)
                return
            
            # Ждем завершения воспроизведения
            greeting_duration = len(greeting_text.split()) * 0.5 + 2
            logging.info(f"⏳ Ждем {greeting_duration:.1f} секунд для завершения приветствия...")
            await asyncio.sleep(greeting_duration)

            # Завершаем звонок после приветствия
            if call.isActive():
                logging.info("📞 Завершаем звонок после приветствия...")
                prm = pj.CallOpParam()
                prm.statusCode = pj.PJSIP_SC_OK
                call.hangup(prm)
                logging.info("✅ Звонок завершен")
                
        except Exception as e:
            logging.error(f"❌ Ошибка обработки звонка: {e}")
            if call.isActive():
                prm = pj.CallOpParam()
                prm.statusCode = pj.PJSIP_SC_INTERNAL_SERVER_ERROR
                call.hangup(prm)

    async def use_pre_generated_voice(self, call):
        """Использование предварительно сгенерированного голоса как резерв."""
        try:
            logging.info("📦 Используем предварительно сгенерированный голос...")
            
            # Проверяем доступность предварительных сэмплов
            if not self.pre_generated_samples:
                logging.error("❌ Нет предварительно сгенерированных сэмплов!")
                return
            
            # Выбираем лучший сэмпл для использования
            best_sample = None
            if 'main_greeting' in self.pre_generated_samples:
                best_sample = self.pre_generated_samples['main_greeting']
                logging.info("✅ Используем основное предварительно сгенерированное приветствие")
            else:
                # Используем первый доступный сэмпл с наибольшим размером данных
                best_sample = max(self.pre_generated_samples.values(), key=lambda x: x.get('length', 0))
                logging.info(f"✅ Используем предварительно сгенерированный сэмпл: {best_sample.get('length', 0)} байт")
            
            if not best_sample or not best_sample.get('pcm_data'):
                logging.error("❌ Выбранный сэмпл пустой или повреждён")
                return
            
            # Создаем медиа-порт для предварительного голоса
            media_port = AudioPlaybackPort(sample_rate=8000, logger=logging.getLogger("AudioPlayback"))
            if not media_port.register_with_conf(self.ep):
                logging.error("❌ Не удалось создать медиа-порт для предварительного голоса")
                return
            
            # Загружаем PCM данные в медиа-порт
            media_port.update_playback_data(best_sample['pcm_data'])
            logging.info(f"✅ PCM данные загружены в медиа-порт: {len(best_sample['pcm_data'])} байт")
            
            # Подключаем медиа-порт к аудио потоку звонка
            try:
                audio_media = call.getAudioMedia(-1)
                media_port.startTransmit(audio_media)
                logging.info("✅ Медиа-порт подключен к аудио потоку")
                
                # Ждем завершения воспроизведения
                greeting_duration = len(best_sample['text'].split()) * 0.5 + 2
                logging.info(f"⏳ Ждем {greeting_duration:.1f} секунд для завершения приветствия...")
                await asyncio.sleep(greeting_duration)
                
            except Exception as e:
                logging.error(f"❌ Ошибка подключения медиа-порта: {e}")
                return
                
        except Exception as e:
            logging.error(f"❌ Ошибка использования предварительного голоса: {e}")

class MyCall(pj.Call):
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, ep=None, tts_adapter=None, loop=None):
        super().__init__(acc, call_id)
        self.ep = ep
        self.loop = loop
        self.tts_adapter = tts_adapter
        self.media_ready = asyncio.Event()

    def onCallState(self, prm):
        ci = self.getInfo()
        logging.info(f"📞 Call state: {ci.stateText}")
        
        if ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            logging.info("🎉 Call CONFIRMED! Setting up media...")
            # Устанавливаем событие готовности медиапотока
            self.media_ready.set()
            logging.info("✅ Media ready event set")
            
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            logging.info("📞 Call disconnected")
            self.media_ready.clear()

    def onCallMediaState(self, prm):
        logging.info("🎵 ENTERING onCallMediaState")
        ci = self.getInfo()
        logging.info(f"🎵 Media state info: media count={len(ci.media)}")
        
        if not ci.media:
            logging.warning("🎵 No media found in call info")
            return
            
        for i, mi in enumerate(ci.media):
            logging.info(f"🎵 Media {i}: type={mi.type}, status={mi.status}")
            
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                logging.info("🎵 Audio media is ACTIVE - signaling media ready!")
                self.media_ready.set()
                break
                
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

        config = {
            "tts": {
                "engine": "turbo",
                "device": "cpu",
                "audio_prompt_path": "/home/user/Test_Phone/voices/PhoneGuy_FNAF1_01.wav",
                "rvc_enabled": True,
                "rvc_model_path": "/home/user/Test_Phone/models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth",
                "rvc_index_path": "/home/user/Test_Phone/models/RVC/PhoneGuyFNAF1/added_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index",
                "rvc_index_rate": 0.5,
                "rvc_f0_method": "rmvpe"
            }
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
            
            # Сохраняем сэмплы в аккаунте
            self.account.pre_generated_samples = {}
            
            for i, text in enumerate(sample_texts):
                try:
                    logging.info(f"🎯 Генерируем сэмпл {i+1}/{len(sample_texts)}: '{text[:50]}...'")
                    
                    # Создаем временный медиа-порт для генерации
                    temp_port = AudioPlaybackPort(sample_rate=8000, logger=logging.getLogger("AudioPlayback"))
                    if not temp_port.register_with_conf(self.ep):
                        logging.error(f"❌ Не удалось создать медиа-порт для сэмпла {i+1}")
                        continue
                    
                    # Генерируем голос
                    await self.tts_adapter.speak(text, temp_port)
                    
                    # Сохраняем результат
                    pcm_data = getattr(temp_port, 'pcm_data', b'')
                    if len(pcm_data) > 0:
                        self.account.pre_generated_samples[f"sample_{i}"] = {
                            'text': text,
                            'pcm_data': pcm_data,
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
            main_port = AudioPlaybackPort(sample_rate=8000, logger=logging.getLogger("AudioPlayback"))
            if not main_port.register_with_conf(self.ep):
                logging.error("❌ Не удалось создать порт для основного приветствия")
            else:
                await self.tts_adapter.speak(main_text, main_port)
                pcm_main = getattr(main_port, 'pcm_data', b'')
                
                if len(pcm_main) > 0:
                    self.account.pre_generated_samples['main_greeting'] = {
                        'text': main_text,
                        'pcm_data': pcm_main,
                        'length': len(pcm_main)
                    }
                    logging.info(f"✅ Основное приветствие готово: {len(pcm_main)} байт")
                else:
                    logging.warning("⚠️ Основное приветствие пустое")
            
            total_samples = len(self.account.pre_generated_samples)
            total_size = sum(sample['length'] for sample in self.account.pre_generated_samples.values())
            
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
            
            # Clean up pre-generated samples from account
            if self.account and hasattr(self.account, 'pre_generated_samples'):
                logging.info(f"🧹 Очищаем {len(self.account.pre_generated_samples)} предварительно сгенерированных сэмплов")
                self.account.pre_generated_samples.clear()
            
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
    if "--tts-only" in sys.argv:
        async def tts_only():
            config = {
                "tts": {
                    "engine": "turbo",
                    "device": "cpu",
                    "audio_prompt_path": "voices/PhoneGuy_FNAF1_01.wav",
                    "rvc_enabled": True,
                    "rvc_model_path": "models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth",
                    "rvc_index_path": "models/RVC/PhoneGuyFNAF1/added_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index",
                    "rvc_index_rate": 0.5,
                    "rvc_f0_method": "rmvpe"
                }
            }
            tts = TTSAdapter(config, logging.getLogger("TTS"))
            ok = await tts.check_health()
            if not ok:
                logging.error("TTS health check failed")
                return
            text = "Hello, this is a test of the voice."
            pcm = await tts.synthesize(text)
            if not pcm:
                logging.error("No PCM data generated")
                return
            with wave.open("output.wav", "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(pcm)
            logging.info("Wrote output.wav")
        asyncio.run(tts_only())
        sys.exit(0)
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <domain> <user> <password> [sip:target@domain] [--tts-only]")
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
