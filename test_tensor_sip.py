"""
Test script for SimpleSIP with Tensor TTS integration
Tests SIP registration, call establishment, and audio streaming with RVC
"""

import asyncio
import audioop
import logging
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simple_sip import SipClient

# Try to import TTSAdapter, but continue if not available
try:
    from AI.tts_adapter import TTSAdapter
    TTS_AVAILABLE = True
except ImportError as e:
    print(f"Warning: TTSAdapter not available ({e})")
    print("Will use dummy audio instead")
    TTS_AVAILABLE = False
    TTSAdapter = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_local_ip():
    """Get local IP address."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


async def main():
    """Main test function."""
    
    # Configuration from .env
    SIP_USER = os.getenv('SIP_USER', '1001')
    SIP_PASSWORD = os.getenv('SIP_PASSWORD', 'password')
    SIP_SERVER = os.getenv('SIP_SERVER', '192.168.1.5')
    TARGET_NUMBER = os.getenv('TARGET_NUMBER', '1002')
    LOCAL_IP = os.getenv('LOCAL_IP', get_local_ip())
    
    # TTS Configuration with RVC
    TTS_ENGINE = os.getenv('TTS_ENGINE', 'turbo')
    TTS_DEVICE = os.getenv('TTS_DEVICE', 'cuda')
    RVC_ENABLED = os.getenv('RVC_ENABLED', 'false').lower() == 'true'
    RVC_MODEL_PATH = os.getenv('RVC_MODEL_PATH', '')
    RVC_INDEX_PATH = os.getenv('RVC_INDEX_PATH', '')
    
    print("=" * 60)
    print("SimpleSIP + Tensor TTS Test")
    print("=" * 60)
    print(f"SIP User: {SIP_USER}")
    print(f"SIP Server: {SIP_SERVER}")
    print(f"Local IP: {LOCAL_IP}")
    print(f"Target: {TARGET_NUMBER}")
    print(f"TTS Engine: {TTS_ENGINE}")
    print(f"RVC Enabled: {RVC_ENABLED}")
    print("=" * 60)
    
    # Initialize SIP client
    client = SipClient(
        user=SIP_USER,
        pwd=SIP_PASSWORD,
        server=SIP_SERVER,
        local_ip=LOCAL_IP
    )
    
    # Initialize TTS with RVC if enabled
    tts_config = {
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
    }
    
    tts = None
    if RVC_ENABLED and RVC_MODEL_PATH:
        print("\nInitializing TTS with RVC...")
        try:
            tts = TTSAdapter(config=tts_config, logger=logger)
            print("TTS initialized successfully!")
        except Exception as e:
            print(f"Failed to initialize TTS: {e}")
            print("Continuing without TTS...")
    
    try:
        # Start SIP transport
        print("\n[1] Starting SIP client...")
        await client.start()
        
        # Register
        print("\n[2] Registering...")
        if await client.register():
            print("✓ Registration successful!")
        else:
            print("✗ Registration failed!")
            return
        
        # Make a call
        print(f"\n[3] Calling {TARGET_NUMBER}...")
        call = await client.invite(TARGET_NUMBER)
        
        if call.success:
            print("✓ Call established!")
            
            # Test audio streaming
            print("\n[4] Streaming audio...")
            
            if tts:
                # Generate audio using TTS (English text as requested)
                text = "Hello, this is a test call from the AI phone system with RVC voice conversion."
                print(f"TTS Text: {text}")
                
                # Synthesize audio (PCM int16, 8000 Hz)
                print("Synthesizing speech...")
                pcm_data = tts.synthesize_sync(text)
                
                if pcm_data:
                    print(f"✓ Generated {len(pcm_data)} bytes of PCM audio")
                    
                    # Convert PCM to PCMA (A-law)
                    print("Converting PCM to PCMA...")
                    pcma_data = audioop.lin2alaw(pcm_data, 2)
                    print(f"✓ Converted to {len(pcma_data)} bytes of PCMA audio")
                    
                    # Send via RTP
                    print("Sending audio via RTP...")
                    await call.send_audio(pcma_data)
                    print("✓ Audio sent successfully!")
                else:
                    print("✗ TTS generated no audio")
            else:
                # Generate dummy audio (silence)
                print("Generating dummy audio (silence)...")
                # 5 seconds of silence at 8000 Hz = 40000 bytes
                dummy_audio = b'\xd5' * (8000 * 5)
                print(f"✓ Generated {len(dummy_audio)} bytes of dummy audio")
                
                # Send via RTP
                print("Sending audio via RTP...")
                await call.send_audio(dummy_audio)
                print("✓ Audio sent successfully!")
            
            # Wait a bit
            print("\n[5] Waiting 2 seconds before hanging up...")
            await asyncio.sleep(2)
            
            # End call
            print("\n[6] Ending call...")
            await call.bye()
            print("✓ Call ended!")
        else:
            print("✗ Call failed to establish!")
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Stop SIP client
        print("\n[7] Stopping SIP client...")
        await client.stop()
        print("✓ Done!")


if __name__ == "__main__":
    asyncio.run(main())
