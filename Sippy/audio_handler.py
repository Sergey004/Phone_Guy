import asyncio
import wave
import pyaudio
import struct
import os
import ffmpeg
import logging
import audioop
import queue
import threading

class AudioHandler:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.p = pyaudio.PyAudio()

        self.stream_out = None
        self.wav_path = self.config.get('audio', {}).get('wav_outgoing')
        self.wav = None
        self.is_float = False
        self.wav_file = None
        self.disable_disk_transcode = False

        # ffmpeg-python pipeline state
        self.ffmpeg_proc = None
        self.ffmpeg_source_proc = None
        self.ffmpeg_source_task = None
        self.using_ffmpeg = False
        self.ffmpeg_pcm_buffer = bytearray()

        # Transcoding state
        self.converted_wav_path = None
        self.prefer_file_wav = False

        # G.722 decoder pipeline
        self.g722_proc = None

        # G.726 encoder/decoder pipelines
        self.g726_enc_proc = None
        self.g726_dec_proc = None
        self.g726_pre_file_path = None
        self.g726_pre_fp = None
        self.g726_frame_bytes = 80

        # Streaming input state (for AI/real-time audio)
        self.stream_active = False
        self.stream_queue = None  # asyncio.Queue of PCM s16le mono @8k
        self.stream_buffer = bytearray()  # accumulates to satisfy read sizes
        self.stream_eof = False
        self.stream_finished_event = threading.Event()
        self.ffmpeg_source_running = False
        self._ratecv_state = None
        self._stream_in_rate = 8000

    async def set_outgoing_wav(self, wav_path):
        """
        Closes any open WAV file and sets a new path for the outgoing audio.
        """
        self.logger.info(f"Setting new outgoing WAV to: {wav_path}")
        self.close()
        self.wav_path = wav_path
        self.prefer_file_wav = False
        if self.converted_wav_path and os.path.exists(self.converted_wav_path) and self.wav_path != wav_path:
            try:
                os.remove(self.converted_wav_path)
                self.converted_wav_path = None
            except OSError as e:
                self.logger.error(f"Error removing old converted WAV: {e}")

    def open_wav(self):
        """
        Opens the WAV file for reading, transcoding it if necessary.
        """
        if self.wav or self.ffmpeg_proc:
            return

        if self.wav_path is None:
            self.logger.debug("No WAV path configured for outgoing audio. Skipping open_wav.")
            return

        original_wav_path_for_session = self.config.get('audio', {}).get('wav_outgoing')
        self.wav_path = original_wav_path_for_session # Ensure it's always set to original at start of open_wav

        # Prefer streaming decode via ffmpeg to avoid on-disk duplicates
        try:
            self._open_ffmpeg()
            if self.using_ffmpeg and self.ffmpeg_proc:
                return
        except Exception:
            self.logger.error("Failed to open ffmpeg stream, falling back to wave module.")

        # Optional: on-disk transcode only if explicitly allowed
        if not self.disable_disk_transcode:
            try:
                self._transcode_outgoing_to_pcm()
                self.prefer_file_wav = True
            except Exception as e:
                self.logger.warning(f'Outgoing file transcode failed, will fallback to wave: {e}')
                self.prefer_file_wav = False
                # If transcode fails, revert self.wav_path to original
                self.wav_path = original_wav_path_for_session

        # Fallback to standard wave module
        if self.wav is None:
            if not os.path.exists(self.wav_path):
                self.logger.error(f'WAV file not found: {self.wav_path}')
                raise FileNotFoundError(f'WAV file not found: {self.wav_path}')
            try:
                self.wav = wave.open(self.wav_path, 'rb')
                self.is_float = False
                self.logger.info(f'Opened WAV file (PCM): {self.wav_path}')
            except wave.Error as e:
                if 'unknown format: 3' in str(e):
                    self._open_float_wav()
                    self.is_float = True
                    self.logger.info(f'Opened WAV file (IEEE float): {self.wav_path}')
                else:
                    self.logger.error(f"Error opening WAV file: {e}")
                    raise
            except FileNotFoundError as e:
                self.logger.error(f'WAV file not found: {self.wav_path} ({e})')
                raise

    def _open_float_wav(self):
        """
        Opens a 32-bit float WAV file for reading.
        """
        try:
            self.wav_file = open(self.wav_path, 'rb')
            self.wav_file.seek(0)
            riff = self.wav_file.read(12)
            if riff[:4] != b'RIFF' or riff[8:] != b'WAVE':
                raise ValueError('Not a WAV file')

            self.channels = 1
            self.sample_rate = 8000
            self.sample_width = 4  # 32-bit float
            self.data_pos = 0
            self.data_size = 0

            while True:
                chunk_id, chunk_size = struct.unpack('<4sI', self.wav_file.read(8))
                if chunk_id == b'fmt ':
                    fmt_data = self.wav_file.read(chunk_size)
                    fmt_tag, self.channels, self.sample_rate, _, _, bit_depth = struct.unpack('<HHIIHH', fmt_data[:16])
                    if fmt_tag != 3:  # IEEE float
                        raise ValueError(f'Expected IEEE float format (3), got {fmt_tag}')
                    self.sample_width = bit_depth // 8
                elif chunk_id == b'data':
                    self.data_pos = self.wav_file.tell()
                    self.data_size = chunk_size
                    self.wav_file.seek(self.data_pos)
                    break
                else:
                    self.wav_file.seek(chunk_size, 1)
        except (EOFError, struct.error, ValueError) as e:
            self.logger.error(f"Failed to parse float WAV file: {e}")
            if self.wav_file:
                self.wav_file.close()
                self.wav_file = None
            raise

    def _open_ffmpeg(self):
        """
        Opens a decoding pipeline using ffmpeg-python.
        """
        ffmpeg_path = self.config.get('audio', {}).get('ffmpeg_path')
        try:
            if not ffmpeg_path:
                try:
                    import imageio_ffmpeg
                    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                except ImportError:
                    self.logger.warning("imageio_ffmpeg not found. ffmpeg must be in PATH.")
            
            if not ffmpeg_path:
                self.logger.error("ffmpeg executable path not found. Please ensure ffmpeg is installed and in your system's PATH, or configure 'ffmpeg_path' in your audio config.")
                raise FileNotFoundError("ffmpeg executable not found.")

            input_options = {}
            if self.wav_path.lower().endswith('.g729'):
                input_options['acodec'] = 'g729'

            self.ffmpeg_proc = (
                ffmpeg
                .input(self.wav_path, **input_options)
                .output('pipe:1', format='s16le', acodec='pcm_s16le', ac=1, ar=8000)
                .run_async(pipe_stdout=True, pipe_stderr=True)
            )
            self.using_ffmpeg = True
            self.ffmpeg_pcm_buffer = bytearray()
            self.logger.info(f'Using ffmpeg-python decoder for {self.wav_path}')
        except Exception as e:
            self.logger.error(f'Failed to start ffmpeg-python process: {e}')
            self.ffmpeg_proc = None
            self.using_ffmpeg = False

    def _transcode_outgoing_to_pcm(self):
        """
        Transcodes the source audio to a temporary 8kHz mono PCM WAV file.
        """
        src = self.wav_path
        base, _ = os.path.splitext(src)
        out_path = base + '_8k_mono.wav'

        if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(src):
            self.wav_path = out_path
            self.converted_wav_path = out_path
            return

        try:
            (
                ffmpeg
                .input(src)
                .output(out_path, format='wav', acodec='pcm_s16le', ac=1, ar=8000)
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            self.wav_path = out_path
            self.converted_wav_path = out_path
            self.logger.info(f'Transcoded outgoing file to PCM 8kHz mono: {out_path}')
        except Exception as e:
            self.logger.error(f'Failed to transcode outgoing file {src} -> {out_path}: {e}')
            raise

    def read_frames(self, num_frames):
        """
        Reads a specified number of audio frames.
        Prefers streaming input if enabled; falls back to file/ffmpeg/float WAV.
        """
        # 0) Prefer live stream input if active
        if self.stream_active and self.stream_queue is not None:
            bytes_needed = num_frames * 2  # 16-bit mono target
            # Drain queue into buffer (non-blocking)
            try:
                while len(self.stream_buffer) < bytes_needed:
                    chunk = self.stream_queue.get_nowait()
                    if chunk:
                        self.stream_buffer.extend(chunk)
                    else:
                        break
            except asyncio.QueueEmpty:
                pass
            # Serve from buffer when enough data
            if len(self.stream_buffer) >= bytes_needed:
                out = bytes(self.stream_buffer[:bytes_needed])
                del self.stream_buffer[:bytes_needed]
                return out
            # If EOF signaled and nothing left, report end of stream
            if self.stream_eof and len(self.stream_buffer) == 0 and (self.stream_queue.empty()):
                if self.stream_finished_event and not self.stream_finished_event.is_set():
                    self.stream_finished_event.set()
                return b''
            # Not enough data yet; caller may send silence
            return b''

        # 1) If using ffmpeg streaming decode
        if self.using_ffmpeg and self.ffmpeg_proc and self.ffmpeg_proc.stdout:
            to_read = num_frames * 2  # 16-bit mono
            try:
                while len(self.ffmpeg_pcm_buffer) < to_read:
                    chunk = self.ffmpeg_proc.stdout.read(to_read - len(self.ffmpeg_pcm_buffer))
                    if not chunk:
                        break
                    self.ffmpeg_pcm_buffer.extend(chunk)
                if len(self.ffmpeg_pcm_buffer) < to_read:
                    return b''
                out = bytes(self.ffmpeg_pcm_buffer[:to_read])
                del self.ffmpeg_pcm_buffer[:to_read]
                return out
            except Exception as e:
                self.logger.error(f'Error reading from ffmpeg stdout: {e}')
                return b''

        # 2) Float WAV manual reader
        if self.is_float and self.wav_file:
            bytes_to_read = num_frames * self.sample_width
            data = self.wav_file.read(bytes_to_read)
            if not data:
                return b''
            floats = struct.unpack(f'<{len(data)//4}f', data)
            pcm = [int(max(-1.0, min(1.0, f)) * 32767.0) for f in floats]
            return struct.pack(f'<{len(pcm)}h', *pcm)

        # 3) Standard wave module
        if self.wav:
            return self.wav.readframes(num_frames)

        return b''

    # --- Streaming input API ---
def start_stream_input(self, max_queue_frames: int | None = None):
    """
    Enable live streaming input mode. Incoming audio should be PCM s16le mono @8kHz.
    Use push_stream_pcm(...) to feed data, end_stream_input() to signal EOF.
    Optionally, max_queue_frames can be provided; if None, reads from config audio.stream_queue_frames (default 200).
    """
    # Resolve queue size from param or config
    if max_queue_frames is None:
        try:
            max_queue_frames = int(self.config.get('audio', {}).get('stream_queue_frames', 200))
        except Exception:
            max_queue_frames = 200
    if not self.stream_active:
        self.stream_active = True
        self.stream_queue = queue.Queue(maxsize=max_queue_frames)
        self.stream_buffer = bytearray()
        self.stream_eof = False
        self._ratecv_state = None
        self._stream_in_rate = 8000
        self.logger.info(f'Streaming input mode enabled (queue={max_queue_frames} frames)')
    else:
        # Reset/flush if already active
        self.stream_buffer.clear()
        self._ratecv_state = None
        self._stream_in_rate = 8000
        self.stream_eof = False
        self.logger.info('Streaming input mode already active: state reset')

    def push_stream_pcm(self, data: bytes, sample_rate: int = 8000, sample_width: int = 2, channels: int = 1):
        """
        Push a chunk of PCM data into the streaming queue.
        Data can be any PCM width (1/2/3/4 bytes), mono/stereo; it will be converted to 8kHz mono 16-bit.
        """
        if not self.stream_active or self.stream_queue is None:
            self.logger.warning('push_stream_pcm called while stream mode is not active')
            return
        try:
            # Convert width to 16-bit
            if sample_width != 2:
                data = audioop.lin2lin(data, sample_width, 2)
            # Downmix to mono if stereo
            if channels == 2:
                data = audioop.tomono(data, 2, 0.5, 0.5)
                channels = 1
            elif channels != 1:
                # Fallback: attempt simple average of first two channels if available
                try:
                    data = audioop.tomono(data, 2, 0.5, 0.5)
                    channels = 1
                except Exception:
                    self.logger.warning(f'Unsupported channel count: {channels}; passing as-is')
            # Resample to 8k if needed
            if sample_rate != 8000:
                if self._stream_in_rate != sample_rate:
                    self._ratecv_state = None
                    self._stream_in_rate = sample_rate
                data, self._ratecv_state = audioop.ratecv(data, 2, 1, sample_rate, 8000, self._ratecv_state)
            # Enqueue, drop oldest on overflow
            try:
                self.stream_queue.put_nowait(data)
            except asyncio.QueueFull:
                try:
                    _ = self.stream_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.stream_queue.put_nowait(data)
                except Exception:
                    pass
        except Exception as e:
            self.logger.error(f'push_stream_pcm failed: {e}', exc_info=True)

    def push_stream_pcm48k(self, data: bytes, sample_width: int = 2, channels: int = 1):
        """
        Convenience wrapper for 48kHz mono/stereo PCM input from TTS engines.
        """
        return self.push_stream_pcm(data, sample_rate=48000, sample_width=sample_width, channels=channels)

    def push_stream_pcm40k(self, data: bytes, sample_width: int = 2, channels: int = 1):
        """
        Convenience wrapper for 40kHz mono/stereo PCM input from TTS engines.
        """
        return self.push_stream_pcm(data, sample_rate=40000, sample_width=sample_width, channels=channels)

    def push_stream_float32(self, data: bytes, sample_rate: int, channels: int = 1):
        """
        Accept float32 PCM data (-1..1), convert to 16-bit signed, and push via common pipeline.
        """
        try:
            if not data:
                return
            count = len(data) // 4
            # Unpack little-endian float32
            floats = struct.unpack(f'<{count}f', data)
            # Clamp and convert to int16
            ints = [
                32767 if f >= 1.0 else (-32768 if f <= -1.0 else int(f * 32767.0))
                for f in floats
            ]
            pcm16 = struct.pack(f'<{len(ints)}h', *ints)
            self.push_stream_pcm(pcm16, sample_rate=sample_rate, sample_width=2, channels=channels)
        except Exception as e:
            self.logger.error(f'push_stream_float32 failed: {e}', exc_info=True)

def end_stream_input(self):
    """
    Signal end-of-stream. When internal buffer and queue drain, stream_finished_event will be set.
    """
    self.stream_eof = True
    # If already drained, set the event
    if self.stream_finished_event and not self.stream_finished_event.is_set():
        if (self.stream_queue is None or self.stream_queue.empty()) and len(self.stream_buffer) == 0:
            self.stream_finished_event.set()
    self.logger.info('Streaming input EOF signaled')

def start_ffmpeg_source_stream(self, source: str, input_options: dict | None = None, read_chunk_ms: int = 100):
    """
    Start ffmpeg process that decodes given source to s16le mono 8kHz and feeds streaming queue in real time.
    This avoids creating any on-disk transcoded WAVs.
    """
    if input_options is None:
        input_options = {}
    # Ensure streaming input is initialized
    if not self.stream_active:
        self.start_stream_input()
    # Stop previous source if any
    self.stop_ffmpeg_source_stream()
    try:
        self.ffmpeg_source_proc = (
            ffmpeg
            .input(source, **input_options)
            .output('pipe:1', format='s16le', acodec='pcm_s16le', ac=1, ar=8000)
            .run_async(pipe_stdout=True, pipe_stderr=True)
        )
        # Reader task: pull chunks from stdout without blocking event loop
        self.ffmpeg_source_running = True
        def _pump():
            try:
                bytes_per_20ms = 160 * 2
                chunk_bytes = max(bytes_per_20ms, (read_chunk_ms // 20) * bytes_per_20ms)
                if chunk_bytes % bytes_per_20ms != 0:
                    chunk_bytes = ((chunk_bytes // bytes_per_20ms) + 1) * bytes_per_20ms
                while self.ffmpeg_source_running:
                    if self.ffmpeg_source_proc is None:
                        break
                    # Blocking read in thread
                    chunk = self.ffmpeg_source_proc.stdout.read(chunk_bytes)
                    if not chunk:
                        break
                    # Push directly as 8k s16 mono
                    try:
                        self.stream_queue.put(chunk)
                    except queue.Full:
                        try:
                            _ = self.stream_queue.get()
                        except queue.Empty:
                            pass
                        try:
                            self.stream_queue.put(chunk)
                        except Exception:
                            pass
            finally:
                self.end_stream_input()
        self.ffmpeg_source_thread = threading.Thread(target=_pump)
        self.ffmpeg_source_thread.daemon = True
        self.ffmpeg_source_thread.start()
        self.logger.info(f'Started ffmpeg source stream from: {source}')
    except Exception as e:
        self.logger.error(f'Failed to start ffmpeg source stream: {e}', exc_info=True)
        self.stop_ffmpeg_source_stream()
        raise

def stop_ffmpeg_source_stream(self):
    """
    Stop ffmpeg source streaming process and reader task if running.
    """
    if self.ffmpeg_source_thread:
        self.ffmpeg_source_running = False
        self.ffmpeg_source_thread.join(timeout=2.0)
        self.ffmpeg_source_thread = None
    if self.ffmpeg_source_proc:
        self._close_ffmpeg_proc('ffmpeg source', self.ffmpeg_source_proc)
        self.ffmpeg_source_proc = None

    def close(self):
        """
        Closes all open audio resources.
        """
        if self.wav:
            self.wav.close()
            self.wav = None
        if self.wav_file:
            self.wav_file.close()
            self.wav_file = None
        if self.stream_out:
            self.stream_out.stop_stream()
            self.stream_out.close()
            self.stream_out = None
        if self.g726_pre_fp:
            self.g726_pre_fp.close()
            self.g726_pre_fp = None

        self._close_ffmpeg_proc('main', self.ffmpeg_proc)
        self.ffmpeg_proc = None
        self.using_ffmpeg = False
        # Close ffmpeg source stream as well
        if self.ffmpeg_source_proc is not None:
            self._close_ffmpeg_proc('ffmpeg source', self.ffmpeg_source_proc)
            self.ffmpeg_source_proc = None
        if self.ffmpeg_source_task is not None:
            try:
                self.ffmpeg_source_task.cancel()
            except Exception:
                pass
            self.ffmpeg_source_task = None

    def get_outgoing_duration_seconds(self):
        """
        Attempts to determine duration (in seconds) of the configured outgoing audio.
        Avoids creating any on-disk transcodes; uses wave if directly readable, otherwise ffprobe.
        Returns float seconds or None if unknown.
        """
        if not self.wav_path:
            return None
        try:
            # Try to read duration via wave when file is already a PCM WAV
            if isinstance(self.wav_path, str) and self.wav_path.lower().endswith('.wav'):
                try:
                    with wave.open(self.wav_path, 'rb') as w:
                        frames = w.getnframes()
                        rate = w.getframerate() or 8000
                        return frames / float(rate) if rate > 0 else None
                except Exception as e:
                    self.logger.debug(f'wave duration read failed, will try ffprobe: {e}')
            # Fallback to ffprobe on original source
            try:
                probe = ffmpeg.probe(self.wav_path)
                dur = None
                fmt = probe.get('format') or {}
                if 'duration' in fmt and fmt['duration'] is not None:
                    dur = float(fmt['duration'])
                if dur is None:
                    for s in probe.get('streams', []):
                        if s.get('codec_type') == 'audio' and s.get('duration'):
                            dur = float(s['duration'])
                            break
                return dur
            except Exception as e:
                self.logger.warning(f'ffprobe failed to get duration: {e}')
                return None
        except Exception as e:
            self.logger.warning(f'get_outgoing_duration_seconds failed: {e}')
            return None

    def _close_ffmpeg_proc(self, name, proc):
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=1.0)
        except Exception as e:
            proc.kill()
            self.logger.error(f"Forcefully killed ffmpeg process '{name}': {e}")
        finally:
            if proc.stdin:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    def open_output_stream(self):
        if self.stream_out is None:
            self.stream_out = self.p.open(format=pyaudio.paInt16, channels=1, rate=8000, output=True, frames_per_buffer=160)

    def write_to_output(self, data):
        if self.stream_out:
            self.stream_out.write(data)

    def terminate(self):
        self.close()
        self.p.terminate()

    # --- Codec specific methods ---

    def _ensure_g726_encoder(self):
        if self.g726_enc_proc is not None:
            return
        try:
            self.g726_enc_proc = (
                ffmpeg
                .input('pipe:0', format='s16le', ar=8000, ac=1)
                .output('pipe:1', format='g726', acodec='g726', ar=8000, ac=1, audio_bitrate='32k')
                .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
            )
            self.logger.info('Initialized G.726 encoder pipeline')
        except Exception as e:
            self.logger.error(f'Failed to start G.726 encoder: {e}')
            self.g726_enc_proc = None

    def encode_g726(self, pcm_s16le: bytes) -> bytes:
        self._ensure_g726_encoder()
        if self.g726_enc_proc is None:
            return b''
        try:
            self.g726_enc_proc.stdin.write(pcm_s16le)
            self.g726_enc_proc.stdin.flush()
            expected = max(1, len(pcm_s16le) // 4)
            return self.g726_enc_proc.stdout.read(expected) or b''
        except Exception as e:
            self.logger.error(f'G.726 encoding error: {e}')
            self._close_ffmpeg_proc('G.726 encoder', self.g726_enc_proc)
            self.g726_enc_proc = None
            return b''

    def _ensure_g726_decoder(self):
        if self.g726_dec_proc is not None:
            return
        try:
            self.g726_dec_proc = (
                ffmpeg
                .input('pipe:0', format='g726', ar=8000, ac=1)
                .output('pipe:1', format='s16le', ar=8000, ac=1)
                .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
            )
            self.logger.info('Initialized G.726 decoder pipeline')
        except Exception as e:
            self.logger.error(f'Failed to start G.726 decoder: {e}')
            self.g726_dec_proc = None

    def decode_g726(self, g726_payload: bytes) -> bytes:
        self._ensure_g726_decoder()
        if self.g726_dec_proc is None:
            return b''
        try:
            self.g726_dec_proc.stdin.write(g726_payload)
            self.g726_dec_proc.stdin.flush()
            to_read = len(g726_payload) * 4
            return self.g726_dec_proc.stdout.read(to_read) or b''
        except Exception as e:
            self.logger.error(f'G.726 decoding error: {e}')
            self._close_ffmpeg_proc('G.726 decoder', self.g726_dec_proc)
            self.g726_dec_proc = None
            return b''

    def encode_mu_law(self, pcm_data):
        mu_law = []
        for sample in struct.unpack(f'<{len(pcm_data)//2}h', pcm_data):
            sign = (sample < 0)
            sample = abs(sample)
            if sample > 32635: sample = 32635
            exponent = 7
            while (sample < (1 << (exponent + 2)) * 8) and exponent > 0:
                exponent -= 1
            mantissa = (sample >> (exponent + 3)) & 0x0F
            mu = (sign << 7) | (exponent << 4) | mantissa
            mu_law.append(~mu & 0xFF)
        return bytes(mu_law)

    def decode_mu_law(self, mu_law_data):
        pcm = []
        for mu in mu_law_data:
            mu = ~mu & 0xFF
            sign = (mu & 0x80)
            exponent = (mu >> 4) & 0x07
            mantissa = mu & 0x0F
            sample = (((mantissa << 3) + 0x84) << exponent) - 0x84
            if sign:
                sample = -sample
            pcm.append(sample)
        return struct.pack(f'<{len(pcm)}h', *pcm)
