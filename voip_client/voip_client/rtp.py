# new_rtp.py
"""
New RTP implementation for VoIP client.
Focuses on improved performance and modularity.
"""

import socket
import struct
import threading
import queue
import time
import logging
import random
import numpy as np
from collections import deque
import io
import librosa
import warnings

# Suppress Librosa warnings
warnings.filterwarnings("ignore", category=UserWarning, module="librosa.core.spectrum")

# Constants
RTP_VERSION = 2
RTP_PAYLOAD_TYPE_PCMU = 0  # G.711 μ-law
RTP_PAYLOAD_TYPE_PCMA = 8  # G.711 A-law
RTP_SAMPLE_RATE = 8000     # 8 kHz
RTP_PACKETIZATION_INTERVAL = 20  # 20 ms
AUDIO_FRAME_SIZE = RTP_SAMPLE_RATE * RTP_PACKETIZATION_INTERVAL // 1000  # 160 samples (for 8kHz, 20ms)
RTP_MAX_JITTER_BUFFER_MS = 200
RTP_MIN_JITTER_BUFFER_MS = 50

def pcm_to_ulaw(pcm_data):
    """Converts 16-bit PCM to G.711 U-law."""
    if not pcm_data:
        return b''
    pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
    # Normalize to -1 to 1
    pcm_normalized = pcm_array / 32768.0

    # Apply mu-law compression
    mu = 255
    ulaw_compressed = np.sign(pcm_normalized) * (np.log(1 + mu * np.abs(pcm_normalized)) / np.log(1 + mu))

    # Scale to 8-bit and invert bits
    ulaw_8bit = ((ulaw_compressed + 1) / 2 * 255).astype(np.uint8)
    ulaw_inverted = ulaw_8bit ^ 0x55 # Invert bits for G.711 U-law

    return ulaw_inverted.tobytes()

def ulaw_to_pcm(ulaw_data):
    """Converts G.711 U-law to 16-bit PCM."""
    if not ulaw_data:
        return b''
    ulaw_array = np.frombuffer(ulaw_data, dtype=np.uint8)
    # Invert bits back
    ulaw_inverted = ulaw_array ^ 0x55

    # Scale back to -1 to 1
    mu = 255
    ulaw_normalized = (ulaw_inverted / 255.0) * 2 - 1
    pcm_normalized = np.sign(ulaw_normalized) * (1 / mu) * ((1 + mu) ** np.abs(ulaw_normalized) - 1)

    # Scale to 16-bit PCM
    pcm_array = (pcm_normalized * 32768).clip(-32768, 32767).astype(np.int16)
    return pcm_array.tobytes()

def pcm_to_alaw(pcm_data):
    """Converts 16-bit PCM to G.711 A-law."""
    if not pcm_data:
        return b''
    pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
    # Normalize to -1 to 1
    pcm_normalized = pcm_array / 32768.0

    # Apply A-law compression
    A = 87.6
    compressed = np.where(np.abs(pcm_normalized) < (1/A),
                          A * np.abs(pcm_normalized) / (1 + np.log(A)),
                          (1 + np.log(A * np.abs(pcm_normalized))) / (1 + np.log(A)))
    alaw_compressed = np.sign(pcm_normalized) * compressed

    # Scale to 8-bit and invert bits
    alaw_8bit = ((alaw_compressed + 1) / 2 * 255).astype(np.uint8)
    alaw_inverted = alaw_8bit ^ 0x55 # Invert bits for G.711 A-law

    return alaw_inverted.tobytes()

def alaw_to_pcm(alaw_data):
    """Converts G.711 A-law to 16-bit PCM."""
    if not alaw_data:
        return b''
    alaw_array = np.frombuffer(alaw_data, dtype=np.uint8)
    # Invert bits back
    alaw_inverted = alaw_array ^ 0x55

    # Scale back to -1 to 1
    A = 87.6
    normalized = (alaw_inverted / 255.0) * 2 - 1
    pcm_normalized = np.where(np.abs(normalized) < (1 / (1 + np.log(A))),
                              np.sign(normalized) * (np.abs(normalized) * (1 + np.log(A))) / A,
                              np.sign(normalized) * np.exp(np.abs(normalized) * (1 + np.log(A))) / A)

    # Scale to 16-bit PCM
    pcm_array = (pcm_normalized * 32768).clip(-32768, 32767).astype(np.int16)
    return pcm_array.tobytes()

def is_seq_less(seq1, seq2):
    """Compares RTP sequence numbers, handling wraparound."""
    return ((seq1 < seq2) and (seq2 - seq1 < 32768)) or \
           ((seq1 > seq2) and (seq1 - seq2 > 32768))

