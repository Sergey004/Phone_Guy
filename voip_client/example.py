import logging
import pyaudio

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from voip_client import VoIPClient

def handle_incoming_call(call):
    call.answer()
    logging.info("Call answered. Starting audio stream...")
    for audio_chunk in call.receive_audio():
        logging.info(f"Received audio chunk: {len(audio_chunk)} bytes")
        call.send_audio(audio_chunk)

def main():
    client = VoIPClient(
        server="192.168.1.176",
        port=5060,
        username="555533",
        password="Test1234",
        local_ip="192.168.1.181",
        local_port=5062,
        rtp_port_range=(10000, 20000)
    )
    client.on_incoming_call(handle_incoming_call)
    client.start()
    
    logging.info("Starting outgoing call...")
    call = client.make_call("sip:1001@192.168.1.176")
    
    # Live audio capture from microphone
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=8000,
                    input=True,
                    frames_per_buffer=320)
    
    while call.state == "answered":
        data = stream.read(320)
        call.send_audio(data)
    
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    call.hangup()
    client.stop()
    logging.info("Call ended and client stopped.")

if __name__ == "__main__":
    main()
