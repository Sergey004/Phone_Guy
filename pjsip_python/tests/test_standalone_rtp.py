#!/usr/bin/env python3
"""
Test call with standalone SimpleRTPClient - bypass built-in media stream.
"""

import asyncio
import sys
import time
import struct
import math

sys.path.insert(0, "/home/user/Test_Phone_new")

from pjsip_python.pjsua import Ua, UaConfig, RegState, CallState
from pjsip_python.pjmedia.stream_simple import SimpleMediaStream
from pjsip_python.pjmedia.codec import G711Codec


async def test_standalone_rtp():
    """Test call using standalone SimpleRTPClient."""
    print("=" * 70)
    print("  STANDALONE RTP CLIENT TEST - BYPASS BUILT-IN STREAM")
    print("=" * 70)

    config = UaConfig()
    config.user_agent = "pjsip_python/1.0"
    config.local_ip = "192.168.1.181"
    config.local_port = 5082

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
            "contact": "sip:555533@192.168.1.181:5082",
        }
    )

    print("[+] Registering...")
    reg_result = await account.register()

    for i in range(150):
        if account.reg_state == RegState.REGISTERED:
            print(f"[+] Registered!")
            break
        await asyncio.sleep(0.1)
    else:
        print(f"[X] Registration failed: {account.reg_state.name}")
        await ua.destroy()
        return False

    print("\n[+] Calling 1001...")
    call = await ua.call("sip:1001@192.168.1.176:5060")

    if not call:
        print("[X] Call failed")
        await ua.destroy()
        return False

    print(f"[+] Call state: {call.state}")

    print("[+] Waiting for CONFIRMED...")
    for i in range(300):
        await asyncio.sleep(0.1)
        if call.state == CallState.CONFIRMED:
            print("[+] Call CONFIRMED!")
            break
        if call.state == CallState.DISCONNECTED:
            print(f"[X] Call disconnected")
            await ua.destroy()
            return False
    else:
        print("[X] Timeout")
        await call.hangup()
        await ua.destroy()
        return False

    print("\n[+] Extracting RTP info from SDP...")
    remote_port = 0
    if call._remote_sdp:
        sdp_text = call._remote_sdp.build()
        for line in sdp_text.split("\n"):
            if line.startswith("m=audio"):
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        remote_port = int(parts[1])
                        print(f"[+] Remote RTP: 192.168.1.176:{remote_port}")
                    except ValueError:
                        pass
                break

    if remote_port == 0:
        print("[X] No remote RTP port")
        await call.hangup()
        await ua.destroy()
        return False

    local_port = 22000 + (id(call) % 1000)

    print(f"[+] Creating SimpleMediaStream: {local_port}")
    media_stream = SimpleMediaStream(
        local_ip="192.168.1.181",
        local_port=local_port,
        payload_type=8,
        a_law=True,
    )

    print(f"[+] Setting remote: 192.168.1.176:{remote_port}")
    media_stream.set_remote("192.168.1.176", remote_port)

    print("[+] Starting media stream...")
    media_stream.start()

    print("\n[+] Sending 3 seconds of audio...")

    codec = G711Codec(a_law=True)

    tone_pcm_20ms = bytearray()
    for i in range(160):
        sample = int(math.sin(2 * math.pi * 440 * i / 8000) * 32767 * 0.3)
        tone_pcm_20ms.extend(struct.pack("<h", sample))
    tone_g711 = codec.encode(bytes(tone_pcm_20ms))

    silence_pcm = b"\x00" * 320
    silence_g711 = codec.encode(silence_pcm)
    print(f"[+] Tone G.711 (first 5): {tone_g711[:5].hex()}")

    for i in range(150):
        if i % 25 < 12:
            media_stream.send_g711(tone_g711)
        else:
            media_stream.send_g711(silence_g711)

        await asyncio.sleep(0.02)

    print("[+] Audio sent!")

    print("\n[+] Waiting 1 second...")
    await asyncio.sleep(1)

    print("[+] Stopping media stream...")
    media_stream.stop()

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
    success = asyncio.run(test_standalone_rtp())
    sys.exit(0 if success else 1)
