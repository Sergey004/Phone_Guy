from enum import Enum, IntEnum
from threading import Timer, Lock
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING
from Sippy.util import acquired_lock_and_unblocked_socket
from Sippy.VoIP.status import PhoneStatus
from .debug import debug, DEBUG
from . import SIPCompatibleMethods, SIPCompatibleVersions
import Sippy
import hashlib
import socket
import random
import re
import time
import uuid
import select
import warnings


if TYPE_CHECKING:
    from .VoIP import VoIPPhone
    from . import RTP


__all__ = [
    "Counter",
    "InvalidAccountInfoError",
    "SIPClient",
    "SIPMessage",
    "SIPMessageType",
    "SIPParseError",
    "SIPStatus",
]


class InvalidAccountInfoError(Exception):
    pass


class SIPParseError(Exception):
    pass


class RetryRequiredError(Exception):
    pass


class Counter:
    def __init__(self, start: int = 1):
        self.x = start

    def count(self) -> int:
        x = self.x
        self.x += 1
        return x

    def next(self) -> int:
        return self.count()

    def current(self) -> int:
        return self.x


class SIPStatus(Enum):
    def __new__(cls, value: int, phrase: str = "", description: str = ""):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.phrase = phrase
        obj.description = description
        return obj

    def __int__(self) -> int:
        return self._value_

    def __str__(self) -> str:
        return f"{self._value_} {self.phrase}"

    @property
    def phrase(self) -> str:
        return self._phrase

    @phrase.setter
    def phrase(self, value: str) -> None:
        self._phrase = value

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str) -> None:
        self._description = value

    # Informational
    TRYING = (
        100,
        "Trying",
        "Extended search being performed, may take a significant time",
    )
    RINGING = (
        180,
        "Ringing",
        "Destination user agent received INVITE, "
        + "and is alerting user of call",
    )
    FORWARDED = 181, "Call is Being Forwarded"
    QUEUED = 182, "Queued"
    SESSION_PROGRESS = 183, "Session Progress"
    TERMINATED = 199, "Early Dialog Terminated"

    # Success
    OK = 200, "OK", "Request successful"
    ACCEPTED = (
        202,
        "Accepted",
        "Request accepted, processing continues (Deprecated.)",
    )
    NO_NOTIFICATION = (
        204,
        "No Notification",
        "Request fulfilled, nothing follows",
    )

    # Redirection
    MULTIPLE_CHOICES = (
        300,
        "Multiple Choices",
        "Object has several resources -- see URI list",
    )
    MOVED_PERMANENTLY = (
        301,
        "Moved Permanently",
        "Object moved permanently -- see URI list",
    )
    MOVED_TEMPORARILY = (
        302,
        "Moved Temporarily",
        "Object moved temporarily -- see URI list",
    )
    USE_PROXY = (
        305,
        "Use Proxy",
        "You must use proxy specified in Location to "
        + "access this resource",
    )
    ALTERNATE_SERVICE = (
        380,
        "Alternate Service",
        "The call failed, but alternatives are available -- see URI list",
    )

    # Client Error
    BAD_REQUEST = (
        400,
        "Bad Request",
        "Bad request syntax or unsupported method",
    )
    UNAUTHORIZED = (
        401,
        "Unauthorized",
        "No permission -- see authorization schemes",
    )
    PAYMENT_REQUIRED = (
        402,
        "Payment Required",
        "No payment -- see charging schemes",
    )
    FORBIDDEN = (
        403,
        "Forbidden",
        "Request forbidden -- authorization will not help",
    )
    NOT_FOUND = (404, "Not Found", "Nothing matches the given URI")
    METHOD_NOT_ALLOWED = (
        405,
        "Method Not Allowed",
        "Specified method is invalid for this resource",
    )
    NOT_ACCEPTABLE = (
        406,
        "Not Acceptable",
        "URI not available in preferred format",
    )
    PROXY_AUTHENTICATION_REQUIRED = (
        407,
        "Proxy Authentication Required",
        "You must authenticate with this proxy before proceeding",
    )
    REQUEST_TIMEOUT = (
        408,
        "Request Timeout",
        "Request timed out; try again later",
    )
    CONFLICT = 409, "Conflict", "Request conflict"
    GONE = (
        410,
        "Gone",
        "URI no longer exists and has been permanently removed",
    )
    LENGTH_REQUIRED = (
        411,
        "Length Required",
        "Client must specify Content-Length",
    )
    CONDITIONAL_REQUEST_FAILED = 412, "Conditional Request Failed"
    REQUEST_ENTITY_TOO_LARGE = (
        413,
        "Request Entity Too Large",
        "Entity is too large",
    )
    REQUEST_URI_TOO_LONG = 414, "Request-URI Too Long", "URI is too long"
    UNSUPPORTED_MEDIA_TYPE = (
        415,
        "Unsupported Media Type",
        "Entity body in unsupported format",
    )
    UNSUPPORTED_URI_SCHEME = (
        416,
        "Unsupported URI Scheme",
        "Cannot satisfy request",
    )
    UNKOWN_RESOURCE_PRIORITY = (
        417,
        "Unkown Resource-Priority",
        "There was a resource-priority option tag, "
        + "but no Resource-Priority header",
    )
    BAD_EXTENSION = (
        420,
        "Bad Extension",
        "Bad SIP Protocol Extension used, not understood by the server.",
    )
    EXTENSION_REQUIRED = (
        421,
        "Extension Required",
        "Server requeires a specific extension to be "
        + "listed in the Supported header",
    )


