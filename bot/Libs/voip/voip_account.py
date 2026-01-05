"""
VoIP Account
SIP account implementation
"""

import logging
import pjsua2 as pj
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .voip_call import VoIPCall


class VoIPAccount(pj.Account):
    """
    SIP account implementation.
    Handles registration and incoming calls.
    """
    
    def __init__(self, ep: pj.Endpoint, 
                 call_class=None,
                 logger: Optional[logging.Logger] = None,
                 **kwargs):
        """
        Initialize SIP account.
        
        Args:
            ep: PJSIP endpoint instance
            call_class: Call class to instantiate for incoming calls
            logger: Logger instance
            **kwargs: Additional arguments for call class
        """
        super().__init__()
        self.ep = ep
        self.call_class = call_class
        self.logger = logger or logging.getLogger(__name__)
        self.call_kwargs = kwargs
        
        self.current_call = None
        self.incoming_call_handler = None
    
    def onRegState(self, prm):
        """
        Called when registration state changes.
        
        Args:
            prm: Registration state parameter
        """
        try:
            info = self.getInfo()
            self.logger.info(f"Account registration: {info.regIsActive} "
                           f"({prm.code} {prm.reason})")
        except Exception as e:
            self.logger.error(f"Error in onRegState: {e}")
    
    def onIncomingCall(self, prm):
        """
        Called when incoming call is received.
        
        Args:
            prm: Incoming call parameter
        """
        try:
            if not self.call_class:
                self.logger.warning("No call class set, ignoring incoming call")
                return
            
            # Create call instance
            call = self.call_class(self, prm.callId, **self.call_kwargs)
            self.current_call = call
            
            ci = call.getInfo()
            self.logger.info(f"Incoming call from {ci.remoteUri}")
            
            # Call custom handler if set
            if self.incoming_call_handler:
                self.incoming_call_handler(call, prm)
            else:
                # Default behavior: answer automatically
                self._answer_call(call, prm)
                
        except Exception as e:
            self.logger.error(f"Error handling incoming call: {e}", exc_info=True)
    
    def _answer_call(self, call: 'VoIPCall', prm):
        """
        Answer incoming call with default behavior.
        
        Args:
            call: VoIP call instance
            prm: Incoming call parameter
        """
        try:
            answer_prm = pj.CallOpParam()
            answer_prm.statusCode = 200
            call.answer(answer_prm)
            self.logger.info("Call answered")
        except Exception as e:
            self.logger.error(f"Error answering call: {e}")
    
    def set_incoming_call_handler(self, handler: Callable):
        """
        Set custom handler for incoming calls.
        
        Args:
            handler: Function to call when incoming call received
                     Signature: handler(call, prm)
        """
        self.incoming_call_handler = handler
        self.logger.info("Incoming call handler set")
    
    def get_current_call(self):
        """Get current active call."""
        return self.current_call
    
    def set_current_call(self, call):
        """Set current active call."""
        self.current_call = call
