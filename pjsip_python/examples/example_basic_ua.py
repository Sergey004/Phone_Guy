#!/usr/bin/env python3
"""
Example: Basic SIP User Agent with pjsip_python

This example demonstrates how to use the pjsip_python stack for:
1. Creating a User Agent
2. Registering with a SIP server
3. Making outgoing calls
4. Handling incoming calls
5. Sending/receiving audio (G.711)

Usage:
    python3 example_basic_ua.py --id sip:1001@192.168.1.5 \
        --reg-server sip:192.168.1.5:5060 \
        --username 1001 --password password

Requirements:
    - A SIP server (Asterisk, FreeSWITCH, etc.)
    - numpy and scipy for audio processing
"""

import asyncio
import argparse
import logging
import numpy as np
import sys
sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python import (
    Ua, UaConfig, UaState,
    Account, AccountConfig, RegState,
    Call, CallState, CallInfo,
    G711Codec, RtpSession,
    numpy_to_g711, resample_audio
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)


class SimpleUa:
    """Simple SIP User Agent for demonstration."""
    
    def __init__(self, config: dict):
        self.config = config
        self.ua: Ua = None
        self.account: Account = None
        self.active_call: Call = None
        self.codec = G711Codec(a_law=True)
        
    async def create(self):
        """Create and configure the UA."""
        logger.info("Creating User Agent...")
        
        ua_config = UaConfig(
            local_ip=self.config['local_ip'],
            local_port=self.config.get('local_port', 5060),
            user_agent="pjsip_python/1.0"
        )
        
        self.ua = await Ua.create(ua_config)
        logger.info(f"UA created with local address: {self.ua.local_ip}:{self.ua.local_port}")
        
    async def register(self):
        """Register with SIP server."""
        if not self.config.get('reg_server'):
            logger.info("No registration server configured, skipping registration")
            return
        
        logger.info(f"Registering with {self.config['reg_server']}...")
        
        acc_config = AccountConfig(
            id=self.config['id'],
            reg_uri=self.config['reg_server'],
            username=self.config.get('username'),
            password=self.config.get('password'),
            realm=self.config.get('realm', '*')
        )
        
        self.account = await self.ua.create_account(acc_config)
        
        if self.account.register():
            logger.info("Registration successful!")
        else:
            logger.error("Registration failed!")
            
    async def make_call(self, target_uri: str):
        """Make an outgoing call."""
        logger.info(f"Calling {target_uri}...")
        
        self.active_call = await self.ua.call(target_uri)
        logger.info(f"Call state: {self.active_call.state}")
        
        await self.wait_for_call_state(CallState.CONFIRMED)
        logger.info("Call connected!")
        
        return self.active_call
        
    async def wait_for_call_state(self, target_state: CallState, timeout: float = 30.0):
        """Wait for call to reach a specific state."""
        import time
        start = time.time()
        while self.active_call and self.active_call.state != target_state:
            if time.time() - start > timeout:
                raise TimeoutError(f"Call did not reach state {target_state} within {timeout}s")
            await asyncio.sleep(0.1)
            
    async def handle_incoming_call(self):
        """Handle incoming calls (demo - would need async callback)."""
        logger.info("Waiting for incoming calls...")
        # In a real app, you'd set up a callback via ua.set_on_incoming_call()
        
    async def send_audio(self, audio_data: bytes):
        """Send audio data to the remote party."""
        if not self.active_call:
            logger.warning("No active call to send audio")
            return
            
        # Encode to G.711
        g711_data = self.codec.encode(audio_data)
        
        # Send via media stream (implementation depends on stream API)
        logger.debug(f"Sent {len(g711_data)} bytes of G.711 audio")
        
    async def hangup(self):
        """Hang up the current call."""
        if self.active_call:
            logger.info("Hanging up call...")
            await self.active_call.hangup()
            self.active_call = None
            
    async def unregister(self):
        """Unregister from SIP server."""
        if self.account:
            logger.info("Unregistering...")
            self.account.unregister()
            
    async def destroy(self):
        """Destroy the UA."""
        if self.ua:
            logger.info("Destroying UA...")
            await self.ua.destroy()
            self.ua = None


async def run_demo():
    """Run the demo with sample audio."""
    config = {
        'local_ip': '192.168.1.181',
        'local_port': 5060,
        'id': 'sip:1001@192.168.1.181',
        'reg_server': 'sip:192.168.1.5:5060',
        'username': '1001',
        'password': 'password'
    }
    
    ua = SimpleUa(config)
    
    try:
        await ua.create()
        await ua.register()
        
        # Wait a bit for registration
        await asyncio.sleep(2)
        
        # Demo: Create some sample audio and send
        sample_rate = 8000
        duration = 0.5  # 500ms
        num_samples = int(sample_rate * duration)
        t = np.linspace(0, duration, num_samples, dtype=np.float32)
        audio_tone = (np.sin(2 * np.pi * 440 * t) * 32767 * 0.5).astype(np.int16)
        audio_bytes = audio_tone.tobytes()
        
        logger.info(f"Generated {len(audio_bytes)} bytes of test audio")
        
        # Optionally make a test call (requires SIP server)
        # await ua.make_call('sip:1002@192.168.1.5')
        # await asyncio.sleep(5)
        # await ua.send_audio(audio_bytes)
        
    except Exception as e:
        logger.error(f"Demo error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await ua.unregister()
        await ua.destroy()


def main():
    parser = argparse.ArgumentParser(description='pjsip_python Basic UA Demo')
    parser.add_argument('--id', help='SIP URI (e.g., sip:1001@192.168.1.5)')
    parser.add_argument('--reg-server', dest='reg_server', help='Registration server URI')
    parser.add_argument('--username', help='SIP username')
    parser.add_argument('--password', help='SIP password')
    parser.add_argument('--local-ip', dest='local_ip', default='127.0.0.1', help='Local IP address')
    parser.add_argument('--local-port', dest='local_port', type=int, default=5060, help='Local SIP port')
    parser.add_argument('--call', help='Make outgoing call to this URI')
    parser.add_argument('--demo', action='store_true', help='Run demo mode')
    
    args = parser.parse_args()
    
    if args.demo:
        asyncio.run(run_demo())
        return
        
    if not args.id:
        parser.print_help()
        print("\nRunning demo mode with default configuration...")
        asyncio.run(run_demo())
        return
        
    config = {
        'local_ip': args.local_ip,
        'local_port': args.local_port,
        'id': args.id,
        'reg_server': args.reg_server,
        'username': args.username,
        'password': args.password
    }
    
    async def run():
        ua = SimpleUa(config)
        try:
            await ua.create()
            await ua.register()
            
            if args.call:
                await ua.make_call(args.call)
                await asyncio.sleep(5)
                await ua.hangup()
            else:
                logger.info("Registered. Press Ctrl+C to exit...")
                while True:
                    await asyncio.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            await ua.unregister()
            await ua.destroy()
            
    asyncio.run(run())


if __name__ == "__main__":
    main()