class SIPMessage:
    def __init__(self, raw_data: bytes):
        self.raw = raw_data.decode('utf-8')
        self.status = None
        self.method = None
        self.headers = {}
        self.parse()

    def parse(self):
        lines = self.raw.splitlines()
        if not lines:
            return
        
        # Parse the first line
        first_line = lines[0].strip()
        if first_line.startswith('SIP/2.0'):
            # Response message
            parts = first_line.split()
            status_code = int(parts[1])
            self.status = SIPStatus(status_code)
            self.reason = parts[2] if len(parts) > 2 else ""
        else:
            # Request message
            parts = first_line.split()
            self.method = parts[0]
            self.uri = parts[1]
            self.version = parts[2]
        
        # Parse headers
        current_header = None
        for line in lines[1:]:
            line = line.strip()
            if line == "":
                continue
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                if key in self.headers:
                    if isinstance(self.headers[key], list):
                        self.headers[key].append(value)
                    else:
                        self.headers[key] = [self.headers[key], value]
                else:
                    self.headers[key] = value
                current_header = key
            else:
                # Continuation line (e.g., long header value split across lines)
                if current_header:
                    self.headers[current_header] += ' ' + line
                else:
                    # This might be part of the body
                    pass

    def summary(self):
        if self.status:
            return f"SIP {self.status} {self.reason}"
        else:
            return f"{self.method} {self.uri} {self.version}"

