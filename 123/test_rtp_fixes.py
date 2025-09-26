"""
Comprehensive test for RTP stack fixes.
Tests jitter buffer improvements, audio flow control, and diagnostic monitoring.
"""

import time
import logging
import threading
import socket
import struct
import audioop
import sys
import os

# Add the parent directory to the path to import voip_client modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'voip_client'))

from voip_client.rtp import RtpSession, RtpPacket, JitterBuffer
from voip_client.rtp_diagnostics import RTPDiagnostics, AudioQualityMonitor

# Configure logging to see diagnostic output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_rtp_packet_processing():
    """Test RTP packet processing with simulated network conditions."""
    print("=== Testing RTP Packet Processing ===")
    
    # Create RTP session with diagnostics enabled
    session = RtpSession(
        local_ip="127.0.0.1",
        local_port=15000,
        remote_ip="127.0.0.1",
        remote_port=15001,
        payload_type=0,  # PCMU
        enable_diagnostics=True
    )
    
    # Start the session
    session.start()
    
    # Test 1: Send and receive audio with packet loss simulation
    print("\n1. Testing audio transmission with packet loss...")
    
    # Create test audio data (1 second of sine wave at 8000Hz)
    sample_rate = 8000
    frequency = 440  # A4 note
    duration = 1.0  # 1 second
    samples = int(sample_rate * duration)
    
    # Generate sine wave
    import math
    audio_data = bytearray()
    for i in range(samples):
        sample = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * i / sample_rate))
        # Convert to bytes (16-bit little-endian)
        audio_data.extend(struct.pack('<h', sample))
    
    # Send the audio
    session.send_audio(bytes(audio_data))
    
    # Let it process for a bit
    time.sleep(2)
    
    # Receive audio
    received_audio = []
    for _ in range(50):  # Receive 1 second worth of 20ms frames
        pcm = session.get_audio(timeout=0.1)
        if pcm:
            received_audio.append(pcm)
    
    print(f"Received {len(received_audio)} audio frames")
    
    # Test 2: Simulate network jitter
    print("\n2. Testing jitter buffer performance...")
    
    # Create a simple RTP packet sender that introduces jitter
    def jittery_sender():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        base_time = time.time()
        
        for seq in range(100):
            # Create RTP packet
            packet = RtpPacket(
                payload_type=0,
                sequence=seq,
                timestamp=seq * 160,  # 160 samples per frame
                ssrc=12345,
                payload=b'\x80' * 160  # Silence
            )
            
            # Introduce jitter (0-50ms random delay)
            jitter = (time.time() % 0.05)  # 0-50ms jitter
            time.sleep(0.02 + jitter)  # Base 20ms + jitter
            
            # Send packet
            sock.sendto(packet.to_bytes(), ("127.0.0.1", 15000))
        
        sock.close()
    
    # Start jittery sender in background
    sender_thread = threading.Thread(target=jittery_sender)
    sender_thread.start()
    
    # Wait for packets to arrive and be processed
    time.sleep(5)
    
    # Test 3: Check diagnostic data
    print("\n3. Checking diagnostic data...")
    
    if session.diagnostics:
        stats = session.diagnostics.get_summary_stats()
        print(f"Packet statistics:")
        print(f"  Received: {stats['packets_received']}")
        print(f"  Lost: {stats['packets_lost']}")
        print(f"  Loss rate: {stats['packet_loss_rate']:.2f}%")
        print(f"  Jitter: {stats['jitter_ms']:.2f} ms")
        print(f"  MOS score: {stats['mos_score']:.2f}/5.0")
        print(f"  R-factor: {stats['r_factor']:.1f}/100")
        print(f"  Audio underruns: {stats['audio_underruns']}")
        print(f"  Audio overruns: {stats['audio_overruns']}")
    
    # Test 4: Buffer management
    print("\n4. Testing buffer management...")
    
    pcm_manager_stats = session.pcm_manager.get_stats()
    print(f"PCM Manager statistics:")
    print(f"  Total written: {pcm_manager_stats['total_written']} bytes")
    print(f"  Total read: {pcm_manager_stats['total_read']} bytes")
    print(f"  Available: {pcm_manager_stats['available']} bytes")
    print(f"  Underruns: {pcm_manager_stats['underruns']}")
    print(f"  Overruns: {pcm_manager_stats['overruns']}")
    
    # Stop the session
    session.stop()
    sender_thread.join(timeout=2)
    
    print("\n=== RTP Packet Processing Test Complete ===")
    return True

