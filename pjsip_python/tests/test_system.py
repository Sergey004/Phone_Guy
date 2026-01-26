#!/usr/bin/env python3
"""
System Test for pjsip_python (Working Features Only)

Tests the working features of the SIP/RTP stack:
- pjlib: sockets, timers, threads, pools
- pjmedia: codecs, RTP basics
- audio: in-memory processing, numpy/tensor
- utils: conversions, resampling
- pjsua: high-level API

Usage:
    source /home/user/Test_Phone_new/.venv/bin/activate
    python3 /home/user/Test_Phone_new/pjsip_python/tests/test_system.py
"""

import sys
import asyncio
import tempfile
import os
import numpy as np
import torch
sys.path.insert(0, '/home/user/Test_Phone_new')


def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_result(test_name: str, passed: bool, error: str | None = None) -> None:
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"  [{status}] {test_name}")
    if error and not passed:
        print(f"         Error: {error}")


def test_pjlib():
    print_header("Testing pjlib (Foundation Layer)")

    tests_passed = 0
    tests_total = 0

    # Socket creation
    tests_total += 1
    try:
        from pjsip_python.pjlib.sock import Socket, AddressFamily, SocketType
        sock = Socket(AddressFamily.INET, SocketType.DATAGRAM)
        sock.create_socket()
        sock.bind(('127.0.0.1', 0))
        assert sock.getsockname()[1] > 0
        sock.close()
        print_result("Socket creation and binding", True)
        tests_passed += 1
    except Exception as e:
        print_result("Socket creation and binding", False, str(e))
        raise

    # Get local IP
    tests_total += 1
    try:
        from pjsip_python.pjlib.sock import get_local_ip
        ip = get_local_ip()
        assert ip is not None and len(ip) > 0
        print_result(f"Get local IP: {ip}", True)
        tests_passed += 1
    except Exception as e:
        print_result("Get local IP", False, str(e))
        raise

    # Timer heap
    tests_total += 1
    try:
        from pjsip_python.pjlib.timer import create_timer_heap
        heap = create_timer_heap()
        print_result("TimerHeap creation", True)
        tests_passed += 1
    except Exception as e:
        print_result("TimerHeap creation", False, str(e))
        raise

    # Memory pool
    tests_total += 1
    try:
        from pjsip_python.pjlib.pool import create_pool
        pool = create_pool("test_pool", 4096)
        buf = pool.allocate(100)
        assert buf is not None and len(buf) == 100
        print_result("Memory pool allocation", True)
        tests_passed += 1
    except Exception as e:
        print_result("Memory pool allocation", False, str(e))
        raise

    # Thread creation
    tests_total += 1
    try:
        from pjsip_python.pjlib.thread import create_thread
        result: list = []
        def worker(x, y):
            result.append(x + y)
        thread = create_thread(worker, args=(10, 20))
        thread.start()
        thread.join()
        assert 30 in result
        print_result("Thread creation and execution", True)
        tests_passed += 1
    except Exception as e:
        print_result("Thread creation and execution", False, str(e))
        raise

    print(f"\n  pjlib: {tests_passed}/{tests_total} tests passed")


