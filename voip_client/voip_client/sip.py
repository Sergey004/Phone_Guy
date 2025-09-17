"""
SIP Signaling module for VoIP client.
Handles SIP message generation, parsing, and authentication.
"""

import socket
import threading
import hashlib
import time
import re
import logging
import secrets
import queue
from .config import DEFAULT_SIP_PORT

class SipTransport:
    """
    UDP transport for SIP messages.
    """
    def __init__(self, local_ip, local_port=DEFAULT_SIP_PORT):
        self.local_ip = local_ip
        self.local_port = local_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((local_ip, local_port))
        self.running = True
        self.sock.settimeout(2.0)  # Increased timeout for better reliability

    def send(self, message, dest_address):
        self.sock.sendto(message.encode(), dest_address)

    def receive(self):
        data, addr = self.sock.recvfrom(4096)
        return data.decode(), addr

    def close(self):
        self.running = False
        self.sock.close()

class SipMessage:
    """
    Represents a SIP message for parsing and generating.
    """
    def __init__(self, method=None, uri=None, headers=None, body=None, status_code=None, reason=None):
        self.method = method
        self.uri = uri
        self.headers = headers or {}
        self.body = body
        self.status_code = status_code
        self.reason = reason

    @classmethod
    def from_string(cls, message_str):
        """
        Parse a SIP message string into a SipMessage object.
        """
        # Do not strip trailing CRLFs from body; split preserving order
        lines = message_str.split('\r\n')
        if not lines:
            return None
        request_line = lines[0].split()
        # Process headers with continuation lines
        merged_headers = []
        current = None
        idx_blank = None
        for i in range(1, len(lines)):
            line = lines[i]
            if line.strip() == '':
                idx_blank = i
                break
            if line.startswith(' ') or line.startswith('\t'):
                if current is not None:
                    current += line
                else:
                    current = line
            else:
                if current is not None:
                    merged_headers.append(current)
                current = line
        if current is not None:
            merged_headers.append(current)

        parsed_headers = {}
        for header_line in merged_headers:
            if ':' in header_line:
                key, value = header_line.split(':', 1)
                key = key.strip()
                value = value.strip()
                if key == 'Via':
                    parsed_headers[key] = ViaHeader(value)
                elif key == 'From':
                    parsed_headers[key] = FromHeader(value)
                elif key == 'To':
                    parsed_headers[key] = ToHeader(value)
                elif key == 'Contact':
                    parsed_headers[key] = ContactHeader(value)
                else:
                    parsed_headers[key] = value
        headers = parsed_headers

        body_str = ''
        if idx_blank is not None and idx_blank + 1 < len(lines):
            body_str = '\r\n'.join(lines[idx_blank + 1:]).rstrip('\r\n')
        # Determine if response or request
        if len(request_line) >= 2 and request_line[0] == 'SIP/2.0' and request_line[1].isdigit():
            status_code = request_line[1]
            reason_phrase = ' '.join(request_line[2:]) if len(request_line) > 2 else ''
            return cls(method=None, uri=None, status_code=status_code, reason=reason_phrase, headers=headers, body=body_str)
        else:
            method = request_line[0] if request_line else None
            uri = request_line[1] if len(request_line) > 1 else None
            return cls(method=method, uri=uri, headers=headers, body=body_str)

    def to_string(self):
        """
        Convert SipMessage object to string format.
        """
        start_line = ''
        if self.method:
            start_line = f"{self.method} {self.uri} SIP/2.0"
        header_lines = []
        for key, value in self.headers.items():
            if isinstance(value, (ViaHeader, FromHeader, ToHeader, ContactHeader)):
                header_lines.append(f"{key}: {value}")
            else:
                header_lines.append(f"{key}: {value}")
        # Compose with correct CRLF CRLF between headers and body
        message = ''
        if start_line:
            message = start_line + '\r\n'
        if header_lines:
            message += '\r\n'.join(header_lines)
        # Terminate headers
        message += '\r\n\r\n'
        if self.body:
            message += self.body
        return message

