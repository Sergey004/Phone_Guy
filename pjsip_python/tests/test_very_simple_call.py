#!/usr/bin/env python3
"""Simple test: call 1001, confirm, send audio, hangup."""

import asyncio
import sys
import os

sys.path.insert(0, "/home/user/Test_Phone_new/pjsip_python")
os.environ.setdefault("PYTHONPATH", "/home/user/Test_Phone_new/pjsip_python")

from pjsua.pjsua import UA
from pjsua.acc import Account, AccountConfig
from pjsua.call import Call
from pjmedia.codec import G711Codec
import math
import struct


async def test_simple_call():
    print("=" * 60)
    print("  SIMPLE CALL TEST")
    print("=" * 60)

    print("\n[+] Creating UA...")
    ua = UA("192.168.1.181")
    await ua.create()

    print(f"[+] UA: {ua.local_ip}:{ua.local_port}")

    print("\n[+] Creating account...")
    acc_config = AccountConfig(
        username="555533", password="Test1234", domain="192.168.1.176", realm="asterisk"
    )
    account = Account(acc_config, ua)
    await account.register()

    await asyncio.sleep(1)

    if account.info().reg_status != 200:
        print(f"[X] Registration failed: {account.info().reg_status}")
        await ua.destroy()
        return False

    print(f"[+] Registered: {account.info().reg_status}")

    print("\n[+] Calling 1001...")
    call = Call(account)
    success = await call.make(ua, "sip:1001@192.168.1.176")

    if not success:
        print(f"[X] Call failed")
        await account.unregister()
        await ua.destroy()
        return False

    await asyncio.sleep(2)

    print(f"[+] Call state: {call.info().state}")
    print(f"[+] Call active: {call.is_active}")

    if call._media_stream:
        print(f"[+] Media stream:")
        print(f"    Local: {call._media_stream.local_addr}")
        print(f"    Remote: {call._media_stream.remote_addr}")
        print(f"    Running: {call._media_stream._running}")

        rtp = call._media_stream.rtp_client
        if rtp:
            print(f"    RTP client:")
            print(f"      inIP/port: {rtp.inIP}:{rtp.inPort}")
            print(f"      outIP/port: {rtp.outIP}:{rtp.outPort}")
            print(f"      NSD: {rtp.NSD}")

    await asyncio.sleep(1)

    print("\n[+] Sending 2 seconds of audio...")
    codec = G711Codec(a_law=True)

    # Generate 20ms frame of 440Hz tone (8-bit PCM)
    tone_pcm_20ms = bytearray()
    for i in range(160):
        sample = int(math.sin(2 * math.pi * 440 * i / 8000) * 127 * 0.3)
        tone_pcm_20ms.append(sample + 128)

    tone_g711 = codec.encode(bytes(tone_pcm_20ms))
    print(f"[+] Tone G.711: {len(tone_g711)} bytes, first 5: {tone_g711[:5].hex()}")

    for i in range(100):
        if call._media_stream:
            call._media_stream.send_g711(tone_g711)
        await asyncio.sleep(0.02)

    print("[+] Audio sent!")

    await asyncio.sleep(2)

    print("\n[+] Hanging up...")
    await call.hangup()

    await asyncio.sleep(1)

    print("\n[+] Unregistering...")
    await account.unregister()

    await asyncio.sleep(1)

    print("\n[+] Destroying UA...")
    await ua.destroy()

    print("\n" + "=" * 60)
    print("  TEST PASSED")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_simple_call())
    sys.exit(0 if success else 1)
