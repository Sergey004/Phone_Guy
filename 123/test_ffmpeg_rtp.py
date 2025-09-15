import Sippy.RTP as RTP
import time

# Test script for ffmpeg to RTP streaming

# Replace with actual destination IP and port
dest_ip = '127.0.0.1'
dest_port = 5004  # Common RTP port, ensure a receiver is listening

# Replace with path to an audio file
audio_source = 'test_audio.mp3'  # Ensure this file exists

client = RTP.RTPClient(dest_ip, dest_port, RTP.PayloadType.PCMU, RTP.TransmitType.SENDONLY)

print("Starting RTP client...")
client.start()

print("Starting ffmpeg stream...")
client.start_ffmpeg_stream(audio_source)

print("Streaming for 30 seconds...")
time.sleep(30)

print("Stopping...")
client.stop()

print("Test completed.")