class ViaHeader:
    def __init__(self, header_str):
        # Parse the Via header string
        parts = header_str.split(';')
        transport_line = parts[0].strip()
        tokens = transport_line.split()
        if len(tokens) < 2:
            self.transport = "UDP"
            self.host = None
            self.port = None
        else:
            proto_parts = tokens[0].split('/')
            if len(proto_parts) >= 3:
                self.transport = proto_parts[2]
            else:
                self.transport = "UDP"
            host_port = tokens[1]
            if ':' in host_port:
                self.host, self.port = host_port.split(':', 1)
            else:
                self.host = host_port
                self.port = None
        self.params = {}
        for param in parts[1:]:
            if '=' in param:
                k, v = param.split('=', 1)
                self.params[k.strip()] = v.strip()
    
    def __str__(self):
        transport_line = f"SIP/2.0/{self.transport} {self.host}:{self.port}"
        params = []
        for k, v in self.params.items():
            params.append(f"{k}={v}")
        return f"{transport_line};{';'.join(params)}"

class FromHeader:
    def __init__(self, header_str):
        self.display_name = None
        self.uri = None
        self.params = {}
        if header_str.startswith('"'):
            end_quote = header_str.find('"', 1)
            if end_quote != -1:
                self.display_name = header_str[1:end_quote]
                rest = header_str[end_quote+1:].strip()
            else:
                rest = header_str
        else:
            rest = header_str
        if rest.startswith('<') and '>' in rest:
            start_bracket = rest.find('<')
            end_bracket = rest.find('>', start_bracket)
            self.uri = rest[start_bracket+1:end_bracket]
            params_str = rest[end_bracket+1:].strip()
        else:
            self.uri = rest
            params_str = ''
        for param in params_str.split(';'):
            if '=' in param:
                k, v = param.split('=', 1)
                self.params[k.strip()] = v.strip().strip('"')
            else:
                self.params[param.strip()] = True
    def __str__(self):
        parts = []
        if self.display_name:
            parts.append(f'"{self.display_name}"')
        parts.append(f'<{self.uri}>')
        for k, v in self.params.items():
            if v is True:
                parts.append(k)
            else:
                parts.append(f"{k}={v}")
        return ' '.join(parts)

class ToHeader:
    def __init__(self, header_str):
        self.display_name = None
        self.uri = None
        self.params = {}
        if header_str.startswith('"'):
            end_quote = header_str.find('"', 1)
            if end_quote != -1:
                self.display_name = header_str[1:end_quote]
                rest = header_str[end_quote+1:].strip()
            else:
                rest = header_str
        else:
            rest = header_str
        if rest.startswith('<') and '>' in rest:
            start_bracket = rest.find('<')
            end_bracket = rest.find('>', start_bracket)
            self.uri = rest[start_bracket+1:end_bracket]
            params_str = rest[end_bracket+1:].strip()
        else:
            self.uri = rest
            params_str = ''
        for param in params_str.split(';'):
            if '=' in param:
                k, v = param.split('=', 1)
                self.params[k.strip()] = v.strip().strip('"')
            else:
                self.params[param.strip()] = True
    def __str__(self):
        parts = []
        if self.display_name:
            parts.append(f'"{self.display_name}"')
        parts.append(f'<{self.uri}>')
        for k, v in self.params.items():
            if v is True:
                parts.append(k)
            else:
                parts.append(f"{k}={v}")
        return ' '.join(parts)

class ContactHeader:
    def __init__(self, header_str):
        self.display_name = None
        self.uri = None
        self.params = {}
        if header_str.startswith('"'):
            end_quote = header_str.find('"', 1)
            if end_quote != -1:
                self.display_name = header_str[1:end_quote]
                rest = header_str[end_quote+1:].strip()
            else:
                rest = header_str
        else:
            rest = header_str
        if rest.startswith('<') and '>' in rest:
            start_bracket = rest.find('<')
            end_bracket = rest.find('>', start_bracket)
            self.uri = rest[start_bracket+1:end_bracket]
            params_str = rest[end_bracket+1:].strip()
        else:
            self.uri = rest
            params_str = ''
        for param in params_str.split(';'):
            if '=' in param:
                k, v = param.split('=', 1)
                self.params[k.strip()] = v.strip().strip('"')
            else:
                self.params[param.strip()] = True
    def __str__(self):
        parts = []
        if self.display_name:
            parts.append(f'"{self.display_name}"')
        parts.append(f'<{self.uri}>')
        for k, v in self.params.items():
            if v is True:
                parts.append(k)
            else:
                parts.append(f"{k}={v}")
        return ' '.join(parts)

