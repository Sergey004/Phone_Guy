import logging
import rich.logging

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

from openai import OpenAI
from dotenv import load_dotenv
import os

import shared_state
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from .ai_config import DEFAULT_PROMPT

logger = logging.getLogger(__name__)

load_dotenv()

NVIDIA_API_BASE = os.getenv("NVIDIA_API_BASE")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
if NVIDIA_API_KEY:
    try:
        llm = ChatNVIDIA(
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_API_BASE if NVIDIA_API_BASE else None,
            model=os.getenv("NVIDIA_MODEL", "mistralai/mixtral-8x22b-instruct-v0.1")
        )
        logger.info("NVIDIA API configured.")
    except Exception as e:
        logger.error(f"Error initializing NVIDIA API: {e}", exc_info=True)
else:
    logger.warning("NVIDIA_API_KEY not found. AI functions will be disabled.")

SYSTEM_INSTRUCTIONS = DEFAULT_PROMPT

def phoneguy_reply(user_text: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": user_text}
    ]

    retrieved_docs_content = ""
    if shared_state.document_processor:
        try:
            retriever = shared_state.document_processor.vector_store.as_retriever()
            retrieved_docs = retriever.invoke(user_text)
            if retrieved_docs:
                retrieved_docs_content = "\n\nRelevant Information:\n" + "\n".join([doc.page_content for doc in retrieved_docs])
                logger.info("Relevant documents retrieved.")
            else:
                logger.info("No relevant documents found.")
        except Exception as e:
            logger.error(f"Error retrieving documents: {e}")

    if retrieved_docs_content:
        messages.insert(0, SystemMessage(content=SYSTEM_INSTRUCTIONS + retrieved_docs_content))
    else:
        messages.insert(0, SystemMessage(content=SYSTEM_INSTRUCTIONS))

    conversation_history = []
    for msg in messages:
        if msg["role"] == 'user':
            conversation_history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == 'system':
            conversation_history.append(SystemMessage(content=msg["content"]))
        else:
            conversation_history.append(AIMessage(content=msg["content"]))

    try:
        completion = llm.invoke(conversation_history)
        return completion.content.strip()
    except Exception as e:
        logger.error(f"Error calling NVIDIA NIM: {e}")
        return "Sorry, an error occurred while processing your request. Please try again later."


if __name__ == "__main__":
    # Пример использования
    test_input = "Сделай первое тестовое приветствие для звонка."
    reply = phoneguy_reply(test_input)
    print("--- Ответ Phone Guy ---")
    print(reply)
