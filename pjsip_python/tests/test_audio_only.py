"""
Simple audio-only call test
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.pjsua import Ua, AccountConfig, UaConfig, RegState
from pjsip_python.pjsua.call import CallState


async def test_audio_only(audio_file: str, target: str):
    """Simple audio-only call test."""
    from pjsip_python.pjsua import UaConfig, RegState

    print(f"[+] Creating User Agent...")
    config = UaConfig()
    config.user_agent = 'pjsip_python/1.0'
    config.local_ip = '192.168.1.181'
    config.local_port = 5062

    ua = await Ua.create(config)
    if ua is None:
        print(f"[X] Failed to create UA!")
        return False

    print(f"[+] UA created on {ua.local_ip}:{ua.local_port}")

    acc_config = AccountConfig(
        id="sip:555533@192.168.1.176",
        reg_uri="sip:192.168.1.176:5060",
        username="555533",
        password="555533",
        realm="asterisk",
        contact="sip:555533@192.168.1.181:5062"
    )

    print(f"[+] Creating account...")
    account = await ua.create_account({
        'id': acc_config.id,
        'reg_uri': acc_config.reg_uri,
        'username': acc_config.username,
        'password': acc_config.password,
        'realm': acc_config.realm,
        'contact': acc_config.contact
    })

    print(f"[+] Registration...")
    await account.register()

    registered = False
    start_time = time.time()
    while time.time() - start_time < 15.0:
        if account.reg_state == RegState.REGISTERED:
            registered = True
            break
        await asyncio.sleep(0.1)

    if not registered:
        print(f"[X] Registration failed: {account.reg_state.name}")
        await ua.destroy()
        return False

    print(f"[✓] Registered successfully!")

    print(f"[+] Calling {target}...")
    call = await ua.call(target)
    if not call:
        print(f"[X] Call failed!")
        await ua.destroy()
        return False

    print(f"[+] Call state: {call.state}")

    print(f"[+] Waiting for call to connect...")
    if call.wait_for_state(CallState.CONFIRMED, timeout=30):
        print(f"[✓] Call connected: CONFIRMED")
        print(f"[+] Remote RTP: {call._media_stream.remote_addr if call._media_stream else 'None'}")

        if audio_file and os.path.exists(audio_file):
            print(f"[+] Playing audio file: {audio_file}")
            from pjsip_python.pjmedia.codec import G711Codec
            import wave

            codec = G711Codec(a_law=True)

            with wave.open(audio_file, 'rb') as wav:
                n_channels = wav.getnchannels()
                sampwidth = wav.getsampwidth()
                framerate = wav.getframerate()
                n_frames = wav.getnframes()

                print(f"[+] WAV: {n_channels}ch, {sampwidth} bytes, {framerate} Hz, {n_frames} frames")

                frame_size = 160
                chunk_size = frame_size * n_channels * sampwidth

                while True:
                    data = wav.readframes(chunk_size)
                    if not data:
                        break

                    if n_channels == 2:
                        from pjsip_python.pjmedia.sdp import SdpSession
                        left_channel = b''.join(data[i] for i in range(0, len(data), 4))
                        data = left_channel

                    if len(data) < frame_size * sampwidth:
                        data = data + b'\x00' * (frame_size * sampwidth - len(data))

                    pcm_data = data
                    if sampwidth == 2:
                        import struct
                        pcm_data = struct.pack('<' + 'h' * (len(data) // 2), *struct.unpack('<' + 'h' * (len(data) // 2), data))

                    if call._media_stream:
                        call._media_stream.send_frame(pcm_data)

                    await asyncio.sleep(0.02)

            print(f"[+] Audio file finished")

        print(f"[+] Waiting 3 seconds before hangup...")
        await asyncio.sleep(3)
    else:
        print(f"[X] Call did not connect")

    print(f"[+] Hanging up...")
    await call.hangup()
    await asyncio.sleep(1)

    print(f"[+] Unregistering...")
    await account.unregister()
    await asyncio.sleep(1)

    await ua.destroy()
    print(f"[+] UA stopped")

    return True


async def main():
    audio_file = '/home/user/Test_Phone_new/output_phone.wav'
    target = 'sip:1001@192.168.1.176:5060'

    if len(sys.argv) > 1:
        target = sys.argv[1]
    if len(sys.argv) > 2:
        audio_file = sys.argv[2]

    print("=" * 60)
    print("  AUDIO ONLY CALL TEST")
    print("=" * 60)
    print(f"  Target: {target}")
    print(f"  Audio file: {audio_file}")
    print("=" * 60)

    success = await test_audio_only(audio_file, target)

    print("=" * 60)
    if success:
        print("  TEST PASSED ✓")
    else:
        print("  TEST FAILED ✗")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
