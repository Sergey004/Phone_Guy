#!/usr/bin/env python3
"""Direct test of the pyVoIP-based RTP client."""

import sys

sys.path.insert(0, "/home/user/Test_Phone_new/pjsip_python")

from pjmedia.rtp_pyvoip import RTPClient, create_rtp_client
import time
import math

print("=" * 60)
print("  DIRECT RTP CLIENT TEST")
print("=" * 60)

print("\n[+] Creating RTP client...")
# Simulate what MediaStream does
rtp = create_rtp_client(
    local_ip="192.168.1.181",
    local_port=20001,
    remote_ip="192.168.1.176",
    remote_port=11000,
    payload_type=8,  # PCMA
)

print(f"[+] RTP client created:")
print(f"    inIP/port: {rtp.inIP}:{rtp.inPort}")
print(f"    outIP/port: {rtp.outIP}:{rtp.outPort}")
print(f"    preference: {rtp.preference}")

print("\n[+] Starting RTP client...")
rtp.start()

print(f"[+] Sleeping 0.3s for threads to start...")
time.sleep(0.3)

print("\n[+] Writing test audio data...")

# Create 160 bytes of 8-bit biased PCM sine tone
for i in range(10):
    tone_pcm = bytearray()
    for j in range(160):
        sample = int(math.sin(2 * math.pi * 440 * j / 8000) * 127 * 0.3)
        tone_pcm.append(sample + 128)

    print(f"[+] Writing frame {i}: {len(tone_pcm)} bytes")
    rtp.write(bytes(tone_pcm))
    time.sleep(0.02)

print("\n[+] Sleeping 2s to let audio transmit...")
time.sleep(2)

print("\n[+] Stopping RTP client...")
rtp.stop()

print("\n" + "=" * 60)
print("  TEST PASSED")
print("=" * 60)
