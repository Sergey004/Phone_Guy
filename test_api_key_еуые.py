# test_tts_output.py
import asyncio
import httpx
import logging
import os

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def test_tts():
    API_KEY = os.getenv("API_KEY", "your_super_secret_api_key")  # Ваш ключ
    SERVER_URL = "http://localhost:8000/v1/audio/speech"
    payload = {
        "model": "1.5B",
        "tokenizer_path": "Qwen/Qwen2.5-7B",
        "input": "Hello, this is a test speech.",
        "voice": "PhoneGuy_FNAF1_01"
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY
    }
    logger = logging.getLogger("TestTTS")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(SERVER_URL, json=payload, headers=headers)
            response.raise_for_status()
            logger.info(f"Response headers: {response.headers}")
            logger.info(f"Content length: {len(response.content)} bytes")
            
            # Сохраняем как есть
            output_file = "tts_output.raw"
            with open(output_file, "wb") as f:
                f.write(response.content)
            logger.info(f"Saved raw TTS output to {output_file}")
            
            # Проверяем формат
            content_type = response.headers.get('content-type', 'unknown')
            if 'mpeg' in content_type:
                logger.info("Detected MP3 output")
                output_file = "tts_output.mp3"
            elif 'wav' in content_type or response.content.startswith(b'RIFF'):
                logger.info("Detected WAV output")
                output_file = "tts_output.wav"
            else:
                logger.warning(f"Unknown content-type: {content_type}")
            
            with open(output_file, "wb") as f:
                f.write(response.content)
            logger.info(f"Saved as {output_file}")
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)

asyncio.run(test_tts())