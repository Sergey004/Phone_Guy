"""
High-level VoIP call management module.
Handles call state transitions and coordination between SIP, RTP, and audio components.
"""

import threading
import logging
import re
import time
import pyaudio
import queue
import secrets
from .sip import SipClient, SipMessage
from .rtp import RtpSession
from .audio import AudioProcessor
from .config import DEFAULT_RTP_PORT_RANGE, AUDIO_FRAME_SIZE, CODEC_PCMU

class CallState:
    """
    Enum-like class for call states.
    """
    IDLE = "idle"
    DIALING = "dialing"
    RINGING = "ringing"
    ANSWERED = "answered"
    ENDED = "ended"

class Call:
    """
    Represents a single VoIP call.
    """
    def __init__(self, sip_client, sip_uri, local_ip, local_port, rtp_port_range):
        self.sip_client = sip_client
        self.sip_uri = sip_uri
        self.local_ip = local_ip
        self.local_port = local_port
        self.rtp_port_range = rtp_port_range
        self.state = CallState.IDLE
        self.rtp_session = None
        self.audio_processor = AudioProcessor(codec=CODEC_PCMU)
        self.lock = threading.Lock()
        self.call_id = None
        self.to_tag = None
        self.invite_message = None
        self.remote_addr = None
        self.local_tag = None
        self.remote_tag = None
        self._rtp_playback_thread = None
        self._rtp_playback_running = False

    def generate_sdp(self):
        rtp_port = self.rtp_port_range[0]
        sdp = f"""v=0
o=- 0 0 IN IP4 {self.local_ip}
s=-
c=IN IP4 {self.local_ip}
t=0 0
m=audio {rtp_port} RTP/AVP 0
a=rtpmap:0 PCMU/8000
"""
        return sdp

    def _start_rtp_playback(self):
        """Start background thread to pull RTP payloads and play them via AudioProcessor."""
        if not self.rtp_session:
            return
        if self._rtp_playback_thread and self._rtp_playback_thread.is_alive():
            return
        self._rtp_playback_running = True
        def loop():
            logging.info("RTP playback thread started")
            while self._rtp_playback_running and self.state == CallState.ANSWERED:
                try:
                    frame = self.rtp_session.get_audio(timeout=0.1)
                    if frame:
                        # frame is encoded payload (e.g., PCMU). Decode+play.
                        self.audio_processor.add_audio_frame(frame)
                except Exception as e:
                    logging.error(f"RTP playback loop error: {e}")
            logging.info("RTP playback thread exiting")
        self._rtp_playback_thread = threading.Thread(target=loop, name="rtp_playback")
        self._rtp_playback_thread.daemon = True
        self._rtp_playback_thread.start()

    def _stop_rtp_playback(self):
        self._rtp_playback_running = False
        if self._rtp_playback_thread and self._rtp_playback_thread.is_alive():
            self._rtp_playback_thread.join(timeout=1.0)
            self._rtp_playback_thread = None

    def start(self):
        with self.lock:
            self.state = CallState.DIALING
            sdp = self.generate_sdp()
            response = self.sip_client.invite(self.sip_uri, sdp, call_id=self.call_id)
            if response and response.status_code == '200':
                to_header = response.headers.get('To', '')
                m = re.search(r';tag=([^;>\s]+)', to_header)
                self.remote_tag = m.group(1) if m else ''
                self.local_tag = self.sip_client.from_tag
                remote_ip = None
                remote_port = None
                if response.body:
                    for line in response.body.splitlines():
                        line = line.strip()
                        if line.startswith('c=IN IP4 '):
                            remote_ip = line.split(' ')[2]
                            logging.info(f"Extracted remote IP: {remote_ip}")
                        elif line.startswith('m=audio '):
                            remote_port = int(line.split(' ')[1])
                            logging.info(f"Extracted remote port: {remote_port}")
                if remote_ip and remote_port:
                    logging.info(f"Creating RTP session with local_ip={self.local_ip}, local_port={self.rtp_port_range[0]}, remote_ip={remote_ip}, remote_port={remote_port}")
                    self.rtp_session = RtpSession(self.local_ip, self.rtp_port_range[0], remote_ip, remote_port)
                self.sip_client.ack(self.sip_uri, self.call_id, self.remote_tag, self.local_tag)
                self.state = CallState.ANSWERED
                self.audio_processor.start()
                self._start_rtp_playback()
            elif response and response.status_code in ['100', '180', '183']:
                pass

    def answer(self):
        if self.state != CallState.IDLE or not self.invite_message or not self.remote_addr:
            return
        # Generate local tag
        self.local_tag = secrets.token_hex(8)
        # Extract remote tag from From
        from_header = self.invite_message.headers.get('From', '')
        m = re.search(r';tag=([^;>\s]+)', from_header)
        self.remote_tag = m.group(1) if m else ''
        # Parse remote SDP
        remote_ip = None
        remote_port = None
        if self.invite_message.body:
            for line in self.invite_message.body.splitlines():
                line = line.strip()
                if line.startswith('c=IN IP4 '):
                    remote_ip = line.split(' ')[2]
                elif line.startswith('m=audio '):
                    remote_port = int(line.split(' ')[1])
        if not remote_ip or not remote_port:
            logging.error("No valid SDP in INVITE")
            return
        # Generate local SDP
        sdp = self.generate_sdp()
        # Build headers
        headers = {
            "Via": self.invite_message.headers["Via"],
            "From": self.invite_message.headers["From"],
            "To": self.invite_message.headers["To"] + f";tag={self.local_tag}",
            "Call-ID": self.call_id,
            "CSeq": self.invite_message.headers["CSeq"],
            "Contact": f"<sip:{self.sip_client.username}@{self.local_ip}:{self.local_port}>",
            "User-Agent": "Python VoIP Client"
        }
        self.sip_client.send_response("200", "OK", headers, self.remote_addr, body=sdp)
        # Create RTP session
        self.rtp_session = RtpSession(self.local_ip, self.rtp_port_range[0], remote_ip, remote_port)
        self.state = CallState.ANSWERED
        self.audio_processor.start()
        self._start_rtp_playback()
    def reject(self):
        if self.state != CallState.IDLE or not self.invite_message or not self.remote_addr:
            return
        headers = {
            "Via": self.invite_message.headers["Via"],
            "From": self.invite_message.headers["From"],
            "To": self.invite_message.headers["To"] + ";tag=" + secrets.token_hex(8),
            "Call-ID": self.call_id,
            "CSeq": self.invite_message.headers["CSeq"],
            "User-Agent": "Python VoIP Client"
        }
        self.sip_client.send_response("486", "Busy Here", headers, self.remote_addr)
        self.state = CallState.ENDED

    def hangup(self):
        with self.lock:
            self.state = CallState.ENDED
            self.sip_client.bye(self.call_id, self.sip_uri, self.local_tag, self.remote_tag)
            self._stop_rtp_playback()
            self.audio_processor.stop()
            if self.rtp_session:
                self.rtp_session.stop()

    def send_audio(self, audio_data):
        """
        Send PCM audio data for transmission.
        """
        if self.state != CallState.ANSWERED:
            return
        encoded = self.audio_processor.encode_pcm(audio_data)
        if self.rtp_session:
            self.rtp_session.send_audio(encoded)

    def receive_audio(self):
        """
        Receive PCM audio frames.
        """
        if self.state != CallState.ANSWERED:
            return
        return self.audio_processor.get_audio_frame()

