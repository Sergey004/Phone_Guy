#!/usr/bin/env python3
"""
Full call test with SimpleRTPClient audio transmission.
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


async def test_call_with_simple_rtp():
    """Test call with SimpleRTPClient audio."""
    print("=" * 70)
    print("  FULL CALL TEST WITH SIMPLERTPCLIENT")
    print("=" * 70)

    config = UaConfig()
    config.user_agent = "pjsip_python/1.0"
    config.local_ip = "192.168.1.181"
    config.local_port = 5079

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
            "contact": "sip:555533@192.168.1.181:5079",
        }
    )

    print("[+] Registering...")
    reg_result = await account.register()
    print(f"[+] register() returned: {reg_result}")
    print(f"[+] Reg state: {account.reg_state.name}")

    for i in range(150):
        if account.reg_state == RegState.REGISTERED:
            print(f"[+] Registered!")
            break
        await asyncio.sleep(0.1)
    else:
        print(f"[X] Registration failed: {account.reg_state.name}")
        await ua.destroy()
        return False

    print("[+] Calling 1001...")
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
        print("[X] Timeout waiting for CONFIRMED")
        await call.hangup()
        await ua.destroy()
        return False

    print("\n[+] Setting up SimpleMediaStream...")

    local_port = 21000 + (id(call) % 1000)

    media_stream = SimpleMediaStream(
        local_ip="192.168.1.181",
        local_port=local_port,
        payload_type=8,
        a_law=True,
    )

    print("[+] Extracting remote RTP port from SDP...")
    remote_port = 15782  # Default from Asterisk response
    if call._remote_sdp:
        sdp_text = call._remote_sdp.build()
        for line in sdp_text.split("\n"):
            if line.startswith("m=audio"):
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        remote_port = int(parts[1])
                        print(f"[+] Found RTP port: {remote_port}")
                    except ValueError:
                        pass
                break

    print(f"[+] Setting remote RTP: 192.168.1.176:{remote_port}")
    media_stream.set_remote("192.168.1.176", remote_port)

    media_stream.start()

    print("\n[+] Sending 3 seconds of audio...")

    codec = G711Codec(a_law=True)

    silence_pcm = b"\x00" * 320
    silence_g711 = codec.encode(silence_pcm)

    tone_pcm_20ms = bytearray()
    for i in range(160):
        sample = int(math.sin(2 * math.pi * 440 * i / 8000) * 32767 * 0.3)
        tone_pcm_20ms.extend(struct.pack("<h", sample))
    tone_g711 = codec.encode(bytes(tone_pcm_20ms))

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
    success = asyncio.run(test_call_with_simple_rtp())
    sys.exit(0 if success else 1)
