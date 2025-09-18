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
import audioop
from .config import DEFAULT_RTP_PORT_RANGE, AUDIO_FRAME_SIZE

class RtpPacket:
    """
    Represents an RTP packet with header and payload.
    """
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

    @classmethod
    def from_bytes(cls, data):
        """
        Parse raw RTP packet bytes into RtpPacket object.
        """
        if len(data) < 12:
            raise ValueError("RTP packet too short")
        header = struct.unpack('!BBHII', data[:12])
        version = (header[0] >> 6) & 0x3
        padding = (header[0] >> 5) & 0x1
        extension = (header[0] >> 4) & 0x1
        csrc_count = header[0] & 0xF
        marker = (header[1] >> 7) & 0x1
        payload_type = header[1] & 0x7F
        sequence = header[2]
        timestamp = header[3]
        ssrc = header[4]
        payload = data[12:]
        return cls(
            payload_type=payload_type,
            sequence=sequence,
            timestamp=timestamp,
            ssrc=ssrc,
            payload=payload
        )

    def to_bytes(self):
        """
        Convert RtpPacket object to raw bytes.
        """
        header = bytearray(12)
        header[0] = (self.version << 6) | (self.padding << 5) | (self.extension << 4) | self.csrc_count
        header[1] = (self.marker << 7) | self.payload_type
        struct.pack_into('!HII', header, 2, self.sequence, self.timestamp, self.ssrc)
        return bytes(header) + self.payload

