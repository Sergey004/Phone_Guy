#!/usr/bin/env python3
"""Simple RTP test."""

import sys
import os
os.environ['PYTHONUNBUFFERED'] = '1'

sys.path.insert(0, '/home/user/Test_Phone_new/pjsip_python')

from pjmedia.rtp_pyvoip import RTPClient

def test_rtp():
    print("[TEST] Creating RTP client...")
    
    client = RTPClient(
        local_ip='192.168.1.181',
        local_port=12000,
        remote_ip='192.168.1.176',
        remote_port=12000,
        payload_type=8
    )
    
    print("[TEST] Starting RTP client...")
    client.start()
    print(f"[TEST] Running: {client._running}")
    print(f"[TEST] Local: {client.local_addr}")
    print(f"[TEST] Remote: {client.remote_addr}")
    print(f"[TEST] Socket: {client._socket}")
    
    print("[TEST] Writing test data...")
    import audioop
    
    # Create simple sine wave-like 8-bit PCM
    import numpy as np
    freq = 440
    duration = 0.5
    sample_rate = 8000
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * freq * t) * 127
    
    # Convert to 8-bit PCM with bias
    pcm16 = (audio * 256).astype(np.int16).tobytes()
    bias_16 = audioop.bias(pcm16, 2, -32768)
    pcm_8bit = audioop.lin2lin(bias_16, 2, 1)
    
    print(f"[TEST] PCM16: {len(pcm16)} bytes, PCM8: {len(pcm_8bit)} bytes")
    print(f"[TEST] First 5 bytes PCM8: {pcm_8bit[:5].hex()}")
    
    # Write data in 160-byte chunks
    for i in range(0, len(pcm_8bit), 160):
        chunk = pcm_8bit[i:i+160]
        if len(chunk) < 160:
            chunk = chunk + b'\x00' * (160 - len(chunk))
        if (i // 160) < 5:
            print(f"[TEST] Writing chunk {i//160}: {len(chunk)} bytes, first 5: {chunk[:5].hex()}")
        client.write(chunk)
    
    print("[TEST] Waiting 1 second...")
    import time
    time.sleep(1)
    
    print("[TEST] Stopping RTP client...")
    client.stop()
    print("[TEST] Done!")

if __name__ == '__main__':
    test_rtp()
