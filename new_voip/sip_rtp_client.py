import asyncio
import socket
import random
import hashlib
import time
import struct
import string

class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, audio_source, dest_ip, dest_port):
        self.audio_source = audio_source
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.transport = None
        self.sequence = 0
        self.timestamp = 0
        self.ssrc = random.randint(0, 0xFFFFFFFF)
        self.running = False

    def connection_made(self, transport):
        self.transport = transport
        self.running = True
        asyncio.create_task(self.stream_audio())

    async def stream_audio(self):
        print(f"[RTP] Start streaming to {self.dest_ip}:{self.dest_port}")
        # G.711 @ 8000Hz. 20ms = 160 samples
        FRAME_MS = 20
        SAMPLES_PER_FRAME = 160 # 8000 * 0.02
        
        next_time = time.time()
        
        while self.running:
            # 1. Get Audio Data
            payload = self.audio_source.get_frame(SAMPLES_PER_FRAME)
            
            # 2. Build RTP Header
            # V=2, P=0, X=0, CC=0, M=0, PT=8 (PCMA), Seq, TS, SSRC
            header = struct.pack('!BBHII', 
                                 0x80, # V=2
                                 8,    # Payload Type 8 (PCMA)
                                 self.sequence, 
                                 self.timestamp, 
                                 self.ssrc)
            
            packet = header + payload
            # Проверка, что транспорт еще жив
            if self.transport and not self.transport.is_closing():
                self.transport.sendto(packet, (self.dest_ip, self.dest_port))
            else:
                break
            
            # 3. Update counters
            self.sequence = (self.sequence + 1) % 65535
            self.timestamp = (self.timestamp + SAMPLES_PER_FRAME) % 4294967295
            
            # 4. Precise Timing
            next_time += (FRAME_MS / 1000.0)
            delay = next_time - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            
    def stop(self):
        print("[RTP] Stopping stream")
        self.running = False
        if self.transport:
            self.transport.close()


