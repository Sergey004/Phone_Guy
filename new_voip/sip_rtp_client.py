import asyncio
import socket
import random
import hashlib
import time
import struct
import string
import audioop

class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, audio_source, dest_ip, dest_port, stt_adapter=None):
        self.audio_source = audio_source
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.stt_adapter = stt_adapter
        self.transport = None
        self.sequence = 0
        self.timestamp = 0
        self.ssrc = random.randint(0, 0xFFFFFFFF)
        self.running = False

    def connection_made(self, transport):
        self.transport = transport
        self.running = True
        print(f"[RTP] Connected. Sending to {self.dest_ip}:{self.dest_port}")
        asyncio.create_task(self.stream_audio())

    def datagram_received(self, data, addr):
        # Принимаем звук от сервера (собеседника)
        if not self.stt_adapter:
            return

        try:
            # RTP заголовок = 12 байт. 
            # Проверяем версию RTP (первые 2 бита = 10.. -> 0x80)
            if len(data) > 12 and (data[0] & 0xC0) == 0x80:
                payload = data[12:]
                
                # Декодируем G.711 A-Law (Bytes) -> PCM 16-bit (Bytes)
                # width=2, так как выходной PCM 16-битный
                pcm_data = audioop.alaw2lin(payload, 2)
                
                # Отправляем в STT адаптер
                self.stt_adapter.enqueue_frame(pcm_data)
        except Exception as e:
            # Игнорируем ошибки декодирования отдельных пакетов, чтобы не крашить поток
            pass

    async def stream_audio(self):
        # Отправка звука (голос бота) на сервер
        FRAME_MS = 20
        SAMPLES_PER_FRAME = 160 # 8000Hz * 0.02s
        
        next_time = time.time()
        
        while self.running:
            # 1. Берем звук из моста (TTS)
            payload = self.audio_source.get_frame(SAMPLES_PER_FRAME)
            
            # 2. Собираем RTP заголовок
            # PT=8 (PCMA)
            header = struct.pack('!BBHII', 
                                 0x80, 
                                 8, 
                                 self.sequence, 
                                 self.timestamp, 
                                 self.ssrc)
            
            packet = header + payload
            
            # 3. Отправляем
            if self.transport and not self.transport.is_closing():
                # self.transport.sendto уже знает адрес, так как мы используем connect в endpoint? 
                # Нет, для UDP лучше явно указывать, если endpoint не связан.
                # Но в create_datagram_endpoint мы обычно не делаем connect.
                # Поэтому шлем явно на dest_ip/port
                self.transport.sendto(packet, (self.dest_ip, self.dest_port))
            else:
                break
            
            # 4. Обновляем счетчики
            self.sequence = (self.sequence + 1) % 65535
            self.timestamp = (self.timestamp + SAMPLES_PER_FRAME) % 4294967295
            
            # 5. Тайминг
            next_time += (FRAME_MS / 1000.0)
            delay = next_time - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

    def stop(self):
        print("[RTP] Stopping.")
        self.running = False
        if self.transport:
            self.transport.close()


