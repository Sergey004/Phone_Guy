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
        # Parse headers up to the first empty line
        headers = {}
        body_str = ''
        idx_blank = None
        for i in range(1, len(lines)):
            line = lines[i]
            if line == '':
                idx_blank = i
                break
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()
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
        header_lines = [f"{key}: {value}" for key, value in self.headers.items()]
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
        """
        Send REGISTER request to SIP server with retry handling.
        """
        while True:
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
            message = SipMessage(method="REGISTER", uri=uri, headers=headers)
            self.transport.send(message.to_string(), (self.server, self.port))
            self.cseq += 1

            # Wait for response
            data, addr = self.transport.receive()
            response = SipMessage.from_string(data)
            logging.info(f"REGISTER response: {response.status_code} {response.reason}")

            if response.status_code == '200':
                # Registration successful
                return
            elif response.status_code == '401' and response.headers.get("WWW-Authenticate"):
                # Process digest auth and resend REGISTER with Authorization
                auth_header = response.headers["WWW-Authenticate"]
                realm_match = re.search(r'realm="([^"]+)"', auth_header)
                nonce_match = re.search(r'nonce="([^"]+)"', auth_header)
                qop = None
                qop_match = re.search(r'qop="?([^"]+)"?', auth_header, re.IGNORECASE)
                if qop_match:
                    qop_opt = qop_match.group(1)
                    qop = qop_opt.split(',')[0].strip()
                if realm_match and nonce_match:
                    realm = realm_match.group(1)
                    nonce = nonce_match.group(1)
                    self.auth_realm = realm
                    self.auth_nonce = nonce
                    # Build Authorization and resend
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
                    headers_auth = {
                        "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
                        "From": f"<sip:{self.username}@{self.server}>;tag={self.from_tag}",
                        "To": f"<sip:{self.username}@{self.server}>",
                        "Call-ID": f"{self.cseq}@{self.local_ip}",
                        "CSeq": f"{self.cseq} REGISTER",
                        "Contact": f"<sip:{self.username}@{self.local_ip}:{self.local_port}>",
                        "Max-Forwards": "70",
                        "User-Agent": "Python VoIP Client",
                        "Authorization": "Digest " + ", ".join(auth_params),
                        "Content-Length": "0"
                    }
                    self.nc_count += 1
                    message2 = SipMessage(method="REGISTER", uri=uri, headers=headers_auth)
                    self.transport.send(message2.to_string(), (self.server, self.port))
                    self.cseq += 1

                    # Wait for final response after auth
                    data2, addr2 = self.transport.receive()
                    response2 = SipMessage.from_string(data2)
                    logging.info(f"REGISTER (auth) response: {response2.status_code} {response2.reason}")
                    if response2.status_code == '200':
                        return
                    else:
                        logging.error(f"Registration failed after auth with status {response2.status_code}")
                        return
                else:
                    # If no auth header, break to avoid infinite loop
                    logging.error("401 Unauthorized but no WWW-Authenticate header")
                    return
            else:
                # Other errors
                logging.error(f"Registration failed with status {response.status_code}")
                return

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

    def bye(self, call_id, sip_uri, to_tag):
        headers = {
            "Via": f"SIP/2.0/UDP {self.local_ip}:{self.local_port};branch=z9hG4bK{self.cseq}",
            "From": f"<sip:{self.username}@{self.server}>;tag={self.from_tag}",
            "To": f"<{sip_uri}>;tag={to_tag}",
            "Call-ID": call_id,
            "CSeq": f"{self.cseq} BYE",
            "Max-Forwards": "70",
            "User-Agent": "Python VoIP Client",
            "Content-Length": "0"
        }
        uri = sip_uri
        message = SipMessage(method="BYE", uri=uri, headers=headers)
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1

        # Wait for final response
        data, addr = self.transport.receive()
        response = SipMessage.from_string(data)
        logging.info(f"BYE response: {response.status_code} {response.reason}")

    def invite(self, sip_uri, sdp=None, call_id=None):
        start_time = time.time()
        timeout = 10  # seconds
        
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
            message = SipMessage(method="INVITE", uri=sip_uri, headers=headers, body=sdp)
        else:
            message = SipMessage(method="INVITE", uri=sip_uri, headers=headers)
        self.last_invite_cseq = self.cseq
        self.transport.send(message.to_string(), (self.server, self.port))
        self.cseq += 1

        while time.time() - start_time < timeout:
            try:
                data, addr = self.transport.receive()
                response = SipMessage.from_string(data)

                if response.status_code in ['100', '180', '183']:
                    continue
                elif response.status_code == '401' and response.headers.get("WWW-Authenticate"):
                    # Process digest auth (WWW-Authenticate)
                    auth_header = response.headers["WWW-Authenticate"]
                    realm_match = re.search(r'realm="([^"]+)"', auth_header)
                    nonce_match = re.search(r'nonce="([^"]+)"', auth_header)
                    qop = None
                    qop_match = re.search(r'qop="?([^\"]+)"?', auth_header, re.IGNORECASE)
                    if qop_match:
                        qop_opt = qop_match.group(1)
                        qop = qop_opt.split(',')[0].strip()
                    if realm_match and nonce_match:
                        realm = realm_match.group(1)
                        nonce = nonce_match.group(1)
                        self.auth_realm = realm
                        self.auth_nonce = nonce
                        # Re-send INVITE with Authorization
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
                        # Recalculate Content-Length in case body changed
                        headers["Content-Length"] = str(len(sdp.encode('utf-8'))) if sdp else "0"
                        message = SipMessage(method="INVITE", uri=sip_uri, headers=headers, body=sdp if sdp else None)
                        self.transport.send(message.to_string(), (self.server, self.port))
                        self.cseq += 1
                        continue  # wait for next response
                elif response.status_code == '407' and response.headers.get("Proxy-Authenticate"):
                    # Process digest auth (Proxy-Authenticate) and send Proxy-Authorization
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
                        message = SipMessage(method="INVITE", uri=sip_uri, headers=headers, body=sdp if sdp else None)
                        self.transport.send(message.to_string(), (self.server, self.port))
                        self.cseq += 1
                        continue
                else:
                    # Final response (200 OK, 4xx, etc.)
                    logging.info(f"INVITE final response: {response.status_code} {response.reason}")
                    return response
            except socket.timeout:
                continue

        logging.info("INVITE timed out")
        return None
