# bot/ai.py
import os
import logging

import datetime
import re

import rich.logging
from .ai_config import DEFAULT_PROMPT

import shared_state # Импортируем shared_state
from langchain_nvidia_ai_endpoints import ChatNVIDIA # Импортируем ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage # Импортируем HumanMessage и AIMessage

NVIDIA_API_BASE = os.getenv("NVIDIA_API_BASE")

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger(__name__)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
if NVIDIA_API_KEY:
    try:
        # client = openai.OpenAI(
        #     api_key=NVIDIA_API_KEY,
        #     base_url=NVIDIA_API_BASE,
        # )
        llm = ChatNVIDIA(
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_API_BASE if NVIDIA_API_BASE else None,
            model=os.getenv("NVIDIA_MODEL", "mistralai/mixtral-8x22b-instruct-v0.1") # Default model if not specified
        )
        AI_ENABLED = True
        logger.info("NVIDIA API настроен.")
    except Exception as e:
        logger.error(f"Ошибка инициализации NVIDIA API: {e}", exc_info=True)
        AI_ENABLED = False
else:
    logger.warning("NVIDIA_API_KEY не найден. AI функции будут отключены.")
    AI_ENABLED = False

SYSTEM_INSTRUCTIONS = DEFAULT_PROMPT

TELEGRAM_MESSAGE_LIMIT = 4096

def split_message(text: str, chunk_size: int = TELEGRAM_MESSAGE_LIMIT):
    """Разбивает длинное сообщение на части."""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks

async def handle_ai_response(ticket_id: int, db_session: Session, bot: Bot):
    ticket = db_session.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        logger.error(f"Ticket with ID {ticket_id} not found.")
        return

    """Обработка взаимодействия с AI и обновление базы данных."""
    logger.info(f"Вызвана функция handle_ai_response для тикета {ticket.ticket_id}")
    if not AI_ENABLED:
        logger.warning(f"AI отключён. Пропуск AI-ответа для тикета {ticket.ticket_id}")
        return None

    # Получаем все сообщения для данного тикета
    messages = db_session.query(TicketMessage).filter(
        TicketMessage.ticket_id == ticket.ticket_id
    ).order_by(TicketMessage.created_at).all()
    logger.info(f"Получены сообщения из базы данных для тикета {ticket.ticket_id}. Количество сообщений: {len(messages)}")

    conversation_history = []

    retrieved_docs_content = "" # Инициализируем переменную пустой строкой

    # Добавляем системную инструкцию первой, если она не игнорируется
    system_instruction_parts = []
    if not ticket.ignore_system_instructions:
        system_instruction_parts.append(SYSTEM_INSTRUCTIONS)
    if retrieved_docs_content:
        system_instruction_parts.append(retrieved_docs_content)

    if system_instruction_parts:
        full_system_instruction = " ".join(system_instruction_parts)
        conversation_history.insert(0, SystemMessage(content=full_system_instruction))

    for msg in messages:
        if msg.sender_type == 'user':
            conversation_history.append(HumanMessage(content=msg.message_text))
        else:
            conversation_history.append(AIMessage(content=msg.message_text))

    # Добавляем текущее сообщение пользователя в историю
    current_user_message = conversation_history[-1].content if conversation_history else ""

    # Извлекаем релевантные документы, если DocumentProcessor доступен
    logger.info(f"Проверка доступности DocumentProcessor: {shared_state.document_processor is not None}")
    retrieved_docs_content = ""
    if shared_state.document_processor:
        try:
            retriever = shared_state.document_processor.vector_store.as_retriever()
            retrieved_docs = retriever.invoke(current_user_message)
            if retrieved_docs:
                retrieved_docs_content = "\n\nРелевантная информация:\n" + "\n".join([doc.page_content for doc in retrieved_docs])
                logger.info(f"Извлечены релевантные документы для тикета {ticket.ticket_id}")
            else:
                logger.info(f"Релевантные документы не найдены для тикета {ticket.ticket_id}")
        except Exception as e:
            logger.error(f"Ошибка при извлечении документов для тикета {ticket.ticket_id}: {e}")

    # Добавляем системную инструкцию первой, если она не игнорируется
    if retrieved_docs_content:
        if SYSTEM_INSTRUCTIONS and not ticket.ignore_system_instructions:
            for i, msg in enumerate(conversation_history):
                if isinstance(msg, SystemMessage):
                    conversation_history[i] = SystemMessage(content=SYSTEM_INSTRUCTIONS + retrieved_docs_content)
                    break
        elif not SYSTEM_INSTRUCTIONS and not ticket.ignore_system_instructions:
            # Если SYSTEM_INSTRUCTIONS нет, но есть retrieved_docs_content, добавляем только его
            conversation_history.insert(0, SystemMessage(content=retrieved_docs_content))
        elif ticket.ignore_system_instructions:
            # Если игнорируем системные инструкции, но есть retrieved_docs_content, добавляем только его
            conversation_history.insert(0, SystemMessage(content=retrieved_docs_content))
    logger.info(f"История разговора для тикета {ticket.ticket_id}: {conversation_history}")

    try:
        # Вызываем модель NVIDIA NIM
        response = llm.invoke(conversation_history)
        ai_response_text = response.content
        logger.info(f"Получен ответ от AI для тикета {ticket.ticket_id}: {ai_response_text}")

        # Сохраняем ответ AI в базу данных
        ai_message = TicketMessage(
            ticket_id=ticket.ticket_id,
            message_text=ai_response_text,
            sender_type='ai',
            sender_telegram_id=bot.id # Use bot's ID for AI messages
        )
        db_session.add(ai_message)
        db_session.commit()
        db_session.refresh(ai_message)
        logger.info(f"Ответ AI сохранен в базу данных: {ai_message.message_text}")

        # Отправляем ответ AI пользователю
        await bot.send_message(
            chat_id=ticket.chat_id,
            text=ai_response_text,
            reply_to_message_id=ticket.message_thread_id,
            reply_markup=get_escalate_keyboard(ticket.ticket_id)
        )
        logger.info(f"Ответ AI отправлен пользователю для тикета {ticket.ticket_id}")

        return ai_response_text

    except Exception as e:
        logger.exception(f"Ошибка при обращении к NVIDIA NIM для тикета {ticket.ticket_id}: {e}")
        db_session.rollback()
        try:
            error_msg = TicketMessage(
                ticket_id=ticket.ticket_id,
                message_text="Извините, произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз позже.",
                sender_type='ai',
                sender_telegram_id=bot.id
            )
            db_session.add(error_msg)
            db_session.commit()
            db_session.refresh(error_msg)
            await bot.send_message(chat_id=ticket.chat_id, text="Извините, произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз позже.")
        except Exception as tg_err:
            logger.error(f"Ошибка отправки уведомления об ошибке пользователю для тикета {ticket.ticket_id}: {tg_err}")
        return None
