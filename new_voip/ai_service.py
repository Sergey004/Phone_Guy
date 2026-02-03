import logging
import rich.logging
from dotenv import load_dotenv
import os
import re
import random
import asyncio
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Настройка логирования
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger(__name__)

load_dotenv()

# Импорт вашего промпта (или используем дефолтный)
try:
    from ai_config import DEFAULT_PROMPT
except ImportError:
    DEFAULT_PROMPT = "You are Phone Guy from FNAF. Be nervous and stutter."

NVIDIA_API_BASE = os.getenv("NVIDIA_API_BASE")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")

# Инициализация LLM
AI_ENABLED = False
llm = None

if NVIDIA_API_KEY:
    try:
        llm = ChatNVIDIA(
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_API_BASE if NVIDIA_API_BASE else None,
            model=os.getenv("NVIDIA_MODEL", "meta/llama3-70b-instruct"),
            temperature=1.7, # Чуть поднял для креативности
            top_p=0.9,
            max_completion_tokens=1024,
            # Увеличиваем таймаут на уровне запроса (если поддерживается библиотекой)
            timeout=10.0, 
            extra_body={"chat_template_kwargs": {"thinking": True}}
        )
        logger.info(f"✅ NVIDIA API configured with model: {os.getenv('NVIDIA_MODEL')}")
        AI_ENABLED = True
    except Exception as e:
        logger.error(f"❌ Error initializing NVIDIA API: {e}", exc_info=True)
else:
    logger.warning("⚠️ NVIDIA_API_KEY not found. AI functions will be disabled.")

SYSTEM_INSTRUCTIONS = DEFAULT_PROMPT

# История диалога
conversation_history = []

# Фразы-заглушки на случай ошибок (чтобы не повторял одно и то же)
FALLBACK_PHRASES = [
    "Uh, hello? I think the signal is breaking up.",
    "Uh, sorry, could you say that again? The radio is acting up.",
    "Um, I didn't catch that. It's a bit loud in here.",
    "[clear throat] Uh, are you still there?",
    "Sorry, I got distracted for a second, uh, checking the cameras.",
]

def phoneguy_reply(user_text: str, ignore_system_instructions: bool = False) -> str:
    """
    Генерирует ответ в стиле Phone Guy с механизмом Retry.
    """
    if not AI_ENABLED or not llm:
        return "Uh, hello? Can you hear me? Something is wrong with the connection."

    # Фильтр совсем короткого мусора
    if not user_text or len(user_text.strip()) < 2:
        logger.info("Ignoring too short input.")
        return None

    # Добавляем историю
    if not ignore_system_instructions and not conversation_history:
        conversation_history.append(SystemMessage(content=SYSTEM_INSTRUCTIONS))
    
    # Добавляем сообщение пользователя ВРЕМЕННО (пока не подтвердим успех)
    user_msg = HumanMessage(content=user_text)
    conversation_history.append(user_msg)

    # === RETRY LOGIC ===
    max_retries = 2
    ai_response_text = ""

    for attempt in range(max_retries):
        try:
            # invoke
            response = llm.invoke(conversation_history)
            raw_text = response.content.strip() if response.content else ""
            
            # Чистка
            # Убираем звездочки *sigh*, но оставляем [tags]
            clean_text = re.sub(r'\*+[^\*]+\*+', '', raw_text).strip()
            clean_text = re.sub(r'\s+', ' ', clean_text)
            
            if clean_text:
                ai_response_text = clean_text
                break # Успех!
            else:
                logger.warning(f"⚠️ Empty response from LLM (Attempt {attempt+1}/{max_retries})")
        
        except Exception as e:
            logger.error(f"❌ NVIDIA API Error (Attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(1) # Ждем секунду перед повтором

    # Если после всех попыток пусто -> берем случайную заглушку
    if not ai_response_text:
        ai_response_text = random.choice(FALLBACK_PHRASES)
        # Удаляем сообщение пользователя из истории, чтобы не портить контекст "глухотой"
        conversation_history.pop() 
    else:
        # Если успех - сохраняем ответ бота
        conversation_history.append(AIMessage(content=ai_response_text))

    # Ограничиваем память
    if len(conversation_history) > 20:
        conversation_history[:] = conversation_history[-20:]

    return ai_response_text

def reset_conversation_history():
    conversation_history.clear()
    logger.info("Conversation history reset.")