class JitterBuffer:
    """
    Manages incoming RTP packets to smooth out network jitter.
    """
    def __init__(self, max_buffer_ms=RTP_MAX_JITTER_BUFFER_MS, min_buffer_ms=RTP_MIN_JITTER_BUFFER_MS):
        self.buffer = deque()
        self.max_buffer_size = int(max_buffer_ms / RTP_PACKETIZATION_INTERVAL)
        self.min_buffer_size = int(min_buffer_ms / RTP_PACKETIZATION_INTERVAL)
        self.lock = threading.Lock()
        self.last_sequence = -1
        self.expected_sequence = 0
        self.packets_received = 0
        self.packets_lost = 0
        self.out_of_order = 0
        logging.info(f"JitterBuffer initialized with max_buffer_size={self.max_buffer_size}, min_buffer_size={self.min_buffer_size}")

    def add_packet(self, packet):
        """Adds an RTP packet to the jitter buffer."""
        with self.lock:
            self.packets_received += 1

            # Update last_sequence and expected_sequence based on arrival order
            if self.last_sequence == -1:
                self.expected_sequence = packet.sequence
            
            # Check for out-of-order packets based on expected sequence
            if is_seq_less(packet.sequence, self.expected_sequence):
                self.out_of_order += 1
                logging.debug(f"Out-of-order packet received: {packet.sequence}, expected: {self.expected_sequence}")
            
            # Check for packet loss based on expected sequence
            if is_seq_less(self.expected_sequence, packet.sequence):
                # Only count loss if the new packet is significantly higher than expected
                # This avoids counting reordered packets as lost if they arrive later
                if (packet.sequence - self.expected_sequence < 32768): # Avoid wraparound issues for loss calculation
                    self.packets_lost += (packet.sequence - self.expected_sequence)
                    logging.warning(f"Packet loss detected: expected {self.expected_sequence}, got {packet.sequence}. Lost {packet.sequence - self.expected_sequence} packets.")
            
            # Insert packet in sequence order, handling wraparound
            inserted = False
            for i, buffered_packet in enumerate(self.buffer):
                if is_seq_less(packet.sequence, buffered_packet.sequence):
                    self.buffer.insert(i, packet)
                    inserted = True
                    break
            if not inserted:
                self.buffer.append(packet)

            self.expected_sequence = (packet.sequence + 1) % 65536
            self.last_sequence = packet.sequence

            # Maintain buffer size
            while len(self.buffer) > self.max_buffer_size:
                self.buffer.popleft()
                logging.warning("Jitter buffer overflow, dropping oldest packet.")

    def get_packet(self):
        """Retrieves the next packet from the jitter buffer."""
        with self.lock:
            if len(self.buffer) > self.min_buffer_size:
                packet = self.buffer.popleft()
                return packet # Changed from packet.payload
            return None

    def is_ready(self):
        """Checks if the jitter buffer has enough packets to start playback."""
        with self.lock:
            return len(self.buffer) >= self.min_buffer_size

    def get_stats(self):
        """Returns jitter buffer statistics."""
        with self.lock:
            return {
                "buffer_size": len(self.buffer),
                "packets_received": self.packets_received,
                "packets_lost": self.packets_lost,
                "out_of_order": self.out_of_order
            }

