"""
High-level VoIP call management module.
Handles call state transitions and coordination between SIP, RTP, and audio components.
"""

import threading
import logging
from .sip import SipClient
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

    def start(self):
        """
        Start the call (for outgoing calls).
        """
        with self.lock:
            self.state = CallState.DIALING
            self.sip_client.invite(self.sip_uri)
            self.audio_processor.start()

    def answer(self):
        """
        Answer an incoming call.
        """
        with self.lock:
            self.state = CallState.ANSWERED
            self.sip_client.ack()
            self.audio_processor.start()

    def hangup(self):
        """
        Terminate the call.
        """
        with self.lock:
            self.state = CallState.ENDED
            self.sip_client.bye()
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
        """
        Handle incoming INVITE request.
        """
        # Create new call
        call = Call(self.sip_client, invite_message.uri, self.local_ip, self.local_port, self.rtp_port_range)
        self.calls.append(call)
        call.state = CallState.RINGING
        
        # Notify callback
        if self.incoming_call_callback:
            self.incoming_call_callback(call)
        
        # Auto-answer (for simplicity)
        call.answer()

    def _handle_bye(self, bye_message):
        """
        Handle BYE request to terminate call.
        """
        call_id = bye_message.headers.get("Call-ID")
        for call in self.calls:
            if call.call_id == call_id:
                call.hangup()
                self.calls.remove(call)
                break

    def make_call(self, sip_uri):
        """
        Initiate an outgoing call.
        """
        call = Call(self.sip_client, sip_uri, self.local_ip, self.local_port, self.rtp_port_range)
        self.calls.append(call)
        call.start()
        return call

    def on_incoming_call(self, callback):
        """
        Set callback for incoming calls.
        """
        self.incoming_call_callback = callback
