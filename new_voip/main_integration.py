import asyncio
import logging
import os
from dotenv import load_dotenv

# Импортируем "слонов"
from stt_adapter import STTAdapter
from tts_adapter import TTSAdapter
from ai_service import phoneguy_reply

# Импортируем нашу сеть и мост
from sip_rtp_client import SIPClient
from bridge import PhoneBridgePort

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PhoneBot")

# Конфиг для адаптеров (заглушка, подставьте свои значения)
MOCK_CONFIG = {
    'stt': {
        'model': 'tiny',       # faster-whisper model
        'device': 'cuda',       # или cuda
        'energy_threshold': 500,
        'target_sample_rate': 16000,
        'language': 'en'
    },
    'tts': {
        'engine': 'turbo',
        'device': 'cuda',      # или cpu
        'language_id': 'en',
        'audio_prompt_path': "/home/user/Test_Phone_new/models/RVC/PhoneGuyFNAF1/PhoneGuy_FNAF1_01.wav",
          # === Настройки RVC ===
        'rvc_enabled': True,
        'rvc_model_path': '/home/user/Test_Phone_new/models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth',
        'rvc_index_path': '/home/user/Test_Phone_new/models/RVC/PhoneGuyFNAF1/added_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index', # Если есть
        'rvc_f0_method': 'rmvpe',
        'rvc_pitch_shift': 0,
        'rvc_index_rate': 0.6 
    }
}

# SIP Настройки
SIP_USER = "555533"
SIP_PASS = "Test1234"
SIP_SERVER = "192.168.1.176"
LOCAL_IP = "192.168.1.181"
TARGET_NUMBER = "1001"

async def generate_greeting(tts: TTSAdapter, bridge: PhoneBridgePort):
    """
    Бот генерирует приветствие первым, инициируя разговор.
    """
    logger.info("👋 Generating initial greeting...")
    
    # Пауза, чтобы юзер поднес телефон к уху
    await asyncio.sleep(2.0)

    # === СЦЕНАРИЙ ДЛЯ ПЕРВОЙ ФРАЗЫ ===
    # Мы говорим LLM, что именно сейчас происходит.
    # Это "скрытая режиссерская указание".
    scenario_prompt = (
        "CONTEXT: You just called the new night guard (the user). "
        "TASK: Start the call with your signature stuttering greeting ('Uh, hello, hello?'). "
        "Then, briefly say you wanted to record a message for him to help him get settled in on his first night. "
        "Keep it under 20 words. Be nervous."
    )
    
    logger.info("🤔 AI thinking about greeting...")
    # Отправляем этот сценарий в мозг
    greeting_text = await asyncio.to_thread(phoneguy_reply, scenario_prompt)
    logger.info(f"🤖 Initial Greeting: {greeting_text}")

    # Озвучиваем
    await tts.speak(greeting_text, media_port=bridge)

async def conversation_loop(stt: STTAdapter, tts: TTSAdapter, bridge: PhoneBridgePort):
    """Главный цикл разговора"""
    logger.info("🟢 Bot is listening...")
    
    # Запускаем обработку очереди фреймов STT
    asyncio.create_task(stt.consume_frame_queue())

    while True:
        # 1. Ждем текст от STT
        user_text = await stt.out_queue.get()
        logger.info(f"🗣️ User said: {user_text}")

        if not user_text: 
            continue

        # 2. Отправляем в LLM (в отдельном потоке, т.к. может быть медленно)
        logger.info("🤔 Thinking...")
        ai_reply = await asyncio.to_thread(phoneguy_reply, user_text)
        logger.info(f"🤖 AI Reply: {ai_reply}")

        # 3. Синтезируем речь (TTS)
        # Метод speak сам вызовет bridge.update_playback_data
        await tts.speak(ai_reply, media_port=bridge)
        
        # RTP сам заберет данные из bridge.buffer, когда они появятся

async def main():
    load_dotenv()
    
    # 1. Инициализация Компонентов
    logger.info("Initializing AI Engines...")
    bridge = PhoneBridgePort()
    
    # STT (передаем media_port=None, т.к. мы будем кормить его вручную из RTP)
    stt = STTAdapter(MOCK_CONFIG, logger)
    
    # TTS
    tts = TTSAdapter(MOCK_CONFIG, logger)
    if not await tts.check_health():
        logger.error("TTS Failed to initialize")
        return

    # 2. Инициализация SIP
    # Передаем stt в клиент, чтобы RTP скармливал ему входящий звук
    client = SIPClient(SIP_USER, SIP_PASS, SIP_SERVER, LOCAL_IP, stt_adapter=stt)
    client.set_audio_source(bridge) # RTP берет звук из моста (куда пишет TTS)

    # Запуск SIP транспорта
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: client,
        local_addr=('0.0.0.0', 5060)
    )

    try:
        # 3. Регистрация и Звонок
        await client.register()
        await asyncio.sleep(1)

        if client.registered:
            logger.info(f"Calling {TARGET_NUMBER}...")
            await client.invite(TARGET_NUMBER)
            
            # Запускаем цикл разговора параллельно
            greeting_task = asyncio.create_task(generate_greeting(tts, bridge))
            conversation_task = asyncio.create_task(conversation_loop(stt, tts, bridge))
            
            # Держим соединение (в реальном коде нужна обработка BYE от сервера)
            while True:
                await asyncio.sleep(1)
        else:
            logger.error("Registration failed")

    except KeyboardInterrupt:
        logger.info("Stopping...")
        stt.close()
        await client.bye()
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())