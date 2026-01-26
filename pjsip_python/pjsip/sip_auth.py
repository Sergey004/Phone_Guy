"""
pjsip/sip_auth.h - SIP Authentication

SIP Digest authentication implementation (RFC 2617, RFC 3261).
Supports both WWW-Authenticate and Proxy-Authenticate headers.
"""

import hashlib
import re
import random
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from .sip_msg import SipMessage, SipHeader


class AuthType(Enum):
    """Authentication type."""
    NONE = 0
    WWW_AUTHENTICATE = 1
    PROXY_AUTHENTICATE = 2


@dataclass
class AuthCredential:
    """Authentication credential for a single realm."""
    username: str
    password: str
    realm: str
    algorithm: str = "MD5"
    qop: Optional[str] = None
    nonce: Optional[str] = None
    opaque: Optional[str] = None

    def __post_init__(self):
        if self.realm == "*":
            self.realm = "default"


@dataclass
class AuthSess:
    """
    Authentication session for a dialog.

    Tracks authentication state and credentials for
    authenticated requests within a dialog.
    """

    credentials: List[AuthCredential] = field(default_factory=list)
    auth_type: AuthType = AuthType.NONE
    realm: str = ""
    nonce: str = ""
    opaque: str = ""
    qop: str = ""
    cnonce: str = ""
    nc: int = 0
    stale: bool = False

    def add_credential(self, cred: AuthCredential) -> None:
        """Add a credential to the session."""
        self.credentials.append(cred)

    def find_credential(self, realm: str) -> Optional[AuthCredential]:
        """Find credential for a realm."""
        for cred in self.credentials:
            if cred.realm == realm:
                return cred
        if self.credentials:
            return self.credentials[0]
        return None

    def clear(self) -> None:
        """Clear authentication session."""
        self.nonce = ""
        self.opaque = ""
        self.qop = ""
        self.cnonce = ""
        self.nc = 0
        self.stale = False