class SIPClient(asyncio.DatagramProtocol):
    def __init__(self, username, password, server_ip, local_ip):
        self.username = username
        self.password = password
        self.server_ip = server_ip
        self.local_ip = local_ip
        self.transport = None
        self.sip_port = 5060
        self.rtp_port = 10000 + random.randint(0, 5000)
        
        # SIP State
        self.call_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
        self.local_tag = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.remote_tag = None # Заполняется при ответе сервера (200 OK)
        self.branch = "z9hG4bK" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.cseq = 1
        
        self.registered = False
        self.current_target = None # Кому звоним
        
        self.rtp_protocol = None
        self.audio_source = None
        
        # Таймауты для SIP транзакций (в секундах)
        self.sip_timeout = 30
        self.register_timeout = 30
        
        # Очередь для ожидания ответов
        self.response_queue = asyncio.Queue()
        self.pending_requests = {} # CSeq -> (future, timeout_task)

    def connection_made(self, transport):
        self.transport = transport
        print(f"[SIP] Listening on {self.local_ip}:{self.sip_port}")

    def datagram_received(self, data, addr):
        msg = data.decode('utf-8', errors='ignore')
        asyncio.create_task(self.handle_sip_message(msg, addr))

    def set_audio_source(self, source):
        self.audio_source = source

    def send_raw(self, msg):
        # print(f">>> SENDING:\n{msg}") # Раскомментируй для отладки
        self.transport.sendto(msg.encode(), (self.server_ip, 5060))

    async def register(self):
        req = self._build_register_packet()
        self.send_raw(req)

    async def invite(self, target_number):
        print(f"[SIP] Calling {target_number}...")
        self.current_target = target_number
        self.cseq += 1
        req = self._build_invite_packet(target_number)
        self.send_raw(req)

    async def bye(self):
        if not self.current_target:
            return
            
        print("[SIP] Sending BYE...")
        self.cseq += 1
        
        # Формируем BYE
        # ВАЖНО: В BYE нужно указать remote_tag, который мы получили в 200 OK
        to_header = f"<sip:{self.current_target}@{self.server_ip}>"
        if self.remote_tag:
            to_header += f";tag={self.remote_tag}"

        msg = f"BYE sip:{self.current_target}@{self.server_ip} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\n"
        msg += f"From: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\n"
        msg += f"To: {to_header}\r\n"
        msg += f"Call-ID: {self.call_id}\r\n"
        msg += f"CSeq: {self.cseq} BYE\r\n"
        msg += f"Max-Forwards: 70\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        
        self.send_raw(msg)
        
        # Останавливаем RTP
        if self.rtp_protocol:
            self.rtp_protocol.stop()

    # --- Packet Builders ---
    def _build_register_packet(self, auth_header=None):
        msg = f"REGISTER sip:{self.server_ip} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch};rport\r\n"
        msg += f"From: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\n"
        msg += f"To: <sip:{self.username}@{self.server_ip}>\r\n"
        msg += f"Call-ID: {self.call_id}\r\n"
        msg += f"CSeq: {self.cseq} REGISTER\r\n"
        msg += f"Contact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\n"
        msg += f"Max-Forwards: 70\r\n"
        msg += f"User-Agent: PythonAIPhone/1.0\r\n"
        if auth_header:
            msg += f"{auth_header}\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return msg

    def _build_invite_packet(self, target, auth_header=None):
        sdp = f"v=0\r\n"
        sdp += f"o=- {self.call_id} {self.cseq} IN IP4 {self.local_ip}\r\n"
        sdp += f"s=-\r\n"
        sdp += f"c=IN IP4 {self.local_ip}\r\n"
        sdp += f"t=0 0\r\n"
        sdp += f"m=audio {self.rtp_port} RTP/AVP 8 0\r\n"
        sdp += f"a=rtpmap:8 PCMA/8000\r\n"
        sdp += f"a=rtpmap:0 PCMU/8000\r\n"
        sdp += f"a=sendrecv\r\n"
        
        msg = f"INVITE sip:{target}@{self.server_ip} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\n"
        msg += f"From: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\n"
        msg += f"To: <sip:{target}@{self.server_ip}>\r\n"
        msg += f"Call-ID: {self.call_id}\r\n"
        msg += f"CSeq: {self.cseq} INVITE\r\n"
        msg += f"Contact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\n"
        msg += f"Content-Type: application/sdp\r\n"
        if auth_header:
            msg += f"{auth_header}\r\n"
        msg += f"Content-Length: {len(sdp)}\r\n\r\n"
        msg += sdp
        return msg

    def _generate_auth(self, nonce, realm, method, uri):
        ha1 = hashlib.md5(f"{self.username}:{realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        return response

    def _extract_header(self, lines, header_name):
        """Безопасное извлечение заголовка"""
        header_name = header_name.lower()
        for line in lines:
            if line.lower().startswith(header_name + ":"):
                return line[len(header_name)+1:].strip()
        return None

    # --- Handlers ---
    async def handle_sip_message(self, msg, addr):
        try:
            lines = msg.splitlines()
            if not lines:
                return
            first_line = lines[0]
            
            # --- 1. Обработка 401/407 Unauthorized ---
            if "401 Unauthorized" in first_line or "407 Proxy Authentication Required" in first_line:
                # Извлекаем CSeq, чтобы понять, какой метод заблокировали (REGISTER или INVITE)
                cseq_line = self._extract_header(lines, "CSeq")
                cseq_method = cseq_line.split()[1] if cseq_line else "REGISTER"

                print(f"[SIP] Auth required for {cseq_method}...")
                
                # Парсим Nonce и Realm
                nonce = ""
                realm = ""
                auth_line = self._extract_header(lines, "WWW-Authenticate") or self._extract_header(lines, "Proxy-Authenticate")
                
                if auth_line:
                    parts = auth_line.split(',')
                    for p in parts:
                        if 'nonce="' in p:
                            nonce = p.split('nonce="')[1].split('"')[0]
                        if 'realm="' in p:
                            realm = p.split('realm="')[1].split('"')[0]

                self.cseq += 1
                self.branch = "z9hG4bK" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
                
                # Добавляем transport=UDP как в pyVoIP
                response = self._generate_auth(nonce, realm, cseq_method, f"sip:{self.server_ip};transport=UDP")
                auth_header = f'Authorization: Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="sip:{self.server_ip};transport=UDP", response="{response}", algorithm=MD5'
                
                if cseq_method == "REGISTER":
                    req = self._build_register_packet(auth_header)
                    self.send_raw(req)
                elif cseq_method == "INVITE":
                    req = self._build_invite_packet(self.current_target, auth_header)
                    self.send_raw(req)

            # --- 2. Обработка 100 Trying ---
            elif "100 Trying" in first_line:
                print("[SIP] Server is processing request...")

            # --- 3. Успешная регистрация ---
            elif "200 OK" in first_line and "REGISTER" in (self._extract_header(lines, "CSeq") or ""):
                print("[SIP] Registered Successfully!")
                self.registered = True

            # --- 4. Звонок идет (Ringing) ---
            elif "180 Ringing" in first_line:
                print("[SIP] Ringing...")

            # --- 5. Звонок принят (200 OK на INVITE) ---
            elif "200 OK" in first_line and "INVITE" in (self._extract_header(lines, "CSeq") or ""):
                print("[SIP] Call Answered! Handshake...")
                
                # ВАЖНО: Сохраняем Tag собеседника из заголовка To
                # Пример To: <sip:1001@IP>;tag=as53535
                to_header = self._extract_header(lines, "To")
                if to_header and "tag=" in to_header:
                    self.remote_tag = to_header.split("tag=")[1].split(";")[0]

                # Парсинг IP/Port для RTP из SDP
                remote_rtp_ip = self.server_ip
                remote_rtp_port = 10000
                
                for line in lines:
                    if line.startswith("c=IN"):
                        remote_rtp_ip = line.split()[-1]
                    if line.startswith("m=audio"):
                        remote_rtp_port = int(line.split()[1])

                # Отправка ACK (обязательно с правильными тегами!)
                ack = f"ACK sip:{self.current_target}@{self.server_ip} SIP/2.0\r\n"
                ack += f"Via: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\n"
                ack += f"From: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\n"
                ack += f"To: {to_header}\r\n" # Берем To прямо из ответа сервера
                ack += f"Call-ID: {self.call_id}\r\n"
                ack += f"CSeq: {self.cseq} ACK\r\n"
                ack += f"Content-Length: 0\r\n\r\n"
                self.send_raw(ack)

                # Запуск RTP
                if self.audio_source and not self.rtp_protocol:
                    loop = asyncio.get_running_loop()
                    _, protocol = await loop.create_datagram_endpoint(
                        lambda: RTPProtocol(self.audio_source, remote_rtp_ip, remote_rtp_port),
                        local_addr=('0.0.0.0', self.rtp_port)
                    )
                    self.rtp_protocol = protocol

            # --- 6. Обработка ошибок ---
            elif "486 Busy" in first_line:
                print(f"[SIP] {self.current_target} is busy")
            elif "404 Not Found" in first_line:
                print(f"[SIP] {self.current_target} not found")
            elif "403 Forbidden" in first_line:
                print("[SIP] Access forbidden")
            elif "487 Request Terminated" in first_line:
                print("[SIP] Request terminated")
            elif "500 Internal Server Error" in first_line:
                print("[SIP] Server error, retrying...")
            elif "503 Service Unavailable" in first_line:
                print("[SIP] Service unavailable")
            elif "408 Request Timeout" in first_line:
                print("[SIP] Request timeout")
            else:
                # Логируем неизвестные ответы для отладки
                print(f"[SIP] Received: {first_line}")
                
        except Exception as e:
            print(f"[SIP] Error handling message: {e}")
