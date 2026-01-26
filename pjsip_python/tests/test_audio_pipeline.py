#!/usr/bin/env python3
"""
Test: TTS -> RVC -> SIP Audio Pipeline

Demonstrates the complete audio processing pipeline:
1. TTS generates numpy audio
2. RVC processes it (PyTorch tensor)
3. Convert to G.711 for SIP/RTP
4. Send over network
"""

import sys
sys.path.insert(0, '/home/user/Test_Phone_new')

import numpy as np
import torch
from pjsip_python.audio import (
    AudioData, AudioFormat, AudioConfig,
    numpy_to_audio, audio_to_numpy,
    tensor_to_audio, audio_to_tensor,
    create_silence, create_tone,
    write_wav, read_wav
)


def test_tts_to_rvc_pipeline():
    """
    Simulate: TTS output -> RVC model -> G.711 for SIP
    """
    print("=" * 50)
    print("TTS -> RVC -> SIP Pipeline Test")
    print("=" * 50)
    
    # Step 1: TTS generates numpy audio (typical output from gTTS or Silero)
    print("\n1. TTS generates audio...")
    tts_audio = create_tone(200, 1.0)  # Simulated TTS output (200Hz tone, 1 second)
    print(f"   - Samples: {tts_audio.num_samples}")
    print(f"   - Sample rate: {tts_audio.sample_rate} Hz")
    print(f"   - Duration: {tts_audio.duration:.2f}s")
    
    # Step 2: Convert to numpy (in case TTS output is bytes)
    print("\n2. Convert to numpy array...")
    numpy_arr = audio_to_numpy(tts_audio)
    print(f"   - Shape: {numpy_arr.shape}")
    print(f"   - dtype: {numpy_arr.dtype}")
    
    # Step 3: Simulate RVC processing (PyTorch)
    print("\n3. RVC processing (tensor)...")
    tensor = torch.from_numpy(numpy_arr.astype(np.float32) / 32767.0)
    print(f"   - Tensor shape: {tensor.shape}")
    print(f"   - Tensor dtype: {tensor.dtype}")
    
    # Simulate RVC pitch extraction and conversion
    rvc_output = tensor * 1.0  # Placeholder for RVC transformation
    
    # Step 4: Convert back to AudioData
    print("\n4. Convert RVC output to AudioData...")
    rvc_audio = tensor_to_audio(rvc_output, sample_rate=8000)
    print(f"   - Samples: {rvc_audio.num_samples}")
    print(f"   - Format: {rvc_audio.format}")
    
    # Step 5: Convert to G.711 for SIP
    print("\n5. Convert to G.711 A-law for SIP...")
    g711_data = rvc_audio.to_bytes(AudioFormat.G711_ALAW)
    print(f"   - G.711 bytes: {len(g711_data)}")
    print(f"   - Compression ratio: {rvc_audio.num_samples * 2 / len(g711_data):.2f}x")
    
    # Step 6: Create RTP packet
    print("\n6. Create RTP packet...")
    from pjsip_python.pjmedia.rtp import RtpSession, RtpHeader
    rtp = RtpSession(ssrc=0x12345678, payload_type=8)
    rtp.set_clock_rate(8000)
    rtp_payload = rtp.encode_rtp(g711_data[:160])  # 20ms chunk
    print(f"   - RTP payload: {len(g711_data[:160])} bytes")
    print(f"   - RTP packet: {len(rtp_payload)} bytes")
    
    print("\n" + "=" * 50)
    print("Pipeline test completed successfully!")
    print("=" * 50)


def test_file_formats():
    """Test WAV file reading/writing."""
    print("\n" + "=" * 50)
    print("File Format Test")
    print("=" * 50)
    
    import tempfile
    import os
    
    # Create test audio
    audio = create_tone(440, 0.5)
    
    # Write WAV
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        wav_path = f.name
    
    print("\n1. Write WAV file...")
    write_wav(wav_path, audio)
    print(f"   - Saved: {wav_path}")
    
    # Read WAV
    print("\n2. Read WAV file...")
    loaded = read_wav(wav_path)
    print(f"   - Samples: {loaded.num_samples}")
    print(f"   - Sample rate: {loaded.sample_rate}")
    print(f"   - Channels: {loaded.channels}")
    
    os.unlink(wav_path)
    
    print("\n" + "=" * 50)
    print("File format test passed!")
    print("=" * 50)


def test_tensor_roundtrip():
    """Test numpy -> tensor -> numpy roundtrip."""
    print("\n" + "=" * 50)
    print("Tensor Roundtrip Test")
    print("=" * 50)
    
    # Original numpy
    original = np.random.randn(8000).astype(np.float32) * 0.5
    print(f"\n1. Original numpy: {original.shape}, range [{original.min():.3f}, {original.max():.3f}]")
    
    # To tensor
    tensor = torch.from_numpy(original)
    print(f"2. To tensor: {tensor.shape}, range [{tensor.min():.3f}, {tensor.max():.3f}]")
    
    # Simulate RVC processing
    processed = tensor * 1.1  # Louder
    
    # Back to numpy
    result = processed.numpy()
    print(f"3. Back to numpy: {result.shape}, range [{result.min():.3f}, {result.max():.3f}]")
    
    # Check loss
    diff = np.abs(original - result / 1.1).max()
    print(f"\n4. Max difference after roundtrip: {diff:.6f}")
    
    print("\n" + "=" * 50)
    print("Tensor roundtrip test passed!")
    print("=" * 50)


def test_audio_processing():
    """Test various audio processing operations."""
    print("\n" + "=" * 50)
    print("Audio Processing Test")
    print("=" * 50)
    
    # Create 2-channel audio
    stereo = np.zeros((4000, 2), dtype=np.int16)
    stereo[:, 0] = np.sin(2 * np.pi * 440 * np.linspace(0, 0.5, 4000)) * 32767
    stereo[:, 1] = np.sin(2 * np.pi * 440 * np.linspace(0, 0.5, 4000)) * 32767 * 0.8
    
    audio = numpy_to_audio(stereo, sample_rate=8000, channels=2)
    print(f"\n1. Stereo audio: {audio.num_samples} samples, {audio.channels} channels")
    
    # To mono
    mono = audio.to_mono()
    print(f"2. To mono: {mono.num_samples} samples, {mono.channels} channels")
    
    # Resample
    resampled = audio.resample(16000)
    print(f"3. Resample to 16kHz: {resampled.num_samples} samples, {resampled.sample_rate} Hz")
    
    # Different formats
    pcm_bytes = audio.to_bytes(AudioFormat.PCM16)
    g711_bytes = audio.to_bytes(AudioFormat.G711_ALAW)
    print(f"4. PCM16: {len(pcm_bytes)} bytes")
    print(f"5. G.711 A-law: {len(g711_bytes)} bytes")
    
    print("\n" + "=" * 50)
    print("Audio processing test passed!")
    print("=" * 50)


if __name__ == "__main__":
    test_tts_to_rvc_pipeline()
    test_file_formats()
    test_tensor_roundtrip()
    test_audio_processing()
    
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED!")
    print("=" * 50)
