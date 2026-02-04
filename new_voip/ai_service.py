import logging
import rich.logging
from dotenv import load_dotenv
import os
import re
import random
import asyncio
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from ai_config import DEFAULT_PROMPT

# Импортируем наш RAG процессор
from document_processor import DocumentProcessor

# Настройка логирования
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger(__name__)

load_dotenv()

# === ПРОМПТ ЛИЧНОСТИ ===
# Мы немного изменим его, чтобы он знал, как пользоваться документами


NVIDIA_API_BASE = os.getenv("NVIDIA_API_BASE")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")

# Инициализация LLM и RAG
AI_ENABLED = False
llm = None
rag_processor = None

if NVIDIA_API_KEY:
    try:
        # 1. Init LLM
        llm = ChatNVIDIA(
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_API_BASE if NVIDIA_API_BASE else None,
            model=os.getenv("NVIDIA_MODEL", "meta/llama3-70b-instruct"),
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
            timeout=10.0,
            extra_body={"chat_template_kwargs": {"thinking": True}}
        )
        logger.info(f"✅ NVIDIA API configured")
        
        # 2. Init RAG (Knowledge Base)
        logger.info("📚 Initializing Knowledge Base...")
        rag_processor = DocumentProcessor(doc_path="knowledge_base")
        AI_ENABLED = True
        
    except Exception as e:
        logger.error(f"❌ Error initializing AI: {e}", exc_info=True)
else:
    logger.warning("⚠️ NVIDIA_API_KEY not found.")

SYSTEM_INSTRUCTIONS = DEFAULT_PROMPT
conversation_history = []

FALLBACK_PHRASES = [
    "Uh, hello? I think the signal is breaking up.",
    "Uh, sorry, could you say that again? The radio is acting up.",
    "Um, I didn't catch that. It's a bit loud in here.",
    "[clear throat] Uh, are you still there?",
]

def phoneguy_reply(user_text: str, ignore_system_instructions: bool = False) -> str:
    """
    Генерирует ответ с использованием RAG (поиск по документам).
    """
    if not AI_ENABLED or not llm:
        return "Uh, hello? Connection lost."

    if not user_text or len(user_text.strip()) < 2:
        return None

    # 1. Поиск контекста в документах (RAG)
    rag_context = ""
    if rag_processor:
        found_text = rag_processor.retrieve_documents(user_text, k=2)
        if found_text:
            logger.info("📄 Found relevant info in docs!")
            rag_context = f"\n\n[RELEVANT COMPANY FILES ON YOUR DESK]:\n{found_text}\n(Use this info but say it in your own words, nervously)"

    # 2. Формируем историю
    # Если история пуста, добавляем системный промпт
    if not ignore_system_instructions and not conversation_history:
        conversation_history.append(SystemMessage(content=SYSTEM_INSTRUCTIONS))
    
    # 3. Добавляем сообщение юзера + найденный контекст
    # Мы "подклеиваем" найденные документы прямо к сообщению пользователя,
    # чтобы LLM видела их в контексте текущего вопроса.
    full_user_message = f"{user_text}{rag_context}"
    
    user_msg_obj = HumanMessage(content=full_user_message)
    conversation_history.append(user_msg_obj)

    # 4. Retry Logic
    max_retries = 2
    ai_response_text = ""

    for attempt in range(max_retries):
        try:
            response = llm.invoke(conversation_history)
            raw_text = response.content.strip() if response.content else ""
            
            clean_text = re.sub(r'\*+[^\*]+\*+', '', raw_text).strip()
            clean_text = re.sub(r'\s+', ' ', clean_text)
            
            if clean_text:
                ai_response_text = clean_text
                break 
            else:
                logger.warning(f"⚠️ Empty response (Attempt {attempt+1})")
        
        except Exception as e:
            logger.error(f"❌ API Error: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(1)

    # 5. Обработка результата
    if not ai_response_text:
        ai_response_text = random.choice(FALLBACK_PHRASES)
        conversation_history.pop() # Удаляем вопрос, раз не ответили
    else:
        # В историю сохраняем чистый ответ
        conversation_history.append(AIMessage(content=ai_response_text))
        
        # ХАК: В истории лучше хранить чистое сообщение юзера (без огромного куска RAG),
        # чтобы не забивать контекстное окно следующими запросами.
        # Подменяем последнее сообщение в истории на оригинал.
        conversation_history[-2] = HumanMessage(content=user_text)

    if len(conversation_history) > 10:
        conversation_history[:] = conversation_history[-10:]

    return ai_response_text

def reset_conversation_history():
    conversation_history.clear()