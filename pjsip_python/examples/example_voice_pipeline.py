#!/usr/bin/env python3
"""
Example: Complete SIP Call with TTS and RVC

This example demonstrates a complete voice call pipeline:
1. Text-to-Speech (TTS) generates audio
2. RVC model processes the voice
3. Convert to G.711 for SIP
4. Send via RTP over SIP call
"""

import asyncio
import numpy as np
import sys
sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python import (
    Ua, UaConfig, Account, AccountConfig,
    Call, CallState, CallInfo
)
from pjsip_python.audio import (
    AudioData, AudioFormat,
    numpy_to_audio, tensor_to_audio, audio_to_tensor,
    create_silence, create_tone, write_wav
)
from pjsip_python.pjmedia.rtp import RtpSession


class VoiceCallPipeline:
    """
    Complete voice call pipeline: TTS -> RVC -> SIP/RTP
    """
    
    def __init__(self):
        self.ua: Ua = None
        self.account: Account = None
        self.rtp = RtpSession(ssrc=0x12345678, payload_type=8)
        self.rtp.set_clock_rate(8000)
        self.codec = None  # Will be set based on negotiated codec
    
    async def create_ua(self, local_ip: str, local_port: int):
        """Create and initialize the User Agent."""
        config = UaConfig(
            local_ip=local_ip,
            local_port=local_port,
            user_agent="TTS-RVC-Pipeline/1.0"
        )
        self.ua = await Ua.create(config)
        print(f"UA created: {local_ip}:{local_port}")
    
    async def register(self, id_uri: str, reg_server: str, username: str, password: str):
        """Register with SIP server."""
        acc_config = AccountConfig(
            id=id_uri,
            reg_uri=reg_server,
            username=username,
            password=password,
            realm='*'
        )
        self.account = await self.ua.create_account(acc_config)
        if self.account.register():
            print(f"Registered: {id_uri}")
            return True
        print(f"Registration failed: {id_uri}")
        return False
    
    def simulate_tts(self, text: str) -> AudioData:
        """
        Simulate TTS output.
        
        In real implementation, use:
        - gTTS (Google TTS)
        - Silero TTS
        - Coqui TTS
        - ElevenLabs API
        """
        print(f"TTS: '{text[:50]}...'")
        
        # Simulate TTS output as a 440Hz tone
        duration = len(text) * 0.1  # ~100ms per character
        audio = create_tone(440, min(duration, 5.0))
        
        return audio
    
    def simulate_rvc(self, audio: AudioData) -> AudioData:
        """
        Simulate RVC voice conversion.
        
        In real implementation:
        - Load RVC model
        - Extract pitch with RMVPE/DIO
        - Convert voice
        - Return converted audio
        """
        # Simulate RVC by adding a slight pitch shift (2 semitones = ~12% speed change)
        import numpy as np
        
        numpy_audio = audio.to_numpy().astype(np.float32) / 32767.0
        
        # Simulated RVC: just adjust amplitude to show processing
        processed = numpy_audio * 1.0  # Placeholder for real RVC
        
        processed = (processed * 32767).astype(np.int16)
        
        return AudioData(processed, audio.sample_rate, audio.channels, audio.format)
    
    def audio_to_g711(self, audio: AudioData, a_law: bool = True) -> bytes:
        """Convert audio to G.711 bytes."""
        return audio.to_bytes(AudioFormat.G711_ALAW if a_law else AudioFormat.G711_ULAW)
    
    def create_rtp_packet(self, g711_data: bytes, timestamp: int = 0) -> bytes:
        """Create RTP packet with G.711 payload."""
        return self.rtp.encode_rtp(g711_data, timestamp=timestamp)
    
    async def make_call(self, target_uri: str, text: str) -> bool:
        """
        Make a call and play TTS message.
        
        Args:
            target_uri: Target SIP URI (e.g., "sip:1002@192.168.1.5")
            text: Text to convert to speech and play
            
        Returns:
            True if call was successful
        """
        print(f"\n=== Making call to {target_uri} ===")
        
        # Create call
        call = await self.ua.call(target_uri)
        
        # Wait for connection (with timeout)
        for i in range(100):  # 10 seconds max
            if call.state == CallState.CONFIRMED:
                break
            await asyncio.sleep(0.1)
        
        if call.state != CallState.CONFIRMED:
            print(f"Call failed to connect: {call.state}")
            await call.hangup()
            return False
        
        print("Call connected!")
        
        # Process TTS -> RVC
        tts_audio = self.simulate_tts(text)
        rvc_audio = self.simulate_rvc(tts_audio)
        
        # Convert to G.711 and send
        g711_data = self.audio_to_g711(rvc_audio)
        
        print(f"Sending {len(g711_data)} bytes of G.711 audio...")
        
        # Send in 20ms chunks (160 bytes at 8kHz)
        chunk_size = 160
        timestamp = 0
        
        for i in range(0, len(g711_data), chunk_size):
            chunk = g711_data[i:i + chunk_size]
            if len(chunk) < chunk_size:
                # Pad with silence for last chunk
                chunk = chunk + b'\xD5' * (chunk_size - len(chunk))
            
            # Create and send RTP packet
            rtp_packet = self.create_rtp_packet(chunk, timestamp)
            
            # In real implementation, send over network
            # socket.sendto(rtp_packet, (remote_addr, remote_port))
            
            timestamp += chunk_size
            await asyncio.sleep(0.02)  # 20ms between chunks
        
        print("Audio sent!")
        
        # Wait a bit then hang up
        await asyncio.sleep(1)
        
        await call.hangup()
        print("Call ended")
        
        return True
    
    async def handle_incoming_call(self, text: str):
        """Handle incoming call by playing TTS message."""
        # This would be called from the incoming call callback
        print(f"\n=== Handling incoming call ===")
        print(f"Would play: '{text[:50]}...'")
        
    async def destroy(self):
        """Cleanup resources."""
        if self.ua:
            await self.ua.destroy()
        print("Pipeline destroyed")


