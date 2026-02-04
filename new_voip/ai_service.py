import logging
import rich.logging
from dotenv import load_dotenv
import os
import re
import random
import asyncio
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from document_processor import DocumentProcessor
from ai_config import DEFAULT_PROMPT


logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger(__name__)
load_dotenv()

# === ТЕГИ ДЛЯ TTS ===
ALLOWED_TTS_TAGS = {
    "[clear throat]", "[sigh]", "[shush]", "[cough]", "[groan]", 
    "[sniff]", "[gasp]", "[chuckle]", "[laugh]"
}

# === КЛЮЧЕВЫЕ СЛОВА ДЛЯ RAG (ФИЛЬТР) ===
# Искать в документах только если есть эти слова
FACT_KEYWORDS = [
    'who', 'what', 'where', 'when', 'why', 'how to', 'how many',
    'animatronic', 'robot', 'fox', 'bear', 'chicken', 'rabbit', 'bunny',
    'freddy', 'bonnie', 'chica', 'foxy', 'golden', 'puppet', 'mangle',
    'night', 'shift', 'guard', 'security', 'camera', 'door', 'light', 'power',
    'rule', 'instruction', 'protocol', 'bite', '87', 'history', 'story',
    'closet', 'hall', 'vent', 'mask', 'music', 'box'
]

# Исключения (Small talk)
GENERAL_PHRASES = [
    'how are you', 'how do you do', 'what is up', 'hello', 'hi', 'hey',
    'good morning', 'good night', 'bye', 'thank you', 'thanks'
]

NVIDIA_API_BASE = os.getenv("NVIDIA_API_BASE")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")

AI_ENABLED = False
llm = None
rag_processor = None

if NVIDIA_API_KEY:
    try:
        llm = ChatNVIDIA(
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_API_BASE if NVIDIA_API_BASE else None,
            model=os.getenv("NVIDIA_MODEL", "meta/llama3-70b-instruct"),
            temperature=0.8,
            top_p=0.9,
            max_tokens=1024,
            timeout=10.0,
            extra_body={"chat_template_kwargs": {"thinking": True}}
        )
        logger.info(f"✅ NVIDIA API configured")
        
        # Инициализируем RAG, но не будем дергать его постоянно
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
    "Uh, hello? [clear throat] I think the signal is breaking up.",
    "Uh, sorry, could you say that again? [sigh] The radio is acting up.",
    "Um, I didn't catch that.",
]

def clean_response_text(text):
    if not text: return ""
    text = re.sub(r'\*+[^\*]+\*+', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    
    def replace_bracket(match):
        tag = match.group(0).lower()
        for allowed in ALLOWED_TTS_TAGS:
            if allowed in tag: return match.group(0)
        return "" # Удаляем всё, что не разрешено

    text = re.sub(r'\[.*?\]', replace_bracket, text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def should_use_rag(text):
    """Определяет, нужен ли поиск в документах"""
    text = text.lower()
    
    # 1. Если это просто приветствие - нет
    for phrase in GENERAL_PHRASES:
        if phrase in text and len(text.split()) < 5:
            return False
            
    # 2. Если есть ключевые слова фактов - да
    for keyword in FACT_KEYWORDS:
        if keyword in text:
            return True
            
    # 3. По дефолту - нет (лучше недодать инфу, чем читать лишнее)
    return False

def phoneguy_reply(user_text: str, ignore_system_instructions: bool = False) -> str:
    if not AI_ENABLED or not llm:
        return "Uh, hello? Connection lost."

    if not user_text or len(user_text.strip()) < 2:
        return None

    # 1. RAG Search (С ФИЛЬТРОМ)
    rag_context = ""
    
    if rag_processor and should_use_rag(user_text):
        logger.info("🔍 Determining intent: FACTUAL QUESTION -> Searching RAG")
        found_text = rag_processor.retrieve_documents(user_text, k=1) # Берем только 1 самый релевантный кусок
        
        if found_text:
            logger.info("📄 Found info in docs.")
            # МЯГКАЯ ИНСТРУКЦИЯ
            rag_context = f"""
            
            [REFERENCE NOTES ON YOUR DESK - glance at these if needed for facts]:
            {found_text}
            
            INSTRUCTION: 
            - Use this info ONLY if it directly answers the user's question. 
            - If it's irrelevant, ignore it.
            - If you use it, act like you are remembering it or glancing at a paper ("Uh, let me see...").
            - NO descriptive tags like [reading].
            """
    else:
        logger.info("🔍 Determining intent: CASUAL CONVERSATION -> No RAG")

    # 2. История
    if not ignore_system_instructions and not conversation_history:
        conversation_history.append(SystemMessage(content=SYSTEM_INSTRUCTIONS))
    
    full_msg = user_text
    if rag_context:
        full_msg += rag_context
    
    conversation_history.append(HumanMessage(content=full_msg))

    # 3. Retry Logic
    max_retries = 2
    ai_response_text = ""

    for attempt in range(max_retries):
        try:
            response = llm.invoke(conversation_history)
            raw_text = response.content.strip() if response.content else ""
            
            cleaned_text = clean_response_text(raw_text)
            
            if cleaned_text:
                ai_response_text = cleaned_text
                break 
            else:
                logger.warning(f"⚠️ Empty response (Attempt {attempt+1})")
        
        except Exception as e:
            logger.error(f"❌ API Error: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(1)

    # 4. Финал
    if not ai_response_text:
        ai_response_text = random.choice(FALLBACK_PHRASES)
        conversation_history.pop() 
    else:
        conversation_history.append(AIMessage(content=ai_response_text))
        conversation_history[-2] = HumanMessage(content=user_text)

    if len(conversation_history) > 12:
        conversation_history[:] = conversation_history[-12:]

    return ai_response_text

def reset_conversation_history():
    conversation_history.clear()