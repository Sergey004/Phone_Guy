# pjsip_python

**Pure Python SIP/RTP Stack** - A complete implementation of SIP signaling and media transport for voice calls, inspired by PJSIP but written entirely in Python.

```
Author: Sergey004
Version: 1.0.0
```

## Overview

This is a research/educational implementation of a SIP/RTP stack in pure Python. It's designed for:

- **Voice calls over IP** - Full SIP signaling and RTP media transport
- **TTS Integration** - Convert text-to-speech audio to G.711 for transmission
- **RVC Integration** - Process audio with RVC models (PyTorch support)
- **NAT Traversal** - STUN, ICE, and TURN support for complex networks

## Architecture

```
pjsip_python/
├── pjlib/              # Foundation Layer (~600 lines)
│   ├── sock.py         # Socket abstraction
│   ├── ioqueue.py      # Async I/O (epoll/select)
│   ├── timer.py        # Timer heap
│   ├── pool.py         # Memory pool
│   ├── lock.py         # Mutex, Event, Semaphore
│   └── thread.py       # Thread management
│
├── pjsip/              # SIP Signaling Layer (~2000 lines)
│   ├── sip_msg.py      # Message parsing/building
│   ├── sip_uri.py      # URI parsing
│   ├── sip_transaction.py  # Transaction state machine
│   ├── sip_dialog.py   # Dialog management
│   ├── sip_transport.py    # UDP/TCP transport
│   ├── sip_auth.py     # MD5 Digest auth
│   ├── sip_endpoint.py # Core endpoint
│   └── sip_util.py     # Utility functions
│
├── pjmedia/            # Media Layer (~1500 lines)
│   ├── codec/          # G.711 codec (A-law/u-law) - OWN IMPLEMENTATION
│   ├── rtp.py          # RTP session
│   ├── rtcp.py         # RTCP statistics
│   ├── sdp.py          # SDP parsing/negotiation
│   ├── jbuf.py         # Jitter buffer + PLC
│   └── stream.py       # Media stream
│
├── pjnath/             # NAT Traversal (~800 lines)
│   ├── stun.py         # STUN client
│   ├── ice.py          # Full ICE (RFC 8445)
│   └── turn.py         # TURN client
│
├── pjsua/              # High-Level API (~600 lines)
│   ├── pjsua.py        # Main UA class
│   ├── call.py         # Call management
│   ├── acc.py          # Account/registration
│   └── buddy.py        # Presence buddies
│
├── audio/              # In-Memory Audio Processing
│   └── __init__.py     # AudioData, numpy/tensor/files/G.711
│
├── utils/              # Utilities
│   ├── numpy_utils.py  # numpy ↔ PCM/G.711 conversion
│   └── resample.py     # Audio resampling
│
└── tests/              # Test suite
    ├── test_system.py  # Comprehensive system test
    ├── test_pjlib.py   # Foundation tests
    ├── test_pjmedia.py # Media tests
    └── test_audio_pipeline.py  # TTS->RVC pipeline test
```

## Features

### SIP Signaling
- **Message parsing** - Parse SIP messages from bytes/string
- **URI parsing** - RFC 3261 compliant URI handling
- **Transaction state machine** - INVITE and non-INVITE transactions
- **Dialog management** - Dialog creation, updates, termination
- **Transport layer** - UDP and TCP transport
- **Authentication** - MD5 Digest authentication

### Media Processing
- **G.711 Codec** - Own implementation with lookup tables (PCMA/PCMU)
- **RTP/RTCP** - Full RTP session management and RTCP statistics
- **SDP** - SDP parsing and negotiation
- **Jitter Buffer** - Adaptive buffering with PLC for packet loss

### NAT Traversal
- **STUN** - NAT detection and mapped address discovery
- **ICE** - Full ICE implementation (RFC 8445)
- **TURN** - Relay candidate support

### Audio Processing (In-Memory)
- **Numpy arrays** - int16, float32 support
- **PyTorch tensors** - Direct tensor support for AI models
- **WAV files** - Read/write operations
- **G.711 conversion** - Convert to/from A-law/u-law
- **Resampling** - 8kHz ↔ 16kHz ↔ 44.1kHz ↔ 48kHz

## Installation

```bash
# Clone the repository
cd /home/user/Test_Phone_new

# Activate virtual environment
source .venv/bin/activate

# Install dependencies (if needed)
pip install numpy scipy torch
```

## Quick Start

### Basic SIP Registration

```python
import asyncio
from pjsip_python import Ua, Account

async def main():
    # Create UA
    ua = await Ua.create()
    
    # Create account and register
    acc = await ua.create_account({
        'id': 'sip:1001@192.168.1.5',
        'reg_uri': 'sip:192.168.1.5:5060',
        'username': '1001',
        'password': 'password'
    })
    acc.register()
    
    await asyncio.sleep(30)  # Stay registered
    await ua.destroy()

asyncio.run(main())
```

### TTS → RVC → SIP Audio Pipeline

```python
import numpy as np
import torch
from pjsip_python.audio import (
    numpy_to_audio, tensor_to_audio, audio_to_tensor,
    AudioFormat
)
from pjsip_python.pjmedia.rtp import RtpSession

# 1. TTS generates numpy audio
tts_numpy = np.array([...], dtype=np.float32)  # Your TTS output
audio = numpy_to_audio(tts_numpy, sample_rate=8000)

# 2. RVC processing (tensor)
tensor = audio_to_tensor(audio)
processed = rvc_model(tensor)  # Your RVC model
rvc_audio = tensor_to_audio(processed, sample_rate=8000)

# 3. Convert to G.711 for SIP
g711_bytes = rvc_audio.to_bytes(AudioFormat.G711_ALAW)

# 4. Create RTP packet
rtp = RtpSession(ssrc=0x12345678, payload_type=8)
rtp.set_clock_rate(8000)
rtp_packet = rtp.encode_rtp(g711_bytes[:160])  # 20ms chunk
```

