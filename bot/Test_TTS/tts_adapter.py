# bot/tts_adapter.py
import asyncio
import logging
import httpx
import ffmpeg
import rich.logging
from rtp_streamer import ByteStreamMediaPort

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
        payload = {
            "model": self.model,
            "tokenizer_path": self.tokenizer_path,
            "input": text,
            "voice": voice
        }
        headers = {"x-api-key": self.api_key}
        for attempt in range(1, retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    self.logger.debug(f"Sending TTS request (attempt {attempt}/{retries}): {text[:50]}...")
                    response = await client.post(f"{self.base_url}/audio/speech", json=payload, headers=headers)
                    response.raise_for_status()
                    wav_data = response.content
                    self.logger.debug(f"Received {len(wav_data)} bytes from TTS server")

                    # Convert to PCM s16le, 8kHz, mono
                    try:
                        process = (
                            ffmpeg.input('pipe:', format='wav')
                            .output('pipe:', format='s16le', ar=self.sample_rate, ac=1)
                            .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
                        )
                        pcm_data, stderr = await asyncio.get_event_loop().run_in_executor(None, lambda: process.communicate(input=wav_data))
                        self.logger.info(f"Decoded PCM: {len(pcm_data)} bytes (~{len(pcm_data)/(self.sample_rate*2):.1f}s)")
                        return pcm_data
                    except ffmpeg.Error as e:
                        err_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
                        self.logger.error(f"FFmpeg decode error on attempt {attempt}/{retries}: {err_msg}")
                        continue
                    except Exception as e:
                        self.logger.error(f"Unexpected decode error on attempt {attempt}/{retries}: {e}", exc_info=True)
                        continue
            except httpx.HTTPStatusError as e:
                self.logger.error(f"TTS HTTP error on attempt {attempt}/{retries}: HTTP {e.response.status_code} - {e.response.text}")
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
            except httpx.ReadTimeout as e:
                self.logger.error(f"TTS ReadTimeout on attempt {attempt}/{retries}: {e}")
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
            except httpx.RequestError as e:
                self.logger.error(f"TTS request error on attempt {attempt}/{retries}: {e}")
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
            except Exception as e:
                self.logger.error(f"TTS synthesize failed on attempt {attempt}/{retries}: {e}", exc_info=True)
                if attempt < retries:
                    await asyncio.sleep(1.0 * attempt)
        self.logger.error("All TTS synthesis attempts failed.")
        return b''

    async def speak(self, text: str, media_port: 'ByteStreamMediaPort'):
        async with self._speak_lock:
            self.logger.info(f"Speaking: '{text[:50]}...'")
            try:
                # Wait for TTS server response
                pcm_data = await self.synthesize(text)
                if not pcm_data:
                    self.logger.warning("No PCM data from synthesize – sending silence.")
                    return
                
                # Check if media_port is valid
                if media_port is None:
                    self.logger.error("Media port is None, cannot update playback data")
                    return
                
                # Update media port only after successful synthesis
                media_port.update_playback_data(pcm_data)
                self.logger.info("TTS PCM data updated in media port.")
            except Exception as e:
                self.logger.error(f"TTS speak error: {e}", exc_info=True)