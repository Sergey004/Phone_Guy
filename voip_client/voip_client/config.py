"""
Configuration constants for the VoIP client.
"""

DEFAULT_SIP_PORT = 5060
# Use a valid UDP port range; choose even ports for RTP typically
DEFAULT_RTP_PORT_RANGE = (10000, 20000)
# AUDIO_FRAME_SIZE options:
# - integer > 0: fixed bytes per RTP payload (e.g., 160 for 20ms G.711 at 8kHz)
# - 0 or negative, or string 'auto': enable dynamic packetization (AUTO)
AUDIO_FRAME_SIZE = 160  # Fixed size for stable transmission
CODEC_PCMU = "PCMU"
CODEC_PCMA = "PCMA"

# RTP Configuration
RTP_PAYLOAD_TYPE_PCMU = 0  # G.711 PCMU
RTP_PAYLOAD_TYPE_PCMA = 8  # G.711 PCMA
RTP_SAMPLE_RATE = 8000  # 8kHz for G.711
RTP_PACKETIZATION_INTERVAL = 20  # 20ms packets
RTP_MAX_JITTER_BUFFER_MS = 200  # Maximum jitter buffer size in milliseconds
RTP_MIN_JITTER_BUFFER_MS = 20   # Minimum jitter buffer size in milliseconds
