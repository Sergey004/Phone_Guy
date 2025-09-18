"""
Configuration constants for the VoIP client.
"""

DEFAULT_SIP_PORT = 5060
# Use a valid UDP port range; choose even ports for RTP typically
DEFAULT_RTP_PORT_RANGE = (10000, 20000)
AUDIO_FRAME_SIZE = 560  # 20ms at 8kHz
CODEC_PCMU = "PCMU"
CODEC_PCMA = "PCMA"
