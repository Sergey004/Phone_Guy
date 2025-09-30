import wave
import logging
import pjsua2 as pj
import numpy as np
from scipy.io import wavfile

logging.basicConfig(level=logging.INFO)


class RtpStreamerMediaPort(pj.AudioMediaPort):
    """
    Кастомный AudioMediaPort для SWIG pjsua2:
    - пишет входящий звук в буфер,
    - проигрывает подготовленный WAV ("output.wav").
    """

    def __init__(self, input_wav=None, clock_rate=8000):
        super().__init__()
        logging.info(f"RtpStreamerMediaPort initialized with input_wav: {input_wav}")
        self.playback_data = b''
        self.playback_pos = 0
        self.input_wav = input_wav
        self.clock_rate = clock_rate
        self.channels = 1
        self.bits_per_sample = 16
        self.rtp_port_id = -1
        self.is_playing = False
        self.is_receiving = False
        self.received_frames = []
        
        # ✅ ИСПРАВЛЕНИЕ 1: Инициализируем buffer
        self.buffer = bytearray()

        if input_wav:
            try:
                samplerate, raw_data = wavfile.read(input_wav)
                self.channels = 1 if len(raw_data.shape) == 1 else raw_data.shape[1]
                self.clock_rate = samplerate
                sampwidth = raw_data.dtype.itemsize

                if sampwidth == 4:
                    # float32 → int16
                    arr = np.frombuffer(raw_data, dtype=np.float32)
                    arr = np.clip(arr, -1.0, 1.0)
                    arr = (arr * 32767).astype(np.int16)
                    self.playback_data = arr.tobytes()
                    logging.info(f"Loaded float WAV and converted to PCM16: {input_wav}")
                    logging.info(f"Playback data length: {len(self.playback_data)} bytes")
                else:
                    self.playback_data = raw_data.tobytes()
                    logging.info(f"Loaded PCM WAV: {input_wav} ({len(raw_data)} bytes)")
                    logging.info(f"Playback data length: {len(self.playback_data)} bytes")
            except FileNotFoundError:
                logging.warning(f"No WAV found for playback: {input_wav}, will output silence")
                self.playback_data = b''
            except Exception as e:
                logging.error(f"Error loading WAV file {input_wav}: {e}")
                logging.warning(f"Will output silence due to WAV loading error.")
                self.playback_data = b''

    def onFrameRequested(self, frame):
        """Когда звонку нужен наш звук"""
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
        """Когда прилетает звук от собеседника"""
        if frame.type == pj.PJMEDIA_FRAME_TYPE_AUDIO and frame.size > 0:
            self.buffer.extend(frame.buf[:frame.size])

    def save_to_wav(self, filename):
        """Сохраняем накопленное входящее аудио"""
        if not self.buffer:
            logging.warning("Buffer empty, nothing to save")
            return

        with wave.open(filename, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16 бит
            wf.setframerate(self.clock_rate)
            wf.writeframes(self.buffer)

        logging.info(f"Saved {len(self.buffer)} bytes of incoming audio to {filename}")