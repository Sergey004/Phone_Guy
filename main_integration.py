import asyncio
import logging
import os
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
        "audio_prompt_path": os.getenv(
            "AUDIO_PROMPT_PATH",
            "ai_core/models/RVC/PhoneGuyFNAF1/PhoneGuy_FNAF1_01.wav",
        ),
        "rvc_enabled": os.getenv("RVC_ENABLED", "true").lower() == "true",
        "rvc_model_path": os.getenv(
            "RVC_MODEL_PATH", "ai_core/models/RVC/PhoneGuyFNAF1/PhoneGuy_FNAF1_best.pth"
        ),
        "rvc_index_path": os.getenv(
            "RVC_INDEX_PATH", "ai_core/models/RVC/PhoneGuyFNAF1/added_index.index"
        ),
        "rvc_f0_method": os.getenv("RVC_F0_METHOD", "rmvpe"),
        "rvc_pitch_shift": int(os.getenv("RVC_PITCH_SHIFT", "0")),
        "rvc_index_rate": float(os.getenv("RVC_INDEX_RATE", "0.6")),
    },
}

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
_tts_ref = None
_bridge_ref = None
_current_log_file = None


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
    await _tts_ref.speak(text, media_port=_bridge_ref)
    logger.info("✅ Audio ready in buffer!")


async def prepare_outgoing_greeting(client_instance):
    """
    Вызывается при исходящем звонке — параллельно гудкам у абонента.
    direction='outgoing' — LLM понимает, что инициировала вызов она.
    Аудио копится в _bridge_ref.buffer и пойдёт в линию после 200 OK (старт RTP).
    """
    setup_logging_file()
    _bridge_ref.buffer.clear()

    target_number = client_instance.remote_number
    if target_number:
        logger.info(f"📂 Outbound call to: {target_number}")
        set_caller_context(target_number)
        reset_conversation_history()
    else:
        logger.warning("⚠️ Target number unknown")

    logger.info("📞 Generating outgoing greeting (parallel to ringing)...")
    logger.info("🤔 AI thinking...")
    text = await asyncio.to_thread(generate_phoneguy_greeting, direction="outgoing")
    logger.info(f"🤖 Generated: {text}")

    # Если абонент отказал/отбил во время генерации — не кладём аудио в буфер
    if client_instance.call_abort_event.is_set():
        logger.info("⚠️ Call aborted during greeting generation — skip TTS")
        return

    log_to_file("Phone Guy", text)
    await _tts_ref.speak(text, media_port=_bridge_ref)
    logger.info("✅ Outgoing audio ready in buffer!")


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

            # Barge-in: пользователь заговорил — прерываем то что бот говорит
            if bridge.buffer:
                logger.info("🤫 Barge-in: clearing TTS buffer")
                bridge.buffer.clear()

            logger.info("🤔 Thinking...")
            ai_reply = await asyncio.to_thread(phoneguy_reply, user_text)

            if not ai_reply:
                continue

            log_to_file("Phone Guy", ai_reply)
            await tts.speak(ai_reply, media_port=bridge)

        except asyncio.TimeoutError:
            continue


