"""
Pure Python SIP/RTP Client Library
No external dependencies - uses only Python 3.9+ standard library
"""

import asyncio
import hashlib
import random
import socket
import struct
import time
import re
from typing import Optional, Tuple, Dict, Any


def generate_branch() -> str:
    return f"z9hG4bK{random.randint(1000000000, 9999999999)}"


def generate_call_id() -> str:
    return f"{random.randint(1000000000, 9999999999)}@{socket.gethostname()}"


def generate_tag() -> str:
    return str(random.randint(1000000000, 9999999999))


def generate_md5_digest(method: str, uri: str, username: str, password: str, 
                       realm: str, nonce: str) -> str:
    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    return response


def parse_sip_message(data: bytes) -> Dict[str, Any]:
    try:
        text = data.decode('utf-8', errors='ignore')
        lines = text.split('\r\n')
        first_line = lines[0]
        parts = first_line.split(' ')
        
        if parts[0].startswith('SIP/2.0'):
            status_code = int(parts[1])
        else:
            status_code = None
        
        headers = {}
        body_start = 0
        for i, line in enumerate(lines[1:], 1):
            if line == '':
                body_start = i + 1
                break
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip().lower()] = value.strip()
        
        body = '\r\n'.join(lines[body_start:]) if body_start > 0 else ''
        return {'status_code': status_code, 'headers': headers, 'body': body}
    except Exception as e:
        return {'status_code': None, 'headers': {}, 'body': ''}


def parse_sdp(body: str) -> Optional[Tuple[str, int]]:
    try:
        lines = body.split('\r\n')
        connection = None
        media_port = None
        for line in lines:
            if line.startswith('c=IN IP4 '):
                connection = line.split(' ')[2]
            elif line.startswith('m=audio '):
                parts = line.split(' ')
                media_port = int(parts[1])
        if connection and media_port:
            return (connection, media_port)
        return None
    except Exception:
        return None


class RtpPacket:
    VERSION = 2
    PAYLOAD_TYPE = 8
    
    def __init__(self, ssrc: int = None):
        self.sequence = random.randint(0, 65535)
        self.timestamp = random.randint(0, 4294967295)
        self.ssrc = ssrc if ssrc is not None else random.randint(0, 4294967295)
    
    def pack(self, payload: bytes) -> bytes:
        first_byte = (self.VERSION << 6) | 0x80
        second_byte = self.PAYLOAD_TYPE
        header = struct.pack('!BBHII', first_byte, second_byte, 
                           self.sequence, self.timestamp, self.ssrc)
        return header + payload
    
    def increment(self, samples: int = 160):
        self.sequence = (self.sequence + 1) & 0xFFFF
        self.timestamp = (self.timestamp + samples) & 0xFFFFFFFF


class RtpTransport:
    CHUNK_SIZE = 160
    CHUNK_DELAY = 0.02
    
    def __init__(self, local_ip: str, local_port: int):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_addr: Optional[Tuple[str, int]] = None
        self.sock: Optional[socket.socket] = None
        self.rtp_packet = RtpPacket()
        self.running = False
    
    async def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.local_ip, self.local_port))
        self.running = True
    
    def set_remote(self, ip: str, port: int):
        self.remote_addr = (ip, port)
    
    async def send_audio(self, data: bytes):
        if not self.running or not self.sock:
            raise RuntimeError("RTP transport not started")
        if not self.remote_addr:
            raise RuntimeError("Remote RTP address not set")
        
        for i in range(0, len(data), self.CHUNK_SIZE):
            chunk = data[i:i + self.CHUNK_SIZE]
            if len(chunk) < self.CHUNK_SIZE:
                chunk = chunk.ljust(self.CHUNK_SIZE, b'\xd5')
            
            packet = self.rtp_packet.pack(chunk)
            self.sock.sendto(packet, self.remote_addr)
            self.rtp_packet.increment(self.CHUNK_SIZE)
            await asyncio.sleep(self.CHUNK_DELAY)
    
    async def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()
            self.sock = None


class SipProtocol(asyncio.DatagramProtocol):
    def __init__(self, client):
        self.client = client
        self.transport = None
        self.pending_requests: Dict[str, asyncio.Future] = {}
    
    def connection_made(self, transport):
        self.transport = transport
    
    def datagram_received(self, data, addr):
        try:
            message = parse_sip_message(data)
            call_id = message['headers'].get('call-id', '')
            
            if call_id in self.pending_requests:
                future = self.pending_requests.pop(call_id)
                if not future.done():
                    future.set_result(message)
            
            if message['status_code'] is None:
                method = data.decode('utf-8', errors='ignore').split(' ')[0]
                if method == 'INVITE':
                    self._handle_invite(data, addr)
        except Exception as e:
            print(f"Error processing SIP message: {e}")
    
    def _handle_invite(self, data: bytes, addr: Tuple[str, int]):
        message = parse_sip_message(data)
        from_tag = message['headers'].get('from', '')
        print(f"Incoming INVITE from: {from_tag}")
    
    async def send_request(self, request: str, call_id: str, timeout: float = 5.0) -> Dict[str, Any]:
        if not self.transport:
            raise RuntimeError("Transport not ready")
        
        future = asyncio.Future()
        self.pending_requests[call_id] = future
        
        # Send to server address
        server_addr = (self.client.server_ip, self.client.server_port)
        self.transport.sendto(request.encode(), server_addr)
        
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            self.pending_requests.pop(call_id, None)
            raise TimeoutError(f"SIP request timeout for {call_id}")
    
    def error_received(self, exc):
        print(f"SIP protocol error: {exc}")
    
    def connection_lost(self, exc):
        print(f"SIP connection lost: {exc}")


