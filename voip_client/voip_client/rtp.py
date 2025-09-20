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
import io


from .config import DEFAULT_RTP_PORT_RANGE, AUDIO_FRAME_SIZE


# A small byte-oriented packet manager (inspired by pyVoIP.RTPPacketManager)
class RTPPacketManager:
    def __init__(self):
        # Offset chosen as in pyVoIP to keep monotonic timestamp space
        self.offset = 4294967296
        self.buffer = io.BytesIO()
        self.bufferLock = threading.Lock()
        self.log = {}
        self.rebuilding = False

    def read(self, length: int = 320) -> bytes:
        # If a rebuild is in progress, wait briefly
        while self.rebuilding:
            time.sleep(0.01)
        with self.bufferLock:
            packet = self.buffer.read(length)
            if len(packet) < length:
                packet = packet + (b"\x00" * (length - len(packet)))
        return packet

    def rebuild(self, reset: bool, offset: int = 0, data: bytes = b"") -> None:
        self.rebuilding = True
        if reset:
            self.log = {}
            self.log[offset] = data
            self.buffer = io.BytesIO(data)
        else:
            bufferloc = self.buffer.tell()
            self.buffer = io.BytesIO()
            for pkt in self.log:
                self.write(pkt, self.log[pkt])
            self.buffer.seek(bufferloc, 0)
        self.rebuilding = False

    def write(self, offset: int, data: bytes) -> None:
        self.bufferLock.acquire()
        self.log[offset] = data
        bufferloc = self.buffer.tell()
        if offset < self.offset:
            reset = abs(offset - self.offset) >= 100000
            self.offset = offset
            self.bufferLock.release()
            self.rebuild(reset, offset, data)
            return
        offset = offset - self.offset
        self.buffer.seek(offset, 0)
        self.buffer.write(data)
        self.buffer.seek(bufferloc, 0)
        self.bufferLock.release()

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

    def is_rtcp(self):
        """
        Checks if the packet is an RTCP packet.
        RTCP packet types are typically in the range 200-204.
        """
        return 200 <= self.payload_type <= 204

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
    def __init__(self, max_delay_ms=200, sample_rate=8000, auto_adjust=False):
        self.max_delay_ms = max_delay_ms
        self.sample_rate = sample_rate
        self.auto_adjust = auto_adjust
        self.buffer = queue.PriorityQueue()
        self.lock = threading.Lock()
        self.next_sequence = 0
        # Capacity based on time window, assuming minimum 10 ms packetization
        self.max_buffer_size = max(10, int(self.max_delay_ms / 10) + 5)
        self.last_good_packet = None
        # Statistics
        self.packets_received = 0
        self.packets_lost = 0
        self.packets_late = 0
        self.log_interval = 5  # Log stats every 5 seconds
        self.last_log_time = time.time()
        self.last_adjust_time = time.time()
        self.comfort_noise_frame = b'\x00' * 160 # Default to 20ms of silence for G.711
        self.adjust_interval = 1 # Adjust every 1 second

        # Asynchronous sending
        self.send_queue = queue.Queue()
        self.send_thread = None
        self.send_running = False

    def _send_loop(self):
        """
        Background thread for sending RTP packets from the send_queue.
        """
        logging.info("RTP send thread started")
        while self.send_running:
            try:
                frame_data = self.send_queue.get(timeout=0.1)
                if frame_data is None: # Sentinel value to stop the thread
                    break

                frame, is_auto_packetization = frame_data

                if is_auto_packetization:
                    # Logic for dynamic packetization
                    packet = RtpPacket(
                        payload_type=self.payload_type,
                        sequence=self.seq,
                        timestamp=self.timestamp,
                        ssrc=self.ssrc,
                        payload=frame
                    )
                    self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                    logging.debug(f"Sent RTP packet seq={packet.sequence} size={len(packet.payload)} to {self.remote_ip}:{self.remote_port}")
                    try:
                        seq_val = int(self.seq) if self.seq is not None else 0
                    except Exception:
                        seq_val = 0
                    self.seq = (seq_val + 1) % 65536
                    try:
                        ts_val = int(self.timestamp) if self.timestamp is not None else 0
                    except Exception:
                        ts_val = 0
                    self.timestamp = (ts_val + len(frame)) % (2**32)
                    logging.debug(f"Before timestamp update: self.timestamp type={type(self.timestamp)}, value={self.timestamp}; len(frame) value={len(frame)}")

                    # Simple backlog-based adaptation
                    backlog_ms = len(self._tx_buffer) // self.bytes_per_ms
                    if backlog_ms > 60 and self.packetization_ms < self.max_packetization_ms:
                        self.packetization_ms = min(self.packetization_ms + 10, self.max_packetization_ms)
                    elif backlog_ms < 15 and self.packetization_ms > self.min_packetization_ms:
                        self.packetization_ms = max(self.packetization_ms - 10, self.min_packetization_ms)
                else:
                    # Logic for fixed-size packetization
                    frame_size = AUDIO_FRAME_SIZE
                    if not isinstance(frame_size, int) or frame_size <= 0:
                        frame_size = 160
                    
                    # Assuming 'frame' here is already a packet-sized chunk
                    packet = RtpPacket(
                        payload_type=self.payload_type,
                        sequence=self.seq,
                        timestamp=self.timestamp,
                        ssrc=self.ssrc,
                        payload=frame
                    )
                    self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                    logging.debug(f"Sent RTP packet seq={packet.sequence} size={len(packet.payload)} to {self.remote_ip}:{self.remote_port}")
                    try:
                        seq_val = int(self.seq) if self.seq is not None else 0
                    except Exception:
                        seq_val = 0
                    self.seq = (seq_val + 1) % 65536
                    try:
                        ts_val = int(self.timestamp) if self.timestamp is not None else 0
                    except Exception:
                        ts_val = 0
                    self.timestamp = (ts_val + len(frame)) % (2**32)
                    logging.debug(f"Before timestamp update: self.timestamp type={type(self.timestamp)}, value={self.timestamp}; len(frame) value={len(frame)}")

            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"RTP send loop error: {e}")
        logging.info("RTP send thread exiting")

    def _adjust_buffer_delay(self):
        if not self.auto_adjust:
            return

        now = time.time()
        if now - self.last_adjust_time < self.adjust_interval:
            return

        self.last_adjust_time = now

        # Simple adjustment logic:
        # If packet loss is high, increase delay to allow more time for packets to arrive.
        # If buffer is consistently low, decrease delay to reduce latency.
        # These are heuristic values and might need tuning.

        if self.packets_lost > 0 and self.max_delay_ms < 500:
            self.max_delay_ms = min(500, self.max_delay_ms + 20)  # Increase by 20ms, max 500ms
            logging.info(f"JitterBuffer: Increasing max_delay_ms to {self.max_delay_ms} due to packet loss.")
        elif self.buffer.qsize() < self.max_buffer_size / 2 and self.max_delay_ms > 60:
            self.max_delay_ms = max(60, self.max_delay_ms - 10)  # Decrease by 10ms, min 60ms
            logging.info(f"JitterBuffer: Decreasing max_delay_ms to {self.max_delay_ms} due to low buffer.")

        # Reset packet loss counter after adjustment period
        self.packets_lost = 0

    def add_packet(self, packet):
        """
        Add RTP packet to the jitter buffer.
        """
        with self.lock:
            self.packets_received += 1
            if self.next_sequence is None or not isinstance(self.next_sequence, int):
                try:
                    self.next_sequence = int(packet.sequence)
                except Exception:
                    self.next_sequence = 0

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
        self._adjust_buffer_delay()

    def write_to_manager(self, packet, manager, codec='pcmu'):
        """
        Convert RTP packet payload (G.711) to 16-bit PCM and write into
        the provided byte-oriented manager at timestamp offset.
        """
        try:
            if codec == 'pcmu':
                # ulaw -> 16-bit PCM (width=2)
                pcm = audioop.ulaw2lin(packet.payload, 2)
            else:
                pcm = audioop.alaw2lin(packet.payload, 2)
        except Exception as e:
            logging.error(f"Error decoding G.711 payload to PCM: {e}")
            pcm = b"\x00" * 320

        # Timestamp offset used as the write offset in manager
        try:
            offset = int(packet.timestamp) if packet.timestamp is not None else 0
        except Exception:
            offset = 0
        manager.write(offset, pcm)

    def get_next_packet(self, timeout=0.05):
        """
        Get the next packet in sequence order.
        Если нет пакета — всегда возвращать тишину (0x80), как pyVoIP.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if not self.buffer.empty():
                    seq, packet = self.buffer.queue[0]
                    if seq == self.next_sequence:
                        _, packet = self.buffer.get()
                        try:
                            seq_val = int(self.next_sequence) if self.next_sequence is not None else 0
                        except Exception:
                            seq_val = 0
                        self.next_sequence = (seq_val + 1) % 65536
                        self.last_good_packet = packet
                        return packet
                    elif seq < self.next_sequence:
                        # Packet is older than what we expect, discard
                        self.buffer.get()
                        self.packets_late += 1
                        continue
                    # Packet is in the future, wait
            time.sleep(0.001)

        # Нет пакета — возвращаем тишину (0x80) длиной 160 байт
        last_len = 160
        payload_type = 0
        if not isinstance(self.next_sequence, int):
            next_ts = 0
        else:
            next_ts = self.next_sequence
        next_ssrc = 0
        plc_payload = b"\x80" * last_len
        if not isinstance(self.next_sequence, int):
            seq_val = 0
        else:
            seq_val = self.next_sequence
        plc_packet = RtpPacket(
            payload_type=payload_type,
            sequence=seq_val,
            timestamp=next_ts,
            ssrc=next_ssrc,
            payload=plc_payload
        )
        self.next_sequence = (seq_val + 1) % 65536
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
            self.next_sequence = 0
            self.last_good_packet = None
            self.packets_received = 0
            self.packets_lost = 0
            self.packets_late = 0

class RtpSession:
    def _send_loop(self):
        """
        Фоновый поток для отправки RTP-пакетов из send_queue.
        """
        import logging
        logging.info("RTP send thread started (RtpSession)")
        while self.send_running:
            try:
                frame_data = self.send_queue.get(timeout=0.1)
                if frame_data is None:  # Sentinel value to остановить поток
                    break

                frame, is_auto_packetization = frame_data

                if is_auto_packetization:
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
                    ts_val = int(self.timestamp) if self.timestamp is not None else 0
                    self.timestamp = (ts_val + len(frame)) % (2**32)
                else:
                    frame_size = AUDIO_FRAME_SIZE
                    if not isinstance(frame_size, int) or frame_size <= 0:
                        frame_size = 160
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
                    ts_val = int(self.timestamp) if self.timestamp is not None else 0
                    self.timestamp = (ts_val + len(frame)) % (2**32)
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"RTP send loop error (RtpSession): {e}")
        logging.info("RTP send thread exiting (RtpSession)")
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

        # No VAD: simplify receive path to avoid numpy/vad dependencies
        self.vad_enabled = False
        self.vad = None
        self.last_vad_state = False

        self.running = False
        self.recv_thread = None
        self.send_lock = threading.Lock()
        self.recv_lock = threading.Lock()
        self.jitter_buffer = JitterBuffer(max_delay_ms=200, auto_adjust=True)

        # Очередь для отправки RTP-пакетов
        self.send_queue = queue.Queue()

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

        self.send_running = True
        self.send_thread = threading.Thread(target=self._send_loop, name="rtp_tx")  
        self.send_thread.daemon = True
        self.send_thread.start()

    def send_audio(self, audio_data):
        """
        Send audio data as RTP packets.
        """
        self._tx_buffer.extend(audio_data)

        if AUDIO_FRAME_SIZE == 'auto':
            # Dynamic packetization
            while len(self._tx_buffer) >= self.packetization_ms * self.bytes_per_ms:
                frame_size = self.packetization_ms * self.bytes_per_ms
                frame = bytes(self._tx_buffer[:frame_size])
                del self._tx_buffer[:frame_size]
                self.send_queue.put((frame, True))
        else:
            # Fixed-size packetization
            frame_size = AUDIO_FRAME_SIZE
            if not isinstance(frame_size, int) or frame_size <= 0:
                frame_size = 160
            while len(self._tx_buffer) >= frame_size:
                frame = bytes(self._tx_buffer[:frame_size])
                del self._tx_buffer[:frame_size]
                self.send_queue.put((frame, False))

    def _receive_loop(self):
        """
        Background thread for receiving RTP packets.
        """
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                packet = RtpPacket.from_bytes(data)
                if not packet.is_rtcp():
                    # Simplified: accept any non-empty payload and add to jitter buffer
                    if packet.payload and len(packet.payload) > 0:
                        self.jitter_buffer.add_packet(packet)
                    else:
                        logging.debug("Received RTP packet with empty payload, skipping")

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
        # On first call, create a byte-oriented manager to aggregate decoded PCM
        if not hasattr(self, '_pcm_manager'):
            self._pcm_manager = RTPPacketManager()

        # Try to collect a packet from jitter buffer and write decoded PCM into manager
        packet = self.jitter_buffer.get_next_packet(timeout=timeout)
        if packet:
            # Decode and write into manager
            try:
                # Assume PCMU for now (payload type 0)
                self.jitter_buffer.write_to_manager(packet, self._pcm_manager, codec='pcmu')
            except Exception as e:
                logging.error(f"Error writing packet to pcm manager: {e}")

        # Read fixed-size PCM chunk (320 bytes by default) and return it
        try:
            pcm = self._pcm_manager.read(320)
            return pcm
        except Exception as e:
            logging.error(f"Error reading PCM from manager: {e}")
            return b"\x00" * 320

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
