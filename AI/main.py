"""
SimpleSIP Orchestrator - Pure Python implementation
No PJSIP dependencies - uses SimpleSIP library
"""

import asyncio
import logging
import sys
import os
import socket
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_sip import SipClient

# Try to import adapters
try:
    from AI import stt_adapter
except Exception as e:
    logging.warning(f'STT adapter import failed: {e}')
    stt_adapter = None

try:
    from AI import llm_adapter
except Exception as e:
    logging.warning(f'LLM adapter import failed: {e}')
    llm_adapter = None

try:
    from AI.tts_adapter_simple import SimpleTTSAdapter
    TTS_AVAILABLE = True
except Exception as e:
    logging.warning(f'TTS adapter import failed: {e}')
    TTS_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SIP Configuration
SIP_DOMAIN = os.getenv('SIP_DOMAIN', 'localhost')
SIP_PORT = int(os.getenv('SIP_PORT', '5060'))
SIP_USER = os.getenv('SIP_USER', 'phoneguy')
SIP_PASSWORD = os.getenv('SIP_PASSWORD', 'password')
SIP_SERVER = os.getenv('SIP_SERVER', f'{SIP_DOMAIN}:{SIP_PORT}')
LOCAL_IP = os.getenv('LOCAL_IP', '192.168.1.181')

# TTS Configuration
TTS_ENGINE = os.getenv('TTS_ENGINE', 'turbo')
TTS_DEVICE = os.getenv('TTS_DEVICE', 'cuda')
RVC_ENABLED = os.getenv('RVC_ENABLED', 'false').lower() == 'true'
RVC_MODEL_PATH = os.getenv('RVC_MODEL_PATH', '')
RVC_INDEX_PATH = os.getenv('RVC_INDEX_PATH', '')

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

async def try_transcribe(stt, pcm):
    if not stt: return None
    try:
        return await stt.transcribe_pcm_async(pcm) if hasattr(stt, 'transcribe_pcm_async') else None
    except: return None

async def try_llm_query(llm, text):
    if not llm: return ""
    try:
        return await llm.phoneguy_reply_async(text) if hasattr(llm, 'phoneguy_reply_async') else ""
    except: return ""

async def try_tts_synthesize(tts, text):
    if not tts: return None
    try:
        return await tts.synthesize(text) if hasattr(tts, 'synthesize') else None
    except: return None

async def orchestrator_loop():
    """Main orchestrator loop using SimpleSIP."""
    
    # Initialize SIP client
    client = SipClient(
        user=SIP_USER,
        pwd=SIP_PASSWORD,
        server=SIP_SERVER,
        local_ip=current_ip
    )
    
    await client.start()
    
    # Register
    if await client.register():
        logging.info('✓ Registered successfully!')
    else:
        logging.error('✗ Registration failed!')
        return
    
    # Initialize AI components
    try:
        stt = stt_adapter.STTAdapter(config={}, logger=logger)
    except: stt = None
    
    try:
        llm = llm_adapter
    except: llm = None
    
    # Initialize TTS
    tts = None
    if TTS_AVAILABLE and RVC_ENABLED and RVC_MODEL_PATH:
        try:
            tts = SimpleTTSAdapter(config={
                'tts': {
                    'engine': TTS_ENGINE,
                    'device': TTS_DEVICE,
                    'rvc_enabled': RVC_ENABLED,
                    'rvc_model_path': RVC_MODEL_PATH,
                    'rvc_index_path': RVC_INDEX_PATH,
                    'rvc_f0_method': 'rmvpe',
                    'rvc_pitch_shift': 0,
                    'rvc_index_rate': 0.5
                }
            }, logger=logger)
            logging.info('✓ TTS initialized with RVC!')
        except Exception as e:
            logging.error(f'✗ TTS initialization failed: {e}')
            tts = None
    
    logging.info('🎧 AI components initialized. Waiting for calls...')
    
    # For now, we'll make an outbound call as a test
    # In a real scenario, this would handle incoming calls
    try:
        # Make a test call
        target = os.getenv('TARGET_NUMBER', '1002')
        
        logging.info(f'📞 Calling {target}...')
        call = await client.invite(target)
        
        if call.success:
            logging.info('✓ Call established!')
            
            # Send some test audio
            if tts:
                text = "Hello, this is a test call from the AI phone system."
                logging.info(f'🎤 Speaking: {text}')
                
                pcm_data = await tts.synthesize(text)
                if pcm_data:
                    import audioop
                    pcma_data = audioop.lin2alaw(pcm_data, 2)
                    await call.send_audio(pcma_data)
                    logging.info('✓ Audio sent!')
            else:
                # Send dummy audio
                dummy_audio = b'\xd5' * (8000 * 5)
                await call.send_audio(dummy_audio)
                logging.info('✓ Dummy audio sent!')
            
            # Wait a bit
            await asyncio.sleep(2)
            
            # End call
            await call.bye()
            logging.info('✓ Call ended!')
        else:
            logging.error('✗ Call failed to establish!')
        
    except KeyboardInterrupt:
        logging.info('Stopping')
    except Exception as e:
        logging.error(f'Error: {e}', exc_info=True)
    finally:
        await client.stop()
        logging.info('✓ Done!')

if __name__ == '__main__':
    asyncio.run(orchestrator_loop())