class SIPClient:
    def __init__(
        self,
        server: str,
        port: int,
        username: str,
        password: str,
        phone: Optional["VoIPPhone"] = None,
        myIP: str = "0.0.0.0",
        myPort: int = 5060,
        socket_type: str = "udp",
        register_timeout: float = 5.0,
        default_expires: int = 120,
    ):
        self.server = server
        self.port = port
        self.username = username
        self.password = password
        self.phone = phone
        if myIP is None or myIP == "0.0.0.0":
            self.myIP = "192.168.1.181"
        else:
            self.myIP = myIP
        self.myPort = myPort
        self.register_timeout = register_timeout
        self.default_expires = default_expires
        self.registerFailures = 0
        self.NSD = False
        self.uuid = str(uuid.uuid4())
        self.registerCounter = Counter()
        self.recvLock = Lock()
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind((self.myIP, self.myPort))

    def start(self):
        # Запуск потока для обработки входящих сообщений
        pass

    def stop(self):
        self.NSD = False
        if hasattr(self, "registerThread") and self.registerThread:
            self.registerThread.cancel()
        self.s.close()
        self.out.close()

    def gen_first_response(self) -> str:
        branch = f"{random.getrandbits(64):x}"
        return (
            f"REGISTER sip:{self.server} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.myIP}:{self.myPort};branch=z9hG4bK{branch};rport\r\n"
            f"From: \"{self.username}\" <sip:{self.username}@{self.server}>;tag={uuid.uuid4().hex[:8]}\r\n"
            f"To: \"{self.username}\" <sip:{self.username}@{self.server}>\r\n"
            f"Call-ID: {uuid.uuid4().hex}@0.0.0.0:{self.myPort}\r\n"
            f"CSeq: {self.registerCounter.count()} REGISTER\r\n"
            f"Contact: <sip:{self.username}@{self.myIP}:{self.myPort};transport=UDP>;+sip.instance=\"<urn:uuid:{self.uuid}>\"\r\n"
            f"Allow: INVITE, ACK, BYE, CANCEL, NOTIFY\r\n"
            f"Max-Forwards: 70\r\n"
            f"Allow-Events: org.3gpp.nwinitdereg\r\n"
            f"User-Agent: Sippy 0.1.0\r\n"
            f"Expires: {self.default_expires}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

    def gen_register(self, response: "SIPMessage") -> str:
        branch = f"{random.getrandbits(64):x}"
        auth_header = self.gen_authorization(response, request_uri=f"sip:{self.server}")
        return (
            f"REGISTER sip:{self.server} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.myIP}:{self.myPort};branch=z9hG4bK{branch};rport\r\n"
            f"From: \"{self.username}\" <sip:{self.username}@{self.server}>;tag={uuid.uuid4().hex[:8]}\r\n"
            f"To: \"{self.username}\" <sip:{self.username}@{self.server}>\r\n"
            f"Call-ID: {uuid.uuid4().hex}@0.0.0.0:{self.myPort}\r\n"
            f"CSeq: {self.registerCounter.count()} REGISTER\r\n"
            f"Contact: <sip:{self.username}@{self.myIP}:{self.myPort};transport=UDP>;+sip.instance=\"<urn:uuid:{self.uuid}>\"\r\n"
            f"Allow: INVITE, ACK, BYE, CANCEL, NOTIFY\r\n"
            f"Max-Forwards: 70\r\n"
            f"Allow-Events: org.3gpp.nwinitdereg\r\n"
            f"User-Agent: Sippy 0.1.0\r\n"
            f"Expires: {self.default_expires}\r\n"
            f"Authorization: {auth_header}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

    def gen_ok(self, request: "SIPMessage") -> str:
        return (
            f"SIP/2.0 200 OK\r\n"
            f"Via: {request.headers['Via'][0]['raw']}\r\n"
            f"From: {request.headers['From']['raw']}\r\n"
            f"To: {request.headers['To']['raw']};tag={uuid.uuid4().hex[:8]}\r\n"
            f"Call-ID: {request.headers['Call-ID']}\r\n"
            f"CSeq: {request.headers['CSeq']['check']} {request.headers['CSeq']['method']}\r\n"
            f"Allow: INVITE, ACK, BYE, CANCEL, NOTIFY, OPTIONS\r\n"
            f"User-Agent: Sippy 0.1.0\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

    def register(self, delay: Optional[float] = None) -> None:
        if delay is None:
            delay = self.default_expires - 5
        if self.NSD:
            debug("New register thread")
            self.registerThread = Timer(delay, self.register)
            self.registerThread.name = (
                "SIP Register CSeq: " + f"{self.registerCounter.x}"
            )
            self.registerThread.start()

    def __register(self) -> bool:
        self.phone._status = PhoneStatus.REGISTERING
        firstRequest = self.gen_first_response()
        self.out.sendto(firstRequest.encode("utf8"), (self.server, self.port))

        self.out.setblocking(False)

        ready = select.select([self.out], [], [], self.register_timeout)
        if ready[0]:
            resp = self.s.recv(8192)
        else:
            raise TimeoutError("Registering on SIP Server timed out")

        response = SIPMessage(resp)
        response = self.trying_timeout_check(response)
        first_response = response

        if response.status == SIPStatus(400):
            self._handle_bad_request()

        if response.status == SIPStatus(401):
            regRequest = self.gen_register(response)
            self.out.sendto(
                regRequest.encode("utf8"), (self.server, self.port)
            )
            ready = select.select([self.s], [], [], self.register_timeout)
            if ready[0]:
                resp = self.s.recv(8192)
                response = SIPMessage(resp)
                response = self.trying_timeout_check(response)
                if response.status == SIPStatus(401):
                    debug("=" * 50)
                    debug("Unauthorized, SIP Message Log:\n")
                    debug("SENT")
                    debug(firstRequest)
                    debug("\nRECEIVED")
                    debug(first_response.summary())
                    debug("\nSENT (DO NOT SHARE THIS PACKET)")
                    debug(regRequest)
                    debug("\nRECEIVED")
                    debug(response.summary())
                    debug("=" * 50)
                    raise InvalidAccountInfoError(
                        "Invalid Username or "
                        + "Password for SIP server "
                        + f"{self.server}:"
                        + f"{self.myPort}"
                    )
                elif response.status == SIPStatus(400):
                    self._handle_bad_request()
            else:
                raise TimeoutError("Registering on SIP Server timed out")

        if response.status == SIPStatus(407):
            debug("Proxy auth required")

        if response.status not in [
            SIPStatus(400),
            SIPStatus(401),
            SIPStatus(407),
        ]:
            if response.status == SIPStatus(500):
                raise RetryRequiredError("Response SIP status of 500")
            else:
                self.parse_message(response)

        debug(response.summary())
        debug(response.raw)

        if response.status == SIPStatus.OK:
            return True
        else:
            raise InvalidAccountInfoError(
                "Invalid Username or Password for "
                + f"SIP server {self.server}:"
                + f"{self.myPort}"
            )

    def _handle_bad_request(self) -> None:
        debug("Bad Request")

    def subscribe(self, lastresponse: "SIPMessage") -> None:
        with self.recvLock:
            subRequest = self.gen_subscribe(lastresponse)
            self.out.sendto(
                subRequest.encode("utf8"), (self.server, self.port)
            )
            response = SIPMessage(self.s.recv(8192))
            debug(
                f'Got response to subscribe: {str(response.heading, "utf8")}'
            )

    def trying_timeout_check(self, response: "SIPMessage") -> "SIPMessage":
        start_time = time.monotonic()
        while response.status == SIPStatus.TRYING:
            if (time.monotonic() - start_time) >= self.register_timeout:
                raise TimeoutError(
                    f"Waited {self.register_timeout} seconds but server is "
                    + "still TRYING"
                )
            ready = select.select([self.s], [], [], self.register_timeout)
            if ready[0]:
                resp = self.s.recv(8192)
            response = SIPMessage(resp)
        return response

    def parse_message(self, response: "SIPMessage") -> None:
        if response.method == "OPTIONS":
            ok_response = self.gen_ok(response)
            self.out.sendto(ok_response.encode("utf8"), (self.server, self.port))
            return
        # Остальная логика обработки сообщений
        pass
