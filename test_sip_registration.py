#!/usr/bin/env python3
import sys
import time

sys.path.insert(0, "/home/user/Test_Phone_new")

from pjsip_python.sip import SIPClient, SIPStatus


def test_sip_registration():
    server = "192.168.1.176"
    port = 5060
    myIP = "192.168.1.181"
    myPort = 5060
    username = "555533"
    password = "Test1234"

    print(f"Testing SIP registration to {server}:{port}")
    print(f"Local: {myIP}:{myPort}")
    print(f"Username: {username}")
    print()

    sip = SIPClient(server, port, myIP, myPort, username, password)

    print("Attempting registration...")
    success = sip.register()

    if success:
        print("✓ Registration successful!")
        print("Waiting for 5 seconds...")
        time.sleep(5)
        print("Deregistering...")
        sip.deregister()
        print("✓ Deregistration successful!")
        return True
    else:
        print("✗ Registration failed!")
        return False


if __name__ == "__main__":
    success = test_sip_registration()
    sys.exit(0 if success else 1)
