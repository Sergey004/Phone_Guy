import logging
import rich.logging
from dotenv import load_dotenv
import os
import re
import random
import asyncio
import datetime
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from ai_core.document_processor import DocumentProcessor
from ai_core.ai_config import DEFAULT_PROMPT
SYSTEM_INSTRUCTIONS = DEFAULT_PROMPT


logging.basicConfig(level="INFO", format="%(message)s", handlers=[rich.logging.RichHandler(rich_tracebacks=True)])
logger = logging.getLogger(__name__)
load_dotenv()

# --- КОНФИГУРАЦИЯ ---
ALLOWED_TTS_TAGS = {"[clear throat]", "[sigh]", "[shush]", "[cough]", "[groan]", "[sniff]", "[gasp]", "[chuckle]", "[laugh]"}
FALLBACK_PHRASES = ["Uh, hello? I think the signal is breaking up.", "Uh, sorry, could you say that again?", "Um, I didn't catch that."]

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
AI_ENABLED = False
llm = None
rag_processor = None    # База знаний (PDF)
memory_processor = None # База пользователей

if NVIDIA_API_KEY:
    try:
        llm = ChatNVIDIA(
            api_key=NVIDIA_API_KEY,
            model=os.getenv("NVIDIA_MODEL", "meta/llama3-70b-instruct"),
            temperature=0.7, top_p=0.9, max_tokens=1024,
            extra_body={"chat_template_kwargs": {"thinking": True}}
        )
        # 1. Знания о мире (FNAF Lore)
        rag_processor = DocumentProcessor(doc_path="knowledge_base", collection_name="phoneguy_brain")
        # 2. Знания о людях (Кто звонил)
        # Создаем папку memory_db для хранения этого
        if not os.path.exists("user_memories"): os.makedirs("user_memories")
        memory_processor = DocumentProcessor(doc_path="user_memories", collection_name="phoneguy_users")
        
        AI_ENABLED = True
        logger.info("✅ AI & Memory Systems Online")
    except Exception as e:
        logger.error(f"❌ Error initializing AI: {e}")


conversation_history = []
current_user_context = "" # Здесь будет текст "Это Майк, он боится лис"

def set_caller_context(caller_id: str):
    """Загружает досье на звонящего"""
    global current_user_context
    current_user_context = ""
    
    if memory_processor and caller_id:
        logger.info(f"🧠 Retrieving memory for CallerID: {caller_id}")
        # Ищем воспоминания, связанные с этим номером
        memories = memory_processor.retrieve_documents("who is this user summary", k=3, filter_meta={"caller_id": caller_id})
        
        if memories:
            current_user_context = f"\n\n[MEMORY - PREVIOUS CALLS WITH THIS GUARD]:\n{memories}\n(If the user seems familiar, acknowledge it nervously. If not, ignore this.)"
            logger.info("🧠 Memory loaded.")
        else:
            logger.info("🧠 No memory found (New Caller).")

async def summarize_and_save(caller_id: str):
    """Сжимает диалог и сохраняет в память"""
    if not memory_processor or not conversation_history or not caller_id: return

    logger.info("📝 Summarizing call...")
    
    # Собираем текст диалога
    dialog_text = "\n".join([f"{m.type}: {m.content}" for m in conversation_history if isinstance(m, (HumanMessage, AIMessage))])
    
    # Промпт для суммаризации
    summary_prompt = f"""
    Analyze this call between Phone Guy and a Guard (User).
    Write a short summary (in English) of 2-3 sentences.
    Focus on: Name (if given), current Night, specific animatronics discussed, user's emotional state.
    
    DIALOGUE:
    {dialog_text[-4000:]} 
    
    SUMMARY:
    """
    
    try:
        # Генерируем саммари (в отдельном потоке)
        res = await asyncio.to_thread(llm.invoke, summary_prompt)
        summary = res.content.strip()
        
        timestamp = datetime.datetime.now().isoformat()
        meta = {"caller_id": caller_id, "timestamp": timestamp, "type": "summary"}
        
        memory_processor.add_memory(summary, meta)
        logger.info(f"💾 Memory saved: {summary}")
    except Exception as e:
        logger.error(f"❌ Summarization failed: {e}")

def clean_response_text(text):
    if not text: return ""
    text = re.sub(r'\*+[^\*]+\*+', '', text)
    text = re.sub(r'\(.*?\)', '', text)
    def replace_bracket(match):
        tag = match.group(0).lower()
        for allowed in ALLOWED_TTS_TAGS:
            if allowed in tag: return match.group(0)
        return ""
    text = re.sub(r'\[.*?\]', replace_bracket, text)
    return re.sub(r'\s+', ' ', text).strip()

def phoneguy_reply(user_text: str, ignore_system_instructions: bool = False) -> str:
    if not AI_ENABLED or not llm: return "Uh, hello?"
    if not user_text or len(user_text.strip()) < 2: return None

    # 1. RAG (База знаний) - ищем факты о FNAF
    rag_context = ""
    if rag_processor:
        # Ищем без фильтра по caller_id, просто по смыслу
        found_text = rag_processor.retrieve_documents(user_text, k=1, filter_meta=None)
        if found_text:
            rag_context = f"\n\n[OFFICE FILES]:\n{found_text}\n(Use this info, act like you're reading it)"

    # 2. Формирование истории
    if not ignore_system_instructions and not conversation_history:
        # В начало диалога добавляем Промпт + Память о юзере
        full_system = SYSTEM_INSTRUCTIONS + current_user_context
        conversation_history.append(SystemMessage(content=full_system))
    
    # Сообщение юзера + найденный факт из PDF
    full_msg = user_text + rag_context
    conversation_history.append(HumanMessage(content=full_msg))

    # 3. Retry
    max_retries = 2
    ai_response_text = ""
    for attempt in range(max_retries):
        try:
            response = llm.invoke(conversation_history)
            raw = response.content.strip() if response.content else ""
            cleaned = clean_response_text(raw)
            if cleaned:
                ai_response_text = cleaned
                break 
        except Exception:
            pass

    if not ai_response_text:
        ai_response_text = random.choice(FALLBACK_PHRASES)
        conversation_history.pop()
    else:
        conversation_history.append(AIMessage(content=ai_response_text))
        conversation_history[-2] = HumanMessage(content=user_text)

    if len(conversation_history) > 12: conversation_history[:] = conversation_history[-12:]
    return ai_response_text

def reset_conversation_history():
    conversation_history.clear()