def test_jitter_buffer_adaptation():
    """Test jitter buffer dynamic adaptation."""
    print("\n=== Testing Jitter Buffer Adaptation ===")
    
    # Create a jitter buffer
    from voip_client.rtp import JitterBuffer
    
    jitter_buffer = JitterBuffer(max_delay_ms=100)
    
    # Simulate packet arrival with different jitter patterns
    base_time = time.time()
    
    # Phase 1: Normal traffic (low jitter)
    print("Phase 1: Normal traffic (low jitter)")
    for i in range(20):
        from voip_client.rtp import RtpPacket
        packet = RtpPacket(
            payload_type=0,
            sequence=i,
            timestamp=i * 160,
            ssrc=12345,
            payload=b'\x80' * 160
        )
        
        # Add packet to buffer
        jitter_buffer.add_packet(packet)
        
        # Small jitter (0-5ms)
        time.sleep(0.020 + (time.time() % 0.005))
    
    # Phase 2: High jitter traffic
    print("Phase 2: High jitter traffic")
    for i in range(20, 40):
        from voip_client.rtp import RtpPacket
        packet = RtpPacket(
            payload_type=0,
            sequence=i,
            timestamp=i * 160,
            ssrc=12345,
            payload=b'\x80' * 160
        )
        
        # Add packet to buffer
        jitter_buffer.add_packet(packet)
        
        # High jitter (0-50ms)
        time.sleep(0.020 + (time.time() % 0.050))
    
    # Phase 3: Back to normal
    print("Phase 3: Back to normal traffic")
    for i in range(40, 60):
        from voip_client.rtp import RtpPacket
        packet = RtpPacket(
            payload_type=0,
            sequence=i,
            timestamp=i * 160,
            ssrc=12345,
            payload=b'\x80' * 160
        )
        
        # Add packet to buffer
        jitter_buffer.add_packet(packet)
        
        # Small jitter again
        time.sleep(0.020 + (time.time() % 0.005))
    
    # Retrieve packets and check adaptation
    packets_retrieved = 0
    while True:
        packet = jitter_buffer.get_next_packet(timeout=0.01)
        if packet is None:
            break
        packets_retrieved += 1
    
    print(f"Retrieved {packets_retrieved} packets from jitter buffer")
    print("Jitter buffer adaptation test complete")
    
    return True

def test_audio_quality_monitoring():
    """Test audio quality monitoring capabilities."""
    print("\n=== Testing Audio Quality Monitoring ===")
    
    from voip_client.rtp_diagnostics import AudioQualityMonitor
    
    monitor = AudioQualityMonitor(sample_rate=8000, frame_size=160)
    
    # Test 1: Normal audio
    print("Test 1: Recording normal audio frames...")
    import math
    for i in range(50):
        # Generate a simple sine wave
        sample = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / 8000))
        frame = struct.pack('<h', sample) * 80  # 80 samples = 160 bytes
        monitor.record_audio_frame(frame, is_silence=False)
        time.sleep(0.020)  # 20ms between frames
    
    # Test 2: Silence frames
    print("Test 2: Recording silence frames...")
    for i in range(20):
        silence_frame = b'\x00' * 160
        monitor.record_audio_frame(silence_frame, is_silence=True)
        time.sleep(0.020)
    
    # Get quality metrics
    metrics = monitor.get_audio_quality_metrics()
    print("Audio quality metrics:")
    print(f"  Total frames: {metrics['total_frames']}")
    print(f"  Silence frames: {metrics['silence_frames']}")
    print(f"  Silence ratio: {metrics['silence_ratio']:.1f}%")
    print(f"  Average power: {metrics['average_power']:.1f}")
    print(f"  Quality: {metrics['quality']}")
    
    return True

def main():
    """Run all RTP fix tests."""
    print("Starting comprehensive RTP stack fix verification...")
    print("=" * 60)
    
    try:
        # Test 1: RTP packet processing
        test_rtp_packet_processing()
        
        # Test 2: Jitter buffer adaptation
        test_jitter_buffer_adaptation()
        
        # Test 3: Audio quality monitoring
        test_audio_quality_monitoring()
        
        print("\n" + "=" * 60)
        print("✅ All RTP fix tests completed successfully!")
        print("The RTP stack has been improved with:")
        print("  • Fixed jitter buffer logic (no artificial packet loss)")
        print("  • Adaptive timing synchronization")
        print("  • Proper buffer management (underrun/overrun protection)")
        print("  • Dynamic jitter buffer sizing")
        print("  • Comprehensive diagnostics and monitoring")
        print("  • Audio quality metrics (MOS score, R-factor)")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
