import logging
import rich.logging
from dotenv import load_dotenv
import os
import re
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from .ai_config import DEFAULT_PROMPT

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

logger = logging.getLogger(__name__)

load_dotenv()

NVIDIA_API_BASE = os.getenv("NVIDIA_API_BASE")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")

# Initialize LLM
if NVIDIA_API_KEY:
    try:
        llm = ChatNVIDIA(
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_API_BASE if NVIDIA_API_BASE else None,
            model=os.getenv("NVIDIA_MODEL"),
            temperature=0.6,
            top_p=0.7,
            max_tokens=4096,
            extra_body={"chat_template_kwargs": {"thinking":False}}
        )
        logger.info(f"NVIDIA API configured with model: {os.getenv('NVIDIA_MODEL')}")
        AI_ENABLED = True
    except Exception as e:
        logger.error(f"Error initializing NVIDIA API: {e}", exc_info=True)
        AI_ENABLED = False
else:
    logger.warning("NVIDIA_API_KEY not found. AI functions will be disabled.")
    AI_ENABLED = False

SYSTEM_INSTRUCTIONS = DEFAULT_PROMPT

# Maintain conversation history as a list of messages
conversation_history = []

def phoneguy_reply(user_text: str, ignore_system_instructions: bool = False) -> str:
    """
    Generate a Phone Guy-style response using the LLM, incorporating conversation history.
    
    Args:
        user_text: The user's input text.
        ignore_system_instructions: If True, skip system instructions in the response.
    
    Returns:
        The LLM-generated response text or a default response if AI fails or returns empty.
    """
    if not AI_ENABLED:
        logger.warning("🤖 AI is disabled. Returning default response.")
        return "Uh, sorry, something's, um, not working right now. Try again later?"

    try:
        logger.info(f"🤖 LLM REQUEST: '{user_text}'")
        
        # Build system message
        if not ignore_system_instructions and not conversation_history:
            conversation_history.append(SystemMessage(content=SYSTEM_INSTRUCTIONS))
        
        # Add user message to history
        conversation_history.append(HumanMessage(content=user_text))

        # Generate response
        logger.info("🤖 Calling NVIDIA API...")
        response = llm.invoke(conversation_history)
        ai_response_text = response.content.strip() if response.content else ""
        
        # Clean up asterisks and formatting
        ai_response_text = re.sub(r'\*+[^\*]+\*+', '', ai_response_text).strip()
        ai_response_text = re.sub(r'\s+', ' ', ai_response_text)  # Normalize whitespace
        
        logger.info(f"🤖 Raw LLM response: {response.content}")
        logger.info(f"🤖 Processed LLM response: {ai_response_text}")

        # Check for empty response
        if not ai_response_text:
            logger.error("❌ LLM returned empty response, using default")
            ai_response_text = "Uh, hello, hello? This is Phone Guy. Something's not right, so, uh, let's try again, okay?"

        # Add AI response to history
        conversation_history.append(AIMessage(content=ai_response_text))

        # Limit history to prevent excessive memory usage
        if len(conversation_history) > 20:  # Keep last 20 messages
            conversation_history[:] = conversation_history[-20:]

        logger.info(f"✅ LLM SUCCESS: '{ai_response_text}'")
        return ai_response_text

    except Exception as e:
        logger.error(f"❌ Error calling NVIDIA NIM: {e}", exc_info=True)
        return "Uh, sorry, something went, um, wrong. Could you repeat that?"

def reset_conversation_history():
    """Reset the conversation history."""
    conversation_history.clear()
    logger.info("Conversation history reset.")