class RTPPacketManager:
    """
    Manages the PCM audio buffer for playback, handling underruns and overruns.
    """
    def __init__(self, max_buffer_size_bytes=16384):
        self.buffer = io.BytesIO()
        self.buffer_lock = threading.Lock()
        self.max_buffer_size_bytes = max_buffer_size_bytes
        self.last_good_pcm = b'\x00' * (AUDIO_FRAME_SIZE * 2) # Silence
        self.underrun_count = 0
        self.consecutive_underruns = 0
        self.overrun_count = 0

    def write(self, pcm_data: bytes):
        """Writes PCM data to the buffer."""
        if not pcm_data:
            return

        with self.buffer_lock:
            current_size = self.buffer.getbuffer().nbytes
            if current_size + len(pcm_data) > self.max_buffer_size_bytes:
                self.overrun_count += 1
                logging.warning(f"RTPPacketManager overrun: current={current_size}, max={self.max_buffer_size_bytes}. Dropping oldest data.")
                # Drop oldest half of the buffer
                self.buffer.seek(0)
                all_data = self.buffer.read()
                half_point = len(all_data) // 2
                self.buffer.seek(0)
                self.buffer.truncate()
                self.buffer.write(all_data[half_point:])
            
            self.buffer.seek(0, io.SEEK_END)
            self.buffer.write(pcm_data)
            self.buffer.seek(0) # Reset read pointer to beginning

    def read(self, length: int) -> bytes:
        """Reads PCM data from the buffer."""
        with self.buffer_lock:
            current_pos = self.buffer.tell()
            self.buffer.seek(0, io.SEEK_END)
            buffer_end = self.buffer.tell()
            available_data = max(0, buffer_end - current_pos)

            if available_data < length:
                self.underrun_count += 1
                self.consecutive_underruns += 1
                logging.warning(f"RTPPacketManager underrun: available={available_data}, requested={length}. Filling with silence/stretched audio.")
                
                # Read available data
                self.buffer.seek(current_pos)
                data = self.buffer.read(available_data)
                
                # Fill with silence or stretched audio
                pad_len = length - len(data)
                if self.consecutive_underruns > 5 and len(self.last_good_pcm) == length:
                    try:
                        # Use librosa for time stretching
                        pcm_array = np.frombuffer(self.last_good_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                        stretched = librosa.effects.time_stretch(pcm_array, rate=0.95)
                        stretched_pcm = (stretched * 32768).clip(-32768, 32767).astype(np.int16).tobytes()
                        data += stretched_pcm[:pad_len]
                    except Exception as e:
                        logging.error(f"Error in librosa time_stretch during underrun recovery: {e}")
                        data += (b"\x00" * pad_len) # Fallback to silence
                else:
                    data += (b"\x00" * pad_len) # Silence
                
                # Clear buffer after underrun
                self.buffer.seek(0)
                self.buffer.truncate()
                self.buffer.write(b'') # Ensure buffer is empty
                self.buffer.seek(0)
                
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
                self.last_good_pcm = data # Update last good frame
            
            return data

    def available(self) -> int:
        """Returns the number of bytes available in the buffer."""
        with self.buffer_lock:
            return self.buffer.getbuffer().nbytes

    def get_stats(self) -> dict:
        """Returns buffer statistics."""
        with self.buffer_lock:
            return {
                "buffer_size_bytes": self.available(),
                "underruns": self.underrun_count,
                "overruns": self.overrun_count
            }

class RTPPacket:
    """
    Represents an RTP packet with methods for serialization and deserialization.
    """
    def __init__(self, payload_type=0, sequence=0, timestamp=0, ssrc=0, payload=b''):
        self.version = RTP_VERSION
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
        """Serialize the RTP packet to bytes."""
        header = struct.pack('!BBHII',
                            (self.version << 6) | (self.padding << 5) | (self.extension << 4) | self.csrc_count,
                            (self.marker << 7) | self.payload_type,
                            self.sequence,
                            self.timestamp,
                            self.ssrc)
        return header + self.payload

    @classmethod
    def from_bytes(cls, data):
        """Deserialize bytes into an RTP packet."""
        if len(data) < 12:
            return None
        version_p_x_cc, m_pt, sequence, timestamp, ssrc = struct.unpack('!BBHII', data[:12])
        version = (version_p_x_cc >> 6) & 0x03
        if version != RTP_VERSION:
            return None
        return cls(
            payload_type=m_pt & 0x7F,
            sequence=sequence,
            timestamp=timestamp,
            ssrc=ssrc,
            payload=data[12:]
        )

class RTPSession:
    """
    Manages an RTP session, including sending and receiving audio data.
    """
    def __init__(self, local_ip, local_port, remote_ip, remote_port, payload_type=RTP_PAYLOAD_TYPE_PCMU):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((local_ip, local_port))
        self.running = False
        self.seq = random.randint(0, 65535)
        self.timestamp = 0
        self.ssrc = random.getrandbits(32)
        self.jitter_buffer = JitterBuffer(min_buffer_ms=0)
        self.pcm_manager = RTPPacketManager()
        self.send_queue = queue.Queue() # Initialize send_queue
        self.receive_thread = None
        self.decode_thread = None
        self.send_thread = None

    def start(self):
        """Start the RTP session threads."""
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop)
        self.decode_thread = threading.Thread(target=self._decode_loop)
        self.send_thread = threading.Thread(target=self._send_loop)
        self.receive_thread.start()
        self.decode_thread.start()
        self.send_thread.start()
        logging.info(f"RTP session started on {self.local_ip}:{self.local_port}")

    def stop(self):
        """Stop the RTP session threads."""
        self.running = False
        if self.receive_thread:
            self.receive_thread.join()
        if self.decode_thread:
            self.decode_thread.join()
        if self.send_thread:
            self.send_thread.join()
        self.sock.close()
        logging.info("RTP session stopped")

    def _receive_loop(self):
        """Thread for receiving RTP packets."""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048) # Increased buffer size
                if addr[0] != self.remote_ip:
                    continue
                packet = RTPPacket.from_bytes(data)
                if packet:
                    self.jitter_buffer.add_packet(packet)
            except Exception as e:
                if self.running:
                    logging.error(f"RTP receive error: {e}")

    def _decode_loop(self):
        """Thread for decoding RTP packets from jitter buffer to PCM."""
        expected_frame_time = RTP_PACKETIZATION_INTERVAL / 1000.0
        while self.running:
            start_time = time.time()
            try:
                if self.jitter_buffer.is_ready():
                    payload = self.jitter_buffer.get_packet()
                    if payload:
                        pcm_data = b''
                        if self.payload_type == RTP_PAYLOAD_TYPE_PCMU:
                            pcm_data = ulaw_to_pcm(payload)
                        elif self.payload_type == RTP_PAYLOAD_TYPE_PCMA:
                            pcm_data = alaw_to_pcm(payload)
                        else:
                            logging.warning(f"Unsupported payload type: {self.payload_type}")
                            pcm_data = b'\x00' * (AUDIO_FRAME_SIZE * 2) # Silence
                        
                        if pcm_data:
                            self.pcm_manager.write(pcm_data)
                else:
                    # Jitter buffer not ready, fill with silence
                    self.pcm_manager.write(b'\x00' * (AUDIO_FRAME_SIZE * 2))
                    logging.debug("Jitter buffer not ready, writing silence.")

            except Exception as e:
                logging.error(f"RTP decode error: {e}")
                self.pcm_manager.write(b'\x00' * (AUDIO_FRAME_SIZE * 2)) # Write silence on error
            
            processing_time = time.time() - start_time
            sleep_time = expected_frame_time - processing_time
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _send_loop(self):
        """Thread for sending RTP packets."""
        while self.running:
            try:
                audio_frame = self.send_queue.get(timeout=0.1)
                if audio_frame is None:
                    break
                
                encoded_payload = b''
                if self.payload_type == RTP_PAYLOAD_TYPE_PCMU:
                    encoded_payload = pcm_to_ulaw(audio_frame)
                elif self.payload_type == RTP_PAYLOAD_TYPE_PCMA:
                    encoded_payload = pcm_to_alaw(audio_frame)
                else:
                    logging.warning(f"Unsupported payload type for sending: {self.payload_type}")
                    encoded_payload = audio_frame # Send as is if unsupported

                packet = RTPPacket(
                    payload_type=self.payload_type,
                    sequence=self.seq,
                    timestamp=self.timestamp,
                    ssrc=self.ssrc,
                    payload=encoded_payload
                )
                self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                self.seq = (self.seq + 1) % 65536
                self.timestamp = (self.timestamp + AUDIO_FRAME_SIZE) % (2**32) # Timestamp increments by samples
            except queue.Empty:
                continue
            except Exception as e:
                if self.running:
                    logging.error(f"RTP send error: {e}")

    def send_audio(self, pcm_audio_data: bytes):
        """Sends PCM audio data over RTP. Assumes pcm_audio_data is a single frame."""
        if not self.running or not pcm_audio_data:
            return
        try:
            self.send_queue.put(pcm_audio_data)
        except queue.Full:
            logging.warning("RTP send queue full, dropping audio frame")

    def get_audio(self, timeout=0.1, chunk_size=AUDIO_FRAME_SIZE * 2):
        """Gets received and decoded PCM audio data."""
        try:
            # Ensure enough data is in the PCM manager before attempting to read
            start_time = time.time()
            while self.running and self.pcm_manager.available() < chunk_size:
                if time.time() - start_time > timeout:
                    logging.warning(f"Timeout waiting for audio data. Available: {self.pcm_manager.available()}, Requested: {chunk_size}")
                    return b'\x00' * chunk_size # Return silence on timeout
                time.sleep(0.001) # Wait a bit for data to accumulate

            return self.pcm_manager.read(chunk_size)
        except Exception as e:
            logging.error(f"get_audio error: {e}")
            return b'\x00' * chunk_size # Return silence on error

    def get_jitter_buffer_stats(self):
        """Returns jitter buffer statistics."""
        return self.jitter_buffer.get_stats()

    def get_pcm_buffer_stats(self):
        """Returns PCM buffer statistics."""
        return self.pcm_manager.get_stats()