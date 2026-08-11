import asyncio
import logging
import os
import time
import datetime
from dotenv import load_dotenv

load_dotenv()

# Проверки библиотек
try:
    import torch

    print(f"✓ PyTorch {torch.__version__} detected")
except ImportError:
    pass

from ai_core.stt_adapter import STTAdapter
from ai_core.tts_adapter import TTSAdapter
from ai_core.ai_service import (
    phoneguy_reply,
    generate_phoneguy_greeting,
    rag_processor,
    set_caller_context,
    summarize_and_save,
    reset_conversation_history,
)
from telephony.sip_rtp_client import SIPClient
from telephony.bridge import PhoneBridgePort

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PhoneBot")

SIP_USER = os.getenv("SIP_USER", "555533")
SIP_PASS = os.getenv("SIP_PASSWORD", "Test1234")
SIP_SERVER = os.getenv("SIP_SERVER", "192.168.1.176:5060").split(":")[0]
LOCAL_IP = os.getenv("HOST_IP", "192.168.1.181")
TARGET_NUMBER = os.getenv("TARGET_NUMBER")

MOCK_CONFIG = {
    "stt": {
        "model": os.getenv("STT_MODEL", "tiny"),
        "device": os.getenv("STT_DEVICE", "cuda"),
        "energy_threshold": int(os.getenv("STT_ENERGY_THRESHOLD", "500")),
        "target_sample_rate": int(os.getenv("STT_TARGET_SAMPLE_RATE", "16000")),
        "language": os.getenv("STT_LANGUAGE", ""),
        "compute_type": os.getenv("STT_COMPUTE_TYPE", "float16"),
        "beam_size": int(os.getenv("STT_BEAM_SIZE", "5")),
        "translate": os.getenv("STT_TRANSLATE", False),
    },
    "tts": {
        "engine": os.getenv("TTS_ENGINE", "turbo"),
        "device": os.getenv("TTS_DEVICE", "cuda"),
        "language_id": "en",
        "cfg_weight": 0.3,
        "use_bf16": os.getenv("TTS_USE_BF16", "true").lower() == "true",
        "use_compile": os.getenv("TTS_USE_COMPILE", "true").lower() == "true",
        "audio_prompt_path": os.getenv("AUDIO_PROMPT_PATH", "ai_core/models/RVC/PhoneGuyFNAF1/PhoneGuy_FNAF1_01.wav"),
        "rvc_enabled": os.getenv("RVC_ENABLED", "true").lower() == "true",
        "rvc_model_path": os.getenv("RVC_MODEL_PATH", "ai_core/models/RVC/PhoneGuyFNAF1/PhoneGuy_FNAF1_best.pth"),
        "rvc_index_path": os.getenv("RVC_INDEX_PATH", "ai_core/models/RVC/PhoneGuyFNAF1/added_index.index"),
        "rvc_f0_method": os.getenv("RVC_F0_METHOD", "rmvpe"),
        "rvc_pitch_shift": int(os.getenv("RVC_PITCH_SHIFT", "0")),
        "rvc_index_rate": float(os.getenv("RVC_INDEX_RATE", "0.6")),
    },
}

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
_tts_ref = None
_bridge_ref = None
_current_log_file = None

# Время (monotonic) последнего запуска TTS-воспроизведения и окно "игнорировать barge-in"
# сразу после старта фразы бота — чтобы эхо/хвост его же голоса на линии не триггерило
# самопрерывание. 250мс с запасом под задержку линии/джиттер FreePBX.
_last_tts_start = 0.0
ECHO_GUARD_SEC = 0.25


async def speak_guarded(tts: TTSAdapter, text: str, bridge: PhoneBridgePort):
    """Обёртка над tts.speak(), фиксирующая момент старта фразы для echo-guard'а."""
    global _last_tts_start
    _last_tts_start = time.monotonic()
    await tts.speak(text, media_port=bridge)


def handle_speech_start(bridge: PhoneBridgePort, logger_: logging.Logger):
    """Вызывается STT-адаптером СРАЗУ при обнаружении голоса — быстрый barge-in."""
    if time.monotonic() - _last_tts_start < ECHO_GUARD_SEC:
        return
    if bridge.buffer:
        logger_.info("🤫 Fast barge-in: clearing TTS buffer")
        bridge.buffer.clear()


def setup_logging_file():
    global _current_log_file
    if not os.path.exists("logs"):
        os.makedirs("logs")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _current_log_file = f"logs/call_{timestamp}.txt"
    with open(_current_log_file, "w", encoding="utf-8") as f:
        f.write(f"=== CALL STARTED AT {timestamp} ===\n\n")
    logger.info(f"📝 Chat log will be saved to: {_current_log_file}")


