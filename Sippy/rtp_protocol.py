import socket
import struct
import random
import logging
import audioop
import time
import queue
from .thread_utils import ThreadedLoop
import threading

class RTPHandler:
    def __init__(self, config, logger, audio_handler):
        self.config = config
        self.logger = logger
        self.audio_handler = audio_handler
        self.rtp_sock = None
        self.rtp_port = config['rtp']['local_port']
        self.remote_rtp_addr = None
        self.ssrc = random.randint(0, 0xFFFFFFFF)
        self.rtp_seq = 0
        self.rtp_timestamp = 0
        self.rtp_running = False
        self.on_hold = False
        self.send_thread = None
        self.recv_thread = None
        self.playout_thread = None
        self.negotiated_pt = 0
        self.negotiated_codec = 'PCMU'
        self.jitter_queue = None
        self.jitter_min_level = 3

    def _timestamp_step(self) -> int:
        # Timestamp step per 20ms frame based on codec
        codec = str(self.negotiated_codec).upper()
        if 'G726' in codec:
            return 160  # 8000 Hz * 0.02s
        # OPUS is not currently implemented in RTPHandler; default to G.711 step
        # if codec == 'OPUS':
        #     return 960
        return 160

    def start_rtp(self, local_addr, remote_rtp_addr):
        self.logger.info(f"Starting RTP on {local_addr}:{self.rtp_port} to {remote_rtp_addr}")
        
        # Create and configure socket
        try:
            self.rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.rtp_sock.bind((local_addr, self.rtp_port))
            self.rtp_sock.setblocking(False)
        except Exception as e:
            self.logger.error(f"Failed to create RTP socket: {e}")
            raise
            
        self.remote_rtp_addr = remote_rtp_addr
        
        # Initialize audio
        try:
            if not getattr(self.audio_handler, 'stream_active', False):
                self.audio_handler.open_wav()
                self.logger.debug("Opened audio input stream")
            else:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug('Streaming input active: skipping open_wav()')
        except Exception as e:
            self.logger.warning(f'Could not open outgoing WAV: {e}')
        
        # Configure jitter buffer
        jitter_ms = int(self.config.get('rtp', {}).get('jitter_ms', 200))
        frames = max(5, min(50, jitter_ms // 20))
        self.jitter_queue = queue.Queue(maxsize=frames)
        self.jitter_min_level = max(2, frames // 2)
        self.logger.debug(f"Jitter buffer configured with {frames} frames, min level {self.jitter_min_level}")
        
        # Set running flag before starting threads
        self.rtp_running = True
        
        # Create and start threads
        self.send_thread = threading.Thread(target=self.send_rtp_packet, daemon=True, name="RTP-Send")
        self.recv_thread = threading.Thread(target=self.process_received_packet, daemon=True, name="RTP-Receive")
        self.playout_thread = threading.Thread(target=self.process_playout, daemon=True, name="RTP-Playout")
        
        self.send_thread.start()
        self.recv_thread.start()
        self.playout_thread.start()
        
        self.logger.info("RTP session started successfully")

    def _encode_payload(self, pcm_s16le: bytes) -> bytes:
        codec = str(self.negotiated_codec).upper()
        if 'G726' in codec:
            try:
                return self.audio_handler.encode_g726(pcm_s16le)
            except Exception as e:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f'encode_g726 failed, sending silence: {e}')
                return b''
        if codec == 'PCMA' or self.negotiated_pt == 8:
            try:
                return audioop.lin2alaw(pcm_s16le, 2)
            except Exception as e:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f'lin2alaw failed, sending PCMA silence: {e}')
                return b''
        elif codec == 'PCMU' or self.negotiated_pt == 0:
            try:
                return self.audio_handler.encode_mu_law(pcm_s16le)
            except Exception as e:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f'encode_mu_law failed, sending PCMU silence: {e}')
                return b''
        else:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f'Codec {self.negotiated_codec} not supported; falling back to PCMU')
            try:
                return self.audio_handler.encode_mu_law(pcm_s16le)
            except Exception as e:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f'Fallback encode_mu_law failed: {e}')
                return b''

    def send_rtp_packet(self):
        while self.rtp_running:
            try:
                step = self._timestamp_step()
                if self.on_hold:
                    pcm = b'\x00' * (160 * 2)
                else:
                    pcm = self.audio_handler.read_frames(160)
                    if not pcm:
                        pcm = b'\x00' * (160 * 2)
                payload = self._encode_payload(pcm)
                if payload and self.rtp_sock and self.remote_rtp_addr:
                    rtp_packet = self._build_rtp_packet(payload)
                    try:
                        self.rtp_sock.sendto(rtp_packet, self.remote_rtp_addr)
                        if self.logger.isEnabledFor(logging.DEBUG):
                            self.logger.debug(f'Sent RTP packet to {self.remote_rtp_addr}, seq={self.rtp_seq}, timestamp={self.rtp_timestamp}, pt={self.negotiated_pt}')
                    except Exception as e:
                        if self.rtp_running:  # Only log errors if we're supposed to be running
                            self.logger.warning(f"Error sending RTP packet: {e}")
                else:
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug('Skipped sending RTP due to unsupported codec or empty payload')
                self.rtp_timestamp += step
                self.rtp_seq += 1
                
                # Sleep to maintain proper packet timing (typically 20ms for audio)
                time.sleep(0.02)
            except Exception as e:
                if self.rtp_running:  # Only log errors if we're supposed to be running
                    self.logger.warning(f"Error in RTP send thread: {e}")
                time.sleep(0.02)  # Sleep to avoid tight loop in case of persistent errors

    def process_received_packet(self, data=None, addr=None):
        # When called as a thread function
        if data is None and addr is None:
            while self.rtp_running:
                try:
                    data, addr = self.rtp_sock.recvfrom(8192)
                    self._process_rtp_packet(data)
                except BlockingIOError:
                    time.sleep(0.01)
                except Exception as e:
                    if self.rtp_running:  # Only log errors if we're supposed to be running
                        self.logger.warning(f"Error receiving RTP packet: {e}")
            return
        
        # When called with specific packet data
        if data is not None:
            self._process_rtp_packet(data)
    
    def _process_rtp_packet(self, data):
        if len(data) < 12:
            return
        b0 = data[0]
        version = (b0 >> 6) & 0x03
        padding = (b0 >> 5) & 0x01
        extension = (b0 >> 4) & 0x01
        csrc_count = b0 & 0x0F
        if version != 2:
            return
        pt = data[1] & 0x7F
        offset = 12 + (csrc_count * 4)
        if len(data) < offset:
            return
        if extension:
            if len(data) < offset + 4:
                return
            ext_len_words = struct.unpack_from('!H', data, offset + 2)[0]
            offset += 4 + (ext_len_words * 4)
            if len(data) < offset:
                return
        payload_end = len(data)
        if padding:
            pad_len = data[-1]
            if pad_len < payload_end:
                payload_end -= pad_len
        if offset >= payload_end:
            return
        payload = data[offset:payload_end]
        codec = str(self.negotiated_codec).upper()
        linear_data = None
        if pt == self.negotiated_pt:
            try:
                if 'G726' in codec:
                    linear_data = self.audio_handler.decode_g726(payload)
                elif codec == 'PCMU':
                    linear_data = self.audio_handler.decode_mu_law(payload)
                elif codec == 'PCMA':
                    linear_data = audioop.alaw2lin(payload, 2)
                else:
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f'Received negotiated PT with unsupported codec {self.negotiated_codec}, dropping')
            except Exception as e:
                self.logger.error(f'Decode error for codec {self.negotiated_codec}: {e}')
                linear_data = None
        if linear_data is None:
            if pt == 0:
                try:
                    linear_data = self.audio_handler.decode_mu_law(payload)
                except Exception as e:
                    self.logger.error(f'u-law decode error: {e}')
                    return
            elif pt == 8:
                try:
                    linear_data = audioop.alaw2lin(payload, 2)
                except Exception as e:
                    self.logger.error(f'a-law decode error: {e}')
                    return
            else:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f'Received PT={pt} not matching negotiated_pt={self.negotiated_pt}, dropping')
                return
        if self.jitter_queue is None:
            self.audio_handler.open_output_stream()
            self.audio_handler.write_to_output(linear_data)
        else:
            frame_size = 160 * 2
            total = len(linear_data)
            idx = 0
            while idx < total:
                frame = linear_data[idx:idx + frame_size]
                if len(frame) < frame_size:
                    frame += b'\x00' * (frame_size - len(frame))
                try:
                    self.jitter_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self.jitter_queue.get_nowait()
                        self.jitter_queue.put_nowait(frame)
                        if self.logger.isEnabledFor(logging.DEBUG):
                            self.logger.debug('Jitter buffer full: dropped oldest frame')
                    except Exception:
                        pass
                idx += frame_size

    def process_playout(self):
        try:
            self.audio_handler.open_output_stream()
        except Exception as e:
            self.logger.warning(f'Could not open output stream: {e}')
            return
            
        frame_interval = 0.02
        frame_bytes = 160 * 2
        prefill = 0
        
        # Initial buffer prefill
        if self.jitter_queue is not None:
            target = max(self.jitter_min_level, 2)
            self.logger.debug(f"Prefilling jitter buffer to {target} frames")
            while prefill < target and self.rtp_running:
                try:
                    frame = self.jitter_queue.get(timeout=1.0)
                    self.audio_handler.write_to_output(frame)
                    prefill += 1
                except queue.Empty:
                    break
            self.logger.debug(f"Prefilled {prefill} frames")
        
        # Main playout loop
        while self.rtp_running:
            try:
                start_time = time.time()
                
                # Get frame from jitter buffer or use silence
                if self.jitter_queue is not None:
                    try:
                        frame = self.jitter_queue.get(timeout=0.1)
                    except queue.Empty:
                        frame = b'\x00' * frame_bytes
                else:
                    frame = b'\x00' * frame_bytes
                    
                # Write to audio output
                self.audio_handler.write_to_output(frame)
                
                # Calculate sleep time to maintain proper timing
                elapsed = time.time() - start_time
                sleep_time = max(0, frame_interval - elapsed)
                time.sleep(sleep_time)
                
            except Exception as e:
                if self.rtp_running:  # Only log errors if we're supposed to be running
                    self.logger.warning(f"Error in playout thread: {e}")
                time.sleep(frame_interval)  # Sleep to avoid tight loop in case of persistent errors

    def _build_rtp_packet(self, payload):
        b0 = 0x80
        b1 = self.negotiated_pt & 0x7F
        header = struct.pack('!BBHII', b0, b1, self.rtp_seq, self.rtp_timestamp, self.ssrc)
        return header + payload

    def stop(self):
        try:
            # Set flag to stop threads first
            self.rtp_running = False
            self.logger.debug("RTP running flag set to False")
            
            # Close socket
            try:
                if self.rtp_sock:
                    self.logger.debug("Closing RTP socket")
                    self.rtp_sock.close()
            except Exception as e:
                self.logger.warning(f"Error closing RTP socket: {e}")
            finally:
                self.rtp_sock = None
            
            # Join threads if they were started
            for thread_name in ('send_thread', 'recv_thread', 'playout_thread'):
                th = getattr(self, thread_name, None)
                if th and th.is_alive():
                    try:
                        self.logger.debug(f"Joining {thread_name}")
                        th.join(timeout=1.0)
                        if th.is_alive():
                            self.logger.warning(f"{thread_name} did not terminate within timeout")
                    except Exception as e:
                        self.logger.warning(f"Error joining {thread_name}: {e}")
            
            # Clear thread references
            self.send_thread = None
            self.recv_thread = None
            self.playout_thread = None
            self.remote_rtp_addr = None
            
            # Clear jitter buffer
            if hasattr(self, 'jitter_queue') and self.jitter_queue is not None:
                try:
                    while not self.jitter_queue.empty():
                        self.jitter_queue.get_nowait()
                except Exception:
                    pass
            
            # Close audio resources to avoid leaking PyAudio streams or ffmpeg processes
            try:
                if getattr(self, 'audio_handler', None):
                    self.logger.debug("Closing audio handler")
                    self.audio_handler.close()
            except Exception as e:
                self.logger.warning(f"Error closing audio handler: {e}")
                
            self.logger.info("RTP cleanup completed successfully")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Error during RTPHandler.stop(): {e}")
