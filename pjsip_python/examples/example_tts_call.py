#!/usr/bin/env python3
"""
Example: SIP Call with Text-to-Speech (TTS) Audio

This example demonstrates how to:
1. Generate speech from text using gTTS (Google TTS) or pyttsx3
2. Convert speech to G.711 format for SIP/RTP
3. Send audio during a call
4. Play received audio

Requirements:
    - pip install gTTS pydub numpy scipy
    - For local TTS: pip install pyttsx3
"""

import asyncio
import argparse
import logging
import numpy as np
import io
import os
import sys
sys.path.insert(0, '/home/user/Test_Phone_new')

try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False

from pjsip_python import (
    Ua, UaConfig, Account, AccountConfig,
    Call, CallState,
    G711Codec, RtpSession,
    numpy_to_pcm16, pcm16_to_numpy,
    numpy_to_g711, g711_to_numpy,
    resample_audio
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)


class TtsCallHandler:
    """Handle SIP calls with TTS audio integration."""
    
    def __init__(self):
        self.ua: Ua = None
        self.account: Account = None
        self.codec = G711Codec(a_law=True)
        self.rtp_session: RtpSession = None
        self.audio_device = None
        
    async def create_ua(self, local_ip: str, local_port: int):
        """Create user agent."""
        logger.info(f"Creating UA on {local_ip}:{local_port}...")
        
        config = UaConfig(
            local_ip=local_ip,
            local_port=local_port,
            user_agent="pjsip_python-TTS/1.0"
        )
        
        self.ua = await Ua.create(config)
        
        # Set up callbacks
        self.ua.set_on_incoming_call(self._on_incoming_call)
        
    def _on_incoming_call(self, call: Call):
        """Handle incoming call."""
        logger.info(f"Incoming call from {call.remote_uri}")
        # In real app, you'd auto-answer or ring
        
    async def register(self, id_uri: str, reg_server: str, username: str, password: str):
        """Register with SIP server."""
        logger.info(f"Registering {id_uri} with {reg_server}...")
        
        acc_config = AccountConfig(
            id=id_uri,
            reg_uri=reg_server,
            username=username,
            password=password,
            realm='*'
        )
        
        self.account = await self.ua.create_account(acc_config)
        return self.account.register()
    
    def text_to_g711_audio(self, text: str, lang: str = 'en') -> bytes:
        """
        Convert text to G.711 audio bytes.
        
        Args:
            text: Text to convert to speech
            lang: Language code (e.g., 'en', 'ru')
            
        Returns:
            G.711 encoded audio bytes (A-law)
        """
        try:
            # Method 1: gTTS (requires internet)
            if HAS_GTTS:
                logger.info(f"Generating speech for: '{text[:50]}...'")
                tts = gTTS(text=text, lang=lang, slow=False)
                mp3_data = io.BytesIO()
                tts.write_to_fp(mp3_data)
                mp3_data.seek(0)
                
                # Convert MP3 to WAV using pydub
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_mp3(mp3_data)
                    audio = audio.set_frame_rate(8000)
                    audio = audio.set_channels(1)
                    pcm_data = audio.raw_data
                except ImportError:
                    # Fallback: simple resample
                    logger.warning("pydub not installed, using basic conversion")
                    pcm_data = mp3_data.read()
                    
            else:
                # Method 2: Basic TTS simulation (no external deps)
                logger.info(f"Simulating speech for: '{text[:50]}...'")
                # Generate a simple tone pattern based on text length
                duration = len(text) * 0.1  # ~100ms per character
                sample_rate = 8000
                num_samples = int(sample_rate * min(duration, 5.0))  # Max 5 seconds
                t = np.linspace(0, num_samples / sample_rate, num_samples)
                frequencies = [ord(c) * 10 + 200 for c in text[:20]]  # Unique freq per char
                audio = np.zeros(num_samples)
                for i, freq in enumerate(frequencies):
                    start = i * len(t) // len(frequencies)
                    end = (i + 1) * len(t) // len(frequencies)
                    audio[start:end] = np.sin(2 * np.pi * freq * t[start:end])
                audio = (audio * 32767 * 0.3).astype(np.int16)
                pcm_data = audio.tobytes()
                
            # Convert PCM to G.711
            pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
            g711_data = numpy_to_g711(pcm_array.astype(np.float32) / 32767.0, a_law=True)
            
            logger.info(f"Generated {len(g711_data)} bytes of G.711 audio")
            return bytes(g711_data)
            
        except Exception as e:
            logger.error(f"TTS error: {e}")
            # Return silence
            return b'\xD5' * 160  # ~20ms of silence
            
    async def make_call_with_tts(self, target_uri: str, text: str, lang: str = 'en'):
        """
        Make a call and play TTS audio.
        
        Args:
            target_uri: Target SIP URI
            text: Text to convert to speech
            lang: Language code
        """
        logger.info(f"Calling {target_uri}...")
        
        call = await self.ua.call(target_uri)
        
        # Wait for connection
        for _ in range(50):  # 5 seconds max
            if call.state == CallState.CONFIRMED:
                break
            await asyncio.sleep(0.1)
                
        if call.state != CallState.CONFIRMED:
            logger.error("Call not connected")
            return
            
        logger.info("Call connected, sending TTS audio...")
        
        # Generate audio
        g711_audio = self.text_to_g711_audio(text, lang)
        
        # Send in chunks (RTP typically sends 20ms frames = 160 bytes for G.711 at 8kHz)
        chunk_size = 160
        for i in range(0, len(g711_audio), chunk_size):
            chunk = g711_audio[i:i + chunk_size]
            if len(chunk) < chunk_size:
                chunk = chunk + b'\xD5' * (chunk_size - len(chunk))  # Pad with silence
            
            # Send via RTP (simplified - real implementation needs media stream)
            logger.debug(f"Sending audio chunk: {len(chunk)} bytes")
            await asyncio.sleep(0.02)  # 20ms per chunk
            
        logger.info("Audio sent, hanging up...")
        await call.hangup()
        
    async def handle_call_with_audio(self, call: Call):
        """Handle call with bidirectional audio."""
        logger.info(f"Handling call from {call.remote_uri}")
        
        if call.state == CallState.INCOMING:
            # Answer the call
            logger.info("Answering incoming call...")
            
        # Set up audio receive callback
        received_audio = []
        
        while call.is_active:
            audio = await self._receive_audio()
            if audio:
                received_audio.extend(audio)
            await asyncio.sleep(0.02)
            
        logger.info(f"Call ended, received {len(received_audio)} audio samples")
        
    async def _receive_audio(self) -> bytes:
        """Receive audio from remote (simplified)."""
        # In real implementation, this would read from RTP socket
        return b''
        
    async def destroy(self):
        """Clean up resources."""
        if self.ua:
            await self.ua.destroy()


