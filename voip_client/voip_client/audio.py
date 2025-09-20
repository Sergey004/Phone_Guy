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
from .config import AUDIO_FRAME_SIZE, CODEC_PCMU, CODEC_PCMA

# Standard decoded PCM silence (320 bytes == 160 samples of 16-bit PCM)
SILENCE_PCM = b"\x00" * 320
# Standard encoded silence for G.711 (160 bytes of 8-bit samples)
SILENCE_ENCODED = b"\x80" * 160

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

    def _process_audio(self):
        """
        Main audio processing loop.
        Only handles playback of PCM frames pushed via add_audio_frame().
        """
        # Choose a sane playback buffer size independent of RTP packetization
        if isinstance(AUDIO_FRAME_SIZE, int) and AUDIO_FRAME_SIZE > 0:
            frames_per_buffer = max(160, 2 * AUDIO_FRAME_SIZE)
        else:
            # AUTO or invalid -> use 20 ms (320 samples) buffer for smooth playback
            frames_per_buffer = 320
        # Create stream and expose it on the instance so `stop()` can close it
        try:
            self.stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=False,
            output=True,
            frames_per_buffer=frames_per_buffer
            )
        except Exception as e:
            logging.error(f"Failed to open audio stream: {e}")
            self.stream = None
        else:
            try:
                self.stream.start_stream()
            except Exception:
                pass
        try:
            bytes_per_sample = 2
            target_bytes = frames_per_buffer * bytes_per_sample
            while self.running and not self._stop_event.is_set():
                try:
                    # Get next decoded PCM frame (may be smaller than the playback buffer)
                    # This queue stores decoded PCM frames (16-bit little-endian)
                    pcm_to_play = self.pcm_queue.get(timeout=0.1)
                    # Wake sentinel to exit
                    if pcm_to_play is None:
                        break
                    if not isinstance(pcm_to_play, (bytes, bytearray)):
                        logging.warning("AudioProcessor: invalid pcm frame type, skipping")
                        continue
                    # Append to playback buffer
                    self.playback_buffer.extend(pcm_to_play)

                    # While we have at least one full buffer, write it
                    while len(self.playback_buffer) >= target_bytes:
                        chunk = bytes(self.playback_buffer[:target_bytes])
                        try:
                            if self.stream is not None:
                                self.stream.write(chunk)
                        except Exception as e:
                            logging.error(f"Audio stream write error: {e}")
                            # On error, drop this chunk and continue
                        del self.playback_buffer[:target_bytes]

                except queue.Empty:
                    # No frame available: if we have partial buffer, optionally pad and write small chunk to avoid underrun
                    if len(self.playback_buffer) > 0:
                        # Pad with silence up to target and write once
                        pad_len = target_bytes - len(self.playback_buffer)
                        if pad_len > 0:
                            self.playback_buffer.extend(b"\x00" * pad_len)
                        try:
                            if self.stream is not None:
                                self.stream.write(bytes(self.playback_buffer[:target_bytes]))
                        except Exception as e:
                            logging.error(f"Audio stream write error on pad: {e}")
                        del self.playback_buffer[:target_bytes]
                    else:
                        # No data at all; small sleep to avoid busy loop
                        time.sleep(0.01)
                except Exception as e:
                    logging.error(f"Audio processing error: {e}")
                    time.sleep(0.01)
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
            if self.codec == CODEC_PCMU:
                return audioop.ulaw2lin(encoded_data, 2)
            elif self.codec == CODEC_PCMA:
                return audioop.alaw2lin(encoded_data, 2)
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
