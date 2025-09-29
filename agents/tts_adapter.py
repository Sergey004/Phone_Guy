import asyncio
import logging
import httpx
import ffmpeg
import rich.logging

from Sippy.SIP import SIPClient

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
        self.sample_rate = 8000  # Для RTP: 8kHz mono s16le
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
                self.logger.error(f"TTS health check failed (attempt {attempt}/{retries}): HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                self.logger.error(f"TTS health check failed (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    await asyncio.sleep(backoff * attempt)
            except Exception as e:
                self.logger.error(f"Unexpected error during TTS health check (attempt {attempt}/{retries}): {e}")
        self.logger.error("All TTS health check attempts failed.")
        return False

    async def synthesize(self, text: str, voice: str = None) -> bytes:
        voice = voice or self.voice
        payload = {
            "model": self.model,
            "tokenizer_path": self.tokenizer_path,
            "input": text,
            "voice": voice
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }
        url = f"{self.base_url}/audio/speech"
        self.logger.debug(f"Sending TTS request: {payload}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                self.logger.debug(f"TTS response: status={response.status_code}, "
                                f"content-type={response.headers.get('content-type', 'unknown')}, "
                                f"size={len(response.content)} bytes")

            audio_bytes = response.content
            if not audio_bytes:
                self.logger.warning("TTS server returned empty audio.")
                return b''

            # Декодируем любой формат в PCM s16le 8kHz mono через FFmpeg
            self.logger.debug("Decoding audio to PCM s16le 8kHz mono via FFmpeg.")
            try:
                process = (
                    ffmpeg
                    .input('pipe:', format=None)  # Auto-detect MP3/WAV/OGG
                    .output('pipe:', format='s16le', acodec='pcm_s16le', ar=8000, ac=1)
                    .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True, quiet=True)
                )
                pcm_data, stderr = process.communicate(input=audio_bytes)
                process.stdin.close()
                process.wait()

                if pcm_data:
                    self.logger.info(f"Decoded PCM: {len(pcm_data)} bytes (~{len(pcm_data)/(8000*2):.1f}s)")
                    return pcm_data
                else:
                    self.logger.warning("FFmpeg returned empty PCM output.")
                    return b''

            except ffmpeg.Error as e:
                err_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
                self.logger.error(f"FFmpeg decode error: {err_msg}")
                return b''
            except Exception as e:
                self.logger.error(f"Unexpected decode error: {e}", exc_info=True)
                return b''

        except httpx.HTTPStatusError as e:
            self.logger.error(f"TTS HTTP error {e.response.status_code}: {e.response.text}")
            return b''
        except Exception as e:
            self.logger.error(f"TTS synthesize failed: {e}", exc_info=True)
            return b''

    async def speak(self, text: str, client: SIPClient):
        async with self._speak_lock:
            self.logger.info(f"Speaking: '{text[:50]}...'")
            try:
                pcm_data = await self.synthesize(text)
                if not pcm_data:
                    self.logger.warning("No PCM data from synthesize — sending silence.")
                    return

                await client.start_streaming_input()
                self.logger.debug(f"Started streaming input, PCM size: {len(pcm_data)} bytes")

                frame_size = 320  # 20ms: 160 samples * 2 bytes (s16le)
                offset = 0
                while offset < len(pcm_data):
                    frame = pcm_data[offset:offset + frame_size]
                    if len(frame) < frame_size:
                        frame += b'\x00' * (frame_size - len(frame))
                    client.push_stream_pcm(frame, sample_rate=8000, sample_width=2, channels=1)
                    offset += frame_size
                    await asyncio.sleep(0.02)

                await client.end_streaming_input()
                finished = await client.wait_stream_finished(timeout=10.0)
                if finished:
                    self.logger.info("TTS speak completed successfully.")
                else:
                    self.logger.warning("TTS stream timeout — possible buffer underrun.")
            except Exception as e:
                self.logger.error(f"TTS speak error: {e}", exc_info=True)
                try:
                    await client.end_streaming_input()
                except:
                    pass