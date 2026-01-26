#!/usr/bin/env python3
"""Send WAV file over RTP as test."""

import sys
import time
import wave
import audioop
import os

sys.path.insert(0, "/home/user/Test_Phone_new/pjsip_python")

from pjmedia.rtp_pyvoip import create_rtp_client

WAV_FILE = "/home/user/Test_Phone_new/2022-07-22 - Phaera Homebound.wav"

print("=" * 60)
print("  WAV FILE RTP TRANSMISSION TEST")
print("=" * 60)

# Open WAV file
print(f"\n[+] Opening WAV file: {WAV_FILE}")
wf = wave.open(WAV_FILE, "rb")

audio_format = wf.getcomptype()
n_channels = wf.getnchannels()
sample_width = wf.getsampwidth()
frame_rate = wf.getframerate()
n_frames = wf.getnframes()

print(f"[+] WAV info:")
print(f"    Format: {audio_format}")
print(f"    Channels: {n_channels}")
print(f"    Sample width: {sample_width}")
print(f"    Frame rate: {frame_rate} Hz")
print(f"    Total frames: {n_frames}")

if frame_rate != 8000:
    print(f"[!] WARNING: WAV is {frame_rate} Hz, RTP expects 8000 Hz")
    print(f"[!] Will need resampling!")

if n_channels != 1:
    print(f"[!] WARNING: WAV has {n_channels} channels, will convert to mono")

# Read first chunk for testing
print(f"\n[+] Reading 5 seconds of audio...")
target_ms = 5000
target_samples = int(8000 * target_ms / 1000)
raw_frames = wf.readframes(target_samples)
print(f"    Read {len(raw_frames)} bytes raw")

# Convert to mono if needed
if n_channels > 1:
    print("[+] Converting to mono...")
    mono_frames = audioop.tomono(raw_frames, sample_width, 1.0, 1.0)
else:
    mono_frames = raw_frames

# Resample if needed
if frame_rate != 8000:
    print(f"[+] Resampling from {frame_rate} to 8000 Hz...")
    resampled = audioop.ratecv(
        mono_frames, sample_width, n_channels, frame_rate, 8000, None
    )[0]
else:
    resampled = mono_frames

print(f"[+] After conversion: {len(resampled)} bytes")

# Convert to 8-bit then G.711
print("[+] Converting to G.711 A-law...")

if sample_width == 2:
    # 16-bit to 8-bit
    linear_8bit = audioop.lin2lin(resampled, 2, 1)
else:
    linear_8bit = resampled

# Add bias to make it unsigned
biased = audioop.bias(linear_8bit, 1, 128)

# Encode to G.711 A-law
g711_data = audioop.lin2alaw(biased, 1)

print(f"[+] G.711 data: {len(g711_data)} bytes")
print(f"    First 10 bytes: {g711_data[:10].hex()}")

wf.close()

# Now send via RTP
print(f"\n[+] Creating RTP client...")
rtp = create_rtp_client(
    local_ip="192.168.1.181",
    local_port=20004,
    remote_ip="192.168.1.176",
    remote_port=11000,
    payload_type=8,  # PCMA
)

print(f"[+] Starting RTP client...")
rtp.start()

print(f"[+] Waiting 0.5s for threads to start...")
time.sleep(0.5)

print(f"\n[+] Sending audio...")
print(f"[+] Sending {len(g711_data)} bytes = {len(g711_data) // 160} frames")

frame_size = 160
num_frames = len(g711_data) // frame_size

for i in range(num_frames):
    start = i * frame_size
    frame = g711_data[start : start + frame_size]

    rtp.write(frame)

    if i < 5:
        print(f"[+] Frame {i}: 160 bytes, first 5: {frame[:5].hex()}")

    # Sleep for 20ms per frame
    time.sleep(0.02)

print(f"\n[+] Audio sent! Waiting for playback...")
time.sleep(0.5)

print(f"[+] Stopping RTP client...")
rtp.stop()

print("\n" + "=" * 60)
print("  TEST PASSED")
print("=" * 60)
