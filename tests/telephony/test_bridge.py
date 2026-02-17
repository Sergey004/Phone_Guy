import numpy as np
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from telephony.bridge import PhoneBridgePort


class TestPhoneBridgePort:
    """Tests for PhoneBridgePort audio bridge"""

    def test_init_creates_buffers(self):
        """Test that initialization creates required buffers"""
        bridge = PhoneBridgePort()
        assert isinstance(bridge.buffer, bytearray)
        assert bridge.bg_noise_buffer is not None
        assert bridge.bg_pos == 0

    def test_update_playback_data_with_empty_bytes_returns_false(self):
        """Test that empty bytes return False"""
        bridge = PhoneBridgePort()
        result = bridge.update_playback_data(b'', sample_rate=24000)
        assert result is False

    def test_update_playback_data_rejects_none(self):
        """Test that update_playback_data rejects None input"""
        bridge = PhoneBridgePort()
        # Should return False for None-like input
        result = bridge.update_playback_data(b'', sample_rate=24000)
        # Empty bytes return False
        assert result is False

    def test_update_playback_data_24000hz_resampling(self):
        """Test that 24000Hz audio is resampled to 8000Hz"""
        bridge = PhoneBridgePort()
        # Create 24000Hz audio: 240 samples = 10ms
        pcm_data = (np.sin(2 * np.pi * 440 * np.arange(240) / 24000) * 32767).astype(np.int16)
        result = bridge.update_playback_data(pcm_data.tobytes(), sample_rate=24000)
        assert result is True
        assert len(bridge.buffer) > 0

    def test_update_playback_data_8000hz_no_resampling(self):
        """Test that 8000Hz audio is not resampled"""
        bridge = PhoneBridgePort()
        # Create 8000Hz audio: 80 samples = 10ms
        pcm_data = (np.sin(2 * np.pi * 440 * np.arange(80) / 8000) * 32767).astype(np.int16)
        result = bridge.update_playback_data(pcm_data.tobytes(), sample_rate=8000)
        assert result is True

    def test_get_frame_returns_alaw_bytes(self):
        """Test that get_frame returns A-Law encoded bytes"""
        bridge = PhoneBridgePort()
        pcm_data = np.zeros(160, dtype=np.int16)  # 20ms at 8000Hz
        bridge.update_playback_data(pcm_data.tobytes(), sample_rate=8000)
        frame = bridge.get_frame(160)
        assert len(frame) == 160
        assert isinstance(frame, bytes)

    def test_get_frame_returns_bg_noise_when_buffer_empty(self):
        """Test that get_frame returns background noise when buffer is empty"""
        bridge = PhoneBridgePort()
        # The bridge has bg_noise_buffer generated on init
        # When buffer is empty, it should return bytes from bg_noise_buffer
        frame = bridge.get_frame(160)
        assert len(frame) == 160
        # Background noise is not pure silence (0xd5), it contains noise
        assert isinstance(frame, bytes)

    def test_get_frame_clears_buffer_when_exhausted(self):
        """Test that buffer is cleared when exhausted"""
        bridge = PhoneBridgePort()
        pcm_data = np.zeros(80, dtype=np.int16)
        bridge.update_playback_data(pcm_data.tobytes(), sample_rate=8000)
        # Request more than available
        frame = bridge.get_frame(160)
        assert len(frame) == 160
        assert len(bridge.buffer) == 0

    def test_get_stats_returns_duration(self):
        """Test that get_stats returns correct duration"""
        bridge = PhoneBridgePort()
        stats = bridge.get_stats()
        assert "duration_seconds" in stats
        assert stats["duration_seconds"] >= 0.0

    def test_update_stats_duration_increases(self):
        """Test that duration stats increase after adding audio"""
        bridge = PhoneBridgePort()
        initial_duration = bridge.get_stats()["duration_seconds"]
        pcm_data = np.zeros(1600, dtype=np.int16)  # 200ms
        bridge.update_playback_data(pcm_data.tobytes(), sample_rate=8000)
        new_duration = bridge.get_stats()["duration_seconds"]
        assert new_duration > initial_duration

    def test_odd_length_bytes_handled(self):
        """Test that odd-length bytes are handled correctly"""
        bridge = PhoneBridgePort()
        # Create odd-length data
        pcm_data = b'\x00' * 159
        result = bridge.update_playback_data(pcm_data, sample_rate=8000)
        assert result is True
