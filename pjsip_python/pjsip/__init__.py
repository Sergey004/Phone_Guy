"""
pjsip - SIP Signaling Layer

SIP protocol implementation including:
- SIP message parsing and building (pjsip/sip_msg.h)
- URI parsing (pjsip/sip_uri.h)
- Transaction state machine (pjsip/sip_transaction.h)
- Dialog management (pjsip/sip_dialog.h)
- Transport layer (pjsip/sip_transport.h)
- Authentication (pjsip/sip_auth.h)
- Core endpoint (pjsip/sip_endpoint.h)
"""

from typing import Optional, Union

from .sip_msg import (
    SipMessage,
    SipMethod, SipStatusCode,
    SipViaHeader, SipFromHeader, SipToHeader, SipContactHeader,
    create_request, create_response,
    generate_branch, generate_call_id, generate_tag
)
from .sip_uri import SipUri, parse_sip_uri, parse_tel_uri
from .sip_transaction import (
    Transaction, TransactionState,
    UacTransaction, UasTransaction,
    TsxLayer, create_tsx_layer,
    TransactionRole
)
from .sip_dialog import (
    Dialog, DialogState, DialogSet,
    DialogRoute
)
from .sip_transport import (
    Transport, TransportType, TransportConfig,
    UdpTransport, TcpTransport,
    TransportManager, create_transport_manager
)
from .sip_auth import (
    AuthCredential, AuthSess, AuthType,
    DigestAuth, generate_auth_header
)
from .sip_endpoint import (
    SipEndpoint, EndpointConfig,
    Module, CoreModule
)
from .sip_util import (
    create_via_header, create_contact_header,
    get_remote_hdrs, get_request_uri,
    get_local_ip, get_local_hostname,
    MsgInfo, log_msg
)

SipRequest = SipMessage
SipResponse = SipMessage

def parse_sip_message(data):
    """Parse SIP message from bytes/string."""
    return SipMessage.parse(data)

def build_sip_message(msg):
    """Build SIP message to bytes."""
    return msg.build()

__all__ = [
    'SipMessage', 'SipRequest', 'SipResponse',
    'parse_sip_message', 'build_sip_message',
    'SipMethod', 'SipStatusCode',
    'SipViaHeader', 'SipFromHeader', 'SipToHeader', 'SipContactHeader',
    'create_request', 'create_response',
    'generate_branch', 'generate_call_id', 'generate_tag',
    'SipUri', 'parse_sip_uri', 'parse_tel_uri',
    'Transaction', 'TransactionState', 'TransactionRole',
    'UacTransaction', 'UasTransaction', 'TsxLayer', 'create_tsx_layer',
    'Dialog', 'DialogState', 'DialogSet', 'DialogRoute',
    'Transport', 'TransportType', 'TransportConfig',
    'UdpTransport', 'TcpTransport', 'TransportManager', 'create_transport_manager',
    'AuthCredential', 'AuthSess', 'AuthType', 'DigestAuth', 'generate_auth_header',
    'SipEndpoint', 'EndpointConfig', 'Module', 'CoreModule',
    'create_via_header', 'create_contact_header',
    'get_remote_hdrs', 'get_request_uri',
    'get_local_ip', 'get_local_hostname',
    'MsgInfo', 'log_msg',
]
