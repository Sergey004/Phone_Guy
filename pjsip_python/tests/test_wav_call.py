#!/usr/bin/env python3
"""
Call test with WAV file playback instead of beep tone.
"""

import asyncio
import sys
import wave
import audioop

sys.path.insert(0, "/home/user/Test_Phone_new")

from pjsip_python.pjsua import Ua, UaConfig, RegState, CallState

WAV_FILE = "/home/user/Test_Phone_new/2022-07-22 - Phaera Homebound.wav"


def prepare_wav_for_rtp(wav_path, target_seconds=10):
    """Convert WAV file to G.711 frames for RTP transmission."""
    print(f"\n[+] Opening WAV file: {wav_path}")
    wf = wave.open(wav_path, "rb")

    # Get WAV info
    n_channels = wf.getnchannels()
    sample_width = wf.getsampwidth()
    frame_rate = wf.getframerate()

    print(f"[+] WAV info:")
    print(f"    Channels: {n_channels}")
    print(f"    Sample width: {sample_width}")
    print(f"    Frame rate: {frame_rate} Hz")

    # Read target seconds
    target_samples = int(8000 * target_seconds)
    raw_frames = wf.readframes(int(target_samples * frame_rate // 8000))
    wf.close()

    print(f"[+] Read {len(raw_frames)} bytes raw")

    # Convert to mono if needed
    if n_channels > 1:
        print("[+] Converting to mono...")
        raw_frames = audioop.tomono(raw_frames, sample_width, 1.0, 1.0)

    # Resample if needed (to 8000 Hz)
    if frame_rate != 8000:
        print(f"[+] Resampling from {frame_rate} to 8000 Hz...")
        raw_frames = audioop.ratecv(
            raw_frames, sample_width, 1, frame_rate, 8000, None
        )[0]

    # Convert to 8-bit
    if sample_width == 2:
        print("[+] Converting 16-bit to 8-bit...")
        linear_8bit = audioop.lin2lin(raw_frames, 2, 1)
    else:
        linear_8bit = raw_frames

    # Add bias to make unsigned
    biased = audioop.bias(linear_8bit, 1, 128)

    # Encode to G.711 A-law
    print("[+] Encoding to G.711 A-law...")
    g711_data = audioop.lin2alaw(biased, 1)

    # Split into 160-byte frames
    frames = []
    offset = 0
    frame_size = 160

    while offset + frame_size <= len(g711_data):
        frames.append(g711_data[offset : offset + frame_size])
        offset += frame_size

    print(f"[+] Prepared {len(frames)} frames ({len(frames) * 20}ms total)")

    return frames


async def test_wav_call():
    """Test call with WAV file playback."""
    print("=" * 70)
    print("  WAV FILE CALL TEST")
    print("=" * 70)

    config = UaConfig()
    config.user_agent = "pjsip_python/1.0"
    config.local_ip = "192.168.1.181"
    config.local_port = 5081

    print("[+] Creating UA...")
    ua = await Ua.create(config)
    print(f"[+] UA: {ua.local_ip}:{ua.local_port}")

    account = await ua.create_account(
        {
            "id": "sip:555533@192.168.1.176",
            "reg_uri": "sip:192.168.1.176:5060",
            "username": "555533",
            "password": "Test1234",
            "realm": "asterisk",
            "contact": "sip:555533@192.168.1.181:5081",
        }
    )

    print("[+] Registering...")
    reg_result = await account.register()
    print(f"[+] register() returned: {reg_result}")
    print(f"[+] Reg state: {account.reg_state.name}")

    for i in range(150):
        if account.reg_state == RegState.REGISTERED:
            print("[+] Registered!")
            break
        await asyncio.sleep(0.04)
    else:
        print("[X] Registration timeout")
        await ua.destroy()
        return False

    print("[+] Calling 1001...")
    call = await ua.call("sip:1001@192.168.1.176:5060")

    if not call:
        print("[X] Call failed")
        await ua.destroy()
        return False

    print(f"[+] Call state: {call.state}")

    # Wait for CONFIRMED
    for i in range(150):
        state = call.state
        if state == CallState.CONFIRMED:
            print("[+] Call CONFIRMED!")
            break
        if state == CallState.DISCONNECTED:
            print(f"[X] Call failed: {state.name}")
            await ua.destroy()
            return False
        await asyncio.sleep(0.04)
    else:
        print("[X] Timeout waiting for CONFIRMED")
        await call.hangup()
        await ua.destroy()
        return False

    # Get remote RTP port
    print("[+] Extracting remote RTP from SDP...")
    remote_port = 0
    if call._remote_sdp:
        sdp_text = call._remote_sdp.build()
        for line in sdp_text.split("\n"):
            if line.startswith("m=audio"):
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        remote_port = int(parts[1])
                        print(f"[+] Remote RTP port: {remote_port}")
                    except ValueError:
                        pass
                break

    if remote_port == 0:
        print("[X] Could not extract remote RTP port")
        await call.hangup()
        await ua.destroy()
        return False

    # Set remote address
    print(f"[+] Setting remote RTP: 192.168.1.176:{remote_port}")
    if call._media_stream:
        call._media_stream.set_remote(("192.168.1.176", remote_port))
        print(f"[+] Remote RTP set: {call._media_stream.remote_addr}")

    # Prepare WAV file
    print("\n[+] Preparing WAV file for playback...")
    frames = prepare_wav_for_rtp(WAV_FILE, target_seconds=15)

    # Send audio frames
    print(
        f"\n[+] Sending {len(frames)} frames ({len(frames) * 20 / 1000:.1f} seconds)..."
    )
    for i, frame in enumerate(frames):
        if call._media_stream:
            call._media_stream.send_g711(frame)

        if i % 100 == 0:
            print(f"[+] Sent {i}/{len(frames)} frames ({i * 20 / 1000:.1f}s)")

        await asyncio.sleep(0.02)

    print("[+] Audio sent!")

    print("\n[+] Waiting 1 second...")
    await asyncio.sleep(1)

    print("[+] Hanging up...")
    await call.hangup()

    await asyncio.sleep(1)

    print("[+] Unregistering...")
    await account.unregister()

    await asyncio.sleep(1)

    print("[+] Destroying UA...")
    await ua.destroy()

    print("=" * 70)
    print("  TEST PASSED ✓")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_wav_call())
    sys.exit(0 if success else 1)
