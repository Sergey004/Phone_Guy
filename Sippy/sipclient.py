import threading
import queue
import time
import json
import logging
import socket
import hashlib
import random
import string
import uuid
import select
from datetime import datetime

from Sippy.audio_handler import AudioHandler
from Sippy.rtp_protocol import RTPHandler
from Sippy.sip_protocol import SIPProtocol

# Основной класс SIP-клиента
class SIPClient:
    def __init__(self, config):
        self.config = config
        self.username = config['sip']['username']
        self.password = config['sip']['password']
        self.domain = config['sip']['domain']
        self.local_addr = config['sip']['local_addr']
        self.local_port = config['sip']['local_port']
        self.remote_port = config['sip']['remote_port']
        self.transport = config['sip']['transport']
        self.register_interval = config['sip']['register_interval']
        self.call_id = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        self.branch = 'z9hG4bK' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        self.cseq = 1
        self.nonce_count = 0
        self.tag = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        self.sock = None
        self.logger = logging.getLogger('SIPClient')
        if config.get('debug', False):
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        self.audio = AudioHandler(config, self.logger)
        self.rtp = RTPHandler(config, self.logger, self.audio)
        self.sip = SIPProtocol(self)
        self.call_established = threading.Event()
        self.established_to = None
        # Адрес для bind(); может оставаться 0.0.0.0, даже если в SIP/SDP нужен реальный IP
        self.bind_addr = self.local_addr
        self.urnUUID = str(uuid.uuid4()).upper()

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)
        bind_ip = self.bind_addr
        if self.local_addr in ('0.0.0.0', '', '::'):
            try:
                tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                tmp.connect((self.domain, self.remote_port))
                detected_ip = tmp.getsockname()[0]
                tmp.close()
                self.logger.info(f"Auto-detected local IP for SIP/SDP: {detected_ip}")
                self.local_addr = detected_ip
                bind_ip = self.bind_addr
            except Exception as e:
                self.logger.warning(f"Failed to auto-detect local IP, continuing with {self.local_addr}: {e}")
        else:
            bind_ip = self.local_addr
        self.sock.bind((bind_ip, self.local_port))

    def _send(self, message, dest=None):
        if dest is None:
            dest = (self.domain, self.remote_port)
        self.sock.sendto(message.encode(), dest)
        self.logger.debug(f'Sent to {dest}: {message}')

    def _receive(self):
        while True:
            readable, _, _ = select.select([self.sock], [], [], 0.1)
            if readable:
                data, _ = self.sock.recvfrom(4096)
                response = data.decode()
                self.logger.debug(f'Received: {response}')
                return response

    def register(self):
        auth = None
        try:
            # First registration attempt
            self.cseq += 1 # Increment cseq for each new request
            register_msg = self.sip.build_register(auth)
            expected_cseq = self.cseq
            self.logger.debug(f"Sending initial REGISTER request:\n{register_msg}")
            self._send(register_msg)
            while True:
                response = self._receive()
                parsed = self.sip.parse_sip_message(response)
                if parsed['type'] == 'request':
                    self.sip.handle_message(parsed)
                    continue
                cseq_header = parsed['headers'].get('CSeq', '')
                if parsed['headers'].get('Call-ID') == self.call_id and cseq_header == f"{expected_cseq} REGISTER":
                    break
                else:
                    self.logger.warning(f"Ignored unrelated response: Call-ID {parsed['headers'].get('Call-ID')} CSeq {cseq_header}")
            
            if parsed['status_code'] == '401':
                # Handle authentication challenge
                auth = self.sip.parse_auth_header(response)
                if auth:
                    self.logger.info(f'Received 401 Unauthorized, attempting digest authentication with realm: {auth.get("realm", "unknown")}.')
                    self.cseq += 1
                    register_msg = self.sip.build_register(auth)
                    expected_cseq = self.cseq
                    self.logger.debug(f"Sending authenticated REGISTER request:\n{register_msg}")
                    self._send(register_msg)
                    while True:
                        response = self._receive()
                        parsed = self.sip.parse_sip_message(response)
                        if parsed['type'] == 'request':
                            self.sip.handle_message(parsed)
                            continue
                        cseq_header = parsed['headers'].get('CSeq', '')
                        if parsed['headers'].get('Call-ID') == self.call_id and cseq_header == f"{expected_cseq} REGISTER":
                            break
                        else:
                            self.logger.warning(f"Ignored unrelated response: Call-ID {parsed['headers'].get('Call-ID')} CSeq {cseq_header}")
                    
                    if parsed['status_code'] == '200':
                        self.logger.info('Registration successful with authentication')
                        # Start registration refresh timer
                        self._start_register_timer()
                        return True
                    else:
                        self.logger.error(f"Registration failed with status code {parsed['status_code']} after authentication attempt")
                        self.logger.debug(f"Failed registration response:\n{response}")
                        return False
                else:
                    self.logger.error('Failed to parse WWW-Authenticate header.')
                    self.logger.debug(f"Problematic WWW-Authenticate response:\n{response}")
                    return False
            elif parsed['status_code'] == '200':
                self.logger.info('Registration successful without authentication')
                # Start registration refresh timer
                self._start_register_timer()
                return True
            else:
                self.logger.error(f"Registration failed with status code {parsed['status_code']}")
                self.logger.debug(f"Failed registration response:\n{response}")
                return False
        except Exception as e:
            self.logger.error(f"Registration error: {e}")
            import traceback
            self.logger.debug(f"Registration error traceback: {traceback.format_exc()}")
            return False
             
    def _start_register_timer(self, delay=None):
        """Start a timer to refresh registration before it expires"""
        if delay is None:
            delay = self.register_interval - 5  # Register 5 seconds before expiration
        
        self.logger.debug(f"Setting up registration refresh timer for {delay} seconds")
        timer = threading.Timer(delay, self.register)
        timer.daemon = True
        timer.name = "SIP Register Refresh"
        timer.start()

    def deregister(self):
        """Deregister from the SIP server"""
        try:
            self.logger.info("Deregistering from SIP server")
            # Send a REGISTER with expires=0
            auth = None
            self.cseq += 1
            
            # First deregistration attempt
            expected_cseq = self.cseq
            register_msg = self.sip.build_register(auth, expires=0)
            self._send(register_msg)
            while True:
                response = self._receive()
                parsed = self.sip.parse_sip_message(response)
                if parsed['type'] == 'request':
                    self.sip.handle_message(parsed)
                    continue
                cseq_header = parsed['headers'].get('CSeq', '')
                if parsed['headers'].get('Call-ID') == self.call_id and cseq_header == f"{expected_cseq} REGISTER":
                    break
                else:
                    self.logger.warning(f"Ignored unrelated response: Call-ID {parsed['headers'].get('Call-ID')} CSeq {cseq_header}")
            
            if parsed['status_code'] == '401':
                # Handle authentication challenge
                auth = self.sip.parse_auth_header(response)
                if auth:
                    self.logger.info('Received 401 Unauthorized, attempting digest authentication for deregistration')
                    self.cseq += 1
                    expected_cseq = self.cseq
                    register_msg = self.sip.build_register(auth, expires=0)
                    self._send(register_msg)
                    while True:
                        response = self._receive()
                        parsed = self.sip.parse_sip_message(response)
                        if parsed['type'] == 'request':
                            self.sip.handle_message(parsed)
                            continue
                        cseq_header = parsed['headers'].get('CSeq', '')
                        if parsed['headers'].get('Call-ID') == self.call_id and cseq_header == f"{expected_cseq} REGISTER":
                            break
                        else:
                            self.logger.warning(f"Ignored unrelated response: Call-ID {parsed['headers'].get('Call-ID')} CSeq {cseq_header}")
                    
                    if parsed['status_code'] == '200':
                        self.logger.info('Deregistration successful')
                        return True
                    else:
                        self.logger.error(f"Deregistration failed with status code {parsed.get('status_code', 'Unknown')}")
                        self.logger.debug(f"Failed deregistration response:\n{response}")
                        return False
                else:
                    self.logger.error('Failed to parse WWW-Authenticate header during deregistration')
                    return False
            elif parsed['status_code'] == '200':
                self.logger.info('Deregistration successful')
                return True
            else:
                self.logger.error(f"Deregistration failed with status code {parsed.get('status_code', 'Unknown')}")
                self.logger.debug(f"Failed deregistration response:\n{response}")
                return False
        except Exception as e:
            self.logger.error(f"Deregistration error: {e}")
            return False
            
    def make_call(self, target):
        # Ensure target is a valid SIP URI
        if not target.startswith('sip:'):
            target = 'sip:' + target
        self.target = target
        self.call_id = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
        self.branch = 'z9hG4bK' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        self.tag = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        self.cseq = 1
        sdp = self.sip.build_sdp()
        invite_headers = {
            'Via': f'SIP/2.0/UDP {self.local_addr}:{self.local_port};branch={self.branch}',
            'From': f'<sip:{self.username}@{self.domain}>;tag={self.tag}',
            'To': f'<{target}>',
            'Call-ID': self.call_id,
            'CSeq': f'{self.cseq} INVITE',
            'Contact': f'<sip:{self.username}@{self.local_addr}:{self.local_port}>',
            'Max-Forwards': '70',
            'User-Agent': 'PurePythonSIP/1.0',
            'Content-Type': 'application/sdp'
        }
        self.invite_from = invite_headers['From']
        self.invite_to = invite_headers['To']
        self.invite_cseq = self.cseq
        invite_msg = self.sip.build_sip_message('INVITE', target, invite_headers, sdp)
        self._send(invite_msg)
        self.cseq += 1
        self.call_established.clear()
        self.call_established.wait()

    def listen(self):
        while True:
            try:
                response = self._receive()
                parsed = self.sip.parse_sip_message(response)
                if parsed['type'] == 'request':
                    self.sip.handle_message(parsed)
                elif parsed['type'] == 'response':
                    if parsed['headers']['Call-ID'] == self.call_id:
                        cseq_parts = parsed['headers']['CSeq'].split()
                        cseq_number = cseq_parts[0]
                        cseq_method = cseq_parts[1]
                        if cseq_method == 'INVITE':
                            if parsed['status_code'] == '100':
                                self.logger.info('Trying...')
                            elif parsed['status_code'] == '180':
                                self.logger.info('Ringing...')
                            elif parsed['status_code'] == '200':
                                self.established_to = parsed['headers']['To']
                                ack_branch = 'z9hG4bK' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                                ack_headers = {
                                    'Via': f'SIP/2.0/UDP {self.local_addr}:{self.local_port};branch={ack_branch}',
                                    'From': self.invite_from,
                                    'To': self.established_to,
                                    'Call-ID': self.call_id,
                                    'CSeq': f'{self.invite_cseq} ACK'
                                }
                                ack_msg = self.sip.build_sip_message('ACK', self.target, ack_headers)
                                self._send(ack_msg)
                                self.logger.info('Call established')
                                self.remote_rtp_addr = self.sip.parse_sdp_for_rtp(parsed['body'])
                                # Negotiate payload type from callee's SDP before starting RTP
                                pt, codec = self.sip.get_preferred_payload_type(parsed['body'])
                                self.rtp.negotiated_pt = pt
                                self.rtp.negotiated_codec = codec
                                self.logger.info(f'Negotiated PT={pt} ({codec}) for outgoing call')
                                # Для RTP биндимся по тому же принципу: если bind_addr = 0.0.0.0, слушаем на всех, но в SDP уже реальный IP
                                bind_ip = self.bind_addr if self.bind_addr in ('0.0.0.0', '::') else self.local_addr
                                self.rtp.start_rtp(bind_ip, self.remote_rtp_addr)
                                self.call_established.set()
                            elif parsed['status_code'] == '401':
                                auth_header = self.sip.parse_auth_header(response)
                                ha1 = hashlib.md5(f'{self.username}:{auth_header["realm"]}:{self.password}'.encode()).hexdigest()
                                ha2 = hashlib.md5(f'INVITE:{self.target}'.encode()).hexdigest()
                                if 'qop' in auth_header:
                                    cnonce = ''.join(random.choices('0123456789abcdef', k=16))
                                    self.nonce_count += 1
                                    nc = f"{self.nonce_count:08x}"
                                    digest_response = hashlib.md5(f'{ha1}:{auth_header["nonce"]}:{nc}:{cnonce}:{auth_header["qop"]}:{ha2}'.encode()).hexdigest()
                                    auth_str = f'Digest username="{self.username}", realm="{auth_header["realm"]}", nonce="{auth_header["nonce"]}", uri="{self.target}", response="{digest_response}", algorithm=MD5, qop="{auth_header["qop"]}", nc={nc}, cnonce="{cnonce}"'
                                else:
                                    digest_response = hashlib.md5(f'{ha1}:{auth_header["nonce"]}:{ha2}'.encode()).hexdigest()
                                    auth_str = f'Digest username="{self.username}", realm="{auth_header["realm"]}", nonce="{auth_header["nonce"]}", uri="{self.target}", response="{digest_response}", algorithm=MD5'
                                invite_headers = {
                                    'Via': f'SIP/2.0/UDP {self.local_addr}:{self.local_port};branch={self.branch}',
                                    'From': self.invite_from,
                                    'To': self.invite_to,
                                    'Call-ID': self.call_id,
                                    'CSeq': f'{self.cseq} INVITE',
                                    'Contact': f'<sip:{self.username}@{self.local_addr}:{self.local_port}>',
                                    'Authorization': auth_str,
                                    'Max-Forwards': '70',
                                    'User-Agent': 'PurePythonSIP/1.0',
                                    'Content-Type': 'application/sdp'
                                }
                                sdp = self.sip.build_sdp()
                                auth_invite_msg = self.sip.build_sip_message('INVITE', self.target, invite_headers, sdp)
                                self._send(auth_invite_msg)
                                self.cseq += 1
                            elif parsed['status_code'] == '486':
                                self.logger.info('Busy')
                            else:
                                self.logger.warning(f"Unhandled INVITE response: {parsed['status_code']} {parsed['reason']}")
                        elif cseq_method == 'BYE':
                            if parsed['status_code'] == '200':
                                self.logger.info('Call terminated')
                        else:
                            self.logger.info(f"Received response for {cseq_method}: {parsed['status_code']} {parsed['reason']}")
                    else:
                        self.logger.debug(f"Received response for other Call-ID: {parsed['headers']['Call-ID']}")
                else:
                    self.logger.warning(f"Unhandled message type: {parsed['type']}")
            except Exception as e:
                self.logger.error(f"Error in listen loop: {e}", exc_info=True)

    def start_rtp(self):
        bind_ip = self.bind_addr if self.bind_addr in ('0.0.0.0', '::') else self.local_addr
        self.rtp.start_rtp(bind_ip, self.remote_rtp_addr)

    def stop_rtp(self):
        self.rtp.stop()

    def play_audio(self, wav_path):
        self.logger.info(f"Setting next outgoing audio to: {wav_path}")
        self.audio.set_outgoing_wav(wav_path)

    def reinvite(self, hold=False):
        mode = 'sendonly' if hold else 'sendrecv'
        sdp = self.sip.build_sdp(mode=mode)
        
        self.cseq += 1
        
        reinvite_branch = 'z9hG4bK' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        
        to_header = self.established_to if self.established_to else self.invite_to
        
        reinvite_headers = {
            'Via': f'SIP/2.0/UDP {self.local_addr}:{self.local_port};branch={reinvite_branch}',
            'From': self.invite_from,
            'To': to_header,
            'Call-ID': self.call_id,
            'CSeq': f'{self.cseq} INVITE',
            'Contact': f'<sip:{self.username}@{self.local_addr}:{self.local_port}>',
            'Content-Type': 'application/sdp'
        }
        
        reinvite_msg = self.sip.build_sip_message('INVITE', f'sip:{self.target}', reinvite_headers, sdp)
        self._send(reinvite_msg)
        self.logger.info(f"Sent re-INVITE to {'hold' if hold else 'unhold'}")

    def send_bye(self):
        bye_msg = self.sip.build_bye()
        self._send(bye_msg)
        self.stop_rtp()
        self.logger.info("Sent BYE")

    def start_streaming_input(self, max_queue_frames: int | None = None):
        self.audio.start_stream_input(max_queue_frames=max_queue_frames)

    def push_stream_pcm(self, data: bytes, sample_rate: int = 8000, sample_width: int = 2, channels: int = 1):
        return self.audio.push_stream_pcm(data, sample_rate=sample_rate, sample_width=sample_width, channels=channels)

    def push_stream_pcm48k(self, data: bytes, sample_width: int = 2, channels: int = 1):
        return self.audio.push_stream_pcm48k(data, sample_width=sample_width, channels=channels)

    def push_stream_pcm40k(self, data: bytes, sample_width: int = 2, channels: int = 1):
        return self.audio.push_stream_pcm40k(data, sample_width=sample_width, channels=channels)

    def push_stream_float32(self, data: bytes, sample_rate: int, channels: int = 1):
        return self.audio.push_stream_float32(data, sample_rate=sample_rate, channels=channels)

    def start_ffmpeg_source_stream(self, source: str, input_options: dict | None = None, read_chunk_ms: int = 100):
        self.audio.start_ffmpeg_source_stream(source, input_options=input_options, read_chunk_ms=read_chunk_ms)

    def stop_ffmpeg_source_stream(self):
        self.audio.stop_ffmpeg_source_stream()

    def end_streaming_input(self):
        self.audio.end_stream_input()

    def wait_stream_finished(self, timeout: float | None = None) -> bool:
        evt = getattr(self.audio, 'stream_finished_event', None)
        if evt is None:
            return True
        try:
            if timeout is None:
                evt.wait()
                return True
            else:
                evt.wait(timeout)
                return True
        except:
            return False
            
    def stop(self):
        # Deregister from SIP server first
        if hasattr(self, 'sock') and self.sock:
            self.deregister()
            self.sock.close()
        if hasattr(self, 'rtp') and self.rtp:
            self.rtp.stop()
