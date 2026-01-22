# Audio Handling Module

This module provides safe audio handling for PJSIP integration, designed to prevent crashes when receiving audio data in unknown formats.

## Overview

The audio module solves critical issues with the original implementation:

1. **Audio Format Mismatch** - Automatic conversion between PCMA, PCMU, and PCM-16
2. **Unsafe Python Callbacks** - All C++ callbacks have comprehensive exception handling
3. **Inefficient File-Based Recording** - Direct frame capture instead of file tailing
4. **Lack of Format Validation** - Validates audio integrity before processing
5. **Mixed Threading Models** - Thread-safe queue management

## Components

### AudioFormatHandler

Handles audio format conversion and validation.

**Key Features:**
- Auto-detects audio format (PCMA, PCMU, PCM-16)
- Converts between formats using lookup tables
- Validates PCM-16 integrity
- Normalizes audio levels

**Example Usage:**
```python
from Libs.audio import AudioFormatHandler

handler = AudioFormatHandler(logger)
pcm_data, format = handler.convert_to_pcm16(audio_data, sample_rate=8000)
```

### AudioCapturePort

Safe audio capture from PJSIP with format conversion.

**Key Features:**
- Thread-safe frame queue
- Automatic format conversion
- Comprehensive error handling in C++ callbacks
- Statistics tracking (frames captured, dropped, errors)
- Non-blocking frame retrieval

**Example Usage:**
```python
from Libs.audio import AudioCapturePort

capture = AudioCapturePort(sample_rate=8000, logger=logger)
capture.register_with_conf(endpoint)

# Connect to audio stream
audio_media.startTransmit(capture)

# Get frames in your processing loop
frame = capture.get_frame(timeout=0.1)
if frame:
    process_frame(frame)
```

### AudioPlaybackPort

Safe audio playback with format validation.

**Key Features:**
- Thread-safe playback control
- Format validation before playback
- Playback statistics and progress tracking
- Loop playback support
- Graceful error handling

**Example Usage:**
```python
from Libs.audio import AudioPlaybackPort

playback = AudioPlaybackPort(sample_rate=8000, logger=logger)
playback.register_with_conf(endpoint)

# Connect to audio stream
playback.startTransmit(audio_media)

# Update audio data
playback.update_playback_data(pcm_bytes)

# Check playback status
if playback.is_playback_done():
    print("Playback complete")
```

### AudioConverter

Utility functions for audio processing.

**Key Features:**
- Sample rate conversion
- Audio mixing
- Gain adjustment
- Fade in/out effects

**Example Usage:**
```python
from Libs.audio import AudioConverter

converter = AudioConverter(logger)

# Resample audio
resampled, success = converter.resample_pcm16(audio_data, 8000, 16000)

# Mix two audio streams
mixed = converter.mix_audio(audio1, audio2)

# Apply gain
louder = converter.apply_gain(audio_data, gain_db=3.0)
```

## Architecture

```
┌─────────────────┐
│   PJSIP C++     │
└────────┬────────┘
         │
    AudioCapturePort (putFrame callback)
         │
         ├─→ Format Detection
         ├─→ Format Conversion (PCMA/PCMU → PCM-16)
         ├─→ Validation
         └─→ Queue (thread-safe)
         │
         ↓
    ┌─────────────────┐
    │  Processing     │
    │  (STT/LLM/TTS)  │
    └────────┬────────┘
             │
    AudioPlaybackPort (getFrame callback)
             │
             ├─→ Validation
             ├─→ Format Conversion (if needed)
             └─→ Playback
             │
             ↓
    ┌─────────────────┐
    │   PJSIP C++     │
    └─────────────────┘
```

## Error Handling

All components follow these error handling principles:

1. **Never crash on bad data** - Return silence or skip invalid frames
2. **Log all errors** - Detailed logging for debugging
3. **Graceful degradation** - Continue operation even if some frames fail
4. **Statistics tracking** - Monitor errors and frame drops

