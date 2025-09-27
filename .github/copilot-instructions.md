# AI Assistant Instructions for Test_Phone Project

This document provides key context for AI coding assistants working in this codebase.

## Project Overview

Test_Phone is a VoIP (Voice over IP) phone implementation using the voip_client library, focusing on SIP signaling, RTP media handling, and AI agent integration. The project implements a Python-based VoIP client that can:

- Register with SIP servers and handle VoIP calls
- Process RTP audio streams for voice communication
- Integrate with AI services for:
  - Speech-to-text transcription
  - Text-to-speech synthesis
  - Language model interactions

## Key Components

### VoIP Client (`voip_client/`)
- `voip.py` - Main VoIP client implementation
- `sip.py` - SIP protocol handling
- `rtp.py` - RTP media transport
- `audio.py` - Audio processing and codecs
- `config.py` - Client configuration

### Client Implementation (`voip_client/`)
- `voip.py` - Main VoIP client class
- `sip.py` - SIP protocol adaptations
- `rtp.py` - RTP/audio handling
- `audio.py` - Audio processing utilities

### Agent Integration (`agents/`)
- `llm_adapter.py` - Large Language Model integration
- `stt_adapter.py` - Speech-to-text service integration
- `tts_adapter.py` - Text-to-speech service integration

## Key Patterns

1. **Call Flow**:
   ```python
   # Initialize client with config
   client = VoIPClient(
       sip_server="192.168.1.100",
       username="1234",
       password="secret",
       local_ip="192.168.1.200"
   )
   
   # Make outbound call
   call = client.make_call("sip:5678@192.168.1.100")
   
   # Handle incoming audio
   for audio_data in call.receive_audio():
       processed_audio = process_audio(audio_data)
       call.send_audio(processed_audio)
   ```

2. **Audio Processing**:
   - Flexible frame size configuration via `AUDIO_FRAME_SIZE` in config
   - Built-in support for PCMU/PCMA codecs using `AudioProcessor`
   - Real-time audio streaming with PyAudio integration
   - Automatic jitter buffer and packet handling

3. **AI Agent Integration**:
   - Modular adapter system in `agents/` directory
   - Async audio processing pipelines
   - Speech-to-text and text-to-speech services
   - LLM-based conversation handling

## Development Workflow

1. **Testing**:
   ```bash
   # Run all integration tests
   python -m pytest 123/
   
   # Test specific components
   python -m pytest 123/test_sip_auth.py
   python -m pytest 123/test_rtp_stt.py
   ```

2. **Configuration**:
   - VoIP settings in `123/config.json`
   - Audio/RTP params in `voip_client/config.py`
   - Agent configs handled by respective adapters

## Common Tasks

1. **Implementing New Audio Features**:
   - Extend `AudioProcessor` in `audio.py`
   - Add codec support if needed
   - Update RTP session handling
   - Add tests in `123/` directory

2. **Adding AI Capabilities**:
   - Create new adapter in `agents/`
   - Implement audio processing pipeline
   - Add service integration
   - Write integration tests

## Important Files for Context

When making changes, check these key files:

- `voip_client/voip.py` - Core call handling and state management
- `voip_client/audio.py` - Audio processing and codec implementations
- `voip_client/config.py` - Global configuration settings
- `agents/llm_adapter.py` - AI integration interface
- `123/test_api_key.py` - Service integration tests

## Best Practices

1. **State Management**:
   ```python
   # Check state before operations
   if call.state == CallState.ANSWERED:
       call.send_audio(audio_data)
   else:
       logging.warning("Call not in ANSWERED state")
   ```

2. **Resource Handling**:
   - Use context managers for audio streams
   - Clean up RTP sessions explicitly
   - Handle threading cleanup properly

3. **Error Recovery**:
   - Implement retry logic for network operations
   - Handle codec negotiation failures gracefully
   - Monitor audio stream health

## Common Pitfalls

1. **Audio Processing**: 
   - Frame size mismatches between codecs
   - Audio buffer underruns/overruns
   - Incorrect sample rate conversions

2. **Network Handling**:
   - SIP registration timeouts
   - RTP packet loss handling
   - NAT traversal issues

3. **Agent Integration**:
   - Long processing delays in AI pipelines
   - Memory leaks in audio buffers
   - Error propagation between components