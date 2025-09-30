import wave
import logging
import pjsua2 as pj
import numpy as np
from scipy.io import wavfile

logging.basicConfig(level=logging.INFO)


class RtpStreamerMediaPort(pj.AudioMediaPort):
    """
    Custom AudioMediaPort for SWIG pjsua2:
    - Writes incoming audio to a buffer.
    - Plays back a prepared WAV ("output.wav").
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
        self.buffer = bytearray()

        if input_wav:
            try:
                samplerate, raw_data = wavfile.read(input_wav)
                logging.info(f"Input WAV: samplerate={samplerate}, channels={1 if len(raw_data.shape) == 1 else raw_data.shape[1]}, dtype={raw_data.dtype}")
                self.channels = 1 if len(raw_data.shape) == 1 else raw_data.shape[1]
                self.clock_rate = samplerate
                sampwidth = raw_data.dtype.itemsize

                if sampwidth == 4:
                    # Convert float32 to int16
                    arr = np.frombuffer(raw_data, dtype=np.float32)
                    arr = np.clip(arr, -1.0, 1.0)
                    arr = (arr * 32767).astype(np.int16)
                    self.playback_data = arr.tobytes()
                    logging.info(f"Converted float32 WAV to PCM16: {input_wav}, length={len(self.playback_data)} bytes")
                else:
                    self.playback_data = raw_data.tobytes()
                    logging.info(f"Loaded PCM WAV: {input_wav}, length={len(self.playback_data)} bytes")
                
                # Verify playback data
                if not self.playback_data:
                    logging.error("Playback data is empty after loading!")
                else:
                    logging.info(f"Playback data ready: {len(self.playback_data)} bytes, {self.clock_rate}Hz, {self.channels} channel(s)")
            except FileNotFoundError:
                logging.warning(f"No WAV found for playback: {input_wav}, will output silence")
                self.playback_data = b''
            except Exception as e:
                logging.error(f"Error loading WAV file {input_wav}: {e}")
                self.playback_data = b''

    def onFrameRequested(self, frame):
        """Called when the call requests audio data"""
        logging.debug(f"Frame requested: size={frame.size}, pos={self.playback_pos}")
        if self.playback_data:
            chunk_size = frame.size
            end = self.playback_pos + chunk_size
            data = self.playback_data[self.playback_pos:end]

            if not data:
                logging.warning(f"No data available at pos={self.playback_pos}, sending silence")
                frame.buf = bytes([0] * frame.size)
                frame.size = frame.size
            else:
                frame.buf = data
                frame.size = len(data)
                logging.debug(f"Providing {len(data)} bytes for playback")

            # Loop playback
            if end >= len(self.playback_data):
                self.playback_pos = 0
                logging.info("Reached end of playback data, looping")
            else:
                self.playback_pos = end

            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
        else:
            logging.warning("No playback data, sending silence")
            frame.buf = bytes([0] * frame.size)
            frame.size = frame.size
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO

    def onFrameReceived(self, frame):
        """Called when audio is received from the call"""
        if frame.type == pj.PJMEDIA_FRAME_TYPE_AUDIO and frame.size > 0:
            logging.debug(f"Received frame: size={frame.size}")
            self.buffer.extend(frame.buf[:frame.size])

    def save_to_wav(self, filename):
        """Save accumulated incoming audio to WAV"""
        if not self.buffer:
            logging.warning("Buffer empty, nothing to save")
            return

        with wave.open(filename, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.clock_rate)
            wf.writeframes(self.buffer)

        logging.info(f"Saved {len(self.buffer)} bytes to {filename}")