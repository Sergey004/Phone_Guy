import asyncio
import numpy as np
import wave
import audioop
from abc import ABC, abstractmethod
from audio_codecs import AudioCodec

class AudioSource(ABC):
    @abstractmethod
    def get_frame(self, samples_needed: int) -> bytes:
        pass

class TTSSource(AudioSource):
    def __init__(self, sample_rate=8000):
        self.queue = asyncio.Queue()
        self.buffer = b''
        self.sample_rate = sample_rate
        self.is_speaking = False

    def push_audio(self, audio_array: np.ndarray, src_rate=24000):
        if src_rate != self.sample_rate:
            step = int(src_rate / self.sample_rate)
            audio_array = audio_array[::step]

        pcm16 = AudioCodec.float_to_pcm16(audio_array)
        
        # Здесь исправление уже внутри AudioCodec.pcm16_to_alaw
        alaw_bytes = AudioCodec.pcm16_to_alaw(pcm16)
        
        self.buffer += alaw_bytes
        self.is_speaking = True

    def get_frame(self, samples_needed: int) -> bytes:
        bytes_needed = samples_needed
        if len(self.buffer) >= bytes_needed:
            chunk = self.buffer[:bytes_needed]
            self.buffer = self.buffer[bytes_needed:]
            return chunk
        else:
            chunk = self.buffer
            self.buffer = b''
            missing = bytes_needed - len(chunk)
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
            # Проверка формата
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
        
        # !!! ИСПРАВЛЕНО ЗДЕСЬ !!!
        # width=2, потому что WAV файл 16-битный
        converted = audioop.lin2alaw(data, 2)

        if len(converted) < samples_needed:
            if self.loop:
                self.wf.rewind()
                remaining = samples_needed - len(converted)
                data_new = self.wf.readframes(remaining)
                # !!! И ЗДЕСЬ ТОЖЕ !!!
                converted += audioop.lin2alaw(data_new, 2)
            else:
                padding = b'\xd5' * (samples_needed - len(converted))
                converted += padding
                self.active = False
        
        return converted