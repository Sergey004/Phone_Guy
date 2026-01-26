#!/usr/bin/env python3
"""Test media stream creation and remote address setting."""

import sys
import time

sys.path.insert(0, "/home/user/Test_Phone_new/pjsip_python")

from pjmedia.stream_pyvoip import MediaStream, MediaStreamConfig

print("Creating MediaStream with dummy remote address...")
config = MediaStreamConfig(
    local_ip="192.168.1.181",
    local_port=20000,
    remote_ip="0.0.0.0",
    remote_port=0,
    payload_type=8,
)

media = MediaStream(config)

print(f"Media stream created")
print(f"  Local addr: {media.local_addr}")
print(f"  Remote addr: {media.remote_addr}")

print("\nStarting media stream...")
media.start()

print(f"After start:")
print(f"  Local addr: {media.local_addr}")
print(f"  Remote addr: {media.remote_addr}")

rtp = media.rtp_client
if rtp:
    print(f"\nRTP client properties:")
    print(f"  inIP/port: {rtp.inIP}:{rtp.inPort}")
    print(f"  outIP/port: {rtp.outIP}:{rtp.outPort}")
    print(f"  sin/sout: {rtp.sin}, {rtp.sout}")
else:
    print(f"No RTP client!")

print("\nSetting remote to real address...")
media.set_remote(("192.168.1.176", 18880))

print(f"After set_remote:")
print(f"  Media stream remote: {media.remote_addr}")
if rtp:
    print(f"  RTP client outIP/port: {rtp.outIP}:{rtp.outPort}")

print("\nWriting test data...")
test_data = b"\x80" * 160
media.send_g711(test_data)

print("Waiting 2 seconds...")
time.sleep(2)

print("\nStopping media stream...")
media.stop()

print("Test completed!")
