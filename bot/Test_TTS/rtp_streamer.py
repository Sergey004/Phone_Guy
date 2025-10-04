import pjsua2 as pj
import numpy as np
import logging
import soundfile as sf
import time
import os
from typing import Optional
from threading import Lock, Timer

logging.basicConfig(level=logging.DEBUG)  # Уберите, если в скрипте уже настроено

# Класс для статического WAV (оригинал, работает стабильно)
class RtpStreamerMediaPort:
    def __init__(self, wav_file, clock_rate=8000):
        self.wav_file = wav_file
        self.clock_rate = clock_rate
        self.channel_count = 1
        self.playback_data = None
        self.recorded_data = []
        self.player = None
        self.recorder = None
        self.playback_duration = 0  # Duration in seconds
        self.playback_start_time = None  # Start time of playback

        logging.info(f"Initializing RtpStreamerMediaPort with WAV: {wav_file}, clock_rate={clock_rate}")
        try:
            data, samplerate = sf.read(wav_file, dtype='int16')
            if samplerate != clock_rate:
                logging.warning(f"WAV samplerate {samplerate} does not match {clock_rate}, may cause issues")
            if data.ndim > 1 and data.shape[1] > 1:
                logging.info("Converting stereo to mono")
                data = np.mean(data, axis=1, dtype=np.int16)
            elif data.ndim > 1:
                data = data[:, 0]  # Ensure 1D array for mono
            logging.info(f"Playback data shape: {data.shape}, {clock_rate}Hz, 1 channel(s)")
            self.playback_data = data
            self.playback_duration = len(data) / clock_rate  # Duration in seconds
            logging.info(f"Playback duration: {self.playback_duration:.2f} seconds")
        except Exception as e:
            logging.error(f"Failed to load WAV: {e}")
            self.playback_data = None

    def createPlayer(self):
        try:
            self.player = pj.AudioMediaPlayer()
            if self.playback_data is not None:
                # Save temporary WAV for AudioMediaPlayer
                temp_wav = "temp_playback.wav"
                sf.write(temp_wav, self.playback_data, self.clock_rate, subtype='PCM_16')
                logging.info(f"Temporary WAV written: {temp_wav}")
                self.player.createPlayer(temp_wav, 0)
                logging.info(f"AudioMediaPlayer created for {temp_wav}")
                self.playback_start_time = time.time()  # Record start time
                # Clean up temporary WAV
                try:
                    os.remove(temp_wav)
                    logging.info(f"Cleaned up temporary WAV: {temp_wav}")
                except Exception as e:
                    logging.error(f"Failed to clean up {temp_wav}: {e}")
            else:
                logging.error("No playback data available for AudioMediaPlayer")
                raise RuntimeError("No playback data")
        except Exception as e:
            logging.error(f"Failed to create AudioMediaPlayer: {e}")
            raise

    def createRecorder(self, filename="captured_audio.wav"):
        try:
            self.recorder = pj.AudioMediaRecorder()
            self.recorder.createRecorder(filename)
            logging.info(f"AudioMediaRecorder created for {filename}")
        except Exception as e:
            logging.error(f"Failed to create AudioMediaRecorder: {e}")
            raise

    def startTransmit(self, sink):
        try:
            if self.player:
                self.player.startTransmit(sink)
                logging.info(f"Playback transmission started to sink port {sink.getPortId()}")
        except Exception as e:
            logging.error(f"Failed to start playback transmission: {e}")
            raise

    def receiveFrom(self, source):
        try:
            if self.recorder:
                source.startTransmit(self.recorder)
                logging.info(f"Recording transmission started from source port {source.getPortId()}")
        except Exception as e:
            logging.error(f"Failed to start recording transmission: {e}")
            raise

    def save_to_wav(self, filename):
        if self.recorder:
            logging.info(f"Recording handled by AudioMediaRecorder, saved to {filename}")
        else:
            logging.warning("No recorder available to save WAV")

    def is_playback_done(self):
        try:
            if self.player and self.playback_start_time is not None:
                elapsed_time = time.time() - self.playback_start_time
                logging.debug(f"Playback elapsed: {elapsed_time:.2f}s, duration: {self.playback_duration:.2f}s")
                return elapsed_time >= self.playback_duration
            return True  # No player or no start time, consider done
        except Exception as e:
            logging.error(f"Error checking playback status: {e}")
            return True  # On error, assume done to avoid hanging

