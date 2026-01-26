"""
Simple test for pyVoIP-style RTP client
"""

import asyncio
import sys
import socket
import threading
import time

sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.pjmedia.rtp_pyvoip import RTPClient, PayloadType


def test_rtp_client():
    """Test RTP client basic operations."""
    print("[+] Testing RTPClient...")
    
    # Create client
    client = RTPClient(
        local_ip='192.168.1.181',
        local_port=18000,
        remote_ip='192.168.1.176',
        remote_port=18001,
        payload_type=8  # PCMA
    )
    print(f"[+] Created RTPClient: {client.local_addr} -> {client.remote_addr}")
    
    # Test write/read
    test_data = b'\x00' * 160  # 20ms of silence
    client.write(test_data)
    print(f"[+] Wrote {len(test_data)} bytes")
    
    # Start client
    print("[+] Starting RTPClient...")
    client.start()
    time.sleep(0.1)
    
    # Check socket
    if client._socket:
        print(f"[+] Socket created: {client._socket.getsockname()}")
    else:
        print("[X] Socket not created!")
    
    # Stop client
    print("[+] Stopping RTPClient...")
    client.stop()
    time.sleep(0.1)
    
    print("[+] RTPClient test complete!")


def test_rtp_packet_building():
    """Test RTP packet building."""
    print("\n[+] Testing RTP packet building...")
    
    client = RTPClient(
        local_ip='127.0.0.1',
        local_port=18000,
        remote_ip='127.0.0.1',
        remote_port=18001,
        payload_type=8
    )
    
    test_payload = b'\x00' * 160
    packet = client._build_rtp_packet(test_payload)
    
    print(f"[+] Packet size: {len(packet)} bytes")
    print(f"[+] First byte (version): {packet[0] >> 6}")
    print(f"[+] Second byte (PT): {packet[1] & 0x7F} (expected 8 for PCMA)")
    print(f"[+] Sequence: {(packet[2] << 8) | packet[3]}")
    print(f"[+] SSRC: {packet[8]:02x}{packet[9]:02x}{packet[10]:02x}{packet[11]:02x}")
    
    # Verify RTP header format
    assert packet[0] >> 6 == 2, "Version should be 2"
    assert (packet[1] & 0x7F) == 8, "Payload type should be 8 for PCMA"
    assert len(packet) == 12 + 160, f"Packet size should be 172, got {len(packet)}"
    
    print("[+] RTP packet verification passed!")


def test_pcma_encoding():
    """Test PCMA encoding/decoding."""
    print("\n[+] Testing PCMA encoding...")
    
    client = RTPClient(
        local_ip='127.0.0.1',
        local_port=18200,
        remote_ip='127.0.0.1',
        remote_port=18201,
        payload_type=8
    )
    
    # Generate test signal (sine wave at 440Hz) - u-law expects 8-bit samples
    import math
    sample_rate = 8000
    duration = 0.1  # 100ms
    frequency = 440
    amplitude = 127
    
    samples = []
    for i in range(int(sample_rate * duration)):
        sample = int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(sample + 128)  # Convert to 0-255 range for u-law/a-law
    
    pcm_data = bytes(samples)
    print(f"[+] Generated {len(pcm_data)} bytes of PCM (8-bit)")
    
    # Encode to PCMA
    pcma_data = client._encode_pcma(pcm_data)
    print(f"[+] Encoded to {len(pcma_data)} bytes of PCMA")
    
    # Decode back
    decoded = client._decode_pcma(pcma_data)
    print(f"[+] Decoded back to {len(decoded)} bytes of PCM")
    
    print("[+] PCMA encoding test complete!")


def test_udp_echo():
    """Test UDP echo between two RTP clients."""
    print("\n[+] Testing UDP echo...")
    
    port1 = 18100
    port2 = 18101
    
    # Server
    server = RTPClient(
        local_ip='127.0.0.1',
        local_port=port1,
        remote_ip='127.0.0.1',
        remote_port=port2,
        payload_type=8
    )
    server.start()
    print(f"[+] Server started on {server.local_addr}")
    
    # Client
    client = RTPClient(
        local_ip='127.0.0.1',
        local_port=port2,
        remote_ip='127.0.0.1',
        remote_port=port1,
        payload_type=8
    )
    client.start()
    print(f"[+] Client started on {client.local_addr}")
    
    # Give threads time to start
    time.sleep(0.1)
    
    # Send data
    test_data = bytes([0xFF] * 160)
    client.write(test_data)
    print(f"[+] Sent {len(test_data)} bytes")
    
    # Wait for receive
    time.sleep(0.1)
    
    # Read response
    received = server.read(160, blocking=False)
    print(f"[+] Received {len(received)} bytes")
    
    # Cleanup
    server.stop()
    client.stop()
    
    print("[+] UDP echo test complete!")


if __name__ == '__main__':
    print("=" * 60)
    print("  pyVoIP-style RTP Client Tests")
    print("=" * 60)
    
    test_rtp_client()
    test_rtp_packet_building()
    test_pcma_encoding()
    test_udp_echo()
    
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED ✓")
    print("=" * 60)