def generate_digest_challenge_response(username, password, realm, nonce, method, uri, qop=None, nc=None, cnonce=None):
    """
    Generate Digest Auth response for SIP methods.
    Supports both legacy (no qop) and qop=auth calculations.
    """
    HA1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    HA2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    if qop and nc and cnonce:
        response = hashlib.md5(f"{HA1}:{nonce}:{nc}:{cnonce}:{qop}:{HA2}".encode()).hexdigest()
    else:
        response = hashlib.md5(f"{HA1}:{nonce}:{HA2}".encode()).hexdigest()
    return response

class SipClient:
    """
    Main SIP client for handling SIP signaling.
    """
    def __init__(self, server, port=DEFAULT_SIP_PORT, username=None, password=None, local_ip="0.0.0.0", local_port=DEFAULT_SIP_PORT):
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        self.local_ip = local_ip
        self.local_port = local_port
        self.transport = SipTransport(local_ip, local_port)
        self.transport.sock.settimeout(0.5)  # Set timeout for receive
        self.cseq = 1
        self.nc_count = 1
        self.auth_nonce = None
        self.auth_realm = None
        self.from_tag = secrets.token_hex(8)
        self.last_invite_cseq = None

    def register(self):
        uri = f"sip:{self.server}"
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>;tag={self.from_tag}",
            "To": f"<sip:{self.username}@{self.server}>",
            "Call-ID": f"{self.cseq}@{self.local_ip}",
            "CSeq": f"{self.cseq} REGISTER",
            "Contact": f"<sip:{self.username}@{self.local_ip}:{self.local_port}>",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": "0"
        }
        call_id = headers["Call-ID"]
        key = (call_id, str(self.cseq), "REGISTER")
        self.owner.pending_responses[key] = queue.Queue()
        message = SipMessage(method="REGISTER", uri=uri, headers=headers)
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1
        start_time = time.time()
        timeout = 10
        response = None
        while time.time() - start_time < timeout and not response:
            try:
                response = self.owner.pending_responses[key].get(timeout=0.5)
            except queue.Empty:
                continue
            if response.status_code == "200":
                del self.owner.pending_responses[key]
                return
            elif response.status_code == "401" and response.headers.get("WWW-Authenticate"):
                auth_header = response.headers["WWW-Authenticate"]
                realm_match = re.search(r'realm=\"([^\"]+)\"', auth_header)
                nonce_match = re.search(r'nonce=\"([^\"]+)\"', auth_header)
                qop = None
                qop_match = re.search(r'qop=\"?([^\"]+)\"?', auth_header, re.IGNORECASE)
                if qop_match:
                    qop_opt = qop_match.group(1)
                    qop = qop_opt.split(',')[0].strip()
                if realm_match and nonce_match:
                    realm = realm_match.group(1)
                    nonce = nonce_match.group(1)
                    self.auth_realm = realm
                    self.auth_nonce = nonce
                    nc_value = format(self.nc_count, '08x')
                    cnonce = secrets.token_hex(8)
                    digest_response = generate_digest_challenge_response(
                        self.username, self.password, realm, nonce, "REGISTER", uri,
                        qop=qop, nc=nc_value, cnonce=cnonce if qop else None
                    )
                    auth_params = [
                        f"username=\"{self.username}\"",
                        f"realm=\"{realm}\"",
                        f"nonce=\"{nonce}\"",
                        f"uri=\"{uri}\"",
                        f"response=\"{digest_response}\"",
                        "algorithm=MD5",
                    ]
                    if qop:
                        auth_params.append("qop=" + qop)
                        auth_params.append(f"nc={nc_value}")
                        auth_params.append(f"cnonce=\"{cnonce}\"")
                    headers_auth = headers.copy()
                    headers_auth["CSeq"] = f"{self.cseq} REGISTER"
                    headers_auth["Authorization"] = "Digest " + ", ".join(auth_params)
                    new_key = (call_id, str(self.cseq), "REGISTER")
                    self.owner.pending_responses[new_key] = queue.Queue()
                    message2 = SipMessage(method="REGISTER", uri=uri, headers=headers_auth)
                    self.transport.send(message2.to_string(), (self.server, self.port))
                    self.cseq += 1
                    self.nc_count += 1
                    key = new_key
                    response = None
                    continue
                else:
                    logging.error("401 Unauthorized but no WWW-Authenticate header")
                    del self.owner.pending_responses[key]
                    return
            else:
                logging.error(f"Registration failed with status {response.status_code}")
                del self.owner.pending_responses[key]
                return
        logging.info("REGISTER timed out")
        if key in self.owner.pending_responses:
            del self.owner.pending_responses[key]

    def ack(self, sip_uri, call_id, to_tag, from_tag):
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>;tag={from_tag}",
            "To": f"<{sip_uri}>;tag={to_tag}",
            "Call-ID": call_id,
            # ACK for 2xx MUST use the same CSeq number as the INVITE
            "CSeq": f"{self.last_invite_cseq} ACK",
            "Contact": f"<sip:{self.username}@{self.local_ip}:{self.local_port}>",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": "0"
        }
        message = SipMessage(method="ACK", uri=sip_uri, headers=headers)
        self.transport.send(message.to_string(), (self.server, self.port))
        # Do NOT increment self.cseq for ACK to 2xx

    def invite(self, sip_uri, sdp=None, call_id=None):
        start_time = time.time()
        timeout = 10
        content_length = str(len(sdp.encode('utf-8'))) if sdp else "0"
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>;tag={self.from_tag}",
            "To": f"<{sip_uri}>",
            "Call-ID": call_id or f"{self.cseq}@{self.local_ip}",
            "CSeq": f"{self.cseq} INVITE",
            "Contact": f"<sip:{self.username}@{self.local_ip}:{self.local_port}>",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": content_length
        }
        if sdp:
            headers["Content-Type"] = "application/sdp"
        call_id = headers["Call-ID"]
        self.last_invite_cseq = self.cseq
        key = (call_id, str(self.last_invite_cseq), "INVITE")
        self.owner.pending_responses[key] = queue.Queue()
        message = SipMessage(method="INVITE", uri=sip_uri, headers=headers, body=sdp)
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1
        response = None
        while time.time() - start_time < timeout and not response:
            try:
                response = self.owner.pending_responses[key].get(timeout=0.5)
            except queue.Empty:
                continue
            if response.status_code in ['100', '180', '183']:
                response = None
                continue
            elif response.status_code == '401':
                if response.headers.get("WWW-Authenticate"):
                    auth_header = response.headers["WWW-Authenticate"]
                    realm_match = re.search(r'realm=\"([^\"]+)\"', auth_header)
                    nonce_match = re.search(r'nonce=\"([^\"]+)\"', auth_header)
                    qop = None
                    qop_match = re.search(r'qop=\"?([^\"]+)\"?', auth_header, re.IGNORECASE)
                    if qop_match:
                        qop_opt = qop_match.group(1)
                        qop = qop_opt.split(',')[0].strip()
                    if realm_match and nonce_match:
                        realm = realm_match.group(1)
                        nonce = nonce_match.group(1)
                        self.auth_realm = realm
                        self.auth_nonce = nonce
                        nc_value = format(self.nc_count, '08x')
                        cnonce = secrets.token_hex(8)
                        digest_response = generate_digest_challenge_response(
                            self.username, self.password, realm, nonce, "INVITE", sip_uri,
                            qop=qop, nc=nc_value, cnonce=cnonce if qop else None
                        )
                        auth_params = [
                            f"username=\"{self.username}\"",
                            f"realm=\"{realm}\"",
                            f"nonce=\"{nonce}\"",
                            f"uri=\"{sip_uri}\"",
                            f"response=\"{digest_response}\"",
                            "algorithm=MD5",
                        ]
                        if qop:
                            auth_params.append("qop=" + qop)
                            auth_params.append(f"nc={nc_value}")
                            auth_params.append(f"cnonce=\"{cnonce}\"")
                        headers["Authorization"] = "Digest " + ", ".join(auth_params)
                        self.nc_count += 1
                        headers["Content-Length"] = str(len(sdp.encode('utf-8'))) if sdp else "0"
                        headers["CSeq"] = f"{self.cseq} INVITE"
                        new_key = (call_id, str(self.cseq), "INVITE")
                        self.owner.pending_responses[new_key] = queue.Queue()
                        message = SipMessage(method="INVITE", uri=sip_uri, headers=headers, body=sdp if sdp else None)
                        self.transport.send(message.to_string(), (self.server, self.port))
                        self.cseq += 1
                        key = new_key
                        response = None
                        continue
                    else:
                        logging.error("401 Unauthorized but no WWW-Authenticate header")
                        del self.owner.pending_responses[key]
                        return None
            elif response.status_code == '407':
                if response.headers.get("Proxy-Authenticate"):
                    auth_header = response.headers["Proxy-Authenticate"]
                    realm_match = re.search(r'realm=\"([^\"]+)\"', auth_header)
                    nonce_match = re.search(r'nonce=\"([^\"]+)\"', auth_header)
                    qop = None
                    qop_match = re.search(r'qop=\"?([^\"]+)\"?', auth_header, re.IGNORECASE)
                    if qop_match:
                        qop_opt = qop_match.group(1)
                        qop = qop_opt.split(',')[0].strip()
                    if realm_match and nonce_match:
                        realm = realm_match.group(1)
                        nonce = nonce_match.group(1)
                        self.auth_realm = realm
                        self.auth_nonce = nonce
                        nc_value = format(self.nc_count, '08x')
                        cnonce = secrets.token_hex(8)
                        digest_response = generate_digest_challenge_response(
                            self.username, self.password, realm, nonce, "INVITE", sip_uri,
                            qop=qop, nc=nc_value, cnonce=cnonce if qop else None
                        )
                        auth_params = [
                            f"username=\"{self.username}\"",
                            f"realm=\"{realm}\"",
                            f"nonce=\"{nonce}\"",
                            f"uri=\"{sip_uri}\"",
                            f"response=\"{digest_response}\"",
                            "algorithm=MD5",
                        ]
                        if qop:
                            auth_params.append("qop=" + qop)
                            auth_params.append(f"nc={nc_value}")
                            auth_params.append(f"cnonce=\"{cnonce}\"")
                        headers["Proxy-Authorization"] = "Digest " + ", ".join(auth_params)
                        self.nc_count += 1
                        headers["Content-Length"] = str(len(sdp.encode('utf-8'))) if sdp else "0"
                        headers["CSeq"] = f"{self.cseq} INVITE"
                        new_key = (call_id, str(self.cseq), "INVITE")
                        self.owner.pending_responses[new_key] = queue.Queue()
                        message = SipMessage(method="INVITE", uri=sip_uri, headers=headers, body=sdp if sdp else None)
                        self.transport.send(message.to_string(), (self.server, self.port))
                        self.cseq += 1
                        key = new_key
                        response = None
                        continue
                    else:
                        logging.error("407 Proxy Authentication Required but no Proxy-Authenticate header")
                        del self.owner.pending_responses[key]
                        return None
        if response:
            logging.info(f"INVITE final response: {response.status_code} {response.reason}")
            del self.owner.pending_responses[key]
            return response
        else:
            logging.info("INVITE timed out")
            if key in self.owner.pending_responses:
                del self.owner.pending_responses[key]

    def bye(self, call_id, sip_uri, from_tag, to_tag):
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>;tag={from_tag}",
            "To": f"<{sip_uri}>;tag={to_tag}",
            "Call-ID": call_id,
            "CSeq": f"{self.cseq} BYE",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": "0"
        }
        uri = sip_uri
        key = (call_id, str(self.cseq), "BYE")
        self.owner.pending_responses[key] = queue.Queue()
        message = SipMessage(method="BYE", uri=uri, headers=headers)
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1
        start_time = time.time()
        timeout = 5
        response = None
        while time.time() - start_time < timeout and not response:
            try:
                response = self.owner.pending_responses[key].get(timeout=0.5)
            except queue.Empty:
                continue
        if response:
            logging.info(f"BYE response: {response.status_code} {response.reason}")
        else:
            logging.info("BYE timed out")
        if key in self.owner.pending_responses:
            del self.owner.pending_responses[key]

    def send_response(self, status_code, reason, headers, dest_address, body=None):
        if body:
            headers["Content-Length"] = str(len(body.encode('utf-8')))
            headers["Content-Type"] = "application/sdp"
        else:
            headers["Content-Length"] = "0"
        message = SipMessage(status_code=status_code, reason=reason, headers=headers, body=body)
        self.transport.send(message.to_string(), dest_address)
