# AGENTS.md - Development Guidelines for Phone Guy Bot

This file provides guidelines for AI agents working on this codebase.

## Build/Lint/Test Commands

### Running the Application
```bash
# Activate virtual environment
source .venv/bin/activate

# Run main application (incoming calls mode)
python main_integration.py

# Run with specific target number (outgoing calls)
python main_integration.py  # Set TARGET_NUMBER in .env
```

### Linting with Ruff
```bash
# Check linting
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

### Testing with Pytest
```bash
# Run all tests
pytest

# Run single test file
pytest tests/test_specific_file.py

# Run single test function
pytest tests/test_file.py::test_function_name

# Run tests matching pattern
pytest -k "test_name_pattern"

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=.
```

### Type Checking
```bash
# mypy type checking (if installed)
mypy .
```

## Code Style Guidelines

### Imports
- Use absolute imports for modules within `telephony/` and `ai_core/`
- Group imports: stdlib → third-party → local
- Example:
  ```python
  import asyncio
  import logging
  import os

  import torch
  from dotenv import load_dotenv

  from ai_core.ai_service import phoneguy_reply
  from telephony.sip_rtp_client import SIPClient
  ```

### Formatting
- Use ruff formatter (config in `.ruff_cache/`)
- Line length: 100 characters (ruff default)
- Use blank lines to separate logical sections
- No trailing whitespace

### Types
- Use type hints for function signatures
- Prefer explicit types over `Any`
- Example:
  ```python
  async def synthesize(self, text: str) -> tuple[bytes, int]:
      ...
  ```

### Naming Conventions
- **Files**: snake_case (`sip_rtp_client.py`)
- **Classes**: PascalCase (`SIPClient`, `TTSAdapter`)
- **Functions/Variables**: snake_case (`get_frame`, `audio_source`)
- **Constants**: UPPER_SNAKE_CASE (`SIP_SERVER`, `LOCAL_IP`)
- **Private methods**: leading underscore (`_get_model()`)

### Error Handling
- Use `try/except` with specific exception types
- Log errors with `logger.error()`
- Propagate exceptions in async code when appropriate
- Example:
  ```python
  try:
      result = await function()
  except Exception as e:
      logger.error(f"Operation failed: {e}")
      raise
  ```

### Async/Await Patterns
- Use `async def` for I/O-bound operations
- Use `await` for async calls
- Use `asyncio.to_thread()` for CPU-bound operations
- Example:
  ```python
  async def process_audio(self, audio_data: bytes) -> np.ndarray:
      loop = asyncio.get_event_loop()
      result = await loop.run_in_executor(None, self._blocking_process, audio_data)
      return result
  ```

### Configuration
- All configurable values should be in `.env`
- Use `os.getenv()` with defaults
- Example:
  ```python
  SIP_USER = os.getenv('SIP_USER', '555533')
  RVC_ENABLED = os.getenv('RVC_ENABLED', 'true').lower() == 'true'
  ```

### Module Structure
- **telephony/**: SIP/RTP, audio streaming, codecs
- **ai_core/**: LLM, STT, TTS, RVC, document processing
- **main_integration.py**: Main orchestration (keep lean)

### Logging
- Use `logger = logging.getLogger(__name__)`
- Log levels: DEBUG for dev, INFO for normal, ERROR for failures
- Include context in log messages

### Audio Processing
- Sample rates: 8000Hz (telephony), 24000Hz/16000Hz (TTS output)
- Codec: G.711 A-law for SIP
- Use `audioop` for conversions

### Testing Guidelines
- Put tests in `tests/` directory (create if missing)
- Use `pytest-asyncio` for async tests
- Mock external services (SIP server, NVIDIA API)
- Test module boundaries between `telephony/` and `ai_core/`
