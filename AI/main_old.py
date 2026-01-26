import time
import logging
import threading
import sys
import os
import socket
import random
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pj
except Exception:
    try:
        import pjsua2 as pj
    except Exception:
        pj = None

from AI import rtp_handler, sip_engine, stt_adapter, llm_adapter

try:
    from AI import tts_adapter
except Exception as e:
    logging.warning(f'TTS adapter import failed: {e}')
    tts_adapter = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SIP Configuration
SIP_DOMAIN = os.getenv('SIP_DOMAIN', 'localhost')
SIP_PORT = int(os.getenv('SIP_PORT', '5060'))
SIP_USER = os.getenv('SIP_USER', 'phoneguy')
SIP_PASSWORD = os.getenv('SIP_PASSWORD', 'password')
SIP_SERVER = os.getenv('SIP_SERVER', f'{SIP_DOMAIN}:{SIP_PORT}')
LOCAL_IP = os.getenv('LOCAL_IP', '192.168.1.181') 

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

current_ip = LOCAL_IP if LOCAL_IP else get_local_ip()

# === FIX 1: Use Inheritance for Account Callbacks ===
class PhoneAccount(pj.Account): 
    def __init__(self):
        super().__init__()
        self.active_calls = []

    def onRegState(self, prm):
        """Handle registration state changes."""
        try:
            info = self.getInfo()
            logging.info(f'📝 SIP Registration Status: {info.regStatus} ({info.regReason})')
        except Exception as e:
            logging.exception('onRegState error')

    def onIncomingCall(self, prm):
        """Handle incoming SIP call with MANUAL SDP and NO PJSIP MEDIA."""
        try:
            logging.info('📞 Incoming call received (Signaling Only Mode)')
            
            # Create Call Object using our wrapper
            call = sip_engine.PhoneCall(self, prm.callId)
            self.active_calls.append(call)

            # 1. Prepare Manual RTP Port
            local_rtp_port = random.randrange(10000, 20000, 2)
            
            # 2. Construct Manual SDP
            # We must provide this so Asterisk knows where to send audio (our raw socket),
            # even though we tell PJSIP audioCount=0.
            sdp = (
                "v=0\r\n"
                f"o=- {int(time.time())} {int(time.time())} IN IP4 {current_ip}\r\n"
                "s=pj-manual\r\n"
                f"c=IN IP4 {current_ip}\r\n"
                "t=0 0\r\n"
                f"m=audio {local_rtp_port} RTP/AVP 8 101\r\n"
                "a=rtpmap:8 PCMA/8000\r\n"
                "a=rtpmap:101 telephone-event/8000\r\n"
                "a=fmtp:101 0-16\r\n"
                "a=sendrecv\r\n"
            )

            # 3. Configure Answer Parameters
            call_prm = pj.CallOpParam()
            call_prm.statusCode = 200
            
            # === FIX 2: PREVENT 488 ERROR ===
            # Explicitly tell PJSIP we have 0 audio streams. 
            # This stops PJSIP from checking for codecs or trying to negotiate media.
            call_prm.opt.audioCount = 0
            call_prm.opt.videoCount = 0
            
            # === FIX 3: OVERRIDE SDP ===
            # PJSIP would normally send "m=audio 0" (disabled).
            # We force it to send our custom SDP with the REAL port.
            call_prm.txOption.msgBody = sdp
            call_prm.txOption.contentType = "application/sdp"

            # 4. Send 200 OK
            call.answer(call_prm)
            
            # 5. Start Manual RTP Handler
            call.start_manual_rtp(local_rtp_port)
            
            logging.info(f'✅ Call answered. PJSIP Media: OFF. Manual RTP: ON (Port {local_rtp_port})')
            
        except Exception as e:
            logging.exception('onIncomingCall error')

def register_sip_account(ep):
    """Register SIP account using the inherited class."""
    if ep is None or pj is None:
        return None

    try:
        logging.info(f'Target: {SIP_USER}@{SIP_SERVER}')
        
        acc_cfg = pj.AccountConfig()
        acc_cfg.idUri = f'sip:{SIP_USER}@{SIP_DOMAIN}'
        acc_cfg.regConfig.registrarUri = f'sip:{SIP_SERVER}'
        
        cred = pj.AuthCredInfo("digest", "*", SIP_USER, 0, SIP_PASSWORD)
        acc_cfg.sipConfig.authCreds.append(cred)
        
        # Instantiate our custom class
        account = PhoneAccount() 
        account.create(acc_cfg)
        
        return account
    except Exception as e:
        logging.exception(f'Failed to register SIP account')
        return None

def _init_endpoint():
    """Initialize PJSIP in absolute minimal mode."""
    if pj is None:
        return None

    try:
        ep = pj.Endpoint()
        ep.libCreate()
        
        cfg = pj.EpConfig()
        # Disable internal media engine
        cfg.medConfig.noAudio = True 
        cfg.uaConfig.threadCnt = 1
        cfg.uaConfig.mainThreadOnly = False
        
        ep.libInit(cfg)
        
        tcfg = pj.TransportConfig()
        tcfg.port = 5060 
        ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)
        
        ep.libStart()
        logging.info('✓ Endpoint ready (Signaling Only Mode)')
        return ep
    except Exception as e:
        logging.exception('Endpoint init failed')
        return None

def try_transcribe(stt, pcm):
    if not stt: return None
    try:
        return stt.transcribe_pcm(pcm) if hasattr(stt, 'transcribe_pcm') else None
    except: return None

def try_llm_query(llm, text):
    if not llm: return ""
    try:
        return llm.phoneguy_reply(text) if hasattr(llm, 'phoneguy_reply') else ""
    except: return ""

def try_tts_synthesize(tts, text):
    if not tts: return None
    try:
        return tts.synthesize_sync(text) if hasattr(tts, 'synthesize_sync') else None
    except: return None

def orchestrator_loop():
    ep = _init_endpoint()
    account = None
    
    if ep is not None:
        account = register_sip_account(ep)
        time.sleep(2) # Give registration a moment

    try:
        stt = stt_adapter.STTAdapter(config={}, logger=logger)
    except: stt = None
    
    try:
        import AI.llm_adapter as llm_mod
        llm = llm_mod
    except: llm = None

    try:
        tts = tts_adapter.TTSAdapter(config={}, logger=logger)
    except: tts = None

    logging.info('🎧 AI components initialized. Waiting for calls...')

    try:
        while True:
            active_call = None
            if account:
                # Poll active calls from our Account object
                for c in account.active_calls:
                    if hasattr(c, 'rtp') and c.rtp is not None:
                        active_call = c
                        break
            
            if active_call is None:
                time.sleep(0.1)
                continue

            # --- RTP/AI Loop ---
            rtp = active_call.rtp
            
            # Non-blocking read from RTP buffer
            pcm = rtp.get_next_rx_chunk(timeout=0.02)
            
            if pcm:
                text = try_transcribe(stt, pcm)
                if text:
                    logging.info(f"🗣️ User: {text}")
                    reply = try_llm_query(llm, text)
                    if reply:
                        logging.info(f"🤖 Bot: {reply}")
                        out_pcm = try_tts_synthesize(tts, reply)
                        if out_pcm:
                            rtp.add_tx_pcm(out_pcm)
            
    except KeyboardInterrupt:
        logging.info('Stopping')
    finally:
        try:
            if ep is not None:
                ep.libDestroy()
        except Exception:
            pass

if __name__ == '__main__':
    orchestrator_loop()
