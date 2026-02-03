import asyncio
import logging
import os
import sys
import datetime
from dotenv import load_dotenv

# Проверки (оставим как было)...
try:
    import torch
    print(f"✓ PyTorch {torch.__version__} detected")
except ImportError:
    pass
try:
    from rvc_py.rvc_infer import rvc_infer
    print("✓ RVC module imported")
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
TARGET_NUMBER = None  # Ждем входящего

MOCK_CONFIG = {
    'stt': {
        'model': 'small',
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

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
_tts_ref = None
_bridge_ref = None
_current_log_file = None # Путь к текущему файлу лога

def setup_logging_file():
    """Создает новый файл лога для текущего звонка"""
    global _current_log_file
    
    # Создаем папку logs если нет
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    # Имя файла: logs/call_YYYY-MM-DD_HH-MM-SS.txt
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _current_log_file = f"logs/call_{timestamp}.txt"
    
    with open(_current_log_file, "w", encoding="utf-8") as f:
        f.write(f"=== CALL STARTED AT {timestamp} ===\n\n")
    
    logger.info(f"📝 Chat log will be saved to: {_current_log_file}")

def log_to_file(role, text):
    """Записывает сообщение в файл"""
    if not _current_log_file: return
    
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        with open(_current_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {role}: {text}\n")
    except Exception as e:
        logger.error(f"Failed to write logs: {e}")

async def prepare_incoming_greeting():
    """
    Эта функция вызывается, когда телефон ЗВОНИТ (Ring).
    """
    # Создаем файл лога при начале звонка
    setup_logging_file()
    
    logger.info("📞 PRE-GENERATING GREETING (While Ringing)...")
    _bridge_ref.buffer.clear()
    
    scenario_prompt = (
        "You are Phone Guy. Someone called your office. "
        "Answer with your signature stutter ('Uh, hello? Hello, hello?'). "
        "Ask who is this. Be nervous."
    )
    
    logger.info("🤔 AI thinking...")
    text = await asyncio.to_thread(phoneguy_reply, scenario_prompt)
    logger.info(f"🤖 Generated: {text}")
    
    # ЗАПИСЫВАЕМ В ЛОГ
    log_to_file("Phone Guy", text)
    
    await _tts_ref.speak(text, media_port=_bridge_ref)
    logger.info("✅ Audio ready in buffer! Pickup the phone now.")

async def conversation_loop(stt: STTAdapter, tts: TTSAdapter, bridge: PhoneBridgePort, client: SIPClient):
    logger.info("🟢 Bot is listening...")
    
    while not stt.out_queue.empty():
        stt.out_queue.get_nowait()

    while client.in_call:
        try:
            user_text = await asyncio.wait_for(stt.out_queue.get(), timeout=1.0)
            if not user_text: continue

            logger.info(f"🗣️ User: {user_text}")
            
            # ЗАПИСЫВАЕМ ЮЗЕРА В ЛОГ
            log_to_file("User", user_text)

            logger.info("🤔 Thinking...")
            ai_reply = await asyncio.to_thread(phoneguy_reply, user_text)
            
            # ЗАПИСЫВАЕМ БОТА В ЛОГ
            log_to_file("Phone Guy", ai_reply)

            await tts.speak(ai_reply, media_port=bridge)
        
        except asyncio.TimeoutError:
            continue

async def main():
    load_dotenv()
    global _tts_ref, _bridge_ref

    bridge = PhoneBridgePort()
    stt = STTAdapter(MOCK_CONFIG, logger)
    tts = TTSAdapter(MOCK_CONFIG, logger)
    if not await tts.check_health(): return
    
    _tts_ref = tts
    _bridge_ref = bridge

    client = SIPClient(SIP_USER, SIP_PASS, SIP_SERVER, LOCAL_IP, stt_adapter=stt)
    client.set_audio_source(bridge)
    client.set_prepare_callback(prepare_incoming_greeting)

    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: client,
        local_addr=('0.0.0.0', 5065)
    )

    try:
        await client.register()
        asyncio.create_task(stt.consume_frame_queue())

        while True:
            if TARGET_NUMBER:
                # Если мы звоним сами, создаем лог здесь
                setup_logging_file()
                await client.invite(TARGET_NUMBER)
            else:
                logger.info("📞 Waiting for call...")
            
            await client.call_connected_event.wait()
            
            await conversation_loop(stt, tts, bridge, client)
            
            logger.info("Call ended.")
            if _current_log_file:
                 with open(_current_log_file, "a", encoding="utf-8") as f:
                    f.write("\n=== CALL ENDED ===\n")

            if TARGET_NUMBER: break
            client.call_connected_event.clear()

    except KeyboardInterrupt:
        logger.info("Stopping...")
        stt.close()
        await client.bye()
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())