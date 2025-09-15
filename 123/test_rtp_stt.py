import Sippy.RTP as RTP
import time
import logging
from agents.stt_adapter import STTAdapter  # Adjust import as needed

# Test script for microphone to RTP and STT

# Replace with actual destination IP and port
dest_ip = '127.0.0.1'
dest_port = 5004

# For STT
config = {'stt': {'energy_threshold': 500, 'min_chunk_ms': 1500, 'silence_end_ms': 600}}
logger = logging.getLogger('test')
stt = STTAdapter(config, logger)

client = RTP.RTPClient(dest_ip, dest_port, RTP.PayloadType.PCMU, RTP.TransmitType.SENDRECV)

print("Starting RTP client...")
client.start()

print("Starting microphone capture with STT stream...")
client.start_microphone_capture(stt_adapter=stt, stt_mode='stream')

print("Speak something for 10 seconds...")
time.sleep(10)

# Check STT output
while not stt.out_queue.empty():
    text = stt.out_queue.get()
    print(f"Transcribed: {text}")

print("Stopping...")
client.stop()

print("Test completed. For file mode, use stt_mode='file' and file_path='output.pcm'")