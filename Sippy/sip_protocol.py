import logging
import hashlib
import random
import string
from datetime import datetime

class SIPProtocol:
    def __init__(self, client):
        self.client = client
        self.logger = logging.getLogger('SIPProtocol')
        if client.config.get('debug', False):
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

    def build_register(self, auth=None):
        method = 'REGISTER'
        uri = f'sip:{self.client.domain}:{self.client.remote_port};transport={self.client.transport}'
        headers = [
            f'{method} {uri} SIP/2.0',
            f'Via: SIP/2.0/UDP {self.client.local_addr}:{self.client.local_port};branch={self.client.branch}',
            f'From: <sip:{self.client.username}@{self.client.domain}>;tag={self.client.tag}',
            f'To: <sip:{self.client.username}@{self.client.domain}>',
            f'Call-ID: {self.client.call_id}',
            f'CSeq: {self.client.cseq} {method}',
            f'Contact: <sip:{self.client.username}@{self.client.local_addr}:{self.client.local_port}>',
            f'Max-Forwards: 70',
            f'User-Agent: PurePythonSIP/1.0',
            f'Expires: {self.client.register_interval}',
            'Content-Length: 0'
        ]
        if auth:
            ha1 = hashlib.md5(f'{self.client.username}:{auth["realm"]}:{self.client.password}'.encode()).hexdigest()
            ha2 = hashlib.md5(f'{method}:{uri}'.encode()).hexdigest()
            self.logger.debug(f'HA1: {ha1}')
            self.logger.debug(f'HA2: {ha2}')
            if 'qop' in auth:
                cnonce = ''.join(random.choices('0123456789abcdef', k=16))
                self.client.nonce_count += 1
                nc = f"{self.client.nonce_count:08x}"
                response = hashlib.md5(f'{ha1}:{auth["nonce"]}:{nc}:{cnonce}:{auth["qop"]}:{ha2}'.encode()).hexdigest()
                auth_str = f'Digest username="{self.client.username}", realm="{auth["realm"]}", nonce="{auth["nonce"]}", uri="{uri}", response="{response}", algorithm=MD5, qop="{auth["qop"]}", nc={nc}, cnonce="{cnonce}"'
            else:
                response = hashlib.md5(f'{ha1}:{auth["nonce"]}:{ha2}'.encode()).hexdigest()
                auth_str = f'Digest username="{self.client.username}", realm="{auth["realm"]}", nonce="{auth["nonce"]}", uri="{uri}", response="{response}", algorithm=MD5'
            self.logger.debug(f'Digest Response: {response}')
            self.logger.debug(f'Authorization Header: {auth_str}')
            headers.insert(6, f'Authorization: {auth_str}')
        return '\r\n'.join(headers) + '\r\n\r\n'

    def parse_auth_header(self, response):
        for line in response.split('\r\n'):
            if line.startswith('WWW-Authenticate:'):
                auth_str = line.split(':', 1)[1].strip()
                if auth_str.startswith('Digest '):
                    auth_str = auth_str[7:]
                parts = [p.strip() for p in auth_str.split(',')]
                auth = {}
                for part in parts:
                    if '=' in part:
                        key, value = part.split('=', 1)
                        auth[key.strip()] = value.strip('"')
                return auth
        return None

    def build_sdp(self, mode='sendrecv'):
        port = self.client.config['rtp']['local_port']
        # Ограничиваем кодеки только PCMU и PCMA, как в pyVoIP
        offered_pts = [0, 8]  # 0 = PCMU, 8 = PCMA
        rtpmap_lines = ['a=rtpmap:0 PCMU/8000\r\n', 'a=rtpmap:8 PCMA/8000\r\n']
        m_line = f"m=audio {port} RTP/AVP " + ' '.join(str(pt) for pt in offered_pts) + '\r\n'
        sdp = (
            'v=0\r\n'
            f'o={self.client.username} {int(datetime.now().timestamp())} {int(datetime.now().timestamp())} IN IP4 {self.client.local_addr}\r\n'
            's=PurePythonSIP\r\n'
            f'c=IN IP4 {self.client.local_addr}\r\n'
            't=0 0\r\n'
            + m_line + ''.join(rtpmap_lines) +
            f'a={mode}\r\n'
        )
        return sdp

    def parse_sip_message(self, message):
        lines = message.split('\r\n')
        request_line = lines[0]
        headers = {}
        body = ''
        header_end = False
        sender_address = None
        
        for line in lines[1:]:
            if not line:
                header_end = True
                continue
            if header_end:
                body += line + '\r\n'
            else:
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    headers[key] = value
                    
                    # Извлекаем адрес отправителя из заголовка Via
                    if key == 'Via':
                        try:
                            # Формат: SIP/2.0/UDP 192.168.1.100:5060;branch=z9hG4bK...
                            via_parts = value.split(';')[0].split(' ')
                            if len(via_parts) > 1:
                                addr_port = via_parts[1]
                                if ':' in addr_port:
                                    addr, port = addr_port.split(':')
                                    sender_address = (addr, int(port))
                                    self.logger.debug(f'Extracted sender address from Via: {sender_address}')
                        except Exception as e:
                            self.logger.warning(f'Failed to extract sender address from Via: {e}')

        parts = request_line.split()
        if len(parts) >= 3 and parts[0].startswith('SIP/'):
            msg_type = 'response'
            version = parts[0]
            status_code = parts[1]
            reason = ' '.join(parts[2:])
            method = None
            uri = None
        elif len(parts) == 3:
            msg_type = 'request'
            method = parts[0]
            uri = parts[1]
            version = parts[2]
            status_code = None
            reason = None
        else:
            msg_type = 'unknown'
            method = None
            uri = None
            version = None
            status_code = None
            reason = None
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f'Parsed SIP headers: {headers}')
        return {
            'type': msg_type,
            'sender_address': sender_address,
            'method': method,
            'uri': uri,
            'version': version,
            'status_code': status_code,
            'reason': reason,
            'headers': headers,
            'body': body.strip()
        }

    def build_sip_message(self, method, uri, headers, body=''):
        if uri:
            start_line = f'{method} {uri} SIP/2.0'
        else:
            start_line = method  # For responses, method is the full 'SIP/2.0 status reason'
        lines = [start_line]
        
        # Создаем копию заголовков, чтобы не изменять оригинальный словарь
        headers_copy = headers.copy()
        
        # Всегда устанавливаем правильный Content-Length
        headers_copy['Content-Length'] = str(len(body))
        
        for k, v in headers_copy.items():
            lines.append(f'{k}: {v}')
            
        lines.append('')
        if body:
            lines.append(body)
        return '\r\n'.join(lines) + '\r\n'
        
    def build_bye(self):
        # Генерируем новый уникальный branch для BYE
        bye_branch = 'z9hG4bK' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        
        bye_headers = {
            'Via': f'SIP/2.0/UDP {self.client.local_addr}:{self.client.local_port};branch={bye_branch}',
            'From': self.client.invite_from if hasattr(self.client, 'invite_from') else f'<sip:{self.client.username}@{self.client.domain}>;tag={self.client.tag}',
            'To': self.client.established_to if hasattr(self.client, 'established_to') else self.client.invite_to,
            'Call-ID': self.client.call_id,
            'CSeq': f'{self.client.cseq} BYE',
            'Max-Forwards': '70',
            'User-Agent': 'PurePythonSIP/1.0'
        }
        
        self.client.cseq += 1
        return self.build_sip_message('BYE', self.client.target, bye_headers)

    def parse_sdp_for_rtp(self, sdp):
        lines = sdp.split('\r\n')
        ip = None
        port = None
        for line in lines:
            if line.startswith('c='):
                ip = line.split(' ')[2]
            if line.startswith('m='):
                port = int(line.split(' ')[1])
        return (ip, port) if ip and port else (self.client.domain, 4000)

    def get_preferred_payload_type(self, sdp):
        # Parse remote SDP and choose by our configured preference order (extended codecs supported)
        lines = sdp.split('\r\n')
        payloads = []
        rtpmap = {}
        for line in lines:
            if line.startswith('m=audio'):
                parts = line.split()
                if len(parts) >= 4:
                    for p in parts[3:]:
                        try:
                            payloads.append(int(p))
                        except ValueError:
                            pass
            if line.startswith('a=rtpmap:'):
                try:
                    rest = line[len('a=rtpmap:'):]
                    pt_str, codec_desc = rest.split(' ', 1)
                    pt = int(pt_str)
                    codec = codec_desc.split('/')[0].upper()
                    rtpmap[pt] = codec
                except Exception:
                    continue
        prefs = [c.upper() for c in self.client.config.get('rtp', {}).get('preferred_codecs', ['PCMU', 'PCMA'])]
        # Try by preference
        for pref in prefs:
            if pref == 'PCMU' and 0 in payloads:
                return 0, 'PCMU'
            if pref == 'PCMA' and 8 in payloads:
                return 8, 'PCMA'
            if pref in ('G729', 'G729A'):
                if 18 in payloads:
                    return 18, 'G729'
                for pt in payloads:
                    if rtpmap.get(pt, '').upper().startswith('G729'):
                        return pt, 'G729'
            if pref == 'OPUS':
                for pt in payloads:
                    if rtpmap.get(pt, '').upper() == 'OPUS':
                        return pt, 'OPUS'
            if pref.startswith('G726') or pref == 'G726':
                for pt in payloads:
                    name = rtpmap.get(pt, '').upper()
                    if 'G726' in name:
                        # Normalize name for RTP layer
                        return pt, 'G726-32'
        # Fallbacks to G.711 if available
        if 0 in payloads:
            return 0, 'PCMU'
        if 8 in payloads:
            return 8, 'PCMA'
        # Fallback to any named codec
        for pt in payloads:
            name = rtpmap.get(pt, '').upper()
            if name in ('PCMU', 'PCMA', 'G729', 'OPUS') or 'G726' in name:
                # Return whatever was advertised
                return pt, name
        if payloads:
            pt = payloads[0]
            return pt, rtpmap.get(pt, f'PT{pt}')
        return 0, 'PCMU'

    def is_hold_sdp(self, sdp):
        lines = sdp.split('\r\n')
        for line in lines:
            if line == 'a=sendonly' or line.startswith('c=IN IP4 0.0.0.0'):
                return True
        return False

    def handle_message(self, msg):
        method = msg['method']
        if method == 'INVITE':
            self.handle_invite(msg)
        elif method == 'ACK':
            self.handle_ack(msg)
        elif method == 'BYE':
            self.handle_bye(msg)
        elif method == 'CANCEL':
            self.handle_cancel(msg)
        elif method == 'OPTIONS':
            self.handle_options(msg)
        elif method == 'NOTIFY':
            self.handle_notify(msg)
        elif method == 'MESSAGE':
            self.handle_message_request(msg)
        else:
            self.logger.warning(f'Unhandled method: {method}')
            
    def handle_message_request(self, msg):
        self.logger.info('Handling MESSAGE request')
        ok_headers = {
            'Via': msg['headers']['Via'],
            'From': msg['headers']['From'],
            'To': msg['headers']['To'] + ';tag=' + self.client.tag,
            'Call-ID': msg['headers']['Call-ID'],
            'CSeq': msg['headers']['CSeq']
        }
        ok_msg = self.build_sip_message('SIP/2.0 200 OK', '', ok_headers)
        self.client._send(ok_msg, dest=msg.get('sender_address'))

    def handle_options(self, msg):
        ok_headers = {
            'Via': msg['headers']['Via'],
            'From': msg['headers']['From'],
            'To': msg['headers']['To'] + ';tag=' + self.client.tag,
            'Call-ID': msg['headers']['Call-ID'],
            'CSeq': msg['headers']['CSeq'],
            'Allow': 'INVITE, ACK, BYE, CANCEL, OPTIONS, NOTIFY'
        }
        ok_msg = self.build_sip_message('SIP/2.0 200 OK', '', ok_headers)
        self.client._send(ok_msg, dest=msg.get('sender_address'))
        self.logger.info('Handled OPTIONS request')

    def handle_notify(self, msg):
        ok_headers = {
            'Via': msg['headers']['Via'],
            'From': msg['headers']['From'],
            'To': msg['headers']['To'] + ';tag=' + self.client.tag,
            'Call-ID': msg['headers']['Call-ID'],
            'CSeq': msg['headers']['CSeq']
        }
        ok_msg = self.build_sip_message('SIP/2.0 200 OK', '', ok_headers)
        self.client._send(ok_msg, dest=msg.get('sender_address'))
        self.logger.info('Handled NOTIFY request')

    def handle_invite(self, msg):
        call_id = msg['headers']['Call-ID']
        if call_id == self.client.call_id and self.client.call_established.is_set():
            # re-INVITE
            is_hold = self.is_hold_sdp(msg['body'])
            self.client.rtp.on_hold = is_hold
            mode = 'recvonly' if is_hold else 'sendrecv'
            sdp = self.build_sdp(mode=mode)
            to_header = msg['headers']['To']
            ok_headers = {
                'Via': msg['headers']['Via'],
                'From': msg['headers']['From'],
                'To': to_header,
                'Call-ID': call_id,
                'CSeq': msg['headers']['CSeq'],
                'Contact': f'<sip:{self.client.username}@{self.client.local_addr}:{self.client.local_port}>',
                'Content-Type': 'application/sdp'
            }
            ok_msg = self.build_sip_message('SIP/2.0 200 OK', '', ok_headers, sdp)
            self.client._send(ok_msg, dest=msg.get('sender_address'))
            new_rtp_addr = self.parse_sdp_for_rtp(msg['body'])
            if new_rtp_addr != self.client.remote_rtp_addr and new_rtp_addr[0] != '0.0.0.0':
                self.client.remote_rtp_addr = new_rtp_addr
            # Update negotiated payload type from remote SDP
            pt, codec = self.get_preferred_payload_type(msg['body'])
            self.client.rtp.negotiated_pt = pt
            self.client.rtp.negotiated_codec = codec
            self.logger.info(f'Handled re-INVITE for {"hold" if is_hold else "unhold"}; negotiated PT={pt} ({codec})')
            return
        # New INVITE
        trying_headers = {
            'Via': msg['headers']['Via'],
            'From': msg['headers']['From'],
            'To': msg['headers']['To'] + ';tag=' + self.client.tag,
            'Call-ID': call_id,
            'CSeq': msg['headers']['CSeq']
        }
        trying_msg = self.build_sip_message('SIP/2.0 100 Trying', '', trying_headers)
        self.client._send(trying_msg, dest=msg.get('sender_address'))
        ringing_headers = trying_headers.copy()
        ringing_msg = self.build_sip_message('SIP/2.0 180 Ringing', '', ringing_headers)
        self.client._send(ringing_msg, dest=msg.get('sender_address'))
        sdp = self.build_sdp()
        ok_headers = trying_headers.copy()
        ok_headers['Contact'] = f'<sip:{self.client.username}@{self.client.local_addr}:{self.client.local_port}>'
        ok_headers['Content-Type'] = 'application/sdp'
        ok_msg = self.build_sip_message('SIP/2.0 200 OK', '', ok_headers, sdp)
        self.client._send(ok_msg, dest=msg.get('sender_address'))
        self.client.remote_rtp_addr = self.parse_sdp_for_rtp(msg['body'])
        # Negotiate payload type from caller's SDP before starting RTP
        pt, codec = self.get_preferred_payload_type(msg['body'])
        self.client.rtp.negotiated_pt = pt
        self.client.rtp.negotiated_codec = codec
        self.logger.info(f'Negotiated PT={pt} ({codec}) for incoming call')

    def handle_ack(self, msg):
        self.logger.info('ACK received, call established')
        if not self.client.rtp.rtp_running:
            self.client.start_rtp()

    def handle_bye(self, msg):
        ok_headers = {
            'Via': msg['headers']['Via'],
            'From': msg['headers']['From'],
            'To': msg['headers']['To'],
            'Call-ID': msg['headers']['Call-ID'],
            'CSeq': msg['headers']['CSeq']
        }
        ok_msg = self.build_sip_message('SIP/2.0 200 OK', '', ok_headers)
        self.client._send(ok_msg, dest=msg.get('sender_address'))
        self.logger.info('Call ended')
        self.client.stop_rtp()
        self.client.call_established.clear()
        self.client.established_to = None

    def handle_cancel(self, msg):
        ok_headers = {
            'Via': msg['headers']['Via'],
            'From': msg['headers']['From'],
            'To': msg['headers']['To'],
            'Call-ID': msg['headers']['Call-ID'],
            'CSeq': msg['headers']['CSeq']
        }
        ok_msg = self.build_sip_message('SIP/2.0 200 OK', '', ok_headers)
        self.client._send(ok_msg, dest=msg.get('sender_address'))
        request_terminated = self.build_sip_message('SIP/2.0 487 Request Terminated', '', ok_headers)
        self.client._send(request_terminated, dest=msg.get('sender_address'))
        self.logger.info('Call cancelled')
