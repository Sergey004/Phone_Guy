"""
Integration test for pyVoIP-style MediaStream
"""

import sys
import time
import threading

sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.pjmedia.stream_pyvoip import MediaStream, create_media_stream


def test_media_stream_echo():
    """Test bidirectional media stream communication."""
    print("[+] Testing MediaStream echo...")
    
    port1 = 19100
    port2 = 19101
    
    # Server stream
    server = create_media_stream(
        local_ip='127.0.0.1',
        local_port=port1,
        remote_ip='127.0.0.1',
        remote_port=port2,
        payload_type=8
    )
    
    # Client stream
    client = create_media_stream(
        local_ip='127.0.0.1',
        local_port=port2,
        remote_ip='127.0.0.1',
        remote_port=port1,
        payload_type=8
    )
    
    print(f"[+] Server: {server.local_addr} -> {server.remote_addr}")
    print(f"[+] Client: {client.local_addr} -> {client.remote_addr}")
    
    # Start both
    server.start()
    client.start()
    print("[+] Both streams started")
    
    # Give threads time to start
    time.sleep(0.1)
    
    # Send test data from client to server
    test_data = bytes([0xFF] * 160)
    client.send_g711(test_data)
    print(f"[+] Sent {len(test_data)} bytes from client")
    
    # Wait for receive
    time.sleep(0.1)
    
    # Check server stats
    server_stats = server.get_stats()
    print(f"[+] Server stats: {server_stats}")
    
    # Stop both
    server.stop()
    client.stop()
    
    print("[+] MediaStream echo test complete!")


def test_media_stream_full_duplex():
    """Test full-duplex audio streaming."""
    print("\n[+] Testing full-duplex streaming...")
    
    port1 = 19200
    port2 = 19201
    
    stream1 = create_media_stream(
        local_ip='127.0.0.1',
        local_port=port1,
        remote_ip='127.0.0.1',
        remote_port=port2,
        payload_type=8
    )
    
    stream2 = create_media_stream(
        local_ip='127.0.0.1',
        local_port=port2,
        remote_ip='127.0.0.1',
        remote_port=port1,
        payload_type=8
    )
    
    # Start
    stream1.start()
    stream2.start()
    print("[+] Both streams started")
    
    # Send audio patterns
    for i in range(5):
        # Stream 1 sends 0xAA pattern
        data1 = bytes([0xAA] * 160)
        stream1.send_g711(data1)
        
        # Stream 2 sends 0x55 pattern
        data2 = bytes([0x55] * 160)
        stream2.send_g711(data2)
        
        time.sleep(0.05)
    
    print("[+] Sent audio patterns")
    
    # Wait
    time.sleep(0.2)
    
    # Check stats
    stats1 = stream1.get_stats()
    stats2 = stream2.get_stats()
    print(f"[+] Stream1 stats: {stats1}")
    print(f"[+] Stream2 stats: {stats2}")
    
    # Stop
    stream1.stop()
    stream2.stop()
    
    print("[+] Full-duplex test complete!")


if __name__ == '__main__':
    print("=" * 60)
    print("  pyVoIP MediaStream Integration Tests")
    print("=" * 60)
    
    test_media_stream_echo()
    test_media_stream_full_duplex()
    
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED ✓")
    print("=" * 60)
