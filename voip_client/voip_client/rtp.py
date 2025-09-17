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
    Basic jitter buffer for RTP packets with 60ms capacity.
    """
    def __init__(self, max_delay_ms=60, sample_rate=8000):
        self.max_delay_ms = max_delay_ms
        self.sample_rate = sample_rate
        self.buffer = {}
        self.lock = threading.Lock()
        self.last_sequence = None
        self.next_sequence = None
        self.max_buffer_size = int(max_delay_ms / 1000 * sample_rate / AUDIO_FRAME_SIZE) # Max packets to buffer
        self.frame_duration = AUDIO_FRAME_SIZE / sample_rate # Duration of one audio frame in seconds

    def add_packet(self, packet):
        """
        Add RTP packet to jitter buffer, handling out-of-order packets.
        """
        with self.lock:
            if self.next_sequence is None:
                self.next_sequence = packet.sequence

            self.buffer[packet.sequence] = packet

            # Remove old packets to prevent buffer overflow
            if len(self.buffer) > self.max_buffer_size * 2: # Allow some leeway
                min_seq = min(self.buffer.keys())
                if min_seq < self.next_sequence - self.max_buffer_size:
                    del self.buffer[min_seq]

    def get_next_packet(self, timeout=0.05):
        """
        Get next packet in sequence order (blocking with timeout).
        If packet is missing, return silence.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if self.next_sequence in self.buffer:
                    packet = self.buffer.pop(self.next_sequence)
                    self.next_sequence = (self.next_sequence + 1) % 65536
                    return packet
            time.sleep(0.001) # Small sleep to prevent busy-waiting

        # If packet is still not found after timeout, assume loss and return silence
        logging.warning(f"Packet with sequence {self.next_sequence} not received, inserting silence.")
        self.next_sequence = (self.next_sequence + 1) % 65536
        return RtpPacket(payload=b'\x00' * AUDIO_FRAME_SIZE) # Return silence

    def clear(self):
        """
        Clear all packets from buffer.
        """
        with self.lock:
            self.buffer.clear()
            self.last_sequence = None
            self.next_sequence = None

class RtpSession:
    """
    Manages RTP session for a single call.
    """
    def __init__(self, local_ip, local_port, remote_ip, remote_port, payload_type=0, ssrc=0):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.ssrc = ssrc
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((local_ip, local_port))
        self.seq = 0
        self.timestamp = 0
        self.send_lock = threading.Lock()
        self.jitter_buffer = JitterBuffer()
        self.running = True
        self.receive_thread = threading.Thread(target=self._receive_loop)
        self.receive_thread.daemon = True
        self.receive_thread.start()

    def send_audio(self, audio_data):
        """
        Send audio data as RTP packets.
        """
        with self.send_lock:
            frame_size = AUDIO_FRAME_SIZE
            for i in range(0, len(audio_data), frame_size):
                frame = audio_data[i:i+frame_size]
                packet = RtpPacket(
                    payload_type=self.payload_type,
                    sequence=self.seq,
                    timestamp=self.timestamp,
                    ssrc=self.ssrc,
                    payload=frame
                )
                self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                logging.info(f"Sent RTP packet seq={packet.sequence} size={len(packet.payload)} to {self.remote_ip}:{self.remote_port}")
                self.seq = (self.seq + 1) % 65536
                self.timestamp += AUDIO_FRAME_SIZE

    def _receive_loop(self):
        """
        Background thread for receiving RTP packets.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                packet = RtpPacket.from_bytes(data)
                self.jitter_buffer.add_packet(packet)
                logging.info(f"Received RTP packet seq={packet.sequence} size={len(packet.payload)} from {addr}")
            except Exception as e:
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
        self.sock.close()
