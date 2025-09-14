# VoIP Client Library

A lightweight Python library for SIP and RTP VoIP communication, implementing core VoIP functionality from scratch.

## Installation

```bash
pip install pyaudio
pip install voip_client
```

Or from source:

```bash
git clone https://github.com/yourusername/voip_client
cd voip_client
pip install .
```

## Usage Example

```python
from voip_client import VoIPClient

def handle_incoming_call(call):
    call.answer()
    print("Call answered. Starting audio stream...")
    for audio_chunk in call.receive_audio():
        # Process PCM audio bytes (e.g., save to file or AI pipeline)
        print(f"Received audio chunk: {len(audio_chunk)} bytes")
        # Echo the audio back for testing
        call.send_audio(audio_chunk)

def main():
    client = VoIPClient(
        server="192.168.1.176",
        port=5060,
        username="555533",
        password="your_password",
        local_ip="192.168.1.181",
        local_port=5062,
        rtp_port_range=(10000, 20000)
    )
    client.on_incoming_call(handle_incoming_call)
    client.start()
    
    print("Starting outgoing call...")
    call = client.make_call("sip:1001@192.168.1.176")
    
    # Send audio from a PCM file (e.g., 8kHz, 16-bit mono)
    with open("input.pcm", "rb") as f:
        while chunk := f.read(320):  # 20ms PCM at 8kHz, 16-bit
            call.send_audio(chunk)
    
    call.hangup()
    client.stop()
    print("Call ended and client stopped.")

if __name__ == "__main__":
    main()
```

## Features

- SIP signaling for REGISTER, INVITE, BYE, etc.
- RTP packet handling with jitter buffer (60ms capacity)
- G.711 PCMU and PCMA codec support
- Audio capture and playback using PyAudio
- Simple API for call management and audio streaming

## Testing

Run unit tests with:

```bash
python -m unittest tests/test_sip.py
python -m unittest tests/test_rtp.py
```

## Notes

- The library is designed for Python 3.10+.
- Ensure your SIP server supports Digest Authentication (MD5).
- For real-world use, consider adding more robust error handling and security measures.
- The example expects a PCM file (`input.pcm`) which can be generated using tools like `ffmpeg`:
  ```bash
  ffmpeg -i input.wav -ar 8000 -ac 1 -f s16le input.pcm
