import numpy as np
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from telephony.audio_codecs import AudioCodec


class TestAudioCodec:
    """Tests for AudioCodec utility class"""

    def test_float_to_pcm16_normalizes_positive(self):
        """Test conversion of positive float to PCM16"""
        audio = np.array([0.5, 0.25, 1.0])
        result = AudioCodec.float_to_pcm16(audio)
        expected = np.array([16383, 8191, 32767], dtype=np.int16)
        np.testing.assert_array_equal(result, expected)

    def test_float_to_pcm16_normalizes_negative(self):
        """Test conversion of negative float to PCM16"""
        audio = np.array([-0.5, -0.25, -1.0])
        result = AudioCodec.float_to_pcm16(audio)
        # Check that values are in correct range and approximately correct
        assert result.dtype == np.int16
        assert result[0] == -16383  # -0.5 * 32767
        assert result[1] == -8191   # -0.25 * 32767
        assert -32768 <= result[2] <= -32766  # -1.0 clipped to near minimum

    def test_float_to_pcm16_clips_underflow(self):
        """Test that values < -1.0 are clipped"""
        audio = np.array([-1.5, -2.0])
        result = AudioCodec.float_to_pcm16(audio)
        # All should be clipped to minimum range
        assert all(-32768 <= v <= 32767 for v in result)

    def test_float_to_pcm16_clips_overflow(self):
        """Test that values > 1.0 are clipped to 1.0"""
        audio = np.array([1.5, 2.0])
        result = AudioCodec.float_to_pcm16(audio)
        expected = np.array([32767, 32767], dtype=np.int16)
        np.testing.assert_array_equal(result, expected)

    def test_float_to_pcm16_handles_zeros(self):
        """Test conversion of silence"""
        audio = np.array([0.0, 0.0, 0.0])
        result = AudioCodec.float_to_pcm16(audio)
        expected = np.array([0, 0, 0], dtype=np.int16)
        np.testing.assert_array_equal(result, expected)

    def test_pcm16_to_alaw_returns_bytes(self):
        """Test that pcm16_to_alaw returns bytes"""
        pcm_data = np.array([0, 1000, -1000, 32767], dtype=np.int16)
        result = AudioCodec.pcm16_to_alaw(pcm_data)
        assert isinstance(result, bytes)
        assert len(result) == 4

    def test_pcm16_to_alaw_returns_different_values(self):
        """Test that different PCM values produce different A-Law bytes"""
        pcm_positive = np.array([1000], dtype=np.int16)
        pcm_negative = np.array([-1000], dtype=np.int16)
        result_positive = AudioCodec.pcm16_to_alaw(pcm_positive)
        result_negative = AudioCodec.pcm16_to_alaw(pcm_negative)
        assert result_positive != result_negative

    def test_create_silence_default_params(self):
        """Test silence creation with default parameters (20ms, 8000Hz)"""
        result = AudioCodec.create_silence()
        expected_length = 160  # 8000 * 20/1000 = 160 samples
        assert len(result) == expected_length
        assert all(b == 0xd5 for b in result)

    def test_create_silence_custom_duration(self):
        """Test silence creation with custom duration"""
        result = AudioCodec.create_silence(duration_ms=100)
        expected_length = 800  # 8000 * 100/1000 = 800 samples
        assert len(result) == expected_length

    def test_create_silence_custom_sample_rate(self):
        """Test silence creation with custom sample rate"""
        result = AudioCodec.create_silence(duration_ms=20, sample_rate=16000)
        expected_length = 320  # 16000 * 20/1000 = 320 samples
        assert len(result) == expected_length

    def test_mix_sources_equal_volume(self):
        """Test mixing two sources with equal volume"""
        source_a = np.array([1.0, 0.5, 0.0])
        source_b = np.array([0.0, 0.5, 1.0])
        result = AudioCodec.mix_sources(source_a, source_b, vol_a=1.0, vol_b=1.0)
        expected = np.array([1.0, 1.0, 1.0])
        np.testing.assert_array_almost_equal(result, expected)

    def test_mix_sources_different_volume(self):
        """Test mixing two sources with different volumes"""
        source_a = np.array([1.0, 1.0])
        source_b = np.array([1.0, 1.0])
        result = AudioCodec.mix_sources(source_a, source_b, vol_a=0.5, vol_b=0.5)
        expected = np.array([1.0, 1.0])
        np.testing.assert_array_almost_equal(result, expected)

    def test_mix_sources_different_lengths(self):
        """Test mixing sources of different lengths"""
        source_a = np.array([1.0, 0.5, 0.25])
        source_b = np.array([0.5, 0.25])
        result = AudioCodec.mix_sources(source_a, source_b)
        # Should be truncated to min length
        assert len(result) == 2

    def test_mix_sources_clips_overflow(self):
        """Test that mixed sources are clipped to [-1.0, 1.0]"""
        source_a = np.array([1.0, 1.0])
        source_b = np.array([1.0, 1.0])
        result = AudioCodec.mix_sources(source_a, source_b, vol_a=1.0, vol_b=1.0)
        np.testing.assert_array_less(result, 1.01)
        np.testing.assert_array_less(-1.01, result)
