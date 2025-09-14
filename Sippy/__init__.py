__all__ = ["SIP", "RTP", "VoIP"]

version_info = (0, 1, 0)

__version__ = ".".join([str(x) for x in version_info])

from .debug import DEBUG, TRANSMIT_DELAY_REDUCTION, REGISTER_FAILURE_THRESHOLD, debug

# noqa because import will fail if debug is not defined
from Sippy.RTP import PayloadType  # noqa: E402

SIPCompatibleMethods = ["INVITE", "ACK", "BYE", "CANCEL", "NOTIFY"]
SIPCompatibleVersions = ["SIP/2.0"]

RTPCompatibleVersions = [2]
RTPCompatibleCodecs = [PayloadType.PCMU, PayloadType.PCMA, PayloadType.EVENT]
