import asyncio
import logging
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from Libs.tts_adapter import TTSAdapter  # Импорт из вашей библиотеки
from Libs.llm_adapter import phoneguy_reply
import wave

# Настройка логирования
logging.basicConfig(level=logging.INFO)

async def test_tts_library():
    # Конфигурация (замените на ваши реальные значения)
    config = {
        'tts': {
            'api_key': 'your_super_secret_api_key',
            'base_url': 'http://localhost:8000/v1',  # URL вашего TTS-сервера
            'model': '1.5B',
            'tokenizer_path': 'Qwen/Qwen2.5-7B',
            'voice': 'PhoneGuy_FNAF1_01'
        }
    }
    logger = logging.getLogger('TTS_Test')
    tts = TTSAdapter(config, logger)
    
    # 1. Проверка здоровья сервера (вызов check_health)
    logger.info("Проверяем здоровье TTS-сервера...")
    is_healthy = await tts.check_health(retries=3, backoff=1.0)
    if is_healthy:
        logger.info("✅ Сервер здоров!")
    else:
        logger.warning("❌ Сервер недоступен. Дальнейшие тесты могут не сработать.")
        return  # Прерываем, если сервер не готов
    
    # 2. Генерация текста с помощью LLM
    llm_response_text = phoneguy_reply("Скажи что-нибудь о погоде. В твоей локации.")
    text_to_synthesize = llm_response_text if llm_response_text else "Hello, this is a test message."
    logger.info(f"LLM сгенерировала текст: {text_to_synthesize}")

    # 3. Синтез речи
    logger.info(f"Синтезируем текст: '{text_to_synthesize}'")
    pcm_data = await tts.synthesize(text_to_synthesize, voice=tts.voice, retries=3)
    if pcm_data:
        logger.info(f"✅ Синтез успешен! Получено {len(pcm_data)} байт PCM-данных.")

        # Сохранение синтезированного звука в WAV-файл
        output_filename = "output.wav"
        try:
            with wave.open(output_filename, 'wb') as wf:
                wf.setnchannels(1)  # Моно
                wf.setsampwidth(2)  # 16 бит (2 байта)
                wf.setframerate(8000)  # 8000 Гц
                wf.writeframes(pcm_data)
            logger.info(f"✅ Звук успешно сохранен в {output_filename}")
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении WAV-файла: {e}")
# Запуск теста
if __name__ == "__main__":
    asyncio.run(test_tts_library())