# Phone Guy Bot 📞

An AI-powered voice bot that simulates Phone Guy from Five Nights at Freddy's, capable of handling real phone calls via SIP protocol with natural voice conversation.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## 🌟 Features

- **Real-time Voice Conversations** - Handle incoming and outgoing SIP phone calls
- **AI-Powered Responses** - Uses NVIDIA NIM API (GLM 4.7) for intelligent, in-character responses
- **Voice Cloning** - RVC (Retrieval-based Voice Conversion) transforms TTS output into Phone Guy's voice
- **Speech Recognition** - faster-whisper for accurate speech-to-text
- **Text-to-Speech** - Chatterbox TTS with multilingual support
- **Conversation Logging** - All calls are automatically logged to `logs/` directory
- **Pre-generation** - Greeting is generated while phone is ringing for faster response
- **GPU Acceleration** - CUDA support for faster inference
- **Asynchronous Architecture** - Built on asyncio for efficient concurrent operations

## 📋 System Requirements

### Hardware
- **GPU**: NVIDIA GPU with CUDA support (recommended for RVC and TTS)
- **RAM**: Minimum 8GB, 16GB+ recommended
- **Storage**: 5GB+ free space for models

### Software
- **OS**: Linux (Ubuntu 22.04+ recommended) or Windows
- **Python**: 3.11+
- **SIP Server**: PBX server (Asterisk, FreeSWITCH, etc.) or SIP provider

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Sergey004/Phone_Guy.git
cd Phone_Guy
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## ⚙️ Configuration

### 1. Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# SIP Configuration
SIP_DOMAIN=pbx.example.com
SIP_PORT=5060
SIP_USER=phoneguy
SIP_PASSWORD=secret123
SIP_SERVER=pbx.example.com:5060

# NVIDIA LLM
NVIDIA_API_KEY=your_key_here
NVIDIA_MODEL=meta/llama3-70b-instruct

