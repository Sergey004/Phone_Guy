"""
VoIP Client
Main PJSIP client implementation
"""

import logging
import pjsua2 as pj
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .voip_account import VoIPAccount
    from .voip_call import VoIPCall


class VoIPClient:
    """
    VoIP client wrapper around PJSIP endpoint.
    Handles initialization, configuration, and lifecycle management.
    """
    
    def __init__(self, 
                 config: Optional[Dict[str, Any]] = None,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize VoIP client.
        
        Args:
            config: Configuration dictionary with SIP settings
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.config = config or {}
        
        # PJSIP endpoint
        self.ep = pj.Endpoint()
        self.account = None
        
        # Configuration
        sip_cfg = self.config.get('sip', {})
        self.domain = sip_cfg.get('domain', '')
        self.user = sip_cfg.get('username', '')
        self.password = sip_cfg.get('password', '')
        self.local_ip = sip_cfg.get('local_addr', '192.168.1.181')
        self.local_port = sip_cfg.get('local_port', 5060)
        
        # Audio configuration
        self.sample_rate = 8000
        self.channels = 1
        self.frame_time = 20  # ms
        
        self._initialized = False
        self._started = False
        
    def initialize(self) -> bool:
        """
        Initialize PJSIP endpoint and configure settings.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create endpoint
            self.ep.libCreate()
            self.logger.info("PJSIP endpoint created")
            
            # Configure endpoint
            ep_cfg = pj.EpConfig()
            ep_cfg.uaConfig.threadCnt = 1
            ep_cfg.uaConfig.maxCalls = 4
            ep_cfg.logConfig.level = 3  # Info level
            ep_cfg.medConfig.sndClockRate = self.sample_rate
            ep_cfg.medConfig.channelCount = self.channels
            ep_cfg.medConfig.audioFramePtime = self.frame_time
            ep_cfg.medConfig.noVad = True
            
            self.ep.libInit(ep_cfg)
            self.logger.info("PJSIP initialized")
            
            # Set null sound device (no hardware audio)
            self.ep.audDevManager().setNullDev()
            self.logger.info("Null sound device set")
            
            # Create transport
            tcfg = pj.TransportConfig()
            tcfg.port = self.local_port
            tcfg.boundAddr = self.local_ip
            tcfg.publicAddr = self.local_ip
            self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)
            self.logger.info(f"Transport created on {self.local_ip}:{self.local_port}")
            
            # Configure codecs
            self._configure_codecs()
            
            self._initialized = True
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize VoIP client: {e}", exc_info=True)
            return False
    
    def _configure_codecs(self):
        """Configure audio codecs."""
        try:
            # Disable all codecs first
            self.ep.codecSetPriority("*", 0)
            
            # Enable PCMA and PCMU
            self.ep.codecSetPriority("PCMA/8000/1", 255)  # Primary
            self.ep.codecSetPriority("PCMU/8000/1", 254)  # Fallback
            
            self.logger.info("Codecs configured: PCMA/8000/1 (255), PCMU/8000/1 (254)")
        except Exception as e:
            self.logger.error(f"Failed to configure codecs: {e}")
    
    def start(self) -> bool:
        """
        Start PJSIP library.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.ep.libStart()
            self._started = True
            self.logger.info("PJSIP started")
            return True
        except Exception as e:
            self.logger.error(f"Failed to start PJSIP: {e}", exc_info=True)
            return False
    
    def create_account(self, account_class, **kwargs) -> bool:
        """
        Create and register SIP account.
        
        Args:
            account_class: Account class to instantiate
            **kwargs: Additional arguments for account class
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self._started:
                self.logger.error("Cannot create account: PJSIP not started")
                return False
            
            # Create account configuration
            acc_cfg = pj.AccountConfig()
            acc_cfg.idUri = f"sip:{self.user}@{self.domain}"
            acc_cfg.regConfig.registrarUri = f"sip:{self.domain}"
            acc_cfg.sipConfig.authCreds.append(
                pj.AuthCredInfo("digest", "*", self.user, 0, self.password)
            )
            
            # Create account instance
            self.account = account_class(self.ep, **kwargs)
            self.account.create(acc_cfg)
            
            self.logger.info(f"Account created: {self.user}@{self.domain}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to create account: {e}", exc_info=True)
            return False
    
    def make_call(self, call_class, uri: str, **kwargs) -> Optional['VoIPCall']:
        """
        Make outgoing call.
        
        Args:
            call_class: Call class to instantiate
            uri: SIP URI to call
            **kwargs: Additional arguments for call class
            
        Returns:
            VoIPCall instance if successful, None otherwise
        """
        try:
            if not self.account:
                self.logger.error("Cannot make call: no account")
                return None
            
            call = call_class(self.account, **kwargs)
            prm = pj.CallOpParam(True)
            call.makeCall(uri, prm)
            
            self.logger.info(f"Call initiated to {uri}")
            return call
            
        except Exception as e:
            self.logger.error(f"Failed to make call to {uri}: {e}", exc_info=True)
            return None
    
    def get_endpoint(self) -> pj.Endpoint:
        """Get PJSIP endpoint instance."""
        return self.ep
    
    def get_account(self):
        """Get SIP account instance."""
        return self.account
    
    def is_initialized(self) -> bool:
        """Check if client is initialized."""
        return self._initialized
    
    def is_started(self) -> bool:
        """Check if client is started."""
        return self._started
    
    def destroy(self):
        """Destroy PJSIP client and cleanup resources."""
        try:
            if self.account:
                try:
                    self.account.setRegistration(False)
                    import time
                    time.sleep(0.5)
                    self.account = None
                    self.logger.info("Account unregistered")
                except Exception as e:
                    self.logger.error(f"Error unregistering account: {e}")
            
            if self._started:
                self.ep.libDestroy()
                self._started = False
                self.logger.info("PJSIP destroyed")
            
            self._initialized = False
            
        except Exception as e:
            self.logger.error(f"Error destroying VoIP client: {e}", exc_info=True)