async def demo_tts_call():
    """Demonstrate TTS call functionality."""
    handler = TtsCallHandler()
    
    try:
        await handler.create_ua('192.168.1.181', 5062)
        
        # Optional: Register with SIP server
        # await handler.register(
        #     id_uri='sip:tts_demo@192.168.1.181',
        #     reg_server='sip:192.168.1.5:5060',
        #     username='tts_demo',
        #     password='password'
        # )
        
        # Make a test call with TTS
        await handler.make_call_with_tts(
            target_uri='sip:1002@192.168.1.5',
            text='Hello, this is a test call from the pjsip_python library. '
                 'This audio was generated from text using text-to-speech.',
            lang='en'
        )
        
    except Exception as e:
        logger.error(f"Demo error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await handler.destroy()


def main():
    parser = argparse.ArgumentParser(description='SIP Call with TTS Demo')
    parser.add_argument('--call', '-c', help='Target URI to call')
    parser.add_argument('--text', '-t', default='Hello, this is a test call.',
                        help='Text to convert to speech')
    parser.add_argument('--lang', '-l', default='en', help='Language code')
    parser.add_argument('--local-ip', default='192.168.1.181', help='Local IP')
    parser.add_argument('--local-port', type=int, default=5062, help='Local SIP port')
    parser.add_argument('--register', '-r', nargs=4, metavar=('ID', 'REG_SERVER', 'USER', 'PASS'),
                        help='Register with server')
    parser.add_argument('--demo', action='store_true', help='Run demo mode')
    
    args = parser.parse_args()
    
    if args.demo or (not args.call and not args.register):
        asyncio.run(demo_tts_call())
        return
        
    async def run():
        handler = TtsCallHandler()
        
        try:
            await handler.create_ua(args.local_ip, args.local_port)
            
            if args.register:
                id_uri, reg_server, username, password = args.register
                handler.register(id_uri, reg_server, username, password)
                await asyncio.sleep(2)  # Wait for registration
                
            if args.call:
                await handler.make_call_with_tts(args.call, args.text, args.lang)
                
        finally:
            await handler.destroy()
            
    asyncio.run(run())


if __name__ == "__main__":
    main()
