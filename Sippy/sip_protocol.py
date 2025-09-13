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

    def build_register(self, auth=None, expires=None):
        method = 'REGISTER'
        # Use the correct URI format for the request line
        request_uri = f'sip:{self.client.domain}:{self.client.remote_port};transport={self.client.transport}'
        # For digest authentication, the URI should match the request URI
        digest_uri = request_uri
        
        # Use provided expires value or default to register_interval
        expires_value = expires if expires is not None else self.client.register_interval
        
        headers = [
            f'{method} {request_uri} SIP/2.0',
            f'Via: SIP/2.0/UDP {self.client.local_addr}:{self.client.local_port};branch={self.client.branch}',
            f'From: <sip:{self.client.username}@{self.client.domain}>;tag={self.client.tag}',
            f'To: <sip:{self.client.username}@{self.client.domain}>',
            f'Call-ID: {self.client.call_id}',
            f'CSeq: {self.client.cseq} {method}',
            f'Contact: <sip:{self.client.username}@{self.client.local_addr}:{self.client.local_port};transport={self.client.transport};+sip.instance="urn:uuid:{self.client.urnUUID}">',
            f'Allow: INVITE, ACK, BYE, CANCEL, OPTIONS, NOTIFY, MESSAGE',
            f'Max-Forwards: 70',
            f'Allow-Events: org.3gpp.nwinitdereg',
            f'User-Agent: PurePythonSIP/1.0',
            f'Expires: {expires_value}',
            'Content-Length: 0'
        ]
        if auth:
            # Calculate HA1 = MD5(username:realm:password)
            ha1 = hashlib.md5(f'{self.client.username}:{auth["realm"]}:{self.client.password}'.encode()).hexdigest()
            # Calculate HA2 = MD5(method:digest-uri)
            # Use simple URI format for digest calculation
            simple_uri = f'sip:{self.client.domain}'
            ha2 = hashlib.md5(f'{method}:{simple_uri}'.encode()).hexdigest()
            self.logger.debug(f'HA1: {ha1}')
            self.logger.debug(f'HA2: {ha2}')
            
            if 'qop' in auth:
                # Generate client nonce
                cnonce = ''.join(random.choices('0123456789abcdef', k=16))
                # Increment nonce count
                self.client.nonce_count += 1
                nc = f"{self.client.nonce_count:08x}"
                # Calculate response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
                response = hashlib.md5(f'{ha1}:{auth["nonce"]}:{nc}:{cnonce}:{auth["qop"]}:{ha2}'.encode()).hexdigest()
                auth_str = f'Digest username="{self.client.username}", realm="{auth["realm"]}", nonce="{auth["nonce"]}", uri="sip:{self.client.domain}", response="{response}", algorithm=MD5, qop="{auth["qop"]}", nc={nc}, cnonce="{cnonce}"'
            else:
                # Calculate response = MD5(HA1:nonce:HA2)
                response = hashlib.md5(f'{ha1}:{auth["nonce"]}:{ha2}'.encode()).hexdigest()
                auth_str = f'Digest username="{self.client.username}", realm="{auth["realm"]}", nonce="{auth["nonce"]}", uri="sip:{self.client.domain}", response="{response}", algorithm=MD5'
            
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
                
                # Improved parsing of authentication parameters
                auth = {}
                # Use regex to properly handle quoted values with commas inside
                import re
                pattern = re.compile(r'(\w+)=(?:"([^"]+)"|([^,]+))')
                matches = pattern.findall(auth_str)
                
                for match in matches:
                    key = match[0].strip()
                    # If quoted value is captured in group 2, otherwise use group 3
                    value = match[1] if match[1] else match[2].strip()
                    auth[key] = value
                
                self.logger.debug(f"Parsed authentication parameters: {auth}")
                return auth
        
        self.logger.warning("WWW-Authenticate header not found in response")
        return None

    def build_sdp(self, mode='sendrecv'):
        port = self.client.config['rtp']['local_port']
        # Offer only codecs implemented in our RTPHandler (PCMU and PCMA)
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
        for line in lines[1:]:
            if not line:
                header_end = True
                continue
            if header_end:
                body += line + '\r\n'
            else:
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip()] = value.strip()
        if request_line.startswith('SIP/2.0 '):
            msg_type = 'response'
            parts = request_line.split(maxsplit=2)
            version = parts[0]
            status_code = parts[1]
            reason = parts[2] if len(parts) > 2 else ''
        else:
            msg_type = 'request'
            parts = request_line.split(maxsplit=2)
            method = parts[0]
            uri = parts[1]
            version = parts[2] if len(parts) > 2 else ''
        parsed = {
            'type': msg_type,
            'headers': headers,
            'body': body.strip()
        }
        
        if msg_type == 'response':
            parsed['version'] = version
            parsed['status_code'] = status_code
            parsed['reason'] = reason
        else:
            parsed['version'] = version
            parsed['method'] = method
            parsed['uri'] = uri
        
        return parsed

    def build_sip_message(self, start_line, uri, headers, body=''):
        msg = [start_line]
        if uri:
            msg[0] += f' {uri}'
        for k, v in headers.items():
            msg.append(f'{k}: {v}')
        msg.append(f'Content-Length: {len(body)}')
        msg.append('')
        if body:
            msg.append(body)
        return '\r\n'.join(msg)

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

    def is_hold_sdp(self, sdp):
        return 'a=sendonly' in sdp or 'c=IN IP4 0.0.0.0' in sdp

    def parse_sdp_for_rtp(self, sdp):
        lines = sdp.split('\r\n')
        ip = None
        port = None
        for line in lines:
            if line.startswith('c=IN IP4 '):
                ip = line.split(' ')[2]
            if line.startswith('m=audio '):
                port = int(line.split(' ')[1])
        return (ip, port) if ip and port else None

    def get_preferred_payload_type(self, sdp):
        # Choose codec/PT based on intersection of remote offer and our supported set
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
        # Our supported codecs (align with RTPHandler implementation)
        supported = [c.upper() for c in self.client.config.get('rtp', {}).get('supported_codecs', ['PCMU', 'PCMA'])]
        # Preference order (default PCMU, PCMA)
        prefs = [c.upper() for c in self.client.config.get('rtp', {}).get('preferred_codecs', supported)]
        # Map well-known static PTs
        def choose_pcm():
            if 0 in payloads and 'PCMU' in supported:
                return 0, 'PCMU'
            if 8 in payloads and 'PCMA' in supported:
                return 8, 'PCMA'
            return None
        # Try preferences
        for pref in prefs:
            if pref == 'PCMU' and 0 in payloads and 'PCMU' in supported:
                return 0, 'PCMU'
            if pref == 'PCMA' and 8 in payloads and 'PCMA' in supported:
                return 8, 'PCMA'
            if pref.startswith('G726') or pref == 'G726':
                if 'G726' in supported:
                    for pt in payloads:
                        name = rtpmap.get(pt, '').upper()
                        if 'G726' in name:
                            # Normalize to a common label for RTP layer
                            return pt, 'G726-32'
        # Fallbacks limited to our implementation
        pcm = choose_pcm()
        if pcm:
            return pcm
        # Last resort: pick any remotely offered PCMU/PCMA/G726 if we support it
        for pt in payloads:
            name = rtpmap.get(pt, '').upper()
            if name in supported or ('G726' in name and 'G726' in supported):
                if name == 'PCMU':
                    return pt, 'PCMU'
                if name == 'PCMA':
                    return pt, 'PCMA'
                if 'G726' in name and 'G726' in supported:
                    return pt, 'G726-32'
        # Default safe codec
        return 0, 'PCMU'

    def is_hold_sdp(self, sdp):
        lines = sdp.split('\r\n')
        for line in lines:
            if line == 'a=sendonly' or line.startswith('c=IN IP4 0.0.0.0'):
                return True
        return False

    def handle_message(self, msg):
        if msg['type'] == 'response':
            self.logger.warning(f"Received response in handle_message: {msg['status_code']} {msg['reason']}")
            return
        if 'method' not in msg:
            self.logger.error("Missing 'method' in request message")
            return
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
