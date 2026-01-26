#!/usr/bin/env python3
"""
Minimal test call to verify audio fixes after timestamp and AttributeError fixes
"""

import asyncio
import sys
import time

sys.path.insert(0, "/home/user/Test_Phone_new")

from pjsip_python.pjsua import Ua, UaConfig, RegState, CallState


async def test_call():
    """Test call with audio."""
    print("=" * 60)
    print("  MINIMAL CALL TEST - VERIFYING FIXES")
    print("=" * 60)

    config = UaConfig()
    config.user_agent = "pjsip_python/1.0"
    config.local_ip = "192.168.1.181"
    config.local_port = 5066

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
            "contact": "sip:555533@192.168.1.181:5066",
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
            if call._media_stream:
                print(f"[+] Remote RTP: {call._media_stream._remote_addr}")
                print(f"[+] RTP client: {call._media_stream._rtp_client}")
            break
        if call.state in (CallState.DISCONNECTED, CallState.FAILED):
            print(f"[X] Call failed: {call.state}")
            await ua.destroy()
            return False
    else:
        print("[X] Timeout waiting for CONFIRMED")
        await call.hangup()
        await ua.destroy()
        return False

    print("[+] Sending 2 seconds of audio...")
    silence = b"\xd5" * 160  # G.711 encoded silence (A-law)

    for i in range(100):  # 2 seconds
        if call._media_stream:
            call._media_stream.send_g711(silence)
        await asyncio.sleep(0.02)

    print("[+] Audio sent, waiting 1 second...")
    await asyncio.sleep(1)

    print("[+] Hanging up...")
    await call.hangup()
    await asyncio.sleep(1)

    print("[+] Unregistering...")
    await account.unregister()
    await asyncio.sleep(1)

    print("[+] Destroying UA...")
    await ua.destroy()

    print("=" * 60)
    print("  TEST PASSED ✓")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_call())
    sys.exit(0 if success else 1)