## Migration Guide

### From ByteStreamMediaPort to AudioPlaybackPort

**Old Code:**
```python
from Libs.rtp_streamer import ByteStreamMediaPort

media_port = ByteStreamMediaPort(pcm_bytes=b'', sample_rate=8000)
media_port.register_with_conf(ep)
media_port.update_playback_data(new_pcm)
```

**New Code:**
```python
from Libs.audio import AudioPlaybackPort

playback = AudioPlaybackPort(pcm_bytes=b'', sample_rate=8000, logger=logger)
playback.register_with_conf(ep)
playback.update_playback_data(new_pcm, validate=True)
```

### From File-Based Recording to AudioCapturePort

**Old Code:**
```python
# Used AudioMediaRecorder to write file
# Then tailed the file in Python
recorder = pj.AudioMediaRecorder()
recorder.createRecorder(filename)
audio_media.startTransmit(recorder)
# Later: tail the file and read frames
```

**New Code:**
```python
# Direct frame capture
from Libs.audio import AudioCapturePort

capture = AudioCapturePort(sample_rate=8000, logger=logger)
capture.register_with_conf(ep)
audio_media.startTransmit(capture)

# Get frames directly
frame = capture.get_frame(timeout=0.1)
```

## Configuration

### AudioCapturePort Options

```python
AudioCapturePort(
    sample_rate=8000,        # Sample rate in Hz
    frame_size_ms=20,        # Frame size in milliseconds
    logger=None              # Logger instance
)
```

Configuration attributes:
- `auto_convert=True` - Auto-convert to PCM-16
- `validate_frames=True` - Validate frame integrity
- `frame_queue.maxsize=100` - Queue size

### AudioPlaybackPort Options

```python
AudioPlaybackPort(
    pcm_bytes=b"",           # Initial audio data
    sample_rate=8000,        # Sample rate in Hz
    logger=None              # Logger instance
)
```

Configuration attributes:
- `loop_playback=False` - Loop audio when done
- `is_playing=False` - Playback state

## Performance Considerations

1. **Frame Queue Size** - Default 100 frames (2 seconds at 8000Hz). Adjust based on processing speed.
2. **Format Conversion** - Lookup tables are fast, but conversion adds minimal overhead.
3. **Thread Safety** - All operations use locks/queues for thread safety.
4. **Memory Usage** - Queued frames consume memory. Monitor queue size.

## Debugging

Enable debug logging to track audio processing:

```python
import logging
logging.getLogger('Libs.audio').setLevel(logging.DEBUG)
```

Check statistics:

```python
# Capture statistics
stats = capture.get_stats()
print(f"Captured: {stats['frames_captured']}")
print(f"Dropped: {stats['frames_dropped']}")
print(f"Errors: {stats['errors']}")

# Playback statistics
stats = playback.get_stats()
print(f"Progress: {stats['progress']:.1%}")
print(f"Duration: {stats['duration_seconds']:.2f}s")
```

## Troubleshooting

### Issue: High frame drop rate

**Solution:** Increase queue size or improve processing speed
```python
capture.frame_queue = queue.Queue(maxsize=200)
```

### Issue: Audio format errors

**Solution:** Check detected format and validate input
```python
pcm_data, detected_format = handler.convert_to_pcm16(audio_data)
logger.info(f"Detected format: {detected_format}")
```

### Issue: Playback not smooth

**Solution:** Ensure PCM data is valid and properly formatted
```python
if handler.validate_pcm16(pcm_data):
    playback.update_playback_data(pcm_data)
```

## Best Practices

1. **Always validate audio data** before playback
2. **Handle exceptions** in all audio processing code
3. **Monitor statistics** to detect issues early
4. **Use appropriate queue sizes** for your use case
5. **Log errors** for debugging
6. **Test with various audio formats** (PCMA, PCMU, PCM-16)

## License

Part of the Phone_Guy project.
