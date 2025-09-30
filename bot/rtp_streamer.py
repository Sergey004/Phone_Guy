import pjsua2 as pj
import numpy as np
import logging
import soundfile as sf
import time
import os

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