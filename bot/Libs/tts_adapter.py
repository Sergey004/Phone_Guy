# bot/tts_adapter.py
import asyncio
import logging
import httpx
import ffmpeg
import rich.logging
from .rtp_streamer import ByteStreamMediaPort

logging.basicConfig(
    level="INFO",
    format="%(message)s",
    handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
)

class TTSAdapter:
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('TTS')
        tts_cfg = config.get('tts', {})
        self.api_key = tts_cfg.get('api_key', 'your_super_secret_api_key')
        self.base_url = tts_cfg.get('base_url', 'http://localhost:8000/v1')
        self.model = tts_cfg.get('model', '1.5B')
        self.tokenizer_path = tts_cfg.get('tokenizer_path', 'Qwen/Qwen2.5-7B')
        self.voice = tts_cfg.get('voice', 'PhoneGuy_FNAF1_01')
        self.sample_rate = 8000
        self._speak_lock = asyncio.Lock()

    async def check_health(self, retries: int = 3, backoff: float = 1.0) -> bool:
        health_url = f"{self.base_url}/healthcheck"
        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(health_url)
                    response.raise_for_status()
                    self.logger.info(f"TTS server health check successful: {health_url}")
                    return True
            except httpx.HTTPStatusError as e:
                self.logger.error(f"TTS health check failed (attempt {attempt}/{retries}): HTTP {e.response.status_code} - {e.response.text}")
            except httpx.RequestError as e:
                self.logger.error(f"TTS health check failed (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    await asyncio.sleep(backoff * attempt)
            except Exception as e:
                self.logger.error(f"Unexpected error during TTS health check (attempt {attempt}/{retries}): {e}")
        self.logger.error("All TTS health check attempts failed.")
        return False

    async def synthesize(self, text: str, voice: str = None, retries: int = 3) -> bytes:
        voice = voice or self.voice
        self.logger.info(f"🎤 Начинаем синтез текста: '{text[:50]}...'")
        self.logger.info(f"🎤 Параметры: model={self.model}, voice={voice}, url={self.base_url}")
        
        payload = {
            "model": self.model,
            "tokenizer_path": self.tokenizer_path,
            "input": text,
            "voice": voice
        }
        headers = {"x-api-key": self.api_key}
        
        self.logger.info(f"🎤 Отправляем запрос на TTS сервер: {self.base_url}/audio/speech")
        
        for attempt in range(1, retries + 1):
            self.logger.info(f"🎤 Попытка синтеза {attempt}/{retries}")
            
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    self.logger.info(f"🎤 Отправка запроса: длина текста = {len(text)}, заголовки = {list(headers.keys())}")
                    
                    response = await client.post(f"{self.base_url}/audio/speech", json=payload, headers=headers)
                    
                    self.logger.info(f"🎤 Ответ получен: статус = {response.status_code}, длина контента = {len(response.content)} байт")
                    
                    if response.status_code != 200:
                        self.logger.error(f"🎤 Неуспешный статус: {response.status_code}, текст: {response.text}")
                        response.raise_for_status()
                    
                    wav_data = response.content
                    self.logger.info(f"🎤 Получены WAV данные: {len(wav_data)} байт")
                    
                    # Convert to PCM s16le, 8kHz, mono
                    try:
                        self.logger.info("🎤 Конвертируем WAV в PCM формат...")
                        process = (
                            ffmpeg.input('pipe:', format='wav')
                            .output('pipe:', format='s16le', ar=self.sample_rate, ac=1)
                            .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
                        )
                        
                        self.logger.info("🎤 Запускаем FFmpeg процесс...")
                        pcm_data, stderr = await asyncio.get_event_loop().run_in_executor(None, lambda: process.communicate(input=wav_data))
                        
                        self.logger.info(f"🎤 FFmpeg завершен: PCM данные = {len(pcm_data)} байт")
                        
                        if len(pcm_data) == 0:
                            self.logger.warning("🎤 PCM данные пустые после конвертации")
                            return b''
                        
                        self.logger.info(f"✅ Синтез успешно завершен: {len(pcm_data)} байт PCM данных")
                        return pcm_data
                        
                    except ffmpeg.Error as e:
                        err_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
                        self.logger.error(f"🎤 Ошибка FFmpeg на попытке {attempt}/{retries}: {err_msg}")
                        if attempt < retries:
                            continue
                        return b''
                    except Exception as e:
                        self.logger.error(f"🎤 Неожиданная ошибка FFmpeg на попытке {attempt}/{retries}: {e}", exc_info=True)
                        if attempt < retries:
                            continue
                        return b''
                        
            except httpx.HTTPStatusError as e:
                self.logger.error(f"🎤 HTTP ошибка на попытке {attempt}/{retries}: статус {e.response.status_code}")
                self.logger.error(f"🎤 Ответ сервера: {e.response.text}")
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                return b''
                
            except httpx.ReadTimeout as e:
                self.logger.error(f"🎤 Таймаут чтения на попытке {attempt}/{retries}: {e}")
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                return b''
                
            except httpx.RequestError as e:
                self.logger.error(f"🎤 Ошибка запроса на попытке {attempt}/{retries}: {e}")
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                return b''
                
            except Exception as e:
                self.logger.error(f"🎤 Неожиданная ошибка на попытке {attempt}/{retries}: {e}", exc_info=True)
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
                    continue
                return b''
        
        self.logger.error("🎤 Все попытки синтеза завершились неудачей.")
        return b''

    async def speak(self, text: str, media_port: 'ByteStreamMediaPort'):
        async with self._speak_lock:
            self.logger.info(f"🎤 TTS speak: '{text[:50]}...'")
            self.logger.info(f"🎤 Media port: {type(media_port).__name__}")
            self.logger.info(f"🎤 Text length: {len(text)} characters, {len(text.split())} words")
            
            try:
                # Wait for TTS server response
                self.logger.info("🎤 Начинаем синтез речи...")
                pcm_data = await self.synthesize(text)
                
                self.logger.info(f"🎤 Получены PCM данные: {len(pcm_data)} байт")
                
                if not pcm_data:
                    self.logger.warning("🎤 Нет PCM данных от synthesize – отправляем тишину.")
                    return
                
                # Check if media_port is valid
                if media_port is None:
                    self.logger.error("🎤 Media port is None, cannot update playback data")
                    return
                
                self.logger.info("🎤 Обновляем данные воспроизведения в медиа-порту...")
                # Update media port only after successful synthesis
                media_port.update_playback_data(pcm_data)
                self.logger.info("✅ TTS PCM данные успешно обновлены в медиа-порту.")
                
            except Exception as e:
                self.logger.error(f"🎤 Ошибка TTS speak: {e}", exc_info=True)
                self.logger.error(f"🎤 Тип ошибки: {type(e).__name__}")
                self.logger.error(f"🎤 Детали ошибки: {str(e)}")
