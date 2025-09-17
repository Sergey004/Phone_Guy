import logging
import pyaudio
import threading
import time
import ffmpeg

from voip_client.config import CODEC_PCMU

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from voip_client import VoIPClient
from voip_client.audio import AudioProcessor

def handle_incoming_call(call):
    call.answer()
    logging.info("Call answered. Starting audio stream...")
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=8000,
                    output=True,
                    frames_per_buffer=320)
    processor = AudioProcessor(codec=CODEC_PCMU)
    try:
        for encoded in call.receive_encoded():
            pcm = processor.decode_pcm(encoded)
            stream.write(pcm)
            call.send_encoded(encoded)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

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
    call = client.make_call("sip:2335584@192.168.1.176")
    call.audio_processor.local_playback_enabled = False # Disable local playback

    p = pyaudio.PyAudio()
    # processor = AudioProcessor(input_stream, output_stream)
    # processor.local_playback_enabled = False # Disable local playback

    output_stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=8000,
                    output=True,
                    frames_per_buffer=320)
    
    # Play the test audio file and send it to RTP stream
    # logging.info(f"Playing audio file: f:\\Test_Phone\\Test_audio.wav and sending to RTP stream")
    # try:
    #     process = (
    #         ffmpeg
    #         .input("f:\\Test_Phone\\Test_audio.wav")
    #         .output('pipe:', format='s16le', acodec='pcm_s16le', ac=1, ar=8000)
    #         .run_async(pipe_stdout=True, pipe_stderr=True)
    #     )

    #     while call.state == "answered":
    #         in_bytes = process.stdout.read(320 * 2)  # 16-bit PCM, 2 bytes per sample
    #         if not in_bytes:
    #             break
    #         call.send_audio(in_bytes)
    #         if call.audio_processor.local_playback_enabled:
    #             output_stream.write(in_bytes) # Also play locally
    #     process.wait()
    # except ffmpeg.Error as e:
    #     logging.error(f"FFmpeg error: {e.stderr.decode()}")
    # except Exception as e:
    #     logging.error(f"Error playing audio file: {e}")

    def playback_loop():
        while call.state == "answered":
            encoded_packet = call.rtp_session.get_audio()
            if encoded_packet:
                pcm = call.audio_processor.decode_pcm(encoded_packet)
                if call.audio_processor.local_playback_enabled:
                    output_stream.write(pcm)
            else:
                silence = b'\x00' * 640
                if call.audio_processor.local_playback_enabled:
                    output_stream.write(silence)
                time.sleep(0.02)
    
    playback_thread = threading.Thread(target=playback_loop)
    playback_thread.daemon = True
    playback_thread.start()
    # Play the test audio file and send it to RTP stream
    logging.info(f"Playing audio file: f:\\Test_Phone\\Test_audio.wav and sending to RTP stream")
    try:
        process = (
            ffmpeg
            .input("f:\\Test_Phone\\Test_audio.wav")
            .output('pipe:', format='s16le', acodec='pcm_s16le', ac=1, ar=8000)
            .run_async(pipe_stdout=True, pipe_stderr=True)
        )

        while call.state == "answered":
            in_bytes = process.stdout.read(320 * 2)  # 16-bit PCM, 2 bytes per sample
            if not in_bytes:
                break
            call.send_audio(in_bytes)
            if call.audio_processor.local_playback_enabled:
                output_stream.write(in_bytes) # Also play locally
            time.sleep(0.04) # Pace the sending to match audio duration
        process.wait()
    except ffmpeg.Error as e:
        logging.error(f"FFmpeg error: {e.stderr.decode()}")
        logging.error(f"Error playing audio file: {e}")

    output_stream.stop_stream()
    output_stream.close()
    p.terminate()
    call.hangup()
    client.stop()
    logging.info("Call ended and client stopped.")

if __name__ == "__main__":
    main()