def log_to_file(role, text):
    if not _current_log_file:
        return
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        with open(_current_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {role}: {text}\n")
    except Exception as e:
        logger.error(f"Failed to write logs: {e}")


async def prepare_incoming_greeting(client_instance):
    """
    Вызывается при звонке (Ring).
    """
    setup_logging_file()
    _bridge_ref.buffer.clear()

    caller_id = client_instance.remote_number
    if caller_id:
        logger.info(f"📂 Identified Caller ID: {caller_id}")
        set_caller_context(caller_id)
        reset_conversation_history()
    else:
        logger.warning("⚠️ Caller ID unknown")

    logger.info("📞 Generating adaptive greeting...")
    logger.info("🤔 AI thinking...")
    text = await asyncio.to_thread(generate_phoneguy_greeting)
    logger.info(f"🤖 Generated: {text}")

    log_to_file("Phone Guy", text)
    await speak_guarded(_tts_ref, text, _bridge_ref)
    logger.info("✅ Audio ready in buffer!")


async def conversation_loop(
    stt: STTAdapter, tts: TTSAdapter, bridge: PhoneBridgePort, client: SIPClient
):
    logger.info("🟢 Bot is listening...")
    while not stt.out_queue.empty():
        stt.out_queue.get_nowait()

    while client.in_call:
        try:
            user_text = await asyncio.wait_for(stt.out_queue.get(), timeout=1.0)
            if not user_text or len(user_text.strip()) < 2:
                continue

            logger.info(f"🗣️ User: {user_text}")
            log_to_file("User", user_text)

            # Основной barge-in теперь происходит мгновенно через STTAdapter.on_speech_start
            # (см. handle_speech_start выше). Здесь оставляем подстраховку на случай,
            # если что-то осталось в буфере к моменту готовного текста.
            if bridge.buffer:
                logger.info("🤫 Barge-in: clearing TTS buffer")
                bridge.buffer.clear()

            logger.info("🤔 Thinking...")
            ai_reply = await asyncio.to_thread(phoneguy_reply, user_text)

            if not ai_reply:
                continue

            log_to_file("Phone Guy", ai_reply)
            await speak_guarded(tts, ai_reply, bridge)

        except asyncio.TimeoutError:
            continue


async def main():
    load_dotenv()
    global _tts_ref, _bridge_ref

    bridge = PhoneBridgePort()
    stt = STTAdapter(MOCK_CONFIG, logger)
    tts = TTSAdapter(MOCK_CONFIG, logger)
    if not await tts.check_health():
        return

    _tts_ref = tts
    _bridge_ref = bridge

    client = SIPClient(SIP_USER, SIP_PASS, SIP_SERVER, LOCAL_IP, stt_adapter=stt)
    client.set_audio_source(bridge)

    # Быстрый barge-in: срабатывает буфер TTS при первом же громком фрейме (~20-40мс),
    # а не ждёт полного распознавания через Whisper (~1.5-2.5с).
    stt.on_speech_start = lambda: handle_speech_start(bridge, logger)

    # Передаем client в колбэк через замыкание (чтобы получить доступ к remote_number)
    async def wrapped_prepare():
        await prepare_incoming_greeting(client)

    client.set_prepare_callback(wrapped_prepare)

    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: client, local_addr=("0.0.0.0", 5065)
    )

    if rag_processor:
        rag_processor.index_documents()

    try:
        await client.register()
        asyncio.create_task(stt.consume_frame_queue())

        while True:
            if TARGET_NUMBER:
                setup_logging_file()
                client.remote_number = TARGET_NUMBER
                set_caller_context(TARGET_NUMBER)
                reset_conversation_history()

                await client.invite(TARGET_NUMBER)
            else:
                logger.info("📞 Waiting for call...")
                client.call_abort_event.clear()

            await client.call_connected_event.wait()

            if TARGET_NUMBER:
                logger.info("📞 Generating outgoing greeting...")
                text = await asyncio.to_thread(generate_phoneguy_greeting)
                logger.info(f"🤖 Generated: {text}")
                log_to_file("Phone Guy", text)
                await speak_guarded(tts, text, bridge)

            await conversation_loop(stt, tts, bridge, client)

            logger.info("Call ended. Saving memory...")

            # 3. Сохранение памяти после звонка
            if client.remote_number:
                await summarize_and_save(client.remote_number)

            if _current_log_file:
                with open(_current_log_file, "a", encoding="utf-8") as f:
                    f.write("\n=== CALL ENDED ===\n")

            if TARGET_NUMBER:
                break
            client.call_connected_event.clear()

    except KeyboardInterrupt:
        logger.info("Stopping...")
        stt.close()
        await client.bye()
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
