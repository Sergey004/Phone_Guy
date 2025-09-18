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
        self.max_buffer_size = int(max_delay_ms / 1000 * sample_rate / AUDIO_FRAME_SIZE)
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

        # Generate comfort noise payload
        if self.last_good_packet:
            # Repeat the last good packet's payload as a simple PLC
            plc_payload = self.last_good_packet.payload
        else:
            # Fallback to silence if no previous packet is available
            noise_pcm = bytearray(AUDIO_FRAME_SIZE * 2)  # 16-bit PCM
            plc_payload = audioop.lin2ulaw(bytes(noise_pcm), 2)


        next_ts = self.last_good_packet.timestamp + AUDIO_FRAME_SIZE if self.last_good_packet else 0
        next_ssrc = self.last_good_packet.ssrc if self.last_good_packet else 0
        payload_type = self.last_good_packet.payload_type if self.last_good_packet else 0

        plc_packet = RtpPacket(
            payload_type=payload_type,
            sequence=self.next_sequence,
            timestamp=next_ts,
            ssrc=next_ssrc,
            payload=plc_payload[:AUDIO_FRAME_SIZE]
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
                logging.debug(f"Sent RTP packet seq={packet.sequence} size={len(packet.payload)} to {self.remote_ip}:{self.remote_port}")
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
                logging.debug(f"Received RTP packet seq={packet.sequence} size={len(packet.payload)} from {addr}")
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
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
