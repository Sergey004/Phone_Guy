"""
Audio processing module for VoIP client.
Handles audio capture, playback, and codec conversion (PCMU/PCMA).
"""

import audioop
import pyaudio
import threading
import queue
import logging
import time
from .config import AUDIO_FRAME_SIZE, CODEC_PCMU, CODEC_PCMA

class AudioProcessor:
    """
    Handles audio capture, encoding, decoding, and playback.
    """
    def __init__(self, codec=CODEC_PCMU, sample_rate=8000):
        self.codec = codec
        self.sample_rate = sample_rate
        self.pcm_queue = queue.Queue()
        self.audio_thread = None
        self.running = False
        self.pyaudio = pyaudio.PyAudio()

    def start(self):
        """
        Start audio processing threads.
        """
        self.running = True
        self.audio_thread = threading.Thread(target=self._process_audio)
        self.audio_thread.daemon = True
        self.audio_thread.start()

    def stop(self):
        """
        Stop audio processing.
        """
        self.running = False
        if self.audio_thread:
            self.audio_thread.join()
        self.pyaudio.terminate()

    def _process_audio(self):
        """
        Main audio processing loop.
        Only handles playback of PCM frames pushed via add_audio_frame().
        """
        stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=False,
            output=True,
            frames_per_buffer=AUDIO_FRAME_SIZE
        )
        try:
            while self.running:
                try:
                    # Block briefly waiting for a frame to play
                    pcm_to_play = self.pcm_queue.get(timeout=0.1)
                    stream.write(pcm_to_play)
                except queue.Empty:
                    # No frame available yet; loop again
                    continue
                except Exception as e:
                    logging.error(f"Audio processing error: {e}")
                    time.sleep(0.01)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

    def encode_pcm(self, pcm_data):
        """
        Encode PCM data to selected codec (PCMU or PCMA).
        """
        if self.codec == CODEC_PCMU:
            return audioop.lin2ulaw(pcm_data, 2)
        elif self.codec == CODEC_PCMA:
            return audioop.lin2alaw(pcm_data, 2)
        else:
            raise ValueError(f"Unsupported codec: {self.codec}")

    def decode_pcm(self, encoded_data):
        """
        Decode encoded data (PCMU or PCMA) to PCM.
        """
        if self.codec == CODEC_PCMU:
            return audioop.ulaw2lin(encoded_data, 2)
        elif self.codec == CODEC_PCMA:
            return audioop.alaw2lin(encoded_data, 2)
        else:
            raise ValueError(f"Unsupported codec: {self.codec}")

    def add_audio_frame(self, frame):
        """
        Add encoded audio frame (e.g., PCMU/PCMA) to be decoded and played.
        """
        pcm_frame = self.decode_pcm(frame)
        self.pcm_queue.put(pcm_frame)

    def get_audio_frame(self):
        """
        Get raw PCM audio frame for encoding and transmission.
        Note: This now returns frames destined for playback queue; callers that
        want microphone capture should record via their own input stream and
        pass PCM to encode_pcm().
        """
        return self.pcm_queue.get()
