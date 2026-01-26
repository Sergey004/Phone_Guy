#!/usr/bin/env python3
"""Quick test that the new RTP client can start."""

import sys
import time

sys.path.insert(0, "/home/user/Test_Phone_new/pjsip_python")

from pjmedia.rtp_pyvoip import RTPClient, create_rtp_client

print("Creating RTP client...")
rtp = RTPClient(
    inIP="192.168.1.181",
    inPort=4000,
    outIP="192.168.1.176",
    outPort=5000,
    payload_type=8,  # PCMA
)

print("Starting RTP client...")
rtp.start()

print("Writing some test data...")
test_data = b"\x80" * 160  # 160 bytes of silence (biased PCM)
rtp.write(test_data)

print("Waiting 2 seconds...")
time.sleep(2)

print("Stopping RTP client...")
rtp.stop()

print("Test completed successfully!")
