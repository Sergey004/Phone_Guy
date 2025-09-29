import wave
import logging
import pjsua2 as pj   # твой SWIG биндинг
import numpy as np
logging.basicConfig(level=logging.INFO)


class RtpStreamerMediaPort(pj.AudioMediaPort):
    """
    Кастомный AudioMediaPort для SWIG pjsua2:
    - пишет входящий звук в буфер,
    - проигрывает подготовленный WAV ("output.wav").
    """

    def __init__(self, clock_rate=8000, channel_count=1, samples_per_frame=160, input_wav="output.wav"):
        super().__init__()  # без AudioMediaFormat
        self.clock_rate = clock_rate
        self.channels = channel_count
        self.samples_per_frame = samples_per_frame
        self.buffer = bytearray()

        # Загружаем WAV для проигрывания
        self.playback_data = None
        self.playback_pos = 0
        

        try:
            with wave.open(input_wav, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                self.channels = wf.getnchannels()
                self.clock_rate = wf.getframerate()
                sampwidth = wf.getsampwidth()

            if sampwidth == 4:
                # float32 → int16
                arr = np.frombuffer(raw, dtype=np.float32)
                arr = np.clip(arr, -1.0, 1.0)
                arr = (arr * 32767).astype(np.int16)
                self.playback_data = arr.tobytes()
                logging.info(f"Loaded float WAV and converted to PCM16: {input_wav}")
            else:
                self.playback_data = raw
                logging.info(f"Loaded PCM WAV: {input_wav} ({len(raw)} bytes)")
        except FileNotFoundError:
            logging.warning(f"No WAV found for playback: {input_wav}, will output silence")

    def onFrameRequested(self, frame):
        # Когда звонку нужен наш звук
        if self.playback_data:
            chunk_size = frame.size
            end = self.playback_pos + chunk_size
            data = self.playback_data[self.playback_pos:end]

            # зацикливаем воспроизведение
            if end >= len(self.playback_data):
                self.playback_pos = 0
            else:
                self.playback_pos = end

            frame.buf = data
            frame.size = len(data)
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
        else:
            # Если нет файла — шлём тишину
            frame.buf = bytes([0] * frame.size)
            frame.size = frame.size
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO

    def onFrameReceived(self, frame):
        # Когда прилетает звук от собеседника
        if frame.type == pj.PJMEDIA_FRAME_TYPE_AUDIO and frame.size > 0:
            self.buffer.extend(frame.buf[:frame.size])

    def save_to_wav(self, filename):
        # Сохраняем накопленное входящее аудио
        if not self.buffer:
            logging.warning("Buffer empty, nothing to save")
            return

        with wave.open(filename, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16 бит
            wf.setframerate(self.clock_rate)
            wf.writeframes(self.buffer)

        logging.info(f"Saved {len(self.buffer)} bytes of incoming audio to {filename}")