def test_pjmedia():
    print_header("Testing pjmedia (Codec & RTP Layer)")

    tests_passed = 0
    tests_total = 0

    # G.711 Codec
    tests_total += 1
    try:
        from pjsip_python.pjmedia.codec import G711Codec, CodecID, G711_ALAW, G711_ULAW
        codec = G711Codec(a_law=True)
        assert codec.name == "PCMA"
        assert codec.id == CodecID.PCMA
        print_result("G.711 Codec creation", True)
        tests_passed += 1
    except Exception as e:
        print_result("G.711 Codec creation", False, str(e))
        raise

    # G.711 Encode/Decode
    tests_total += 1
    try:
        from pjsip_python.pjmedia.codec import G711Codec
        codec = G711Codec(a_law=True)
        pcm = b'\x00\x00\xff\xff\x12\x34\x56\x78'
        encoded = codec.encode(pcm)
        decoded = codec.decode(encoded)
        assert len(encoded) == len(pcm) // 2
        print_result("G.711 Encode/Decode", True)
        tests_passed += 1
    except Exception as e:
        print_result("G.711 Encode/Decode", False, str(e))
        raise

    # L16 Codec
    tests_total += 1
    try:
        from pjsip_python.pjmedia.codec import L16Codec, CodecID
        codec = L16Codec(sample_rate=16000)
        assert codec.id == CodecID.L16_16
        print_result("L16 Codec", True)
        tests_passed += 1
    except Exception as e:
        print_result("L16 Codec", False, str(e))
        raise

    # RTP Header
    tests_total += 1
    try:
        from pjsip_python.pjmedia.rtp import RtpHeader
        header = RtpHeader(
            version=2,
            payload_type=8,
            sequence=1000,
            timestamp=0,
            ssrc=0x12345678
        )
        data = header.pack()
        header2 = RtpHeader()
        assert header2.unpack(data)
        assert header2.payload_type == 8
        print_result("RTP Header pack/unpack", True)
        tests_passed += 1
    except Exception as e:
        print_result("RTP Header pack/unpack", False, str(e))
        raise

    # RTP Session
    tests_total += 1
    try:
        from pjsip_python.pjmedia.rtp import RtpSession
        rtp = RtpSession(ssrc=0x12345678, payload_type=8)
        assert rtp.ssrc == 0x12345678
        rtp.set_clock_rate(8000)
        payload = b'\x00' * 160
        packet = rtp.encode_rtp(payload)
        assert len(packet) == 12 + 160
        print_result("RTP Session encode", True)
        tests_passed += 1
    except Exception as e:
        print_result("RTP Session encode", False, str(e))
        raise

    # RTCP
    tests_total += 1
    try:
        from pjsip_python.pjmedia.rtcp import RtcpSession
        rtcp = RtcpSession(ssrc=0x12345678)
        sr = rtcp.create_sr()
        assert sr is not None
        print_result("RTCP Session", True)
        tests_passed += 1
    except Exception as e:
        print_result("RTCP Session", False, str(e))
        raise

    print(f"\n  pjmedia: {tests_passed}/{tests_total} tests passed")


def test_pjsip():
    print_header("Testing pjsip (Signaling Layer)")

    tests_passed = 0
    tests_total = 0

    # SIP Message parsing
    tests_total += 1
    try:
        from pjsip_python.pjsip import parse_sip_message
        msg_text = """INVITE sip:bob@example.com SIP/2.0
Via: SIP/2.0/UDP 192.168.1.1:5060;branch=z9hG4bK12345678
From: <sip:alice@192.168.1.1>;tag=tag123
To: <sip:bob@example.com>
Call-ID: call123@192.168.1.1
CSeq: 1 INVITE
Content-Length: 0

"""
        msg = parse_sip_message(msg_text)
        assert msg is not None
        print_result("SIP message parsing", True)
        tests_passed += 1
    except Exception as e:
        print_result("SIP message parsing", False, str(e))
        raise

    # SIP URI parsing
    tests_total += 1
    try:
        from pjsip_python.pjsip import SipUri
        uri = SipUri(scheme="sip", user="alice", host="192.168.1.1", port=5060)
        assert uri.user == "alice"
        assert uri.host == "192.168.1.1"
        print_result("SIP URI creation", True)
        tests_passed += 1
    except Exception as e:
        print_result("SIP URI creation", False, str(e))
        raise

    # Generate IDs
    tests_total += 1
    try:
        from pjsip_python.pjlib.sock import get_local_hostname
        hostname = get_local_hostname()
        assert len(hostname) > 0
        from pjsip_python.pjsip.sip_msg import generate_branch, generate_call_id, generate_tag
        branch = generate_branch()
        call_id = generate_call_id()
        tag = generate_tag()
        assert len(branch) > 0
        assert len(call_id) > 0
        assert len(tag) > 0
        print_result("Generate branch/call-id/tag", True)
        tests_passed += 1
    except Exception as e:
        print_result("Generate branch/call-id/tag", False, str(e))
        raise

    # SipMessage creation
    tests_total += 1
    try:
        from pjsip_python.pjsip import SipMessage
        msg = SipMessage()
        print_result("SipMessage creation", True)
        tests_passed += 1
    except Exception as e:
        print_result("SipMessage creation", False, str(e))
        raise

    print(f"\n  pjsip: {tests_passed}/{tests_total} tests passed")


