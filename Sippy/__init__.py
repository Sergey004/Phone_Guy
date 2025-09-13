from enum import Enum

__all__ = [
    "PhoneStatus",
    "SIPCompatibleMethods",
    "SIPCompatibleVersions",
    "RTPCompatibleVersions",
    "RTPCompatibleCodecs",
    "PayloadType",
    "RTP",
    "debug",
    "__version__",
    "DEBUG",
    "REGISTER_FAILURE_THRESHOLD",
]

version_info = (0, 1, 0)
__version__ = ".".join(str(x) for x in version_info)

# Global debug flag compatible with prior expectations
DEBUG = False

# If registration fails this many times, set status to FAILED and stop
REGISTER_FAILURE_THRESHOLD = 3


def debug(s, e=None):
    if DEBUG:
        print(s)
    elif e is not None:
        # Maintain behavior parity: print exceptions even if not in debug
        print(e)


# SIP compatibility sets (mirroring pyVoIP expectations where used)
SIPCompatibleMethods = ["INVITE", "ACK", "BYE", "CANCEL"]
SIPCompatibleVersions = ["SIP/2.0"]


class PayloadType(Enum):
    PCMU = 0
    PCMA = 8
    EVENT = 101  # common DTMF payload type


RTPCompatibleVersions = [2]
RTPCompatibleCodecs = [PayloadType.PCMU, PayloadType.PCMA, PayloadType.EVENT]


class PhoneStatus(Enum):
    INACTIVE = 0
    REGISTERING = 1
    REGISTERED = 2
    DEREGISTERING = 3
    FAILED = 4


class RTP:
    # Expose PayloadType under RTP namespace for compatibility
    PayloadType = PayloadType

    class RTPProtocol(int):
        def __new__(cls, value):
            try:
                return int.__new__(cls, int(value))
            except Exception:
                return int.__new__(cls, 0)

    class TransmitType(str):
        def __new__(cls, value):
            return str.__new__(cls, str(value))