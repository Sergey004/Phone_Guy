"""
Configuration constants for the VoIP client.
"""

DEFAULT_SIP_PORT = 5060
# Use a valid UDP port range; choose even ports for RTP typically
DEFAULT_RTP_PORT_RANGE = (10000, 20000)
# AUDIO_FRAME_SIZE options:
# - integer > 0: fixed bytes per RTP payload (e.g., 160 for 20ms G.711 at 8kHz)
# - 0 or negative, or string 'auto': enable dynamic packetization (AUTO)
AUDIO_FRAME_SIZE = 'auto'
CODEC_PCMU = "PCMU"
CODEC_PCMA = "PCMA"
