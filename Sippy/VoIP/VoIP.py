from enum import Enum
from typing import Optional, Callable, List, Dict, TYPE_CHECKING, Any
from threading import Lock, Timer
import random

from Sippy import RTP
import Sippy.SIP as SIP

from Sippy.VoIP.status import PhoneStatus

if TYPE_CHECKING:
    from Sippy.SIP import SIPMessage

import audioop
import io
import Sippy
import random
import time
import warnings


__all__ = [
    "CallState",
    "InvalidRangeError",
    "InvalidStateError",
    "NoPortsAvailableError",
    "VoIPCall",
    "VoIPPhone",
]

debug = Sippy.debug


class InvalidRangeError(Exception):
    pass


class InvalidStateError(Exception):
    pass


class NoPortsAvailableError(Exception):
    pass


class CallState(Enum):
    DIALING = "DIALING"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    ENDED = "ENDED"


class VoIPCall:
    def __init__(
        self,
        phone: "VoIPPhone",
        callstate: CallState,
        request: "SIPMessage",
        session_id: int,
        myIP: str,
        ms: Optional[Dict[int, RTP.PayloadType]] = None,
        sendmode="sendonly",
    ):
        self.state = callstate
        self.phone = phone
        self.sip = self.phone.sip
        self.request = request
        self.call_id = request.headers["Call-ID"]
        self.session_id = str(session_id)
        self.myIP = myIP
        self.rtpPortHigh = self.phone.rtpPortHigh
        self.rtpPortLow = self.phone.rtpPortLow
        self.sendmode = sendmode

        self.dtmfLock = Lock()
        self.dtmf = io.StringIO()

        self.RTPClients: List[RTP.RTPClient] = []

        self.connections = 0
        self.audioPorts = 0
        self.videoPorts = 0

        self.assignedPorts: Any = {}

        if callstate == CallState.RINGING:
            audio = []
            video = []
            for x in self.request.body["c"]:
                self.connections += x["address_count"]
            for x in self.request.body["m"]:
                if x["type"] == "audio":
                    self.audioPorts += x["port_count"]
                    audio.append(x)
                elif x["type"] == "video":
                    self.videoPorts += x["port_count"]
                    video.append(x)
                else:
                    warnings.warn(
                        f"Unknown media description: {x['type']}", stacklevel=2
                    )

            if len(audio) > 0:
                audioPortsAdj = self.audioPorts / len(audio)
            else:
                audioPortsAdj = 0
            if len(video) > 0:
                videoPortsAdj = self.videoPorts / len(video)
            else:
                videoPortsAdj = 0

            if not (
                (audioPortsAdj == self.connections or self.audioPorts == 0)
                and (videoPortsAdj == self.connections or self.videoPorts == 0)
            ):
                warnings.warn("Unable to assign ports for RTP.", stacklevel=2)
                return

            for i in request.body["m"]:
                if i["type"] == "video":  # Disable Video
                    continue
                assoc = {}
                e = False
                for x in i["methods"]:
                    try:
                        p = RTP.PayloadType(int(x))
                        assoc[int(x)] = p
                    except ValueError:
                        try:
                            p = RTP.PayloadType(
                                i["attributes"][x]["rtpmap"]["name"]
                            )
                            assoc[int(x)] = p
                        except ValueError:
                            warnings.warn(
                                f"RTP Payload type {i['attributes'][x]['rtpmap']['name']} not found.",
                                stacklevel=20,
                            )
                            warnings.simplefilter("default")
                            p = RTP.PayloadType("UNKNOWN")
                            assoc[int(x)] = p
                        except KeyError:
                            warnings.warn(
                                f"RTP KeyError {x} not found.", stacklevel=20
                            )
                            p = RTP.PayloadType("UNKNOWN")
                            assoc[int(x)] = p

                if e:
                    pt = i["attributes"][x]["rtpmap"]["name"] if 'rtpmap' in i["attributes"][x] else None
                    raise RTP.RTPParseError(
                        f"RTP Payload type {pt or 'unknown'} not found."
                    )

                codecs = {}
                for m in assoc:
                    if assoc[m] in Sippy.RTPCompatibleCodecs:
                        codecs[m] = assoc[m]

                port = self.phone.request_port()
                self.create_rtp_clients(
                    codecs, self.myIP, port, request, i["port"]
                )
        elif callstate == CallState.DIALING:
            if ms is None:
                raise RuntimeError("Media streams required for DIALING state")

    def bye(self):
        pass

    def renegotiate(self, request):
        pass

    def answered(self, request):
        pass

    def not_found(self, request):
        pass

    def unavailable(self, request):
        pass