class JitterBuffer:
    """
    A more advanced jitter buffer for RTP packets.
    It uses a priority queue to handle out-of-order packets and adapts to jitter.
    """
    def __init__(self, max_delay_ms=200, sample_rate=8000):
        self.max_delay_ms = max_delay_ms
        self.sample_rate = sample_rate
        self.buffer = queue.PriorityQueue()
        self.lock = threading.Lock()
        self.next_sequence = None
        # Capacity based on time window, assuming minimum 10 ms packetization
        self.max_buffer_size = max(10, int(self.max_delay_ms / 10) + 5)
        self.last_good_packet = None
        # Statistics
        self.packets_received = 0
        self.packets_lost = 0
        self.packets_late = 0
        self.log_interval = 5  # Log stats every 5 seconds
        self.last_log_time = time.time()

    def add_packet(self, packet):
        """
        Add RTP packet to the jitter buffer.
        """
        with self.lock:
            self.packets_received += 1
            if self.next_sequence is None:
                self.next_sequence = packet.sequence

            # Check for late packets
            if packet.sequence < self.next_sequence:
                self.packets_late += 1
                return  # Discard late packet

            self.buffer.put((packet.sequence, packet))

            # Basic overflow protection
            if self.buffer.qsize() > self.max_buffer_size * 2:
                try:
                    self.buffer.get_nowait()
                except queue.Empty:
                    pass
        
        self._log_stats()

    def get_next_packet(self, timeout=0.05):
        """
        Get the next packet in sequence order.
        If a packet is missing, generate comfort noise (PLC).
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if not self.buffer.empty():
                    seq, packet = self.buffer.queue[0]
                    if seq == self.next_sequence:
                        _, packet = self.buffer.get()
                        self.next_sequence = (self.next_sequence + 1) % 65536
                        self.last_good_packet = packet
                        return packet
                    elif seq < self.next_sequence:
                        # Packet is older than what we expect, discard
                        self.buffer.get()
                        self.packets_late += 1
                        continue
                    # Packet is in the future, wait
            time.sleep(0.001)

        # Packet not found, generate comfort noise
        self.packets_lost += 1
        logging.warning(f"Packet {self.next_sequence} not received, generating comfort noise (PLC).")
        self._log_stats()

        # Generate PLC payload length based on last good packet or default to 20 ms (160 samples encoded)
        if self.last_good_packet:
            last_len = len(self.last_good_packet.payload)
            payload_type = self.last_good_packet.payload_type
            next_ts = (self.last_good_packet.timestamp + last_len) % (2**32)
            next_ssrc = self.last_good_packet.ssrc
            # Simple PLC: repeat last payload
            plc_payload = self.last_good_packet.payload
        else:
            last_len = 160
            payload_type = 0
            next_ts = 0
            next_ssrc = 0
            # Silence -> encode zero PCM of size last_len samples (2 bytes per sample)
            noise_pcm = bytearray(last_len * 2)
            plc_payload = audioop.lin2ulaw(bytes(noise_pcm), 2)

        plc_packet = RtpPacket(
            payload_type=payload_type,
            sequence=self.next_sequence,
            timestamp=next_ts,
            ssrc=next_ssrc,
            payload=plc_payload[:last_len]
        )

        self.next_sequence = (self.next_sequence + 1) % 65536
        # We don't set last_good_packet to the PLC packet
        return plc_packet

    def _log_stats(self):
        """
        Log jitter buffer statistics periodically.
        """
        current_time = time.time()
        if current_time - self.last_log_time > self.log_interval:
            with self.lock:
                logging.info(f"JitterBuffer Stats: Received={self.packets_received}, Lost={self.packets_lost}, Late={self.packets_late}, Buffer Size={self.buffer.qsize()}")
                self.last_log_time = current_time

    def clear(self):
        """
        Clear all packets from the buffer and reset stats.
        """
        with self.lock:
            while not self.buffer.empty():
                try:
                    self.buffer.get_nowait()
                except queue.Empty:
                    break
            self.next_sequence = None
            self.last_good_packet = None
            self.packets_received = 0
            self.packets_lost = 0
            self.packets_late = 0

class RtpSession:
    """
    Manages RTP session for a single call.
    """
    def __init__(self, local_ip, local_port, remote_ip, remote_port, payload_type=0):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((local_ip, local_port))
        self.sock.settimeout(0.5)
        self.seq = random.randint(0, 65535)
        self.timestamp = random.randint(0, 2**32 - 1)
        self.ssrc = random.randint(1, 2**32 - 1)
        self.running = False
        self.recv_thread = None
        self.send_lock = threading.Lock()
        self.recv_lock = threading.Lock()
        self.jitter_buffer = JitterBuffer(max_delay_ms=60)
        # AUTO packetization support for G.711 (8kHz, 8-bit per sample)
        self.sample_rate = 8000
        self.bytes_per_ms = self.sample_rate // 1000  # 8 bytes/ms for PCMU/PCMA
        # Enable AUTO when AUDIO_FRAME_SIZE <= 0 or set to 'auto'
        self.auto_packetization = False
        try:
            if isinstance(AUDIO_FRAME_SIZE, str) and AUDIO_FRAME_SIZE.strip().lower() == 'auto':
                self.auto_packetization = True
            elif isinstance(AUDIO_FRAME_SIZE, int) and AUDIO_FRAME_SIZE <= 0:
                self.auto_packetization = True
        except Exception:
            self.auto_packetization = False
        # Dynamic packetization parameters (in milliseconds)
        self.packetization_ms = 20
        self.min_packetization_ms = 20
        self.max_packetization_ms = 40
        # Outgoing buffer for encoded audio
        self._tx_buffer = bytearray()
        # Start receive loop immediately
        self.start()

    def start(self):
        if self.running:
            return
        self.running = True
        self.recv_thread = threading.Thread(target=self._receive_loop, name="rtp_rx")
        self.recv_thread.daemon = True
        self.recv_thread.start()

    def send_audio(self, audio_data):
        """
        Send audio data as RTP packets.
        Accepts encoded G.711 (PCMU/PCMA) bytes of arbitrary length and performs
        fixed or dynamic packetization depending on configuration.
        """
        with self.send_lock:
            # Append to transmit buffer
            if audio_data:
                self._tx_buffer.extend(audio_data)

            if self.auto_packetization:
                # Dynamic target size in bytes based on current packetization_ms
                while len(self._tx_buffer) >= (self.bytes_per_ms * self.packetization_ms):
                    target_bytes = self.bytes_per_ms * self.packetization_ms
                    frame = bytes(self._tx_buffer[:target_bytes])
                    del self._tx_buffer[:target_bytes]
                    packet = RtpPacket(
                        payload_type=self.payload_type,
                        sequence=self.seq,
                        timestamp=self.timestamp,
                        ssrc=self.ssrc,
                        payload=frame
                    )
                    self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                    logging.debug(f"Sent RTP packet seq={packet.sequence} size={len(packet.payload)} to {self.remote_ip}:{self.remote_port}")
                    self.seq = (self.seq + 1) % 65536
                    # Timestamp increments by number of audio samples (1 byte == 1 sample for G.711)
                    self.timestamp = (self.timestamp + len(frame)) % (2**32)

                    # Simple backlog-based adaptation
                    backlog_ms = len(self._tx_buffer) // self.bytes_per_ms
                    if backlog_ms > 60 and self.packetization_ms < self.max_packetization_ms:
                        self.packetization_ms = min(self.packetization_ms + 10, self.max_packetization_ms)
                    elif backlog_ms < 15 and self.packetization_ms > self.min_packetization_ms:
                        self.packetization_ms = max(self.packetization_ms - 10, self.min_packetization_ms)
            else:
                # Fixed-size packetization using AUDIO_FRAME_SIZE
                frame_size = AUDIO_FRAME_SIZE
                if not isinstance(frame_size, int) or frame_size <= 0:
                    # Fallback to 160 bytes (20ms at 8kHz for G.711)
                    frame_size = 160
                while len(self._tx_buffer) >= frame_size:
                    frame = bytes(self._tx_buffer[:frame_size])
                    del self._tx_buffer[:frame_size]
                    packet = RtpPacket(
                        payload_type=self.payload_type,
                        sequence=self.seq,
                        timestamp=self.timestamp,
                        ssrc=self.ssrc,
                        payload=frame
                    )
                    self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                    logging.debug(f"Sent RTP packet seq={packet.sequence} size={len(packet.payload)} to {self.remote_ip}:{self.remote_port}")
                    self.seq = (self.seq + 1) % 65536
                    # Increment timestamp by actual payload length (samples)
                    self.timestamp = (self.timestamp + len(frame)) % (2**32)

    def _receive_loop(self):
        """
        Background thread for receiving RTP packets.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                packet = RtpPacket.from_bytes(data)
                self.jitter_buffer.add_packet(packet)
                logging.debug(f"Received RTP packet seq={packet.sequence} size={len(packet.payload)} from {addr}")
            except socket.timeout:
                # Normal idle timeout
                continue
            except OSError as e:
                # Suppress expected errors during shutdown on Windows (WinError 10038)
                if not self.running:
                    break
                if getattr(e, 'winerror', None) == 10038:
                    logging.info("RTP socket closed, receive loop exiting")
                    break
                logging.error(f"RTP receive error: {e}")
            except Exception as e:
                if not self.running:
                    break
                logging.error(f"RTP receive error: {e}")

    def get_audio(self, timeout=0.1):
        """
        Get next decoded audio frame from jitter buffer.
        """
        packet = self.jitter_buffer.get_next_packet(timeout=timeout)
        if packet:
            return packet.payload
        return None

    def stop(self):
        """
        Stop RTP session.
        """
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        if self.recv_thread and self.recv_thread.is_alive():
            self.recv_thread.join(timeout=1.0)