async def _do_outbound_call(client: SIPClient, target: str, stt, tts, bridge):
    """Инициирует исходящий звонок к `target`.

    Алгоритм:
    1. Генерирует OUTGOING-Greeting (Сначала!, чтобы аудио было готово).
    2. Сбрасываем remote_number и abort — пре- gén использует remote_number.
    3. Отправляем INVITE.
    4. Ждём ответа/отказа (408/486 и т.п.).
    5. Запускаем conversation_loop (уже готовое аудио лежит в buffer).
    Возвращает True, если разговор состоялся, False — если абонент не ответил.
    """
    # 0. Сбрасываем состояние вызова ДО генерации приветствия
    client.remote_number = target
    client.call_abort_event.clear()

    # 1. Генерация OUTGOING-Greeting (Сначала!, чтобы аудио было готово)
    await prepare_outgoing_greeting(client)

    # 2. Отправляем INVITE
    await client.invite(target)

    # 3. Ждём ответа/отказа (408/486 и т.п.)
    connect_task = asyncio.create_task(client.call_connected_event.wait())
    abort_task = asyncio.create_task(client.call_abort_event.wait())
    done, pending = await asyncio.wait(
        {connect_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
    if abort_task in done and not connect_task.done():
        logger.info("⚠️ Call aborted (no answer / rejected) — skipping")
        return False

    # 5. У аудио уже есть готовый фрейм в buffer от prepare_outgoing_greeting,
    #    conversation_loop сам возьмёт его оттуда и начнёт проигрывать.
    await conversation_loop(stt, tts, bridge, client)


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

    # --- DTMF admin-menu: удалённое управление ботом через DTMF (RFC 4733) ---
    # pending_dial — очередь номеров, которые бот должны позвонить после bye(),
    # проставляемая DtmfAdminController'ом после #9+PIN+9+<digits>+#.
    pending_dial: asyncio.Queue[str] = asyncio.Queue()

    async def _on_dial_request(number: str) -> None:
        await pending_dial.put(number)

    dtmf_admin = None
    if os.getenv("IVR_ENABLED", "true").lower() == "true":
        from ai_core.dtmf_admin import DtmfAdminController

        dtmf_admin = DtmfAdminController(
            client,
            bridge=bridge,
            tts=tts,
            stt=stt,
            admin_pin=os.getenv("IVR_ADMIN_PIN", "1234"),
            enter_prefix=os.getenv("IVR_ENTER_PREFIX", "#9"),
            dial_delay_sec=float(os.getenv("IVR_DIAL_DELAY_SEC", "2.5")),
            menu_timeout_sec=float(os.getenv("IVR_MENU_TIMEOUT_SEC", "5.0")),
            collect_timeout_sec=float(os.getenv("IVR_COLLECT_TIMEOUT_SEC", "8.0")),
            prompts={
                "menu": os.getenv(
                    "IVR_PROMPT_MENU",
                    "Admin menu. Press 9 to dial a number, 0 to hang up, hash to exit.",
                ),
                "enter_num": os.getenv(
                    "IVR_PROMPT_ENTER_NUM", "Enter the number, then press hash."
                ),
                "confirm": os.getenv(
                    "IVR_PROMPT_CONFIRM", "Okay, I will call to {number} after hung-up."
                ),
                "bad_pin": os.getenv("IVR_PROMPT_BAD_PIN", "Incorrect PIN. Exiting."),
                "exit": os.getenv("IVR_PROMPT_EXIT", "Exiting admin menu."),
                "timeout": os.getenv("IVR_PROMPT_TIMEOUT", "Menu timeout."),
            },
            on_dial_request=_on_dial_request,
        )
        client.dtmf_received_callback = dtmf_admin.handle_digit
        logger.info(
            "📟 DTMF admin menu enabled (prefix=%r, dial_delay=%.2fs)",
            os.getenv("IVR_ENTER_PREFIX", "#9"),
            float(os.getenv("IVR_DIAL_DELAY_SEC", "2.5")),
        )
    else:
        logger.info("📟 DTMF admin menu disabled (IVR_ENABLED=false)")

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
            # Если в очереди pending_dial лежит номер (от DTMF admin-menu),
            # переключаемся в режим outbound call к этому номеру.
            next_target: str | None = None
            if not pending_dial.empty():
                try:
                    next_target = pending_dial.get_nowait()
                except asyncio.QueueEmpty:
                    next_target = None
                if next_target:
                    logger.info("🔁 Admin dial-out requested -> %s", next_target)
                    # Сбрасываем состояние admin-меню и STT — бот начинает новый звонок
                    if dtmf_admin is not None:
                        dtmf_admin.reset()
                    # Даём SIP-провайдеру "успокоиться" после bye() c короткой паузой
                    await asyncio.sleep(1.5)

            if next_target is not None:
                if dtmf_admin is not None:
                    # перед стартом нового звонка — новый admin scope
                    dtmf_admin.reset()
                await _do_outbound_call(client, next_target, stt, tts, bridge)

                logger.info("Call ended. Saving memory...")
                if client.remote_number:
                    await summarize_and_save(client.remote_number)
                if _current_log_file:
                    with open(_current_log_file, "a", encoding="utf-8") as f:
                        f.write("\n=== CALL ENDED ===\n")
                client.call_connected_event.clear()
                continue

            if TARGET_NUMBER:
                if dtmf_admin is not None:
                    dtmf_admin.reset()
                await _do_outbound_call(client, TARGET_NUMBER, stt, tts, bridge)

                logger.info("Call ended. Saving memory...")
                if client.remote_number:
                    await summarize_and_save(client.remote_number)

                if _current_log_file:
                    with open(_current_log_file, "a", encoding="utf-8") as f:
                        f.write("\n=== CALL ENDED ===\n")
                break  # одиночный outbound-режим по TARGET_NUMBER

            logger.info("📞 Waiting for call...")
            client.call_abort_event.clear()
            # Ждём входящего (abort сработает при CANCEL, connect — при _start_rtp)
            connect_task = asyncio.create_task(client.call_connected_event.wait())
            abort_task = asyncio.create_task(client.call_abort_event.wait())
            done, pending = await asyncio.wait(
                {connect_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            if abort_task in done and not connect_task.done():
                logger.info("⚠️ Call aborted (no answer / rejected) — skipping")
                continue
            # Входящий состоялся — крутим conversation
            await conversation_loop(stt, tts, bridge, client)

            logger.info("Call ended. Saving memory...")
            if client.remote_number:
                await summarize_and_save(client.remote_number)

            if _current_log_file:
                with open(_current_log_file, "a", encoding="utf-8") as f:
                    f.write("\n=== CALL ENDED ===\n")
            client.call_connected_event.clear()

    except KeyboardInterrupt:
        logger.info("Stopping...")
        stt.close()
        await client.bye()
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
