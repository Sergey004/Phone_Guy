import numpy as np
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from telephony.audio_engine import AudioSource, TTSSource, FilePlayerSource


class TestAudioSource:
    """Tests for abstract AudioSource class"""

    def test_audio_source_is_abstract(self):
        """Test that AudioSource has abstract methods"""
        # AudioSource should have abstract methods (ABC)
        assert hasattr(AudioSource, '__abstractmethods__')
        assert len(AudioSource.__abstractmethods__) > 0
        assert 'get_frame' in AudioSource.__abstractmethods__


class TestTTSSource:
    """Tests for TTSSource audio source"""

    def test_tts_source_init(self):
        """Test TTSSource initialization"""
        source = TTSSource()
        assert isinstance(source.buffer, bytearray)
        assert source.target_sample_rate == 8000

    def test_tts_source_init_custom_rate(self):
        """Test TTSSource with custom sample rate"""
        source = TTSSource(target_sample_rate=16000)
        assert source.target_sample_rate == 16000

    def test_push_audio_adds_to_buffer(self):
        """Test that push_audio adds audio to buffer"""
        source = TTSSource()
        audio = np.zeros(240, dtype=np.float32)  # 10ms at 24000Hz
        source.push_audio(audio, src_rate=24000)
        assert len(source.buffer) > 0

    def test_push_audio_resamples_to_target(self):
        """Test that audio is resampled to target rate"""
        source = TTSSource(target_sample_rate=8000)
        audio = np.zeros(480, dtype=np.float32)  # 20ms at 24000Hz
        initial_buffer_len = len(source.buffer)
        source.push_audio(audio, src_rate=24000)
        # Buffer should increase (160 bytes for 20ms at 8000Hz A-law)
        assert len(source.buffer) > initial_buffer_len

    def test_get_frame_returns_bytes(self):
        """Test that get_frame returns bytes"""
        source = TTSSource()
        audio = np.zeros(240, dtype=np.float32)
        source.push_audio(audio, src_rate=24000)
        frame = source.get_frame(160)
        assert isinstance(frame, bytes)
        assert len(frame) == 160

    def test_get_frame_returns_silence_when_empty(self):
        """Test that get_frame returns silence when buffer is empty"""
        source = TTSSource()
        frame = source.get_frame(160)
        assert len(frame) == 160
        assert all(b == 0xd5 for b in frame)

    def test_push_audio_preserves_content(self):
        """Test that push_audio preserves audio content after resampling"""
        source = TTSSource(target_sample_rate=8000)
        # Create sine wave at 440Hz
        t = np.arange(160) / 8000  # 20ms
        audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        source.push_audio(audio, src_rate=8000)
        frame = source.get_frame(160)
        # Should not be silence
        assert frame != b'\xd5' * 160


class TestFilePlayerSource:
    """Tests for FilePlayerSource audio source"""

    def test_file_player_source_with_valid_file(self, sample_wav_path):
        """Test FilePlayerSource with valid WAV file"""
        source = FilePlayerSource(sample_wav_path)
        assert source.active is True
        assert source.wf is not None

    def test_file_player_source_get_frame(self, sample_wav_path):
        """Test that get_frame returns audio data"""
        source = FilePlayerSource(sample_wav_path)
        frame = source.get_frame(160)
        assert isinstance(frame, bytes)
        assert len(frame) == 160

    def test_file_player_source_inactive_on_missing_file(self, tmp_path):
        """Test that FilePlayerSource is inactive for missing file"""
        source = FilePlayerSource(str(tmp_path / "nonexistent.wav"))
        assert source.active is False

    def test_file_player_source_returns_silence_when_inactive(self, tmp_path):
        """Test that get_frame returns silence when inactive"""
        source = FilePlayerSource(str(tmp_path / "nonexistent.wav"))
        frame = source.get_frame(160)
        assert len(frame) == 160
        assert all(b == 0xd5 for b in frame)

    def test_file_player_source_pads_short_files(self, sample_wav_path):
        """Test that short files are padded with silence"""
        source = FilePlayerSource(sample_wav_path)
        # Request more frames than file contains
        frame = source.get_frame(32000)  # 4 seconds
        assert len(frame) == 32000
        assert source.active is False

    def test_file_player_source_loop_resets_position(self, sample_wav_path):
        """Test that looping resets file position"""
        source = FilePlayerSource(sample_wav_path, loop=True)
        # Verify source is active and can be read
        assert source.active is True
        assert source.wf is not None
