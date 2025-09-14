"""
SIP Signaling module for VoIP client.
Handles SIP message generation, parsing, and authentication.
"""

import socket
import threading
import hashlib
import time
import re
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
    def __init__(self, method=None, uri=None, headers=None, body=None):
        self.method = method
        self.uri = uri
        self.headers = headers or {}
        self.body = body

    @classmethod
    def from_string(cls, message_str):
        """
        Parse a SIP message string into a SipMessage object.
        """
        lines = message_str.strip().split('\r\n')
        if not lines:
            return None
        # First line is request line
        request_line = lines[0].split()
        method = request_line[0]
        uri = request_line[1]
        version = request_line[2]
        headers = {}
        body = []
        for line in lines[1:]:
            if line == '':
                break
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()
            else:
                body.append(line)
        body_str = '\r\n'.join(body)
        return cls(method, uri, headers, body_str)

    def to_string(self):
        """
        Convert SipMessage object to string format.
        """
        lines = []
        if self.method:
            lines.append(f"{self.method} {self.uri} SIP/2.0")
        for key, value in self.headers.items():
            lines.append(f"{key}: {value}")
        lines.append("")
        if self.body:
            lines.append(self.body)
        return '\r\n'.join(lines)

def generate_digest_challenge_response(username, password, realm, nonce, method, uri):
    """
    Generate Digest Auth response for SIP REGISTER.
    """
    HA1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    HA2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
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
        self.cseq = 1
        self.auth_nonce = None
        self.auth_realm = None

    def register(self):
        """
        Send REGISTER request to SIP server.
        """
        uri = f"sip:{self.server}"
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>",
            "To": f"<sip:{self.username}@{self.server}>",
            "Call-ID": f"{self.cseq}@{self.local_ip}",
            "CSeq": f"{self.cseq} REGISTER",
            "Contact": f"<sip:{self.username}@{self.local_ip}:{self.local_port}>",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": "0"
        }
        message = SipMessage(method="REGISTER", uri=uri, headers=headers)
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1

    def bye(self, call_id, sip_uri):
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>",
            "To": f"<{sip_uri}>",
            "Call-ID": call_id,
            "CSeq": f"{self.cseq} BYE",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": "0"
        }
        uri = f"sip:{self.server}"
        message = SipMessage(method="BYE", uri=uri, headers=headers)
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1

        # Wait for final response
        data, addr = self.transport.receive()
        response = SipMessage.from_string(data)

    def invite(self, sip_uri):
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>",
            "To": f"<{sip_uri}>",
            "Call-ID": f"{self.cseq}@{self.local_ip}",
            "CSeq": f"{self.cseq} INVITE",
            "Contact": f"<sip:{self.username}@{self.local_ip}:{self.local_port}>",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": "0"
        }
        message = SipMessage(method="INVITE", uri=sip_uri, headers=headers)
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1

        # Wait for response
        data, addr = self.transport.receive()
        response = SipMessage.from_string(data)
        if response.headers.get("WWW-Authenticate"):
            # Process digest auth
            auth_header = response.headers["WWW-Authenticate"]
            # Parse realm and nonce from WWW-Authenticate header
            realm_match = re.search(r'realm="([^"]+)"', auth_header)
            nonce_match = re.search(r'nonce="([^"]+)"', auth_header)
            if realm_match and nonce_match:
                realm = realm_match.group(1)
                nonce = nonce_match.group(1)
                self.auth_realm = realm
                self.auth_nonce = nonce
                # Re-send REGISTER with auth
                digest_response = generate_digest_challenge_response(self.username, self.password, realm, nonce, "INVITE", sip_uri)
                headers["Authorization"] = f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{sip_uri}", response="{digest_response}", algorithm=MD5'
                message = SipMessage(method="INVITE", uri=sip_uri, headers=headers)
                self.transport.send(message.to_string(), (self.server, self.port))
                self.cseq += 1