async def demo():
    """Demonstrate the voice call pipeline."""
    print("=" * 60)
    print("Voice Call Pipeline Demo")
    print("TTS -> RVC -> G.711 -> SIP/RTP")
    print("=" * 60)
    
    pipeline = VoiceCallPipeline()
    
    try:
        # Create UA (use port 0 for auto-assign)
        await pipeline.create_ua("192.168.1.181", 5063)
        
        # Optional: Register with SIP server
        # await pipeline.register(
        #     id_uri="sip:pipeline@192.168.1.181",
        #     reg_server="sip:192.168.1.5:5060",
        #     username="pipeline",
        #     password="password"
        # )
        # await asyncio.sleep(2)
        
        # Make a test call (requires running SIP server)
        # await pipeline.make_call(
        #     target_uri="sip:1002@192.168.1.5",
        #     text="Hello, this is a test call from the TTS-RVC pipeline demo."
        # )
        
        # Demo offline (no actual call)
        print("\n=== Offline Demo ===")
        
        text = "Hello, this is a test call from the TTS-RVC pipeline demo."
        
        # TTS
        tts_audio = pipeline.simulate_tts(text)
        print(f"TTS audio: {tts_audio.num_samples} samples, {tts_audio.duration:.2f}s")
        
        # RVC
        rvc_audio = pipeline.simulate_rvc(tts_audio)
        print(f"RVC audio: {rvc_audio.num_samples} samples")
        
        # G.711
        g711_data = pipeline.audio_to_g711(rvc_audio)
        print(f"G.711: {len(g711_data)} bytes")
        
        # RTP
        rtp_packet = pipeline.create_rtp_packet(g711_data[:160])
        print(f"RTP packet: {len(rtp_packet)} bytes (12 header + 160 payload)")
        
        print("\n=== Demo Complete ===")
        
    finally:
        await pipeline.destroy()


if __name__ == "__main__":
    asyncio.run(demo())
