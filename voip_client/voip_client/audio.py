# audio.py
"""voip_client.audio

Audio processing utilities used by the VoIP client.

This module provides a small, robust audio pipeline for decoding incoming
encoded frames (PCMU/PCMA), queueing decoded PCM for playback and encoding
PCM for transmission. The implementation is intentionally defensive:

- All public methods validate input and fall back to silence on error.
- Encoded silence is represented as 0x80 bytes for G.711 (typical u-law/a-law
    silence value). Decoded PCM silence is 16-bit zero samples.
- Playback uses an internal buffer that accumulates PCM and writes only
    full-sized chunks to the audio device to reduce small-chunk clicks.

The goal is stability in adverse network/runtime conditions (malformed
packets, transient decode errors, underruns).
"""

import audioop
import pyaudio
import threading
import queue
import logging
import time
import numpy as np  # Added for improved decoding
from .config import AUDIO_FRAME_SIZE, CODEC_PCMU, CODEC_PCMA

# Standard decoded PCM silence (640 bytes == 320 samples of 16-bit PCM, adjusted for new frame size)
SILENCE_PCM = b"\x00" * 640
# Standard encoded silence for G.711 (320 bytes of 8-bit samples)
SILENCE_ENCODED = b"\x80" * 320

class AudioProcessor:
    """
        Handles audio decode/encode and playback for the VoIP client.

        Usage notes:
        - Call `start()` to spawn the playback thread and `stop()` to terminate it.
        - Push encoded frames (PCMU/PCMA) into `add_audio_frame()` to play them.
        - `encode_pcm()` / `decode_pcm()` wrap `audioop` and will return silence on
            failure instead of raising.
    """
    def __init__(self, codec=CODEC_PCMU, sample_rate=8000):
        self.codec = codec
        self.sample_rate = sample_rate
        self.pcm_queue = queue.Queue()
        # Buffer to accumulate PCM bytes for smooth playback
        self.playback_buffer = bytearray()
        self.audio_thread = None
        self.running = False
        # Event to request thread shutdown more reliably
        self._stop_event = threading.Event()
        # Expose stream so stop() can close it from another thread
        self.stream = None
        self.pyaudio = pyaudio.PyAudio()

    def start(self):
        """
        Start audio processing threads.
        """
        self.running = True
        self._stop_event.clear()
        self.audio_thread = threading.Thread(target=self._process_audio)
        self.audio_thread.daemon = True
        self.audio_thread.start()

    def stop(self):
        """
        Stop audio processing.
        """
        # Signal the thread to stop and wake any blocking get()
        self.running = False
        self._stop_event.set()
        try:
            # Put sentinel to wake queue.get() if blocked
            self.pcm_queue.put_nowait(None)
        except Exception:
            pass

        if self.stream is not None:
            try:
                try:
                    self.stream.stop_stream()
                except Exception:
                    pass
                try:
                    self.stream.close()
                except Exception:
                    pass
            finally:
                self.stream = None

        if self.audio_thread:
            self.audio_thread.join(timeout=1.0)
            if self.audio_thread.is_alive():
                logging.warning("AudioProcessor: audio thread did not stop within timeout")
            self.audio_thread = None

        # Полная очистка PCM-очереди после остановки
        try:
            while not self.pcm_queue.empty():
                self.pcm_queue.get_nowait()
        except Exception:
            pass

        try:
            self.pyaudio.terminate()
        except Exception:
            pass

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback for non-blocking output."""
        bytes_per_sample = 2
        target_bytes = frame_count * bytes_per_sample
        try:
            pcm = self.pcm_queue.get_nowait()
            if not isinstance(pcm, (bytes, bytearray)):
                pcm = SILENCE_PCM
            if len(pcm) < target_bytes:
                pcm += b'\x00' * (target_bytes - len(pcm))
            return (pcm[:target_bytes], pyaudio.paContinue)
        except queue.Empty:
            return (b'\x00' * target_bytes, pyaudio.paContinue)
        except Exception as e:
            logging.error(f"Audio callback error: {e}")
            return (b'\x00' * target_bytes, pyaudio.paContinue)

    def _process_audio(self):
        """
        Main audio processing loop.
        Only handles playback of PCM frames pushed via add_audio_frame().
        """
        # Increased buffer size for reduced underrun
        frames_per_buffer = 1024  # Increased from 320/640
        # Create stream in callback mode for better handling
        try:
            self.stream = self.pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=False,
                output=True,
                frames_per_buffer=frames_per_buffer,
                stream_callback=self._audio_callback
            )
        except Exception as e:
            logging.error(f"Failed to open audio stream: {e}")
            self.stream = None
            return
        try:
            self.stream.start_stream()
            while self.running and not self._stop_event.is_set():
                time.sleep(0.1)  # Let callback handle the work
        finally:
            try:
                if self.stream is not None:
                    try:
                        self.stream.stop_stream()
                    except Exception:
                        pass
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                    self.stream = None
            except Exception:
                pass

    def encode_pcm(self, pcm_data):
        """
        Encode PCM (16-bit little-endian) to the selected codec.

        Returns encoded bytes. On any error, a reasonable encoded-silence
        buffer is returned instead of raising to keep the RTP/send path stable.
        """
        try:
            if self.codec == CODEC_PCMU:
                return audioop.lin2ulaw(pcm_data, 2)
            elif self.codec == CODEC_PCMA:
                return audioop.lin2alaw(pcm_data, 2)
            else:
                raise ValueError(f"Unsupported codec: {self.codec}")
        except Exception as e:
            logging.error(f"encode_pcm error: {e}")
            # Fallback: return a conservative encoded-silence buffer
            try:
                # Use pre-built silence if length cannot be derived
                wanted = max(1, len(pcm_data) // 2)
                return (SILENCE_ENCODED * ((wanted // len(SILENCE_ENCODED)) + 1))[:wanted]
            except Exception:
                return SILENCE_ENCODED

    def decode_pcm(self, encoded_data):
        """
        Decode encoded G.711 data to 16-bit PCM.

        Returns 16-bit PCM bytes. On error, returns a fixed-length PCM silence
        buffer so downstream playback is not interrupted.
        """
        try:
            if len(encoded_data) == 0:
                return SILENCE_PCM
            # Use numpy for faster and more robust decoding
            data_np = np.frombuffer(encoded_data, dtype=np.uint8)
            if self.codec == CODEC_PCMU:
                # Mu-law decode
                s = np.sign(data_np - 128) * (1.0 / 255) * ((1 + 255) ** np.abs(data_np - 128) - 1)
                decoded = np.clip(s * 32767, -32768, 32767).astype(np.int16)
                # Remove DC offset
                decoded -= np.mean(decoded)
                return decoded.tobytes()
            elif self.codec == CODEC_PCMA:
                # A-law decode (similar, adjust table)
                return audioop.alaw2lin(encoded_data, 2)  # Fallback to audioop for A-law
            else:
                raise ValueError(f"Unsupported codec: {self.codec}")
        except Exception as e:
            logging.error(f"decode_pcm error: {e}")
            # Return silence PCM (16-bit samples)
            try:
                return b"\x00" * (len(encoded_data) * 2)
            except Exception:
                return SILENCE_PCM

    def add_audio_frame(self, frame):
        """
        Add encoded audio frame (e.g., PCMU/PCMA) to be decoded and played.

        Behavior and guarantees:
        - Accepts `bytes`/`bytearray` encoded frames. If `None` or invalid
          input is provided, a decoded silence frame is queued instead.
        - Any decode error results in queuing silence rather than raising.
        """
        if frame is None:
            logging.debug("Received None frame in add_audio_frame, pushing silence")
            try:
                self.pcm_queue.put(SILENCE_PCM)
            except Exception:
                logging.error("Failed to queue silence frame")
            return

        if not isinstance(frame, (bytes, bytearray)) or len(frame) == 0:
            logging.warning("add_audio_frame received invalid frame, pushing silence")
            self.pcm_queue.put(SILENCE_PCM)
            return

        try:
            pcm_frame = self.decode_pcm(frame)
            if not isinstance(pcm_frame, (bytes, bytearray)) or len(pcm_frame) == 0:
                raise ValueError("Decoded PCM empty")
            self.pcm_queue.put(pcm_frame)
        except Exception as e:
            logging.error(f"Error decoding audio frame: {e}; pushing silence")
            self.pcm_queue.put(SILENCE_PCM)

    def get_audio_frame(self):
        """
        Get raw PCM audio frame for encoding and transmission.
        Note: This now returns frames destined for playback queue; callers that
        want microphone capture should record via their own input stream and
        pass PCM to encode_pcm().
        """
        try:
            return self.pcm_queue.get(timeout=0.1)
        except Exception:
            # Return silence if none available
            return SILENCE_PCM