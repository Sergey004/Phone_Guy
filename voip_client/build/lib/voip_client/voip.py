"""
High-level VoIP call management module.
Handles call state transitions and coordination between SIP, RTP, and audio components.
"""

import threading
import logging
import re
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
        self.to_tag = None  # remote tag extracted from 200 OK
        self.playback_thread = None
        self.playback_stream = None

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

    def start(self):
        """
        Start the call (for outgoing calls).
        """
        with self.lock:
            self.state = CallState.DIALING
            sdp = self.generate_sdp()
            response = self.sip_client.invite(self.sip_uri, sdp, call_id=self.call_id)
            if response and response.status_code == '200':
                # Extract To tag from 200 OK for dialog
                to_header = response.headers.get('To', '')
                m = re.search(r';tag=([^;>\s]+)', to_header)
                if m:
                    self.to_tag = m.group(1)
                # Parse SDP from response body
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
                # Send ACK with proper tags and original INVITE CSeq
                self.sip_client.ack(self.sip_uri, self.call_id, self.to_tag, self.sip_client.from_tag)
                self.state = CallState.ANSWERED
                self.audio_processor.start()
                self._start_playback()
            elif response and response.status_code in ['100', '180', '183']:
                # Handle provisional responses
                pass

    def answer(self):
        """
        Answer an incoming call (placeholder: actual 200 OK handling not implemented).
        """
        with self.lock:
            self.state = CallState.ANSWERED
            # In a full implementation, we would send 200 OK with SDP here and wait for remote ACK.
            self.audio_processor.start()
            self._start_playback()

    def hangup(self):
        """
        Terminate the call.
        """
        with self.lock:
            self.state = CallState.ENDED
            self.sip_client.bye(self.call_id, self.sip_uri, self.to_tag)
            self.audio_processor.stop()
            if self.rtp_session:
                self.rtp_session.stop()
            if self.playback_stream:
                self.playback_stream.stop_stream()
                self.playback_stream.close()
            if self.playback_thread and self.playback_thread.is_alive():
                self.playback_thread.join()

    def receive_audio(self):
        """
        Generator to yield received PCM audio frames from RTP.
        """
        while self.state == CallState.ANSWERED and self.rtp_session:
            payload = self.rtp_session.get_audio(timeout=0.02)
            if payload:
                yield self.audio_processor.decode_pcm(payload)
            else:
                time.sleep(0.02)

    def _start_playback(self):
        self.playback_thread = threading.Thread(target=self._playback_loop)
        self.playback_thread.daemon = True
        self.playback_thread.start()
    def _playback_loop(self):
        self.playback_stream = self.audio_processor.pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.audio_processor.sample_rate,
            output=True,
            frames_per_buffer=AUDIO_FRAME_SIZE
        )
        for pcm in self.receive_audio():
            self.playback_stream.write(pcm)
        self.playback_stream.stop_stream()
        self.playback_stream.close()

    def send_audio(self, audio_data):
        """
        Send PCM audio data for transmission.
        """
        if self.state != CallState.ANSWERED:
            return
        encoded = self.audio_processor.encode_pcm(audio_data)
        if self.rtp_session:
            self.rtp_session.send_audio(encoded)

class VoIPClient:
    """
    Main VoIP client with call management.
    """
    def __init__(self, server, port=5060, username=None, password=None, local_ip="0.0.0.0", local_port=5060, rtp_port_range=(10000, 20000)):
        self.sip_client = SipClient(server, port, username, password, local_ip, local_port)
        self.local_ip = local_ip
        self.local_port = local_port
        self.rtp_port_range = rtp_port_range
        self.calls = []
        self.incoming_call_callback = None
        self.running = False

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
        """
        Background thread for receiving SIP messages.
        """
        while self.running:
            try:
                data, addr = self.sip_client.transport.receive()
                message = SipMessage.from_string(data)
                if message.method == "INVITE":
                    self._handle_incoming_invite(message)
                elif message.method == "BYE":
                    self._handle_bye(message)
            except Exception as e:
                logging.error(f"SIP receive error: {e}")

    def _handle_incoming_invite(self, invite_message):
        # Create a new call object for the incoming INVITE
        sip_uri = invite_message.headers.get("From", "")
        call = Call(self.sip_client, sip_uri, self.local_ip, self.local_port, self.rtp_port_range)
        # Capture the Call-ID to maintain dialog
        call.call_id = invite_message.headers.get("Call-ID")
        self.calls.append(call)
        if self.incoming_call_callback:
            self.incoming_call_callback(call)
        else:
            logging.info("Incoming call received, but no handler is set.")

    def _handle_bye(self, bye_message):
        # Find the relevant call and end it
        call_id = bye_message.headers.get("Call-ID")
        for call in self.calls:
            if call.call_id == call_id:
                call.hangup()
                break

    def make_call(self, sip_uri):
        """
        Initiate an outgoing call.
        """
        call = Call(self.sip_client, sip_uri, self.local_ip, self.local_port, self.rtp_port_range)
        call.call_id = f"{self.sip_client.cseq}@{self.local_ip}"
        self.calls.append(call)
        call.start()
        return call

    def on_incoming_call(self, callback):
        """
        Set callback for incoming calls.
        """
        self.incoming_call_callback = callback
