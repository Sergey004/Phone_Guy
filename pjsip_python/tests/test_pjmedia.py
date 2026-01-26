"""
Tests for pjmedia - Media Layer
"""

import sys
import numpy as np
sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.pjmedia.codec import (
    CodecID, G711Codec, L16Codec, create_codec, get_codec_name,
    G711_ALAW, G711_ULAW
)
from pjsip_python.pjmedia.rtp import RtpSession, RtpPacket, RtpHeader, create_rtp_session
from pjsip_python.utils import (
    numpy_to_pcm16, pcm16_to_numpy,
    numpy_to_g711, g711_to_numpy,
    resample_audio
)


def test_g711_codec():
    """Test G.711 codec operations."""
    print("Testing G.711 Codec...")

    codec_a = G711Codec(a_law=True)
    codec_u = G711Codec(a_law=False)

    assert codec_a.name == "PCMA"
    assert codec_u.name == "PCMU"
    assert codec_a.id == CodecID.PCMA
    assert codec_u.id == CodecID.PCMU

    pcm_data = b'\x00\x00\xff\xff\x12\x34\x56\x78'

    alaw_encoded = codec_a.encode(pcm_data)
    ulaw_encoded = codec_u.encode(pcm_data)

    assert len(alaw_encoded) == len(pcm_data) // 2
    assert len(ulaw_encoded) == len(pcm_data) // 2

    alaw_decoded = codec_a.decode(alaw_encoded)
    ulaw_decoded = codec_u.decode(ulaw_encoded)

    assert len(alaw_decoded) == len(pcm_data)
    assert len(ulaw_decoded) == len(pcm_data)

    print("  - G.711 encode/decode passed")


def test_g711_functions():
    """Test G.711 conversion functions."""
    print("Testing G.711 conversion functions (skipped - using codec methods)...")
    print("  - G.711 conversion functions skipped")


def test_rtp_session():
    """Test RTP session."""
    print("Testing RTP Session...")
    
    rtp = RtpSession(
        ssrc=0x12345678,
        sequence=1000,
        timestamp=0,
        payload_type=0
    )
    
    assert rtp.ssrc == 0x12345678
    assert rtp.sequence == 1000
    assert rtp.timestamp == 0
    
    rtp.set_payload_type(8)
    rtp.set_clock_rate(8000)
    
    payload = b'\x00\x01\x02\x03\x04\x05\x06\x07'
    packet_bytes = rtp.encode_rtp(payload)
    
    header = RtpHeader()
    assert header.unpack(packet_bytes)
    assert header.payload_type == 8
    assert header.sequence == 1000
    assert header.ssrc == 0x12345678
    
    print("  - RTP session operations passed")


def test_numpy_conversion():
    """Test numpy audio conversions."""
    print("Testing numpy conversions...")

    audio = np.array([0, 1000, -1000, 500, -500], dtype=np.int16)

    pcm = numpy_to_pcm16(audio)
    assert len(pcm) == len(audio) * 2

    back = pcm16_to_numpy(pcm)
    assert np.array_equal(audio, back)

    from pjsip_python.utils import numpy_to_g711, g711_to_numpy

    g711_enc = numpy_to_g711(audio, a_law=True)
    assert len(g711_enc) == len(audio)

    back = g711_to_numpy(g711_enc.tobytes(), a_law=True)
    assert len(back.tobytes()) == len(pcm)

    print("  - numpy conversions passed")


def test_resample():
    """Test audio resampling."""
    print("Testing audio resampling...")
    
    audio = np.random.randn(1600).astype(np.float32)  # 100ms at 16kHz
    
    resampled = resample_audio(audio, 16000, 8000)
    assert len(resampled) == 800  # Should be half the length
    
    print("  - audio resampling passed")


def test_singleton_codecs():
    """Test singleton codec instances."""
    print("Testing singleton codecs...")
    
    assert G711_ALAW.name == "PCMA"
    assert G711_ULAW.name == "PCMU"
    
    print("  - singleton codecs passed")


def main():
    print("=" * 50)
    print("Running pjmedia tests")
    print("=" * 50)
    
    test_g711_codec()
    test_g711_functions()
    test_rtp_session()
    test_numpy_conversion()
    test_resample()
    test_singleton_codecs()
    
    print("=" * 50)
    print("All pjmedia tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    main()
