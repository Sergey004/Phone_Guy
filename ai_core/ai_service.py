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
            model_kwargs={
                "extra_body":{"chat_template_kwargs": {"thinking": True}}}
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
        memories = memory_processor.retrieve_documents("who is this user summary", k=3, filter_meta={"caller_id": caller_id})
        
        if memories:
            current_user_context = f"\n\n[MEMORY - PREVIOUS CALLS WITH THIS GUARD]:\n{memories}\n(If the user seems familiar, acknowledge it nervously. If not, ignore this.)"
            logger.info("🧠 Memory loaded.")
        else:
            logger.info("🧠 No memory found (New Caller).")


def _build_adaptive_system_prompt(context_type: str = "normal") -> str:
    """
    Создаёт адаптивный system prompt в зависимости от контекста.
    
    Args:
        context_type: 'greeting' | 'normal' | 'ongoing'
    """
    base = SYSTEM_INSTRUCTIONS
    
    if current_user_context:
        base += f"\n\n=== KNOWN CALLER ==={current_user_context}\nYou RECOGNIZE this person. Greet them by name warmly but nervously."
    else:
        base += "\n\n=== NEW CALLER ===\nYou do NOT recognize this caller. Be cautious and suspicious. Ask 'Uh, hello? Who is this?'"
    
    if context_type == "greeting":
        base += "\n\nFIRST CONTACT: Your greeting just played. Wait for their response."
    elif context_type == "ongoing":
        base += "\n\nCONVERSATION ACTIVE: Respond naturally to what they say. Reference previous calls if you know them."
    elif context_type == "normal":
        base += "\n\nRespond to the user's message naturally."
    
    return base


def generate_phoneguy_greeting() -> str:
    """
    Генерирует приветствие для первого контакта.
    Правильно инициализирует conversation_history без дублирования сообщений.
    """
    if not AI_ENABLED or not llm:
        return "Uh, hello?"
    
    logger.info("🎯 Generating adaptive greeting...")
    
    full_system = _build_adaptive_system_prompt(context_type="greeting")
    conversation_history.append(SystemMessage(content=full_system))
    
    greeting_prompt = "You are Phone Guy. Someone just called your office. Your greeting audio just played. Say hello nervously. Start with 'Uh, hello? Hello, hello?'"
    
    conversation_history.append(HumanMessage(content=greeting_prompt))
    
    try:
        response = llm.invoke(conversation_history)
        raw = response.content.strip() if response.content else ""
        cleaned = clean_response_text(raw)
        
        if cleaned:
            conversation_history.append(AIMessage(content=cleaned))
            logger.info(f"🤖 Greeting generated: {cleaned[:50]}...")
            return cleaned
    except Exception as e:
        logger.error(f"❌ Greeting generation failed: {e}")
    
    fallback = "Uh, hello? Hello, hello?"
    conversation_history.append(AIMessage(content=fallback))
    return fallback

async def summarize_and_save(caller_id: str):
    """Сжимает диалог и сохраняет в память"""
    logger.info(f"📝 [summarize_and_save] Called for caller_id: {caller_id}")
    logger.info(f"📝 [summarize_and_save] memory_processor exists: {memory_processor is not None}")
    logger.info(f"📝 [summarize_and_save] conversation_history length: {len(conversation_history)}")
    
    if not memory_processor:
        logger.error("❌ memory_processor is None - NVIDIA_API_KEY missing or initialization failed")
        return
    if not conversation_history:
        logger.warning("⚠️ conversation_history is empty - nothing to save")
        return
    if not caller_id:
        logger.warning("⚠️ caller_id is empty")
        return

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

    rag_context = ""
    if rag_processor:
        found_text = rag_processor.retrieve_documents(user_text, k=1, filter_meta=None)
        if found_text:
            rag_context = f"\n\n[OFFICE FILES]:\n{found_text}\n(Use this info, act like you're reading it)"

    if not ignore_system_instructions:
        if not conversation_history:
            full_system = _build_adaptive_system_prompt(context_type="normal")
            conversation_history.append(SystemMessage(content=full_system))
        elif len(conversation_history) == 2:
            system_msg = conversation_history[0]
            if isinstance(system_msg, SystemMessage):
                adaptive_system = _build_adaptive_system_prompt(context_type="ongoing")
                conversation_history[0] = SystemMessage(content=adaptive_system)
                logger.info("🔄 Updated system prompt for ongoing conversation")

    full_msg = user_text + rag_context
    conversation_history.append(HumanMessage(content=full_msg))

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