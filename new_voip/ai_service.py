import logging
import rich.logging
from dotenv import load_dotenv
import os
import re
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from ai_config import DEFAULT_PROMPT

# Настройка логирования
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger(__name__)

load_dotenv()

# === КОНФИГУРАЦИЯ ПРОМПТА ===
# Если у вас есть файл ai_config, можно импортировать оттуда.
# Если нет, используем этот дефолтный промпт:

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
            model=os.getenv("NVIDIA_MODEL", "meta/llama3-70b-instruct"), # Дефолтная модель если нет в env
            temperature=1.5,
            top_p=0.7,
            max_tokens=1024,
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

def phoneguy_reply(user_text: str, ignore_system_instructions: bool = False) -> str:
    """
    Генерирует ответ в стиле Phone Guy, используя историю переписки.
    """
    if not AI_ENABLED or not llm:
        logger.warning("🤖 AI is disabled. Returning default response.")
        return "Uh, hello? Can you hear me? Something is wrong with the connection."

    try:
        # 1. Добавляем системный промпт (только если история пуста)
        if not ignore_system_instructions and not conversation_history:
            conversation_history.append(SystemMessage(content=SYSTEM_INSTRUCTIONS))
        
        # 2. Добавляем сообщение пользователя
        conversation_history.append(HumanMessage(content=user_text))

        # 3. Генерируем ответ
        response = llm.invoke(conversation_history)
        ai_response_text = response.content.strip() if response.content else ""
        
        # 4. Чистим текст от звездочек (действий в ролевой игре)
        # Phone Guy только говорит, он не пишет *sighs* в аудио.
        ai_response_text = re.sub(r'\*+[^\*]+\*+', '', ai_response_text).strip()
        ai_response_text = re.sub(r'\s+', ' ', ai_response_text) 
        
        if not ai_response_text:
            ai_response_text = "Uh, hello, hello? I think I lost you there."

        # 5. Сохраняем ответ бота в историю
        conversation_history.append(AIMessage(content=ai_response_text))

        # Ограничиваем память (последние 20 сообщений)
        if len(conversation_history) > 20:
            conversation_history[:] = conversation_history[-20:]

        return ai_response_text

    except Exception as e:
        logger.error(f"❌ Error calling NVIDIA NIM: {e}", exc_info=True)
        return "Uh, sorry, technical difficulties."

def reset_conversation_history():
    """Сброс памяти бота"""
    conversation_history.clear()
    logger.info("Conversation history reset.")