import pytest
import os
import sys
from unittest.mock import MagicMock, patch

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


@pytest.fixture
def mock_logger():
    """Mock logger for testing"""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.debug = MagicMock()
    return logger


@pytest.fixture
def sample_audio_bytes():
    """Sample PCM audio bytes (8kHz, 16-bit, mono)"""
    return b'\x00' * 1600  # 200ms of silence


@pytest.fixture
def sample_text():
    """Sample text for TTS/STT testing"""
    return "Hello, this is a test message"


@pytest.fixture
def mock_env():
    """Mock environment variables"""
    env_vars = {
        'SIP_USER': '555533',
        'SIP_PASSWORD': 'Test1234',
        'SIP_SERVER': '192.168.1.176:5060',
        'NVIDIA_API_KEY': 'test_key',
        'RVC_ENABLED': 'false',
        'TTS_ENGINE': 'turbo',
        'TTS_DEVICE': 'cpu',
    }
    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def sample_wav_path(tmp_path):
    """Create a temporary WAV file for testing"""
    import wave
    wav_file = tmp_path / "test.wav"
    with wave.open(str(wav_file), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b'\x00' * 16000)  # 2 seconds of silence
    return str(wav_file)
