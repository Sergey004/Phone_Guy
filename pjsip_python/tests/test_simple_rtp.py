#!/usr/bin/env python3
"""
Test call using SimpleRTPClient for audio transmission.
This uses the new simplified RTP implementation based on pyVoIP.
"""

import asyncio
import sys
import time

sys.path.insert(0, "/home/user/Test_Phone_new")

from pjsip_python.pjsua import Ua, UaConfig, RegState, CallState
from pjsip_python.pjmedia.stream_simple import SimpleMediaStream
from pjsip_python.pjmedia.codec import G711Codec


async def test_simple_rtp_call():
    """Test call with SimpleRTPClient audio."""
    print("=" * 70)
    print("  SIMPLE RTP CLIENT TEST - NEW IMPLEMENTATION")
    print("=" * 70)

    config = UaConfig()
    config.user_agent = "pjsip_python/1.0"
    config.local_ip = "192.168.1.181"
    config.local_port = 5067

    print("[+] Creating UA...")
    ua = await Ua.create(config)
    print(f"[+] UA created: {ua.local_ip}:{ua.local_port}")

    account = await ua.create_account(
        {
            "id": "sip:555533@192.168.1.176",
            "reg_uri": "sip:192.168.1.176:5060",
            "username": "555533",
            "password": "555533",
            "realm": "asterisk",
            "contact": "sip:555533@192.168.1.181:5067",
        }
    )

    print("[+] Registering...")
    await account.register()

    for i in range(150):
        if account.reg_state == RegState.REGISTERED:
            print("[+] Registered!")
            break
        await asyncio.sleep(0.1)
    else:
        print("[X] Registration failed")
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

            if call._remote_sdp:
                print("[+] Remote SDP received")
                sdp_text = call._remote_sdp.build()
                if "audio" in sdp_text.lower():
                    for line in sdp_text.split("\n"):
                        if line.startswith("c="):
                            print(f"  {line}")
                        elif "RTP" in line or "AVP" in line:
                            print(f"  {line}")

            break
        if call.state in (CallState.DISCONNECTED,):
            print(f"[X] Call failed: {call.state}")
            await ua.destroy()
            return False
    else:
        print("[X] Timeout waiting for CONFIRMED")
        await call.hangup()
        await ua.destroy()
        return False

    print("\n[+] Setting up SimpleMediaStream...")
    from pjsip_python.pjmedia.sdp import SdpSession

    local_port = 19000 + (id(call) % 5000)

    media_stream = SimpleMediaStream(
        local_ip="192.168.1.181",
        local_port=local_port,
        payload_type=8,
        a_law=True,
    )

    print("[+] Setting remote RTP address from SDP...")
    if call._remote_sdp and call._remote_sdp.media:
        for media in call._remote_sdp.media:
            if media.media_type == "audio":
                remote_port = getattr(media, "port", 0)
                if remote_port > 0:
                    media_stream.set_remote("192.168.1.176", remote_port)
                    print(f"[+] Remote RTP: 192.168.1.176:{remote_port}")
                    break

    media_stream.start()

    print("\n[+] Sending 3 seconds of audio (G.711 A-law)...")

    codec = G711Codec(a_law=True)

    silence_pcm = b"\x00" * 320  # 20ms of silence in 16-bit PCM
    silence_g711 = codec.encode(silence_pcm)  # Encode to G.711

    tone_pcm_20ms = bytearray()
    import struct

    for i in range(160):
        sample = int(math.sin(2 * math.pi * 440 * i / 8000) * 32767 * 0.3)
        tone_pcm_20ms.extend(struct.pack("<h", sample))
    tone_g711 = codec.encode(bytes(tone_pcm_20ms))

    silence_bytes = b"\xd5" * 160  # A-law silence

    for i in range(150):  # 3 seconds
        if i % 25 < 12:  # Every second, play 240ms tone
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
    import math

    success = asyncio.run(test_simple_rtp_call())
    sys.exit(0 if success else 1)