# Optional: Local SIP testing
# SIP_DOMAIN=127.0.0.1
# SIP_SERVER=127.0.0.1:5060
```

### 2. Bot Configuration

Edit `new_voip/main_integration.py` to configure SIP settings:

```python
SIP_USER = "555533"
SIP_PASS = "Test1234"
SIP_SERVER = "192.168.1.176"
LOCAL_IP = "192.168.1.181"
TARGET_NUMBER = None  # Set to None for incoming calls, or number for outgoing
```

### 3. Configure AI and Voice

Edit `MOCK_CONFIG` in `new_voip/main_integration.py`:

```python
MOCK_CONFIG = {
    'stt': {
        'model': 'small',  # tiny, base, small, medium, large
        'device': 'cuda',
        'language': 'en'
    },
    'tts': {
        'engine': 'turbo',  # turbo, multilingual, standard
        'device': 'cuda',
        'language_id': 'en',
        'audio_prompt_path': "/path/to/reference/audio.wav",
        'rvc_enabled': True,
        'rvc_model_path': '/path/to/rvc_model.pth',
        'rvc_index_path': '/path/to/rvc_index.index',
        'rvc_f0_method': 'rmvpe',
        'rvc_pitch_shift': 0,
        'rvc_index_rate': 0.6
    }
}
```

## 📁 Project Structure

```
Phone_Guy/
├── new_voip/
│   ├── main_integration.py    # Main entry point
│   ├── ai_service.py          # NVIDIA LLM integration
│   ├── ai_config.py           # AI prompts and configuration
│   ├── stt_adapter.py         # Speech-to-Text (Whisper)
│   ├── tts_adapter.py         # Text-to-Speech (Chatterbox)
│   ├── sip_rtp_client.py      # SIP/RTP protocol handler
│   ├── bridge.py              # Audio bridge for RTP
│   ├── audio_engine.py        # Audio processing utilities
│   ├── audio_codecs.py        # Codec implementations
│   ├── rvc_py/                # RVC voice conversion module
│   │   ├── rvc_infer.py       # RVC inference function
│   │   ├── rvc_model.py       # RVC model class
│   │   └── ...
│   └── models/                # Voice models directory
├── logs/                      # Call logs (auto-created)
├── .env.example              # Environment variables template
├── requirements.txt          # Python dependencies
├── run.sh                    # Startup script
└── README.md                 # This file
```

## 🎯 Usage

### Running the Bot

**Option 1: Using the startup script (Linux/Mac)**
```bash
chmod +x run.sh
./run.sh
```

**Option 2: Direct Python execution**
```bash
source .venv/bin/activate
python new_voip/main_integration.py
```

### Incoming Calls

Set `TARGET_NUMBER = None` in `main_integration.py`. The bot will:
1. Register with the SIP server
2. Wait for incoming calls
3. Generate greeting while phone rings
4. Answer and start conversation
5. Log the entire call to `logs/call_YYYY-MM-DD_HH-MM-SS.txt`

### Outgoing Calls

Set `TARGET_NUMBER = "destination_number"` in `main_integration.py`. The bot will:
1. Register with the SIP server
2. Initiate call to the specified number
3. Start conversation when connected
4. Log the call

### Stopping the Bot

Press `Ctrl+C` to gracefully stop the bot.

## 🎤 RVC Models Setup

To enable voice cloning (Phone Guy's voice), you need RVC models:

### 1. Download RVC Models

- **Models Directory**: `new_voip/models/RVC/`
- **Required Files**:
  - `.pth` file - The trained RVC model
  - `.index` file - Faiss index for voice retrieval

### 2. Model Sources

You can find RVC models at:

- [Hugging Face](https://huggingface.co/models?search=rvc)
- In web



### 3. Configure Model Paths

Update paths in `MOCK_CONFIG`:

```python
'rvc_model_path': '/home/user/Test_Phone_new/new_voip/models/RVC/PhoneGuyFNAF1/PhoneGuyFNAF1_e1000_s22000.pth',
'rvc_index_path': '/home/user/Test_Phone_new/new_voip/models/RVC/PhoneGuyFNAFadded_IVF339_Flat_nprobe_1_PhoneGuyFNAF1_v2.index',
```

### 4. Reference Audio

Provide a reference audio file for TTS style matching:

```python
'audio_prompt_path': "/home/user/Test_Phone_new/new_voip/models/RVC/PhoneGuyFNAF1/PhoneGuy_FNAF1_01.wav",
```

## 🔧 Troubleshooting

### SIP Registration Issues

**Problem**: Bot fails to register with SIP server

**Solutions**:
- Check SIP credentials in `.env` and `main_integration.py`
- Verify SIP server is reachable: `telnet SIP_SERVER 5060`
- Check firewall rules for UDP port 5060
- Ensure `LOCAL_IP` is correctly set

### Audio Quality Issues

**Problem**: Poor speech recognition or TTS quality

**Solutions**:
- Use Whisper `medium` or `large` model for better STT
- Increase `target_sample_rate` to 16000 or 24000
- Adjust `energy_threshold` in STT config
- Use CUDA for better TTS performance

### RVC Not Working

**Problem**: Voice conversion fails or doesn't work

**Solutions**:
- Verify RVC model paths are correct
- Check if model file is corrupted
- Ensure all RVC dependencies are installed
- Try different `f0_method`: `rmvpe`, `torchcrepe`, `parselmouth`
- Check CUDA availability: `torch.cuda.is_available()`

### NVIDIA API Issues

**Problem**: AI responses fail

**Solutions**:
- Verify `NVIDIA_API_KEY` in `.env`
- Check API key is valid and has credits
- Ensure internet connection
- Try different model: `meta/llama3-8b-instruct`

### Performance Issues

**Problem**: Slow response times

**Solutions**:

- Use GPU acceleration (CUDA)
- Use smaller Whisper model (`tiny` or `base`)
- Use `turbo` TTS engine
- Reduce conversation history size
- Close other GPU-intensive applications

## 📝 Call Logs

All conversations are automatically logged to the `logs/` directory:

```
logs/
└── call_2024-03-15_14-30-22.txt
```

Log format:
```
=== CALL STARTED AT 2024-03-15_14-30-22 ===

[14:30:25] Phone Guy: Uh, hello? Hello, hello? [clear throat] I wanted to record a message for you.

[14:30:32] User: Hello, who is this?

[14:30:35] Phone Guy: Oh, uh, this is Phone Guy. Did you just get hired?

=== CALL ENDED ===
```

## 🤝 Contributing

Contributions are welcome! Feel free to:

- Report bugs
- Suggest new features
- Submit pull requests
- Improve documentation

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [NVIDIA NIM](https://build.nvidia.com/) - AI inference
- [Chatterbox TTS](https://github.com/resemble-ai/chatterbox) - Text-to-Speech
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) - Speech Recognition
- [RVC-Project](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) - Voice Conversion

## 📞 Support

For issues and questions:
- Open an issue on GitHub
- Check existing issues for solutions
- Review the troubleshooting section

---

**Made with ❤️ for FNAF fans and AI enthusiasts**