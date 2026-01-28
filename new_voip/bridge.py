import asyncio
import numpy as np
import audioop
from audio_engine import AudioSource

class PhoneBridgePort(AudioSource):
    def __init__(self):
        self.buffer = bytearray()
        self.stats = {"duration_seconds": 0.0}
        # Состояние ресемплера (нужно для потокового аудио, чтобы не было щелчков)
        self._resample_state = None
        self._last_sr = 0

    def update_playback_data(self, pcm_bytes: bytes, sample_rate=24000, validate=True):
        """
        Принимает PCM данные и их частоту (sample_rate).
        Автоматически ресемплит всё в 8000 Hz для телефона.
        """
        if not pcm_bytes:
            return False
            
        try:
            # 1. Проверка четности байт (критично для 16-bit PCM)
            if len(pcm_bytes) % 2 != 0:
                pcm_bytes = pcm_bytes[:-1]

            # 2. Если частота изменилась (например, другая модель), сбрасываем состояние
            if sample_rate != self._last_sr:
                self._resample_state = None
                self._last_sr = sample_rate

            # 3. Ресемплинг (Dynamic -> 8000)
            if sample_rate != 8000:
                # audioop.ratecv(fragment, width, nchannels, in_rate, out_rate, state, weightA=1, weightB=0)
                # width=2 (16-bit), channels=1 (Mono)
                pcm_8k, self._resample_state = audioop.ratecv(
                    pcm_bytes, 2, 1, sample_rate, 8000, self._resample_state
                )
            else:
                pcm_8k = pcm_bytes
            
            # 4. Проверка четности после ресемплинга
            if len(pcm_8k) % 2 != 0:
                pcm_8k = pcm_8k[:-1]

            # 5. Конвертация в G.711 A-Law (телефонный стандарт)
            alaw = audioop.lin2alaw(pcm_8k, 2)
            self.buffer.extend(alaw)
            
            # Статистика
            samples = len(pcm_bytes) / 2
            self.stats["duration_seconds"] += samples / sample_rate
            return True
        except Exception as e:
            print(f"Bridge Error: {e}")
            return False

    def get_stats(self):
        return self.stats

    def get_frame(self, samples_needed: int) -> bytes:
        bytes_needed = samples_needed
        if len(self.buffer) >= bytes_needed:
            chunk = self.buffer[:bytes_needed]
            del self.buffer[:bytes_needed]
            return bytes(chunk)
        else:
            return b'\xd5' * bytes_needed