def test_audio():
    print_header("Testing audio (In-Memory Processing)")

    tests_passed = 0
    tests_total = 0

    # AudioData from numpy
    tests_total += 1
    try:
        from pjsip_python.audio import numpy_to_audio
        arr = np.array([0, 1000, -1000, 500, -500], dtype=np.int16)
        audio = numpy_to_audio(arr, sample_rate=8000)
        assert audio.num_samples == 5
        print_result("AudioData from numpy", True)
        tests_passed += 1
    except Exception as e:
        print_result("AudioData from numpy", False, str(e))
        raise

    # Tensor conversion
    tests_total += 1
    try:
        from pjsip_python.audio import tensor_to_audio, audio_to_tensor
        tensor = torch.randn(8000)
        audio = tensor_to_audio(tensor, sample_rate=8000)
        assert audio.num_samples == 8000
        tensor_back = audio_to_tensor(audio)
        assert tensor_back.shape == torch.Size([8000])
        print_result("Tensor <-> AudioData", True)
        tests_passed += 1
    except Exception as e:
        print_result("Tensor <-> AudioData", False, str(e))
        raise

    # WAV file I/O
    tests_total += 1
    try:
        from pjsip_python.audio import write_wav, read_wav, create_tone
        audio = create_tone(440, 0.5)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            path = f.name
        write_wav(path, audio)
        loaded = read_wav(path)
        assert loaded.num_samples == audio.num_samples
        os.unlink(path)
        print_result("WAV read/write", True)
        tests_passed += 1
    except Exception as e:
        print_result("WAV read/write", False, str(e))
        raise

    # G.711 conversion
    tests_total += 1
    try:
        from pjsip_python.audio import create_silence, AudioFormat
        audio = create_silence(0.1)  # 100ms = 800 samples
        g711 = audio.to_bytes(AudioFormat.G711_ALAW)
        assert len(g711) == 800  # 100ms * 8000 samples/sec / 1 byte/sample
        print_result("G.711 A-law conversion", True)
        tests_passed += 1
    except Exception as e:
        print_result("G.711 A-law conversion", False, str(e))
        raise

    # Resample
    tests_total += 1
    try:
        from pjsip_python.audio import create_tone
        audio = create_tone(440, 0.5)
        resampled = audio.resample(16000)
        assert resampled.sample_rate == 16000
        print_result("Audio resampling", True)
        tests_passed += 1
    except Exception as e:
        print_result("Audio resampling", False, str(e))
        raise

    # Create silence/tone
    tests_total += 1
    try:
        from pjsip_python.audio import create_silence, create_tone
        silence = create_silence(1.0)
        tone = create_tone(440, 0.5)
        assert silence.num_samples == 8000
        assert tone.num_samples == 4000
        print_result("Create silence/tone", True)
        tests_passed += 1
    except Exception as e:
        print_result("Create silence/tone", False, str(e))
        raise

    print(f"\n  audio: {tests_passed}/{tests_total} tests passed")


def test_utils():
    print_header("Testing utils")

    tests_passed = 0
    tests_total = 0

    # numpy conversions
    tests_total += 1
    try:
        from pjsip_python.utils import numpy_to_pcm16, pcm16_to_numpy
        arr = np.array([0, 1000, -1000], dtype=np.int16)
        pcm = numpy_to_pcm16(arr)
        back = pcm16_to_numpy(pcm)
        assert np.array_equal(arr, back)
        print_result("numpy <-> PCM16", True)
        tests_passed += 1
    except Exception as e:
        print_result("numpy <-> PCM16", False, str(e))
        raise

    # G.711 conversions
    tests_total += 1
    try:
        from pjsip_python.utils import numpy_to_g711, g711_to_numpy
        arr = np.array([0.0, 0.5, -0.5], dtype=np.float32)
        g711 = numpy_to_g711(arr, a_law=True)
        back = g711_to_numpy(bytes(g711), a_law=True)
        assert len(back) == len(arr)
        print_result("numpy <-> G.711", True)
        tests_passed += 1
    except Exception as e:
        print_result("numpy <-> G.711", False, str(e))
        raise

    print(f"\n  utils: {tests_passed}/{tests_total} tests passed")