### Example Scripts

```bash
# Basic UA example
python3 examples/example_basic_ua.py --demo

# TTS call example
python3 examples/example_tts_call.py --demo

# Run tests
python3 tests/test_system.py
python3 tests/test_audio_pipeline.py
```

## Audio Formats

### Input/Output

| Format | Type | Usage |
|--------|------|-------|
| `np.ndarray(int16)` | Numpy | Standard PCM audio |
| `np.ndarray(float32)` | Numpy | Normalized audio (-1.0 to 1.0) |
| `torch.Tensor` | PyTorch | AI model input/output |
| `bytes` | Raw | PCM16 raw bytes |
| `bytes` | G.711 | A-law/u-law encoded |

### Conversions

```python
from pjsip_python.audio import (
    numpy_to_audio, audio_to_numpy,
    tensor_to_audio, audio_to_tensor,
    read_wav, write_wav
)

# Numpy
audio = numpy_to_audio(np_array, sample_rate=8000)
np_array = audio.to_numpy()

# Tensor
audio = tensor_to_audio(tensor, sample_rate=8000)
tensor = audio_to_tensor(audio)

# Files
audio = read_wav("speech.wav")
write_wav("output.wav", audio)

# G.711
g711 = audio.to_bytes(AudioFormat.G711_ALAW)
```

## Configuration

### UaConfig

```python
from pjsip_python.pjsua import UaConfig

config = UaConfig(
    local_ip="192.168.1.181",  # Your local IP
    local_port=5060,           # SIP port
    user_agent="MySIPClient/1.0"
)
```

### AccountConfig

```python
from pjsip_python.pjsua import AccountConfig

config = AccountConfig(
    id="sip:user@domain.com",      # SIP URI
    reg_uri="sip:domain.com:5060", # Registrar
    username="user",               # Authentication
    password="password",
    realm="*"                      # Authentication realm
)
```

## Current Status

### Working Features ✓
- Socket abstraction and networking
- SIP message parsing and building
- G.711 codec (A-law and u-law)
- RTP header/packet handling
- RTCP statistics
- In-memory audio processing (numpy, tensor, files)
- Audio conversions and resampling
- High-level UA API (create, register, call)
- ICE session (basic)
- TTS → RVC → G.711 → RTP pipeline

### Not Implemented ✗
- Video support
- TLS transport
- Complex dialog usage
- Full transaction state machine
- Advanced SIP features (PUBLISH, REFER, etc.)
- Real audio device I/O (microphone/speaker)

## Why This Project?

This is a **research/educational implementation** designed to:

1. **Understand SIP/RTP** - Learn how VoIP protocols work
2. **AI Integration** - Process audio with ML models (RVC, TTS)
3. **Custom Solutions** - Build specialized VoIP applications
4. **No External Dependencies** - Pure Python implementation

## Performance

This is **NOT** optimized for production use. It's designed for:

- Learning and experimentation
- AI/ML audio pipelines
- Custom VoIP solutions
- Research projects
- And for Fun

For production, use established stacks like:
- [PJSIP](https://www.pjsip.org/) - C-based, highly optimized
- [Sofia-SIP](https://github.com/freeswitch/sofia-sip) - C-based
- [Kamilio](https://www.kamailio.org/) - Full VoIP platform

## Testing

```bash
# Run all tests
python3 tests/test_system.py

# Run audio pipeline tests
python3 tests/test_audio_pipeline.py

# Run individual module tests
python3 tests/test_pjlib.py
python3 tests/test_pjmedia.py
```

## API Reference

### Top-Level Imports

```python
from pjsip_python import (
    # High-Level API
    Ua, UaConfig,           # User Agent
    Account, AccountConfig, # Registration
    Call, CallState,        # Calls
    Buddy,                  # Presence
    
    # SIP Core
    SipMessage,             # SIP messages
    Dialog,                 # Dialog management
    Transaction,            # Transactions
    
    # Media
    G711Codec, RtpSession,  # Codec and transport
    MediaStream,            # Media stream
    SdpSession,             # SDP handling
    
    # NAT Traversal
    IceSession, StunClient, TurnClient,
    
    # Utilities
    resample_audio,         # Audio resampling
    numpy_to_pcm16,         # Format conversion
    numpy_to_g711, g711_to_numpy,
    
    # Audio Generation
    create_silence, create_tone,
)
```

### Audio Processing

```python
from pjsip_python.audio import (
    AudioData,              # Unified audio container
    AudioFormat,            # Format enum
    numpy_to_audio,         # From numpy
    audio_to_numpy,         # To numpy
    tensor_to_audio,        # From PyTorch
    audio_to_tensor,        # To PyTorch
    read_wav, write_wav,    # File I/O
    read_mp3,               # MP3 support
    create_silence,         # Generate silence
    create_tone,            # Generate tone
)
```

## License

This project is for educational and research purposes.

## Author

**Sergey004**

## References

- [RFC 3261](https://tools.ietf.org/html/rfc3261) - SIP: Session Initiation Protocol
- [RFC 3550](https://tools.ietf.org/html/rfc3550) - RTP: Real-time Transport Protocol
- [RFC 8445](https://tools.ietf.org/html/rfc8445) - ICE: Interactive Connectivity Establishment
- [ITU-T G.711](https://www.itu.int/rec/T-REC-G.711) - Pulse Code Modulation of voice frequencies