class SIPClient(asyncio.DatagramProtocol):
    def __init__(self, username, password, server_ip, local_ip, stt_adapter=None):
        self.username = username
        self.password = password
        self.server_ip = server_ip
        self.local_ip = local_ip
        self.stt_adapter = stt_adapter
        
        self.transport = None
        self.sip_port = 5060
        self.rtp_port = 10000 + random.randint(0, 5000)
        
        self.call_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
        self.local_tag = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.remote_tag = None
        self.branch = "z9hG4bK" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.cseq = 1
        self.sess_id = random.randint(1, 999999999)
        self.sess_version = 1
        
        self.registered = False
        self.current_target = None
        self.rtp_protocol = None
        self.audio_source = None

    def connection_made(self, transport):
        self.transport = transport
        print(f"[SIP] Listening on {self.local_ip}:{self.sip_port}")

    def datagram_received(self, data, addr):
        msg = data.decode('utf-8', errors='ignore')
        asyncio.create_task(self.handle_sip_message(msg, addr))

    def set_audio_source(self, source):
        self.audio_source = source

    def send_raw(self, msg):
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
        if not self.current_target: return
        print("[SIP] Sending BYE...")
        self.cseq += 1
        
        to_header = f"<sip:{self.current_target}@{self.server_ip}>"
        if self.remote_tag: to_header += f";tag={self.remote_tag}"

        msg = f"BYE sip:{self.current_target}@{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: {to_header}\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} BYE\r\nMax-Forwards: 70\r\nContent-Length: 0\r\n\r\n"
        self.send_raw(msg)
        if self.rtp_protocol: self.rtp_protocol.stop()

    # --- Packet Builders ---
    def _build_register_packet(self, auth_header=None):
        msg = f"REGISTER sip:{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch};rport\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: <sip:{self.username}@{self.server_ip}>\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} REGISTER\r\nContact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\nMax-Forwards: 70\r\nUser-Agent: PhoneGuyBot/1.0\r\n"
        if auth_header: msg += f"{auth_header}\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return msg

    def _build_invite_packet(self, target, auth_header=None):
        self.sess_version += 1
        sdp = f"v=0\r\no=- {self.sess_id} {self.sess_version} IN IP4 {self.local_ip}\r\ns=-\r\nc=IN IP4 {self.local_ip}\r\nt=0 0\r\nm=audio {self.rtp_port} RTP/AVP 8 0\r\na=rtpmap:8 PCMA/8000\r\na=rtpmap:0 PCMU/8000\r\na=sendrecv\r\n"
        
        msg = f"INVITE sip:{target}@{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: <sip:{target}@{self.server_ip}>\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} INVITE\r\nContact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\nContent-Type: application/sdp\r\n"
        if auth_header: msg += f"{auth_header}\r\n"
        msg += f"Content-Length: {len(sdp)}\r\n\r\n{sdp}"
        return msg

    def _generate_auth(self, nonce, realm, method, uri):
        ha1 = hashlib.md5(f"{self.username}:{realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        return hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

    def _extract_header(self, lines, header_name):
        header_name = header_name.lower()
        for line in lines:
            if line.lower().startswith(header_name + ":"):
                return line[len(header_name)+1:].strip()
        return None

    # --- Handlers ---
    async def handle_sip_message(self, msg, addr):
        lines = msg.splitlines()
        if not lines: return
        first_line = lines[0]
        
        # 1. Auth Challenge
        if "401 Unauthorized" in first_line or "407 Proxy Authentication Required" in first_line:
            cseq_line = self._extract_header(lines, "CSeq")
            cseq_method = cseq_line.split()[1] if cseq_line else "REGISTER"
            
            # Parsing Auth Header
            nonce = ""
            realm = ""
            auth_line = self._extract_header(lines, "WWW-Authenticate") or self._extract_header(lines, "Proxy-Authenticate")
            if auth_line:
                for p in auth_line.split(','):
                    if 'nonce="' in p: nonce = p.split('nonce="')[1].split('"')[0]
                    if 'realm="' in p: realm = p.split('realm="')[1].split('"')[0]

            self.cseq += 1
            self.branch = "z9hG4bK" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            
            uri = f"sip:{self.server_ip}" if cseq_method == "REGISTER" else f"sip:{self.current_target}@{self.server_ip}"
            response = self._generate_auth(nonce, realm, cseq_method, uri)
            auth_header = f'Authorization: Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}", algorithm=MD5'
            
            if cseq_method == "REGISTER": self.send_raw(self._build_register_packet(auth_header))
            elif cseq_method == "INVITE": self.send_raw(self._build_invite_packet(self.current_target, auth_header))

        # 2. Registered
        elif "200 OK" in first_line and "REGISTER" in (self._extract_header(lines, "CSeq") or ""):
            print("[SIP] Registered Successfully!")
            self.registered = True

        # 3. Call Answered
        elif "200 OK" in first_line and "INVITE" in (self._extract_header(lines, "CSeq") or ""):
            print("[SIP] Call Answered! Starting RTP...")
            to_header = self._extract_header(lines, "To")
            if to_header and "tag=" in to_header: self.remote_tag = to_header.split("tag=")[1].split(";")[0]

            # --- ИСПРАВЛЕНИЕ: ПАРСИНГ ПРАВИЛЬНОГО ПОРТА ---
            remote_rtp_ip = self.server_ip
            remote_rtp_port = 10000 
            
            for line in lines:
                if line.startswith("c=IN"): remote_rtp_ip = line.split()[-1]
                if line.startswith("m=audio"): remote_rtp_port = int(line.split()[1])

            # Send ACK
            ack = f"ACK sip:{self.current_target}@{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: {to_header}\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} ACK\r\nContent-Length: 0\r\n\r\n"
            self.send_raw(ack)

            # --- ИСПРАВЛЕНИЕ: ПЕРЕДАЧА ПРАВИЛЬНОГО ПОРТА В RTP ---
            if self.audio_source and not self.rtp_protocol:
                loop = asyncio.get_running_loop()
                _, protocol = await loop.create_datagram_endpoint(
                    lambda: RTPProtocol(self.audio_source, remote_rtp_ip, remote_rtp_port, self.stt_adapter),
                    local_addr=('0.0.0.0', self.rtp_port)
                )
                self.rtp_protocol = protocol