class DigestAuth:
    """
    Digest authentication helper.

    Provides methods for generating and validating
    Digest authentication headers.
    """

    def __init__(self):
        self._algo = "MD5"

    @staticmethod
    def generate_nonce() -> str:
        """Generate a random nonce."""
        import time
        data = f"{random.randint(1, 1000000)}:{time.time()}"
        return hashlib.md5(data.encode()).hexdigest()

    @staticmethod
    def generate_cnonce() -> str:
        """Generate a client nonce."""
        import time
        data = f"{random.randint(1, 1000000)}:{time.time()}"
        return hashlib.md5(data.encode()).hexdigest()[:16]

    @staticmethod
    def calc_ha1(
        username: str,
        realm: str,
        password: str
    ) -> str:
        """
        Calculate HA1 hash.

        HA1 = MD5(username:realm:password)
        """
        ha1_str = f"{username}:{realm}:{password}"
        return hashlib.md5(ha1_str.encode()).hexdigest()

    @staticmethod
    def calc_ha2(
        method: str,
        uri: str,
        qop: str = ""
    ) -> str:
        """
        Calculate HA2 hash.

        HA2 = MD5(method:uri)
        qop is not included in HA2 (per RFC 2617)
        """
        ha2_str = f"{method}:{uri}"
        return hashlib.md5(ha2_str.encode()).hexdigest()

    @staticmethod
    def calc_response(
        ha1: str,
        nonce: str,
        nc: int,
        cnonce: str,
        qop: str,
        ha2: str
    ) -> str:
        """
        Calculate digest response.

        Response = MD5(ha1:nonce:nc:cnonce:qop:ha2)
        """
        response_str = f"{ha1}:{nonce}:{nc:08x}:{cnonce}:{qop}:{ha2}"
        return hashlib.md5(response_str.encode()).hexdigest()

    @staticmethod
    def calc_response_simple(
        username: str,
        password: str,
        method: str,
        uri: str,
        realm: str,
        nonce: str,
        qop: str = "",
        nc: int = 0,
        cnonce: str = ""
    ) -> str:
        """
        Calculate response directly from credentials.

        Simplified method for one-shot authentication.
        """
        ha1 = DigestAuth.calc_ha1(username, realm, password)
        ha2 = DigestAuth.calc_ha2(method, uri, qop)

        if qop:
            return DigestAuth.calc_response(ha1, nonce, nc, cnonce, qop, ha2)
        else:
            response_str = f"{ha1}:{nonce}:{ha2}"
            return hashlib.md5(response_str.encode()).hexdigest()

    @staticmethod
    def parse_www_authenticate(header: str) -> Dict[str, str]:
        """
        Parse WWW-Authenticate header value.

        Returns dictionary of auth parameters.
        """
        params = {}

        header = header.strip()
        if header.startswith('Digest '):
            header = header[7:]

        for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header):
            key = match.group(1)
            value = match.group(2) or match.group(3)
            params[key] = value

        return params

    @staticmethod
    def parse_authorization(header: str) -> Dict[str, str]:
        """
        Parse Authorization header value.

        Returns dictionary of auth parameters.
        """
        return DigestAuth.parse_www_authenticate(header)

    @staticmethod
    def build_www_authenticate(
        realm: str,
        nonce: Optional[str] = None,
        opaque: Optional[str] = None,
        qop: str = "auth",
        stale: bool = False,
        algorithm: str = "MD5"
    ) -> str:
        """
        Build WWW-Authenticate header value.

        Args:
            realm: Authentication realm.
            nonce: Nonce value (generated if None).
            opaque: Opaque value.
            qop: Quality of protection (auth, auth-int).
            stale: Whether previous request was stale.
            algorithm: Hash algorithm.

        Returns:
            WWW-Authenticate header value.
        """
        if nonce is None:
            nonce = DigestAuth.generate_nonce()

        header = f'Digest realm="{realm}", algorithm={algorithm}'

        if qop:
            header += f', qop={qop}'
            header += f', nonce="{nonce}"'
        else:
            header += f', nonce="{nonce}"'

        if opaque:
            header += f', opaque="{opaque}"'

        if stale:
            header += ', stale=true'

        return header

    @staticmethod
    def build_authorization(
        username: str,
        realm: str,
        nonce: str,
        uri: str,
        response: str,
        qop: str = "auth",
        nc: int = 1,
        cnonce: Optional[str] = None,
        opaque: Optional[str] = None,
        algorithm: str = "MD5"
    ) -> str:
        """
        Build Authorization header value.

        Args:
            username: Username.
            realm: Realm from challenge.
            nonce: Nonce from challenge.
            uri: Request URI.
            response: Digest response.
            qop: Quality of protection.
            nc: Nonce count (hex).
            cnonce: Client nonce.
            opaque: Opaque value from challenge.
            algorithm: Hash algorithm.

        Returns:
            Authorization header value.
        """
        if cnonce is None:
            cnonce = DigestAuth.generate_cnonce()

        header = (
            f'Digest username="{username}", '
            f'realm="{realm}", '
            f'nonce="{nonce}", '
            f'uri="{uri}", '
            f'response="{response}", '
            f'algorithm={algorithm}'
        )

        if qop:
            header += f', qop={qop}'
            header += f', nc={nc:08x}'
            header += f', cnonce="{cnonce}"'

        if opaque:
            header += f', opaque="{opaque}"'

        return header

    @staticmethod
    def verify_response(
        username: str,
        password: str,
        method: str,
        uri: str,
        realm: str,
        nonce: str,
        qop: str,
        nc: int,
        cnonce: str,
        response: str,
        opaque: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Verify a Digest response.

        Args:
            username: Username.
            password: Password.
            method: SIP method.
            uri: Request URI.
            realm: Realm.
            nonce: Nonce value.
            qop: Quality of protection.
            nc: Nonce count (decimal).
            cnonce: Client nonce.
            response: Response to verify.
            opaque: Opaque value (ignored for verification).

        Returns:
            Tuple of (is_valid, reason).
        """
        expected = DigestAuth.calc_response_simple(
            username=username,
            password=password,
            method=method,
            uri=uri,
            realm=realm,
            nonce=nonce,
            qop=qop if qop else "",
            nc=nc,
            cnonce=cnonce
        )

        if expected == response:
            return True, ""
        return False, "Response mismatch"


def generate_auth_header(
    username: str,
    password: str,
    method: str,
    uri: str,
    challenge: Dict[str, str]
) -> str:
    """
    Generate Authorization header from challenge.

    Args:
        username: Username.
        password: Password.
        method: SIP method.
        uri: Request URI.
        challenge: Parsed challenge parameters.

    Returns:
        Authorization header value.
    """
    realm = challenge.get('realm', '')
    nonce = challenge.get('nonce', '')
    qop = challenge.get('qop', '')
    opaque = challenge.get('opaque', '')
    algorithm = challenge.get('algorithm', 'MD5')

    nc = 1
    cnonce = DigestAuth.generate_cnonce()

    response = DigestAuth.calc_response_simple(
        username=username,
        password=password,
        method=method,
        uri=uri,
        realm=realm,
        nonce=nonce,
        qop=qop,
        nc=nc,
        cnonce=cnonce
    )

    return DigestAuth.build_authorization(
        username=username,
        realm=realm,
        nonce=nonce,
        uri=uri,
        response=response,
        qop=qop,
        nc=nc,
        cnonce=cnonce,
        opaque=opaque,
        algorithm=algorithm
    )
