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
        if str(self.negotiated_codec).upper() == 'OPUS':
            return 960
        return 160

    def start_rtp(self, local_addr, remote_rtp_addr):
        self.rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.rtp_sock.bind((local_addr, self.rtp_port))
        self.rtp_sock.setblocking(False)
        self.remote_rtp_addr = remote_rtp_addr
        self.rtp_running = True
        try:
            if not getattr(self.audio_handler, 'stream_active', False):
                self.audio_handler.open_wav()
            else:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug('Streaming input active: skipping open_wav()')
        except Exception as e:
            self.logger.warning(f'Could not open outgoing WAV: {e}')
        jitter_ms = int(self.config.get('rtp', {}).get('jitter_ms', 200))
        frames = max(5, min(50, jitter_ms // 20))
        self.jitter_queue = queue.Queue(maxsize=frames)
        self.jitter_min_level = max(2, frames // 2)
        self.send_thread = threading.Thread(target=self.send_rtp_packet, daemon=True)
        self.recv_thread = threading.Thread(target=self.process_received_packet, daemon=True)
        self.playout_thread = threading.Thread(target=self.process_playout, daemon=True)
        self.send_thread.start()
        self.recv_thread.start()
        self.playout_thread.start()

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
        if not self.rtp_running:
            return
        step = self._timestamp_step()
        if self.on_hold:
            pcm = b'\x00' * (160 * 2)
        else:
            pcm = self.audio_handler.read_frames(160)
            if not pcm:
                pcm = b'\x00' * (160 * 2)
        payload = self._encode_payload(pcm)
        if payload and self.rtp_sock:
            rtp_packet = self._build_rtp_packet(payload)
            self.rtp_sock.sendto(rtp_packet, self.remote_rtp_addr)
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f'Sent RTP packet to {self.remote_rtp_addr}, seq={self.rtp_seq}, timestamp={self.rtp_timestamp}, pt={self.negotiated_pt}')
        else:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug('Skipped sending RTP due to unsupported codec or empty payload')
        self.rtp_timestamp += step
        self.rtp_seq += 1

    def process_received_packet(self, data, addr):
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
        if self.jitter_queue is not None:
            target = max(self.jitter_min_level, 2)
            while prefill < target and self.rtp_running:
                try:
                    frame = self.jitter_queue.get(timeout=1.0)
                    self.audio_handler.write_to_output(frame)
                    prefill += 1
                except queue.Empty:
                    break
        if self.jitter_queue is not None:
            try:
                frame = self.jitter_queue.get_nowait()
            except queue.Empty:
                frame = None
        if frame is None:
            frame = b'\x00' * frame_bytes
        self.audio_handler.write_to_output(frame)

    def _build_rtp_packet(self, payload):
        b0 = 0x80
        b1 = self.negotiated_pt & 0x7F
        header = struct.pack('!BBHII', b0, b1, self.rtp_seq, self.rtp_timestamp, self.ssrc)
        return header + payload
