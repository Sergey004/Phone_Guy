import numpy as np
import audioop
from telephony.audio_engine import AudioSource

class PhoneBridgePort(AudioSource):
    def __init__(self):
        self.buffer = bytearray()
        self.stats = {"duration_seconds": 0.0}
        self._resample_state = None
        self._last_sr = 0
        
        # === НАСТРОЙКИ ШУМА ===
        # 0.0005 = ОЧЕНЬ ТИХО. 
        # Достаточно, чтобы линия не "хлопала" в цифровую тишину,
        # но недостаточно, чтобы вызвать эхо у собеседника.
        self.noise_level = 0.0005 
        self.bg_noise_buffer = self._generate_balanced_noise(duration=5.0)
        self.bg_pos = 0

    def _generate_balanced_noise(self, duration=5.0):
        """
        Генерирует очень тихий фоновый шум.
        """
        sample_rate = 8000
        num_samples = int(sample_rate * duration)
        
        # 1. Белый шум
        white = np.random.normal(0, 1, num_samples)
        
        # 2. Легкое сглаживание (Pink shift)
        window_size = 2
        window = np.ones(window_size) / window_size
        filtered_noise = np.convolve(white, window, mode='same')
        
        # 3. Нормализация
        max_val = np.max(np.abs(filtered_noise))
        if max_val > 0:
            filtered_noise = filtered_noise / max_val
            
        # 4. Применяем громкость
        filtered_noise = filtered_noise * self.noise_level
        
        # 5. Конвертация в PCM 16-bit
        noise_pcm = (filtered_noise * 32767).astype(np.int16)
        
        # 6. В A-Law
        return audioop.lin2alaw(noise_pcm.tobytes(), 2)

    def update_playback_data(self, pcm_bytes: bytes, sample_rate=24000, validate=True):
        if not pcm_bytes:
            return False
            
        try:
            if len(pcm_bytes) % 2 != 0:
                pcm_bytes = pcm_bytes[:-1]

            if sample_rate != self._last_sr:
                self._resample_state = None
                self._last_sr = sample_rate

            if sample_rate != 8000:
                pcm_8k, self._resample_state = audioop.ratecv(
                    pcm_bytes, 2, 1, sample_rate, 8000, self._resample_state
                )
            else:
                pcm_8k = pcm_bytes
            
            if len(pcm_8k) % 2 != 0:
                pcm_8k = pcm_8k[:-1]

            alaw = audioop.lin2alaw(pcm_8k, 2)
            self.buffer.extend(alaw)
            
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
            if self.buffer:
                self.buffer.clear()
            
            start = self.bg_pos
            end = self.bg_pos + bytes_needed
            
            if end > len(self.bg_noise_buffer):
                chunk = self.bg_noise_buffer[start:]
                remaining = bytes_needed - len(chunk)
                chunk += self.bg_noise_buffer[:remaining]
                self.bg_pos = remaining
            else:
                chunk = self.bg_noise_buffer[start:end]
                self.bg_pos = end
            
            return chunk