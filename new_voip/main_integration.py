import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

# Проверки библиотек... (оставил ваш код)
try:
    import torch
    print(f"✓ PyTorch {torch.__version__} detected")
except ImportError:
    print("❌ ERROR: PyTorch not found!")
    sys.exit(1)

try:
    from rvc_py.rvc_infer import rvc_infer
    print("✓ RVC module imported successfully")
except ImportError:
    pass

from stt_adapter import STTAdapter
from tts_adapter import TTSAdapter
from ai_service import phoneguy_reply
from sip_rtp_client import SIPClient
from bridge import PhoneBridgePort

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PhoneBot")

# === НАСТРОЙКИ ===
SIP_USER = "555533"
SIP_PASS = "Test1234"
SIP_SERVER = "192.168.1.176"
LOCAL_IP = "192.168.1.181"

# !!! ВАЖНО !!!
# Если хотите, чтобы бот ЖДАЛ звонка -> оставьте TARGET_NUMBER = None
# Если хотите, чтобы бот ЗВОНИЛ сам -> напишите номер "1001"
TARGET_NUMBER = None  # <--- РЕЖИМ ОЖИДАНИЯ ВХОДЯЩЕГО

# Ваш конфиг...
MOCK_CONFIG = {
    'stt': {
        'model': 'tiny',
        'device': 'cuda',
        'energy_threshold': 500,
        'target_sample_rate': 16000,
        'language': 'en'
    },
    'tts': {
        'engine': 'turbo',
        'device': 'cuda',
        'language_id': 'en',
        'audio_prompt_path': "/home/user/Test_Phone_new/new_voip/models/RVC/PhoneGuyFNAF1/PhoneGuy_FNAF1_01.wav",
        'rvc_enabled': True,
        'rvc_model_path': '/home/user/Test_Phone_new/new_voip/models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth',
        'rvc_index_path': '/home/user/Test_Phone_new/new_voip/models/RVC/PhoneGuyFNAFadded_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index',
        'rvc_f0_method': 'rmvpe',
        'rvc_pitch_shift': 0,
        'rvc_index_rate': 0.6 
    }
}

async def generate_greeting(tts: TTSAdapter, bridge: PhoneBridgePort, inbound=False):
    """
    Бот здоровается. Сценарий зависит от того, кто позвонил.
    """
    logger.info("👋 Generating initial greeting...")
    await asyncio.sleep(1.5)

    if inbound:
        # Сценарий: Нам позвонили
        scenario_prompt = (
            "You are Phone Guy. Someone just called your office phone. "
            "Answer the phone naturally with your signature stutter ('Uh, hello? Hello, hello?'). "
            "Ask who is calling and why they are bothering you at night. Be slightly annoyed but polite."
        )
    else:
        # Сценарий: Мы позвонили
        scenario_prompt = (
            "You are Phone Guy. You just called the new night guard. "
            "Start with 'Uh, hello, hello?'. Say you wanted to record a message for them to help them get settled in."
        )

    logger.info("🤔 AI thinking about greeting...")
    greeting_text = await asyncio.to_thread(phoneguy_reply, scenario_prompt)
    logger.info(f"🤖 Initial Greeting: {greeting_text}")
    await tts.speak(greeting_text, media_port=bridge)

async def conversation_loop(stt: STTAdapter, tts: TTSAdapter, bridge: PhoneBridgePort, client: SIPClient):
    """Главный цикл разговора"""
    logger.info("🟢 Bot is listening...")
    
    # Очищаем очередь STT от старых фраз (если были)
    while not stt.out_queue.empty():
        stt.out_queue.get_nowait()

    while client.in_call:
        try:
            # Ждем фразу с таймаутом, чтобы проверять статус звонка
            user_text = await asyncio.wait_for(stt.out_queue.get(), timeout=1.0)
            
            logger.info(f"🗣️ User said: {user_text}")
            if not user_text: continue

            logger.info("🤔 Thinking...")
            ai_reply = await asyncio.to_thread(phoneguy_reply, user_text)
            logger.info(f"🤖 AI Reply: {ai_reply}")

            await tts.speak(ai_reply, media_port=bridge)
        
        except asyncio.TimeoutError:
            continue # Просто проверяем in_call и крутимся дальше

async def main():
    load_dotenv()
    logger.info("Initializing AI Engines...")
    bridge = PhoneBridgePort()
    stt = STTAdapter(MOCK_CONFIG, logger)
    tts = TTSAdapter(MOCK_CONFIG, logger)
    if not await tts.check_health(): return

    # Инициализация SIP
    client = SIPClient(SIP_USER, SIP_PASS, SIP_SERVER, LOCAL_IP, stt_adapter=stt)
    client.set_audio_source(bridge)

    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: client,
        local_addr=('0.0.0.0', 5065)
    )

    try:
        # 1. Регистрация
        await client.register()
        await asyncio.sleep(1)
        if not client.registered:
            logger.error("Registration failed")
            return

        # Запускаем STT consumer
        asyncio.create_task(stt.consume_frame_queue())

        while True:
            # === РЕЖИМ 1: Мы звоним (Outbound) ===
            if TARGET_NUMBER:
                logger.info(f"📞 Calling {TARGET_NUMBER}...")
                await client.invite(TARGET_NUMBER)
            
            # === РЕЖИМ 2: Мы ждем (Inbound) ===
            else:
                logger.info("📞 Waiting for incoming call...")
            
            # Ждем пока поднимут трубку (или мы, или они)
            await client.call_connected_event.wait()
            logger.info("✅ Call Connected!")

            # Генерируем приветствие (разное для входящих/исходящих)
            is_inbound = (TARGET_NUMBER is None)
            await generate_greeting(tts, bridge, inbound=is_inbound)

            # Запускаем разговор
            await conversation_loop(stt, tts, bridge, client)
            
            logger.info("Call ended. Resetting...")
            # Если был исходящий, выходим (или можно сделать повторный звонок)
            if TARGET_NUMBER:
                break
            
            # Если входящий - цикл крутится, ждем следующего
            client.call_connected_event.clear()

    except KeyboardInterrupt:
        logger.info("Stopping...")
        stt.close()
        await client.bye()
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())