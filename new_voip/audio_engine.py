import asyncio
import numpy as np
import wave
import time
from abc import ABC, abstractmethod
from audio_codecs import AudioCodec

class AudioSource(ABC):
    @abstractmethod
    def get_frame(self, samples_needed: int) -> bytes:
        """Должен вернуть A-Law закодированные байты для отправки."""
        pass

class TTSSource(AudioSource):
    def __init__(self, sample_rate=8000):
        self.queue = asyncio.Queue()
        self.buffer = b''
        self.sample_rate = sample_rate
        self.is_speaking = False

    def push_audio(self, audio_array: np.ndarray, src_rate=24000):
        """
        Принимает numpy array (float32).
        Если src_rate != 8000, делает грубый ресемплинг.
        """
        # 1. Resampling (простейший: пропуск сэмплов)
        if src_rate != self.sample_rate:
            step = int(src_rate / self.sample_rate)
            audio_array = audio_array[::step]

        # 2. Convert to int16
        pcm16 = AudioCodec.float_to_pcm16(audio_array)
        
        # 3. Convert to A-Law
        alaw_bytes = AudioCodec.pcm16_to_alaw(pcm16)
        
        # 4. Put into buffer (синхронно, так как это байты)
        self.buffer += alaw_bytes
        self.is_speaking = True

    def get_frame(self, samples_needed: int) -> bytes:
        # A-law: 1 сэмпл = 1 байт.
        bytes_needed = samples_needed
        
        if len(self.buffer) >= bytes_needed:
            chunk = self.buffer[:bytes_needed]
            self.buffer = self.buffer[bytes_needed:]
            return chunk
        else:
            # Если буфер пуст или почти пуст
            chunk = self.buffer
            self.buffer = b''
            padding = AudioCodec.create_silence(duration_ms=0) # dummy
            missing = bytes_needed - len(chunk)
            # Заполняем тишиной остаток
            return chunk + (b'\xd5' * missing)

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
            if self.wf.getnchannels() != 1 or self.wf.getframerate() != 8000:
                print(f"[WARN] Файл {self.filepath} должен быть 8000Hz Mono!")
            self.active = True
        except Exception as e:
            print(f"[ERR] Не удалось открыть файл: {e}")
            self.active = False

    def get_frame(self, samples_needed: int) -> bytes:
        if not self.active or not self.wf:
            return b'\xd5' * samples_needed

        data = self.wf.readframes(samples_needed)
        
        # Конвертация PCM16 (wav) -> A-law
        # Если файл уже A-law, пропускаем. Допустим файл PCM16.
        import audioop
        # width=1 для 8-bit A-law (как в pyVoIP)
        converted = audioop.lin2alaw(data, 1)

        if len(converted) < samples_needed:
            if self.loop:
                self.wf.rewind()
                remaining = samples_needed - len(converted)
                data_new = self.wf.readframes(remaining)
                converted += audioop.lin2alaw(data_new, 1)
            else:
                padding = b'\xd5' * (samples_needed - len(converted))
                converted += padding
                self.active = False
        
        return converted