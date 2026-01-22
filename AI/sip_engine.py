import pjsua2 as pj
import logging
from .rtp_handler import PhoneGuyRTP

class PhoneCall(pj.Call):
    """SIP Call handler for manual RTP mode."""
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID):
        super().__init__(acc, call_id)
        self.rtp = None
        self._rtp = None  # For orchestrator_loop detection

    def onCallRxOffer(self, prm):
        """
        *** CRITICAL: SIP-ONLY MODE - PREVENT SDP NEGOTIATION ***
        
        Intercept incoming SDP offer and disable SDP negotiation.
        This prevents PJSUA from trying to match codecs when noAudio=True.
        
        Args:
            prm: Call RX offer parameter with pAnswer field
            
        Returns:
            PJ_SUCCESS
        """
        logging.info("📨 onCallRxOffer: Disabling SDP negotiation (SIP-only mode)")
        prm.pAnswer = None
        return pj.PJ_SUCCESS

    def onCallMediaState(self, prm):
        """DISABLED in manual RTP mode - media is handled externally."""
        # В режиме manual RTP этот коллбэк не используется
        # Оставляем пустым для совместимости
        pass

    def start_manual_rtp(self, local_port):
        """Start RTP thread manually with latching (remote_addr=None)."""
        try:
            import logging
            logging.info(f"🎙️ Manual RTP started on port {local_port}, waiting for incoming audio...")
            # Создаём RTP с remote_addr=None - адрес определится при первом входящем пакете
            self.rtp = PhoneGuyRTP(remote_addr=None, local_port=local_port)
            self._rtp = self.rtp  # For orchestrator_loop
            self.rtp.start()
        except Exception as e:
            logging.error(f"Failed to start manual RTP: {e}")

    def onCallState(self, prm):
        """Handle call state changes."""
        try:
            info = self.getInfo()
            state_str = str(info.state).replace('PJSIP_INV_STATE_', '')
            logging.info(f"Call state: {state_str}")
            if info.state == pj.PJSIP_INV_STATE_DISCONNECTED and self.rtp:
                self.rtp.stop()
                self.rtp = None
                self._rtp = None
        except Exception as e:
            logging.error(f"onCallState error: {e}")