class VoIPPhone:
    def __init__(
        self,
        server: str,
        port: int,
        username: str,
        password: str,
        myIP: str,
        sipPort: int = 5060,
        rtpPortLow: int = 10000,
        rtpPortHigh: int = 20000,
        callCallback: Optional[Callable[["VoIPCall"], None]] = None,
        register: bool = False,
    ):
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        if myIP is None or myIP == "0.0.0.0":
            self.myIP = "192.168.1.181"
        else:
            self.myIP = myIP
        self.sipPort = sipPort
        self.rtpPortLow = rtpPortLow
        self.rtpPortHigh = rtpPortHigh
        self.callCallback = callCallback
        self._status = PhoneStatus.INACTIVE
        self.calls: Dict[str, VoIPCall] = {}
        self.session_ids: List[int] = []
        self.assignedPorts: List[int] = []
        self.portsLock = Lock()
        self.NSD = False

        self.sip = SIP.SIPClient(
            server=server,
            port=port,
            username=username,
            password=password,
            phone=self,
            myIP=self.myIP,
            myPort=sipPort,
        )

        if register:
            self.start()

    def _callback_MSG_Invite(self, request: "SIPMessage") -> None:
        call_id = request.headers["Call-ID"]
        if call_id in self.calls:
            debug("Re-negotiation detected!")
            if self.calls[call_id].state != CallState.RINGING:
                self.calls[call_id].renegotiate(request)
            return
        if self.callCallback is None:
            message = self.sip.gen_busy(request)
            self.sip.out.sendto(
                message.encode("utf8"), (self.server, self.port)
            )
        else:
            debug("New call!")
            sess_id = None
            while sess_id is None:
                proposed = random.randint(1, 100000)
                if proposed not in self.session_ids:
                    self.session_ids.append(proposed)
                    sess_id = proposed
            message = self.sip.gen_ringing(request)
            self.sip.out.sendto(
                message.encode("utf8"), (self.server, self.port)
            )
            call = VoIPCall(
                self, CallState.RINGING, request, sess_id, self.myIP
            )
            self.calls[call_id] = call
            self.callCallback(call)

    def _callback_MSG_Bye(self, request: "SIPMessage") -> None:
        call_id = request.headers["Call-ID"]
        if call_id in self.calls:
            self.calls[call_id].bye()
            message = self.sip.gen_ok(request)
            self.sip.out.sendto(
                message.encode("utf8"), (self.server, self.port)
            )
        else:
            message = self.sip.gen_call_transaction_does_not_exist(request)
            self.sip.out.sendto(
                message.encode("utf8"), (self.server, self.port)
            )

    def _callback_RESP_OK(self, request: "SIPMessage") -> None:
        call_id = request.headers["Call-ID"]
        if call_id not in self.calls:
            debug(f"OK for unknown call {call_id}, ignoring.")
            return
        if self.calls[call_id].state == CallState.DIALING:
            self.calls[call_id].answered(request)
            message = self.sip.gen_ack(request)
            self.sip.out.sendto(
                message.encode("utf8"), (self.server, self.port)
            )
        elif self.calls[call_id].state == CallState.ENDED:
            del self.calls[call_id]
        else:
            debug(f"TODO: 500 Error, received an OK response for a call not in the dialing state. Call: {call_id}, Call State: {str(self.calls[call_id].state)}")

    def _callback_RESP_NotFound(self, request: "SIPMessage") -> None:
        call_id = request.headers["Call-ID"]
        if call_id in self.calls:
            self.calls[call_id].not_found(request)
        else:
            debug(f"TODO: 500 Error, received a not found response for a call not in the calls dictionary. Call: {call_id}")

    def _callback_RESP_Unavailable(self, request: "SIPMessage") -> None:
        call_id = request.headers["Call-ID"]
        if call_id in self.calls:
            self.calls[call_id].unavailable(request)
        else:
            debug(f"TODO: 500 Error, received an unavailable response for a call not in the calls dictionary. Call: {call_id}")

    def fatal(self, request: Optional["SIPMessage"] = None) -> None:
        if request is not None:
            call_id = request.headers["Call-ID"]
            if call_id in self.calls:
                self.calls[call_id].bye()
                del self.calls[call_id]
            else:
                debug(f"TODO: 500 Error, received a fatal response for a call not in the calls dictionary. Call: {call_id}")
        else:
            debug("Fatal error occurred during non-call operation.")
            self.stop()

    def start(self) -> None:
        self.sip.start()
        self._status = PhoneStatus.REGISTERING
        self.sip.register()
        self.NSD = True

    def stop(self) -> None:
        self.sip.stop()
        self._status = PhoneStatus.INACTIVE
        self.NSD = False

    def request_port(self) -> int:
        with self.portsLock:
            for x in range(self.rtpPortLow, self.rtpPortHigh + 1):
                if x not in self.assignedPorts:
                    self.assignedPorts.append(x)
                    return x
            raise NoPortsAvailableError("No ports available for RTP.")

    def release_ports(self, call: VoIPCall) -> None:
        with self.portsLock:
            for x in call.assignedPorts:
                self.assignedPorts.remove(x)
            if call.session_id in self.session_ids:
                self.session_ids.remove(call.session_id)

    def call(self, number: str) -> VoIPCall:
        sess_id = None
        while sess_id is None:
            proposed = random.randint(1, 100000)
            if proposed not in self.session_ids:
                self.session_ids.append(proposed)
                sess_id = proposed
        request = self.sip.gen_invite(number, sess_id, self.myIP, self.sendmode)
        call = VoIPCall(self, CallState.DIALING, request, sess_id, self.myIP)
        self.calls[request.headers["Call-ID"]] = call
        self.sip.out.sendto(request.encode("utf8"), (self.server, self.port))
        return call


    def get_status(self) -> PhoneStatus:
        return self._status