class Call:
    def __init__(self, client, call_id: str, target: str, local_rtp_port: int):
        self.client = client
        self.call_id = call_id
        self.target = target
        self.local_rtp_port = local_rtp_port
        self.success = False
        self.rtp_transport: Optional[RtpTransport] = None
        self.remote_rtp_addr: Optional[Tuple[str, int]] = None
        self._cseq = 1
    
    async def send_audio(self, data: bytes):
        if not self.success:
            raise RuntimeError("Call not established")
        if not self.rtp_transport:
            raise RuntimeError("RTP transport not started")
        await self.rtp_transport.send_audio(data)
    
    async def bye(self):
        if not self.success:
            return
        
        from_tag = self.client.from_tag
        to_tag = self.client.to_tag
        
        request = (
            f"BYE sip:{self.target}@{self.client.server} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.client.local_ip}:{self.client.local_port};branch={generate_branch()}\r\n"
            f"From: <sip:{self.client.user}@{self.client.server}>;tag={from_tag}\r\n"
            f"To: <sip:{self.target}@{self.client.server}>;tag={to_tag}\r\n"
            f"Call-ID: {self.call_id}\r\n"
            f"CSeq: {self._cseq} BYE\r\n"
            f"Max-Forwards: 70\r\n"
            f"User-Agent: SimpleSIP/1.0\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        
        self._cseq += 1
        
        try:
            await self.client.protocol.send_request(request, self.call_id, timeout=5.0)
        except Exception as e:
            print(f"Error sending BYE: {e}")
        
        if self.rtp_transport:
            await self.rtp_transport.stop()
            self.rtp_transport = None
        
        self.success = False


class SipClient:
    def __init__(self, user: str, pwd: str, server: str, local_ip: str):
        self.user = user
        self.pwd = pwd
        self.server = server
        self.local_ip = local_ip
        
        if ':' in server:
            self.server_ip, self.server_port = server.split(':')
            self.server_port = int(self.server_port)
        else:
            self.server_ip = server
            self.server_port = 5060
        
        self.local_port = 5060
        self.call_id = generate_call_id()
        self.from_tag = generate_tag()
        self.to_tag = None
        self.cseq = 1
        self.registered = False
        self.protocol: Optional[SipProtocol] = None
        self.transport = None
        self.calls: Dict[str, Call] = {}
    
    async def start(self):
        loop = asyncio.get_event_loop()
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: SipProtocol(self),
            local_addr=(self.local_ip, self.local_port)
        )
        print(f"SIP client started on {self.local_ip}:{self.local_port}")
    
    async def stop(self):
        for call in list(self.calls.values()):
            if call.success:
                await call.bye()
        
        if self.transport:
            self.transport.close()
            self.transport = None
            self.protocol = None
        
        print("SIP client stopped")
    
    def _build_register(self, auth_header: str = None) -> str:
        from_tag = self.from_tag
        headers = [
            f"REGISTER sip:{self.server_ip} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};branch={generate_branch()}",
            f"From: <sip:{self.user}@{self.server_ip}>;tag={from_tag}",
            f"To: <sip:{self.user}@{self.server_ip}>",
            f"Call-ID: {self.call_id}",
            f"CSeq: {self.cseq} REGISTER",
            "Max-Forwards: 70",
            "User-Agent: SimpleSIP/1.0",
            f"Contact: <sip:{self.user}@{self.local_ip}:{self.local_port}>",
            "Expires: 3600",
        ]
        
        if auth_header:
            headers.append(auth_header)
        
        headers.append("Content-Length: 0")
        headers.append("")
        
        return "\r\n".join(headers) + "\r\n"
    
    async def register(self) -> bool:
        print(f"Registering {self.user}@{self.server_ip}...")
        
        request = self._build_register()
        self.cseq += 1
        
        try:
            response = await self.protocol.send_request(request, self.call_id)
        except Exception as e:
            print(f"REGISTER failed: {e}")
            return False
        
        if response['status_code'] == 401:
            www_auth = response['headers'].get('www-authenticate', '')
            
            if not www_auth:
                print("No WWW-Authenticate header")
                return False
            
            realm = re.search(r'realm="([^"]+)"', www_auth)
            nonce = re.search(r'nonce="([^"]+)"', www_auth)
            
            if not realm or not nonce:
                print("Failed to parse WWW-Authenticate")
                return False
            
            realm = realm.group(1)
            nonce = nonce.group(1)
            
            uri = f"sip:{self.server_ip}"
            response_digest = generate_md5_digest(
                "REGISTER", uri, self.user, self.pwd, realm, nonce
            )
            
            auth_header = (
                f'Authorization: Digest username="{self.user}", '
                f'realm="{realm}", '
                f'nonce="{nonce}", '
                f'uri="{uri}", '
                f'response="{response_digest}"'
            )
            
            request = self._build_register(auth_header)
            self.cseq += 1
            
            try:
                response = await self.protocol.send_request(request, self.call_id)
            except Exception as e:
                print(f"REGISTER with auth failed: {e}")
                return False
            
            if response['status_code'] == 200:
                self.registered = True
                print("Registration successful!")
                return True
        
        elif response['status_code'] == 200:
            self.registered = True
            print("Registration successful (no auth needed)!")
            return True
        
        print(f"Registration failed with status {response['status_code']}")
        return False
    
    def _build_invite(self, target: str, local_rtp_port: int) -> str:
        call_id = generate_call_id()
        from_tag = self.from_tag
        
        sdp = (
            "v=0\r\n"
            f"o=- {int(time.time())} {int(time.time())} IN IP4 {self.local_ip}\r\n"
            "s=SimpleSIP\r\n"
            f"c=IN IP4 {self.local_ip}\r\n"
            "t=0 0\r\n"
            f"m=audio {local_rtp_port} RTP/AVP 8\r\n"
            "a=rtpmap:8 PCMA/8000\r\n"
            "a=sendrecv\r\n"
        )
        
        headers = [
            f"INVITE sip:{target}@{self.server_ip} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};branch={generate_branch()}",
            f"From: <sip:{self.user}@{self.server_ip}>;tag={from_tag}",
            f"To: <sip:{target}@{self.server_ip}>",
            f"Call-ID: {call_id}",
            f"CSeq: {self.cseq} INVITE",
            "Max-Forwards: 70",
            "User-Agent: SimpleSIP/1.0",
            f"Contact: <sip:{self.user}@{self.local_ip}:{self.local_port}>",
            "Content-Type: application/sdp",
            f"Content-Length: {len(sdp)}",
            "",
            sdp
        ]
        
        return "\r\n".join(headers) + "\r\n"
    
    async def invite(self, target: str) -> Call:
        print(f"Calling {target}@{self.server_ip}...")
        
        local_rtp_port = random.randint(10000, 20000)
        
        request = self._build_invite(target, local_rtp_port)
        self.cseq += 1
        
        call_id_match = re.search(r'Call-ID: ([^\r\n]+)', request)
        call_id = call_id_match.group(1) if call_id_match else generate_call_id()
        
        try:
            response = await self.protocol.send_request(request, call_id, timeout=10.0)
        except Exception as e:
            print(f"INVITE failed: {e}")
            call = Call(self, call_id, target, local_rtp_port)
            return call
        
        if response['status_code'] == 200:
            to_header = response['headers'].get('to', '')
            to_tag_match = re.search(r'tag=([^\s;]+)', to_header)
            self.to_tag = to_tag_match.group(1) if to_tag_match else None
            
            sdp_info = parse_sdp(response['body'])
            if sdp_info:
                remote_ip, remote_port = sdp_info
                print(f"Remote RTP: {remote_ip}:{remote_port}")
            else:
                print("Failed to parse SDP")
                remote_ip, remote_port = self.server_ip, local_rtp_port
            
            call = Call(self, call_id, target, local_rtp_port)
            call.remote_rtp_addr = (remote_ip, remote_port)
            
            call.rtp_transport = RtpTransport(self.local_ip, local_rtp_port)
            await call.rtp_transport.start()
            call.rtp_transport.set_remote(remote_ip, remote_port)
            
            self._send_ack(target, call_id)
            
            call.success = True
            print("Call established!")
            
            self.calls[call_id] = call
            
            return call
        else:
            print(f"INVITE failed with status {response['status_code']}")
            call = Call(self, call_id, target, local_rtp_port)
            return call
    
    def _send_ack(self, target: str, call_id: str):
        from_tag = self.from_tag
        to_tag = self.to_tag
        
        request = (
            f"ACK sip:{target}@{self.server_ip} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};branch={generate_branch()}\r\n"
            f"From: <sip:{self.user}@{self.server_ip}>;tag={from_tag}\r\n"
            f"To: <sip:{target}@{self.server_ip}>;tag={to_tag}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {self.cseq} ACK\r\n"
            "Max-Forwards: 70\r\n"
            "User-Agent: SimpleSIP/1.0\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        
        self.cseq += 1
        
        if self.transport:
            server_addr = (self.server_ip, self.server_port)
            self.transport.sendto(request.encode(), server_addr)
