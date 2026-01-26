#!/usr/bin/env python3
"""
Test SimpleRTP client registration - fix timing
"""

import sys

sys.path.insert(0, "/home/user/Test_Phone_new")

import asyncio
from pjsip_python.pjsua import Ua, UaConfig, RegState


async def test_registration():
    """Test account registration with longer timeout."""
    print("=" * 60)
    print("  REGISTRATION TEST WITH LONGER TIMEOUT")
    print("=" * 60)

    config = UaConfig()
    config.user_agent = "pjsip_python/1.0"
    config.local_ip = "192.168.1.181"
    config.local_port = 5075

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
            "contact": "sip:555533@192.168.1.181:5075",
        }
    )

    print("[+] Registering...")
    reg_result = await account.register()
    print(f"[+] register() returned: {reg_result}")
    print(f"[+] Initial state: {account.reg_state.name}")

    print("[+] Waiting up to 30 seconds for registration...")
    for i in range(300):
        if account.reg_state == RegState.REGISTERED:
            print(f"[+] Registered after {i * 0.1}s!")
            break
        await asyncio.sleep(0.1)
        if i % 50 == 49:
            print(f"  Still waiting... state: {account.reg_state.name}")
    else:
        print(f"[X] Registration failed: {account.reg_state.name}")
        await ua.destroy()
        return False

    print("[+] Unregistering...")
    await account.unregister()

    print("[+] Destroying UA...")
    await ua.destroy()

    print("=" * 60)
    print("  TEST PASSED ✓")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_registration())
    sys.exit(0 if success else 1)
