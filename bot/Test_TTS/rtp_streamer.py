import pjsua2 as pj
import logging
from typing import Optional
from threading import Lock, Timer

class ByteStreamMediaPort(pj.AudioMediaPort):
    def __init__(self, pcm_bytes: bytes = b"", sample_rate: int = 8000):
        super().__init__()
        self.pcm_data: bytes = pcm_bytes
        self.sample_rate: int = sample_rate
        self.position: int = 0
        self._lock = Lock()
        self.conf_port_id: int = -1
        self.frame_size: int = sample_rate // 50 * 2  # 20ms frames, 16-bit samples
        self.timer = None
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
            self.createPort("byte_stream_port")
            self.conf_port_id = self.getPortId()
            logging.info(f"Registered ByteStreamMediaPort with conf port ID: {self.conf_port_id}")
        except Exception as e:
            logging.error(f"Error registering ByteStreamMediaPort: {e}")
            self.conf_port_id = -1