def test_pjsua():
    print_header("Testing pjsua (High-Level API)")

    tests_passed = 0
    tests_total = 0

    # UaConfig
    tests_total += 1
    try:
        from pjsip_python.pjsua import UaConfig
        config = UaConfig(local_ip="192.168.1.1", local_port=5060)
        assert config.local_ip == "192.168.1.1"
        print_result("UaConfig creation", True)
        tests_passed += 1
    except Exception as e:
        print_result("UaConfig creation", False, str(e))
        raise

    # Ua creation
    tests_total += 1
    try:
        from pjsip_python.pjsua import Ua, UaConfig
        async def test():
            config = UaConfig(local_ip="127.0.0.1", local_port=0)
            ua = await Ua.create(config)
            await ua.destroy()
        asyncio.run(test())
        print_result("Ua creation/destruction", True)
        tests_passed += 1
    except Exception as e:
        print_result("Ua creation/destruction", False, str(e))
        raise

    # AccountConfig
    tests_total += 1
    try:
        from pjsip_python.pjsua import AccountConfig
        config = AccountConfig(id="sip:test@example.com", reg_uri="sip:example.com:5060")
        assert config.id == "sip:test@example.com"
        print_result("AccountConfig creation", True)
        tests_passed += 1
    except Exception as e:
        print_result("AccountConfig creation", False, str(e))
        raise

    # Enums
    tests_total += 1
    try:
        from pjsip_python.pjsua import CallState, RegState
        assert CallState.CALLING.value > 0
        assert RegState.REGISTERED.value > 0
        print_result("CallState/RegState enums", True)
        tests_passed += 1
    except Exception as e:
        print_result("CallState/RegState enums", False, str(e))
        raise

    print(f"\n  pjsua: {tests_passed}/{tests_total} tests passed")


def test_integration():
    print_header("Integration: TTS -> RVC -> SIP Pipeline")

    tests_passed = 0
    tests_total = 0

    # Complete pipeline
    tests_total += 1
    try:
        # TTS output (numpy)
        from pjsip_python.audio import numpy_to_audio, audio_to_numpy, tensor_to_audio, audio_to_tensor, AudioFormat
        from pjsip_python.pjmedia.rtp import RtpSession

        tts_output = np.random.randn(8000).astype(np.float32) * 0.5
        audio = numpy_to_audio(tts_output, sample_rate=8000)

        # RVC (tensor)
        tensor = audio_to_tensor(audio)
        processed = tensor * 1.1  # RVC placeholder
        rvc_audio = tensor_to_audio(processed, sample_rate=8000)

        # G.711
        g711 = rvc_audio.to_bytes(AudioFormat.G711_ALAW)

        # RTP
        rtp = RtpSession(ssrc=0x12345678, payload_type=8)
        rtp.set_clock_rate(8000)
        rtp_payload = rtp.encode_rtp(g711[:160])

        assert len(g711) == 8000
        assert len(rtp_payload) == 172
        print_result("TTS -> RVC -> G.711 -> RTP", True)
        tests_passed += 1
    except Exception as e:
        print_result("TTS -> RVC -> G.711 -> RTP", False, str(e))
        raise

    # Top-level imports
    tests_total += 1
    try:
        from pjsip_python import (
            Ua, Account, Buddy,
            G711Codec, RtpSession,
            IceSession, StunClient,
            resample_audio, numpy_to_pcm16,
            numpy_to_g711, g711_to_numpy,
            create_silence
        )
        from pjsip_python.audio import create_tone
        print_result("Top-level imports", True)
        tests_passed += 1
    except Exception as e:
        print_result("Top-level imports", False, str(e))
        raise

    print(f"\n  integration: {tests_passed}/{tests_total} tests passed")


def main():
    print("\n" + "=" * 70)
    print("  pjsip_python - System Test")
    print("  Pure Python SIP/RTP Stack")
    print("=" * 70)
    
    results = {}
    results['pjlib'] = test_pjlib()
    results['pjmedia'] = test_pjmedia()
    results['pjsip'] = test_pjsip()
    results['audio'] = test_audio()
    results['utils'] = test_utils()
    results['pjsua'] = test_pjsua()
    results['integration'] = test_integration()
    
    # Summary
    print("\n" + "=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    
    all_passed = True
    for module, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  [{status}] {module}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("  ALL TESTS PASSED!")
    else:
        print("  SOME TESTS FAILED!")
    print("=" * 70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