class VoIPClient:
    """
    Main VoIP client with call management.
    """
    def __init__(self, server, port=5060, username=None, password=None, local_ip="0.0.0.0", local_port=5060, rtp_port_range=(10000, 20000)):
        self.sip_client = SipClient(server, port, username, password, local_ip, local_port)
        self.local_ip = local_ip
        self.local_port = local_port
        self.rtp_port_range = rtp_port_range
        self.pending_responses = {}
        self.sip_client.owner = self
        self.calls = []
        self.incoming_call_callback = None
        self.running = False
        # Pause flag to avoid racing receives during blocking transactions (invite)
        self._pause_receive = False

    def start(self):
        """
        Start SIP registration and listen for incoming calls.
        """
        self.sip_client.register()
        self.running = True
        # Start SIP receive thread
        self.sip_receive_thread = threading.Thread(target=self._sip_receive_loop)
        self.sip_receive_thread.daemon = True
        self.sip_receive_thread.start()

    def stop(self):
        """
        Stop all call processing.
        """
        self.running = False
        for call in self.calls:
            call.hangup()
        self.sip_client.transport.close()

    def _sip_receive_loop(self):
        while self.running:
            try:
                data, addr = self.sip_client.transport.receive()
                message = SipMessage.from_string(data)
                if message.status_code is not None:  # it's a response
                    call_id = message.headers.get('Call-ID')
                    cseq = message.headers.get('CSeq')
                    if call_id and cseq:
                        cseq_parts = cseq.split()
                        if len(cseq_parts) == 2:
                            cseq_num, cseq_method = cseq_parts
                            key = (call_id, cseq_num, cseq_method)
                            if key in self.pending_responses:
                                self.pending_responses[key].put(message)
                                continue
                # Handle requests
                if message.method == "INVITE":
                    self._handle_incoming_invite(message, addr)
                elif message.method == "BYE":
                    self._handle_bye(message, addr)
                else:
                    pass
            except Exception as e:
                logging.error(f"SIP receive error: {e}")

    def _handle_incoming_invite(self, message, addr):
        sip_uri = message.headers.get("From", "")
        call = Call(self.sip_client, sip_uri, self.local_ip, self.local_port, self.rtp_port_range)
        call.call_id = message.headers.get("Call-ID")
        call.invite_message = message
        call.remote_addr = addr
        headers = {
            "Via": message.headers["Via"],
            "From": message.headers["From"],
            "To": message.headers["To"] + ";tag=" + secrets.token_hex(8),
            "Call-ID": call.call_id,
            "CSeq": message.headers["CSeq"],
            "User-Agent": "Python VoIP Client"
        }
        self.sip_client.send_response("180", "Ringing", headers, addr)
        self.calls.append(call)
        if self.incoming_call_callback:
            self.incoming_call_callback(call)
        else:
            logging.info("Incoming call received, but no handler is set.")

    def _handle_bye(self, message, addr):
        call_id = message.headers.get("Call-ID")
        for call in self.calls:
            if call.call_id == call_id:
                call.hangup()
                headers = {
                    "Via": message.headers["Via"],
                    "From": message.headers["From"],
                    "To": message.headers["To"],
                    "Call-ID": call_id,
                    "CSeq": message.headers["CSeq"],
                    "User-Agent": "Python VoIP Client"
                }
                self.sip_client.send_response("200", "OK", headers, addr)
                break

    def make_call(self, sip_uri):
        """
        Initiate an outgoing call.
        """
        call = Call(self.sip_client, sip_uri, self.local_ip, self.local_port, self.rtp_port_range)
        call.call_id = f"{self.sip_client.cseq}@{self.local_ip}"
        self.calls.append(call)
        # Pause background receive loop during blocking INVITE transaction
        self._pause_receive = True
        try:
            call.start()
        finally:
            self._pause_receive = False
        return call

    def on_incoming_call(self, callback):
        """
        Set callback for incoming calls.
        """
        self.incoming_call_callback = callback
