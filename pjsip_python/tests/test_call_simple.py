"""
Simple audio call test without TTS
Tests: registration -> call -> RTP audio
"""

import asyncio
import sys
import time
import threading

sys.path.insert(0, "/home/user/Test_Phone_new")

from pjsip_python.pjsua import Ua, AccountConfig, UaConfig, RegState, CallState
from pjsip_python.pjsua.call import Call, CallInfo
from pjsip_python.pjmedia.rtp_pyvoip import RTPClient, PayloadType


async def test_simple_call():
    """Simple call test with audio."""
    print("=" * 60)
    print("  SIMPLE CALL TEST (NO TTS)")
    print("=" * 60)

    # Create UA
    print("[+] Creating UA...")
    config = UaConfig()
    config.user_agent = "pjsip_python/1.0"
    config.local_ip = "192.168.1.181"
    config.local_port = 5065

    ua = await Ua.create(config)
    if not ua:
        print("[X] Failed to create UA!")
        return False

    print(f"[+] UA created: {ua.local_ip}:{ua.local_port}")

    # Create account
    print("[+] Creating account...")
    account = await ua.create_account(
        {
            "id": "sip:555533@192.168.1.176",
            "reg_uri": "sip:192.168.1.176:5060",
            "username": "555533",
            "password": "Test1234",
            "realm": "asterisk",
            "contact": "sip:555533@192.168.1.181:5065",
        }
    )

    # Register
    print("[+] Registering...")
    await account.register()

    registered = False
    for i in range(150):  # 15 seconds
        if account.reg_state == RegState.REGISTERED:
            registered = True
            break
        await asyncio.sleep(0.1)

    if not registered:
        print(f"[X] Registration failed: {account.reg_state.name}")
        await ua.destroy()
        return False

    print("[+] Registered successfully!")

    # Create RTP client for test
    print("[+] Creating RTP client...")
    rtp_client = RTPClient(
        local_ip="192.168.1.181",
        local_port=19500,
        remote_ip="192.168.1.176",
        remote_port=19501,
        payload_type=8,  # PCMA only!
    )

    # Check SDP that would be sent
    from pjsip_python.pjmedia import create_offer, SdpSession

    local_sdp = create_offer(
        local_ip="192.168.1.181",
        local_port=19500,
        payload_types=[8],  # ONLY PCMA!
        codec_names={8: "PCMA"},
    )

    sdp_text = local_sdp.build()
    print("[+] SDP Offer:")
    print(sdp_text)

    # Verify SDP has only one codec
    assert "m=audio" in sdp_text
    assert "PCMA" in sdp_text
    assert "PCMU" not in sdp_text, "ERROR: PCMU should NOT be in SDP!"

    print("[+] SDP verified: Only PCMA (8)")

    # Call
    print("[+] Calling 1001...")
    call = await ua.call("sip:1001@192.168.1.176:5060")

    if not call:
        print("[X] Call failed!")
        await ua.destroy()
        return False

    print(f"[+] Call state: {call.state}")

    # Wait for call to connect
    print("[+] Waiting for call to connect...")
    for i in range(300):  # 30 seconds
        await asyncio.sleep(0.1)
        if call.state == CallState.CONFIRMED:
            print("[+] Call connected!")
            break
        if call.state in (CallState.DISCONNECTED, CallState.FAILED):
            print(f"[X] Call failed: {call.state}")
            return False
    else:
        print("[X] Call timeout")
        await call.hangup()
        await ua.destroy()
        return False

    # Check remote SDP
    print("[+] Remote SDP:")
    if call._remote_sdp:
        print(call._remote_sdp.build())

    # Check media stream
    if call._media_stream:
        print(f"[+] Media stream remote addr: {call._media_stream.remote_addr}")

    # Start RTP
    print("[+] Starting RTP client...")
    rtp_client.start()

    # Send audio for 3 seconds
    print("[+] Sending audio for 3 seconds...")
    silence = b"\x00" * 160  # 20ms of silence

    for i in range(150):  # 3 seconds
        rtp_client.write(silence)
        await asyncio.sleep(0.02)

    print("[+] Audio sent!")

    # Stop RTP
    rtp_client.stop()

    # Hangup
    print("[+] Hanging up...")
    await call.hangup()

    await asyncio.sleep(1)

    # Unregister
    print("[+] Unregistering...")
    await account.unregister()
    await asyncio.sleep(1)

    # Destroy UA
    await ua.destroy()

    print("=" * 60)
    print("  TEST PASSED ✓")
    print("=" * 60)
    return True


async def main():
    success = await test_simple_call()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
