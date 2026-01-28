import asyncio
import numpy as np
import wave
import audioop
from abc import ABC, abstractmethod
from audio_codecs import AudioCodec

class AudioSource(ABC):
    @abstractmethod
    def get_frame(self, samples_needed: int) -> bytes:
        """Должен вернуть A-Law закодированные байты для отправки."""
        pass

class TTSSource(AudioSource):
    def __init__(self, target_sample_rate=8000):
        self.buffer = bytearray()
        self.target_sample_rate = target_sample_rate
        # Состояние для ресемплера (чтобы не было щелчков между чанками)
        self._resample_state = None 

    def push_audio(self, audio_array: np.ndarray, src_rate=24000):
        """
        Принимает chunk аудио (float32, -1.0..1.0) от нейросети.
        Конвертирует в PCM16 -> Ресемплит -> A-Law -> Кладет в буфер.
        """
        # 1. Float32 -> Int16 PCM (bytes)
        # Важно сделать это ДО ресемплинга, так как audioop работает с байтами
        pcm16_data = AudioCodec.float_to_pcm16(audio_array).tobytes()

        # 2. Resampling (24000/22050 -> 8000)
        # Используем ratecv - это качественный линейный ресемплер внутри python
        if src_rate != self.target_sample_rate:
            pcm16_data, self._resample_state = audioop.ratecv(
                pcm16_data, 
                2,                          # width=2 (16 bit)
                1,                          # channels=1
                src_rate,                   # in_rate
                self.target_sample_rate,    # out_rate
                self._resample_state        # state
            )

        # 3. PCM16 -> A-Law (G.711)
        # width=2, так как у нас 16-битный звук после конвертации
        alaw_bytes = audioop.lin2alaw(pcm16_data, 2)

        # 4. Добавляем в буфер
        self.buffer.extend(alaw_bytes)

    def get_frame(self, samples_needed: int) -> bytes:
        # Для G.711 A-law 1 сэмпл = 1 байт
        bytes_needed = samples_needed
        
        if len(self.buffer) >= bytes_needed:
            # Отрезаем кусок от буфера
            chunk = self.buffer[:bytes_needed]
            # Удаляем этот кусок из буфера (эффективно для bytearray)
            del self.buffer[:bytes_needed]
            return bytes(chunk)
        else:
            # Если буфер пуст (AI "задумался"), шлем тишину
            # Это предотвращает разрыв соединения, просто будет пауза в голосе
            return b'\xd5' * bytes_needed

class FilePlayerSource(AudioSource):
    def __init__(self, filepath, loop=False):
        self.filepath = filepath
        self.loop = loop
        self.wf = None
        self.active = False
        self._open()

    def _open(self):
        try:
            self.wf = wave.open(self.filepath, 'rb')
            if self.wf.getnchannels() != 1:
                print(f"[WARN] Файл {self.filepath} стерео! Используйте convert_audio.py.")
            if self.wf.getframerate() != 8000:
                print(f"[WARN] Файл {self.filepath} не 8000Hz! Звук будет искажен.")
            self.active = True
        except Exception as e:
            print(f"[ERR] Не удалось открыть файл: {e}")
            self.active = False

    def get_frame(self, samples_needed: int) -> bytes:
        if not self.active or not self.wf:
            return b'\xd5' * samples_needed

        data = self.wf.readframes(samples_needed)
        
        # PCM16 (wav) -> A-law
        converted = audioop.lin2alaw(data, 2)

        if len(converted) < samples_needed:
            if self.loop:
                self.wf.rewind()
                remaining = samples_needed - len(converted)
                data_new = self.wf.readframes(remaining)
                converted += audioop.lin2alaw(data_new, 2)
            else:
                padding = b'\xd5' * (samples_needed - len(converted))
                converted += padding
                self.active = False
        
        return converted