# Класс для динамического TTS (оригинал, с фреймами)
class ByteStreamMediaPort(pj.AudioMediaPort):
    def __init__(self, pcm_bytes: bytes = b"", sample_rate: int = 8000, fmt=pj.PJMEDIA_FORMAT_PCMA):
        super().__init__()
        self.pcm_data: bytes = pcm_bytes
        self.sample_rate: int = sample_rate
        self.position: int = 0
        self._lock = Lock()
        self.conf_port_id: int = -1
        self.frame_size: int = sample_rate // 50 * 2  # 20ms frames, 16-bit samples
        self.timer = None
        self.fmt=fmt
        logging.info(f"Initialized ByteStreamMediaPort with sample_rate={sample_rate}, frame_size={self.frame_size}")

    def getFrame(self, frame: pj.MediaFrame) -> int:
        with self._lock:
            logging.debug(f"getFrame called, position={self.position}/{len(self.pcm_data)}")
            if self.position >= len(self.pcm_data):
                frame.buf = []
                frame.size = 0
                logging.debug("No more PCM data to send")
                return pj.PJ_SUCCESS

            # Calculate how many bytes to send in this frame
            bytes_to_send = min(self.frame_size, len(self.pcm_data) - self.position)
            frame.buf = self.pcm_data[self.position:self.position + bytes_to_send]
            frame.size = bytes_to_send
            self.position += bytes_to_send
            logging.debug(f"Sending frame: size={frame.size}, position={self.position}/{len(self.pcm_data)}")
            return pj.PJ_SUCCESS

    def update_playback_data(self, pcm_bytes: bytes):
        with self._lock:
            self.pcm_data = pcm_bytes
            self.position = 0
            logging.info(f"Updated playback data: {len(pcm_bytes)} bytes, ~{len(pcm_bytes)/(self.sample_rate*2):.2f}s")
            # Start periodic frame push
            if self.conf_port_id >= 0 and not self.timer:
                logging.debug("Starting frame push timer")
                self.timer = Timer(0.02, self.push_frame)
                self.timer.start()

    def push_frame(self):
        """Periodically push a frame to trigger transmission."""
        try:
            with self._lock:
                if self.position < len(self.pcm_data):
                    frame = pj.MediaFrame()
                    frame.buf = []  # Initialize empty buffer
                    frame.size = 0
                    self.getFrame(frame)
                    logging.debug("Pushed frame to trigger transmission")
            if self.position < len(self.pcm_data):
                logging.debug("Scheduling next frame push")
                self.timer = Timer(0.02, self.push_frame)
                self.timer.start()
        except Exception as e:
            logging.error(f"Error in push_frame: {e}")
            self.timer = None

    def is_playback_done(self) -> bool:
        with self._lock:
            done = self.position >= len(self.pcm_data)
            logging.debug(f"Playback done: {done}, position={self.position}/{len(self.pcm_data)}")
            if done and self.timer:
                logging.debug("Cancelling frame push timer")
                self.timer.cancel()
                self.timer = None
            return done

    def register_with_conf(self, ep: pj.Endpoint):
        try:
            # Create proper audio format for the port
            audio_format = pj.MediaFormatAudio()
            audio_format.type = pj.PJMEDIA_TYPE_AUDIO
            audio_format.clockRate = self.sample_rate
            audio_format.channelCount = 1
            audio_format.bitsPerSample = 16
            audio_format.frameTimeUsec = 20000  # 20ms frames
            
            # Create the audio media port with proper format
            self.createPort("byte_stream_port", audio_format)
            self.conf_port_id = self.getPortId()
            
            if self.conf_port_id < 0:
                logging.error(f"Failed to create ByteStreamMediaPort - getPortId returned {self.conf_port_id}")
                raise RuntimeError("Port creation failed")
                
            logging.info(f"Registered ByteStreamMediaPort with conf port ID: {self.conf_port_id}")
            
            # Verify the port is properly registered by checking if we can get frame info
            try:
                # Test if the port is functional by getting a frame
                test_frame = pj.MediaFrame()
                test_frame.buf = []  # Initialize empty buffer
                test_frame.size = 0
                result = self.getFrame(test_frame)
                if result != pj.PJ_SUCCESS:
                    logging.warning(f"getFrame test returned {result}, but continuing")
            except Exception as test_e:
                logging.warning(f"Port functionality test failed: {test_e}, but continuing")
                
        except Exception as e:
            logging.error(f"Error registering ByteStreamMediaPort: {e}")
            self.conf_port_id = -1
            # Re-raise the exception to let calling code handle it
            raise
