# rtp.py
"""
RTP Handling module for VoIP client.
Implements RTP packet processing, jitter buffer, and sequence management.
"""

import socket
import struct
import threading
import queue
import time
import logging
import random
import io
import numpy as np
import librosa
from collections import deque

# Suppress Numba debug logs
logging.getLogger('numba').setLevel(logging.WARNING)
# Suppress Librosa warnings
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="librosa.core.spectrum")

from .jitter_analyzer import JitterAnalyzer
from .config import DEFAULT_RTP_PORT_RANGE, AUDIO_FRAME_SIZE, RTP_PAYLOAD_TYPE_PCMU, RTP_SAMPLE_RATE, RTP_PACKETIZATION_INTERVAL, RTP_MAX_JITTER_BUFFER_MS, RTP_MIN_JITTER_BUFFER_MS
from .rtp_diagnostics import RTPDiagnostics, AudioQualityMonitor

class RTPPacketManager:
    def __init__(self, max_buffer_size=16384):  # Increased default size
        self.buffer = io.BytesIO()
        self.bufferLock = threading.Lock()
        self.last_read_time = time.time()
        self.max_buffer_size = max_buffer_size
        self.total_written = 0
        self.total_read = 0
        self.underrun_count = 0
        self.overrun_count = 0
        self.last_good_pcm = b'\x00' * (AUDIO_FRAME_SIZE * 2)  # Initial silence, 16-bit PCM
        self.consecutive_underruns = 0
        
    def read(self, length: int = AUDIO_FRAME_SIZE * 2) -> bytes:
        with self.bufferLock:
            current_pos = self.buffer.tell()
            self.buffer.seek(0, io.SEEK_END)
            buffer_end = self.buffer.tell()
            
            # Check available data
            available_data = max(0, buffer_end - current_pos)
            
            if available_data < length:
                self.underrun_count += 1
                self.consecutive_underruns += 1
                if self.underrun_count % 10 == 0:  # Log every 10th underrun
                    logging.warning(f"RTPPacketManager underrun: available={available_data}, requested={length}")
                
                # Read available data
                self.buffer.seek(current_pos)
                data = self.buffer.read(available_data)
                
                # Adaptive recovery: Stretch last good frame if many underruns
                pad_len = length - len(data)
                if self.consecutive_underruns > 5 and len(self.last_good_pcm) > 0:
                    try:
                        # Convert bytes to float array for Librosa
                        pcm_array = np.frombuffer(self.last_good_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                        
                        # Set small n_fft to avoid 'too large' warning
                        n_fft = 256  # Increased for better quality
                        hop_length = n_fft // 4
                        
                        # Pad if signal is shorter than n_fft * 2 to ensure stability
                        min_len = n_fft * 2
                        if len(pcm_array) < min_len:
                            pcm_array = np.pad(pcm_array, (0, min_len - len(pcm_array)), mode='reflect')  # Use reflect pad for better audio quality
                        
                        # Custom time stretch to make longer (rate <1 for slower, longer output)
                        stft = librosa.stft(pcm_array, n_fft=n_fft, hop_length=hop_length)
                        stretched_stft = librosa.phase_vocoder(stft, rate=0.95, hop_length=hop_length)
                        stretched = librosa.istft(stretched_stft, hop_length=hop_length, n_fft=n_fft)
                        
                        # Trim to needed length, convert back to 16-bit PCM
                        stretched = stretched[:len(pcm_array)]  # Avoid extra padding
                        stretched = (stretched * 32768).clip(-32768, 32767).astype(np.int16)
                        data += stretched.tobytes()[:pad_len]
                    except Exception as e:
                        logging.error(f"Error in custom Librosa time_stretch during underrun recovery: {e}")
                        data += (b"\x00" * pad_len)  # Fallback to silence
                else:
                    data += (b"\x00" * pad_len)  # PCM silence
                
                # Clear buffer
                self.buffer.seek(0, io.SEEK_END)
                self.buffer.truncate()
                
            else:
                # Normal read
                self.buffer.seek(current_pos)
                data = self.buffer.read(length)
                
                # Remove read data from buffer
                remaining_data = self.buffer.read()
                self.buffer.seek(0)
                self.buffer.truncate()
                self.buffer.write(remaining_data)
                self.buffer.seek(0)
                
                self.consecutive_underruns = 0
                self.last_good_pcm = data  # Update last good frame
            
            self.last_read_time = time.time()
            self.total_read += len(data)
            return data
            
    def write_seq(self, data: bytes, timestamp: float = None) -> None:
        if not data:
            return
            
        with self.bufferLock:
            current_pos = self.buffer.tell()
            self.buffer.seek(0, io.SEEK_END)
            current_size = self.buffer.tell()
            
            # Handle buffer overflow
            if current_size > self.max_buffer_size:
                self.overrun_count += 1
                if self.overrun_count % 100 == 0:
                    logging.warning(f"RTPPacketManager overrun: size={current_size}, max={self.max_buffer_size}")
                
                self.buffer.seek(0)
                all_data = self.buffer.read()
                half_point = len(all_data) // 2
                self.buffer.seek(0)
                self.buffer.truncate()
                self.buffer.write(all_data[half_point:])
                current_size = len(all_data) - half_point
            
            # Write new data
            self.buffer.write(data)
            self.total_written += len(data)
            
            # Restore read position
            if current_pos == 0:
                self.buffer.seek(0)
            else:
                self.buffer.seek(min(current_pos, current_size))
    
    def available(self) -> int:
        with self.bufferLock:
            current_pos = self.buffer.tell()
            self.buffer.seek(0, io.SEEK_END)
            end_pos = self.buffer.tell()
            self.buffer.seek(current_pos)
            return max(0, end_pos - current_pos)
    
    def get_stats(self) -> dict:
        with self.bufferLock:
            return {
                'total_written': self.total_written,
                'total_read': self.total_read,
                'available': self.available(),
                'underruns': self.underrun_count,
                'overruns': self.overrun_count
            }

class RtpPacket:
    def __init__(self, payload_type=0, sequence=0, timestamp=0, ssrc=0, payload=b''):
        self.version = 2
        self.padding = 0
        self.extension = 0
        self.csrc_count = 0
        self.marker = 0
        self.payload_type = payload_type
        self.sequence = sequence
        self.timestamp = timestamp
        self.ssrc = ssrc
        self.payload = payload

    def to_bytes(self):
        header = struct.pack('!BBHII', 
                             (self.version << 6) | (self.padding << 5) | (self.extension << 4) | self.csrc_count,
                             (self.marker << 7) | self.payload_type,
                             self.sequence,
                             self.timestamp,
                             self.ssrc)
        return header + self.payload

    @classmethod
    def from_bytes(cls, data):
        if len(data) < 12:
            return None
        version_p_x_cc, m_pt, sequence, timestamp, ssrc = struct.unpack('!BBHII', data[:12])
        version = (version_p_x_cc >> 6) & 0x03
        if version != 2:
            return None
        padding = (version_p_x_cc >> 5) & 0x01
        extension = (version_p_x_cc >> 4) & 0x01
        csrc_count = version_p_x_cc & 0x0F
        marker = (m_pt >> 7) & 0x01
        payload_type = m_pt & 0x7F
        payload = data[12 + 4 * csrc_count:]
        return cls(payload_type, sequence, timestamp, ssrc, payload)

class RtpSession:
    def __init__(self, local_ip, local_port, remote_ip, remote_port, payload_type=RTP_PAYLOAD_TYPE_PCMU):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((local_ip, local_port))
        logging.info(f"RtpSession bound to {local_ip}:{local_port}, sending to {remote_ip}:{remote_port}")
        self.running = False
        self.seq = random.randint(0, 65535)
        self.timestamp = 0
        self.ssrc = random.getrandbits(32)
        self.receive_queue = queue.Queue(maxsize=100)  # Added maxsize to prevent overflow
        self.send_queue = queue.Queue(maxsize=100)
        self.pcm_manager = RTPPacketManager(max_buffer_size=16384)
        self.jitter_analyzer = JitterAnalyzer(target_jitter_ms=100)
        self.diagnostics = RTPDiagnostics()
        self.quality_monitor = AudioQualityMonitor()
        self.receive_thread = None
        self.decode_thread = None
        self.send_thread = None
        self.last_buffer_adjust_time = time.time()

    def start(self):
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop)
        self.decode_thread = threading.Thread(target=self._decode_loop)
        self.send_thread = threading.Thread(target=self._send_loop)
        self.receive_thread.start()
        self.decode_thread.start()
        self.send_thread.start()

    def stop(self):
        self.running = False
        self.send_queue.put(None)
        if self.receive_thread:
            self.receive_thread.join()
        if self.decode_thread:
            self.decode_thread.join()
        if self.send_thread:
            self.send_thread.join()
        self.sock.close()

    def _receive_loop(self):
        logging.info("RTP receive thread started")
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                logging.debug(f"Received RTP data from {addr}, length={len(data)}")  # Added debug for RTP receipt
                if addr[0] != self.remote_ip:
                    continue
                packet = RtpPacket.from_bytes(data)
                if packet:
                    self.jitter_analyzer.analyze_packet(packet.sequence, time.time())
                    self.diagnostics.record_packet_arrival(packet.sequence, packet.timestamp, len(packet.payload))
                    try:
                        self.receive_queue.put(packet.payload, timeout=0.1)
                    except queue.Full:
                        logging.warning("Receive queue full, dropping RTP packet")
                    if time.time() - self.last_buffer_adjust_time > 5:
                        new_size = int(self.jitter_analyzer.get_required_buffer_size() * (RTP_SAMPLE_RATE / 1000) * 2)
                        self.pcm_manager.max_buffer_size = max(new_size, 8192)
                        self.last_buffer_adjust_time = time.time()
                        logging.info(f"Adjusted buffer size to {self.pcm_manager.max_buffer_size} bytes")
            except Exception as e:
                if self.running:
                    logging.error(f"RTP receive error: {e}")
        logging.info("RTP receive thread stopped")

    def _decode_loop(self):
        logging.info("RTP decode thread started")
        expected_frame_time = RTP_PACKETIZATION_INTERVAL / 1000.0
        while self.running:
            try:
                start_time = time.time()
                payload = self.receive_queue.get(timeout=0.1)
                if len(payload) == 0:
                    continue
                
                # Decode G.711 to PCM using NumPy
                pcm = b''
                if self.payload_type == 0:  # PCMU
                    ulaw = np.frombuffer(payload, dtype=np.uint8)
                    sign = np.sign(ulaw - 128)
                    abs_val = np.abs(ulaw - 128)
                    pcm_array = np.clip(sign * (1.0 / 255) * ((1 + 255) ** abs_val - 1) * 32767, -32768, 32767).astype(np.int16)
                    pcm = pcm_array.tobytes()
                elif self.payload_type == 8:  # PCMA
                    alaw = np.frombuffer(payload, dtype=np.uint8)
                    sign = np.sign(alaw - 128)
                    abs_val = np.abs(alaw - 128)
                    pcm_array = np.clip(sign * (1.0 / 87.7) * ((1 + 87.7) ** abs_val - 1) * 32767, -32768, 32767).astype(np.int16)
                    pcm = pcm_array.tobytes()
                else:
                    pcm = b'\x00' * (len(payload) * 2)
                
                if len(pcm) > 0:
                    self.pcm_manager.write_seq(pcm)
                    self.quality_monitor.record_audio_frame(pcm, is_silence=(pcm == b'\x00' * len(pcm)))
                    self.diagnostics.record_audio_buffer_state(self.pcm_manager.available(), self.jitter_analyzer.get_required_buffer_size())
                
                processing_time = time.time() - start_time
                sleep_time = expected_frame_time - processing_time
                if sleep_time > 0.001:
                    time.sleep(sleep_time)
                elif sleep_time < -0.010:
                    logging.warning(f"Decode loop falling behind: {sleep_time*1000:.1f}ms")
            except queue.Empty:
                self.pcm_manager.write_seq(b'\x00' * (AUDIO_FRAME_SIZE * 2))
                time.sleep(expected_frame_time)
            except Exception as e:
                logging.error(f"Decode error: {e}")
                self.pcm_manager.write_seq(b'\x00' * (AUDIO_FRAME_SIZE * 2))
                time.sleep(expected_frame_time)
        
        logging.info("RTP decode thread stopped")

    def _send_loop(self):
        logging.info("RTP send thread started")
        while self.running:
            try:
                data = self.send_queue.get(timeout=0.1)
                if data is None:
                    break
                packet = RtpPacket(
                    payload_type=self.payload_type,
                    sequence=self.seq,
                    timestamp=self.timestamp,
                    ssrc=self.ssrc,
                    payload=data
                )
                self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                logging.debug(f"Sent RTP packet to {self.remote_ip}:{self.remote_port}, seq={self.seq}, timestamp={self.timestamp}, payload_len={len(data)}")
                self.seq = (self.seq + 1) % 65536
                self.timestamp = (self.timestamp + len(data)) % (2**32)
            except queue.Empty:
                continue
            except Exception as e:
                if self.running:
                    logging.error(f"RTP send error: {e}")
        logging.info("RTP send thread stopped")

    def send_audio(self, audio_data):
        if not self.running or not audio_data:
            return
        try:
            frame_size = AUDIO_FRAME_SIZE
            data = bytes(audio_data)
            offset = 0
            while offset < len(data):
                frame = data[offset:offset + frame_size * 2]
                if len(frame) < frame_size * 2:
                    frame += b'\x00' * (frame_size * 2 - len(frame))
                
                # Encode to G.711 using NumPy
                encoded = frame
                if self.payload_type == 0:  # PCMU
                    pcm = np.frombuffer(frame, dtype=np.int16) / 32768.0
                    abs_pcm = np.abs(pcm)
                    ulaw = np.sign(pcm) * np.log1p(255 * abs_pcm) / np.log1p(255)
                    encoded = np.clip((ulaw + 1) * 128, 0, 255).astype(np.uint8).tobytes()
                elif self.payload_type == 8:  # PCMA
                    pcm = np.frombuffer(frame, dtype=np.int16) / 32768.0
                    abs_pcm = np.abs(pcm)
                    alaw = np.sign(pcm) * np.log1p(87.7 * abs_pcm) / np.log1p(87.7)
                    encoded = np.clip((alaw + 1) * 128, 0, 255).astype(np.uint8).tobytes()
                
                try:
                    self.send_queue.put_nowait(encoded)
                except queue.Full:
                    logging.warning("Send queue full, dropping packet")
                
                offset += frame_size * 2
        except Exception as e:
            logging.error(f"send_audio error: {e}")

    def get_audio(self, timeout=0.1, blocking=True):
        try:
            chunk_size = AUDIO_FRAME_SIZE * 2
            if blocking:
                start_time = time.time()
                while self.running and (time.time() - start_time < timeout):
                    if self.pcm_manager.available() >= chunk_size:
                        break
                    time.sleep(0.001)
            pcm = self.pcm_manager.read(chunk_size)
            logging.debug(f"Got audio chunk: length={len(pcm)}, stats={self.pcm_manager.get_stats()}")  # Added debug
            if pcm and len(pcm) == chunk_size:
                return pcm
            return b'\x00' * chunk_size
        except Exception as e:
            logging.error(f"get_audio error: {e}")
            return b'\x00' * (AUDIO_FRAME_SIZE * 2)