import logging
import wave
import time
import argparse
import socket

from voip_client.config import CODEC_PCMU
from voip_client.voip import CallState, VoIPClient

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def handle_incoming_call(call):
    logging.info(f"Incoming call from {call.remote_uri}")
    call.answer()
    logging.info("Call answered")
    time.sleep(5)  # Keep the call open for 5 seconds
    call.hangup()
    logging.info("Call hung up")

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def main():
    parser = argparse.ArgumentParser(description="VoIP Client Example")
    parser.add_argument("--server", required=True, help="SIP server address")
    parser.add_argument("--port", type=int, default=5060, help="SIP server port")
    parser.add_argument("--username", required=True, help="SIP username")
    parser.add_argument("--password", required=True, help="SIP password")
    parser.add_argument("--local-ip", help="Local IP address (optional, auto-detected if not provided)")
    parser.add_argument("--local-port", type=int, default=5062, help="Local SIP port")
    parser.add_argument("--rtp-ports", default="10000-20000", help="RTP port range (e.g., 10000-20000)")
    parser.add_argument("--callee", required=True, help="SIP URI of the callee")
    parser.add_argument("--audio-file", required=True, help="Path to the audio file to play")
    args = parser.parse_args()

    rtp_port_range = tuple(map(int, args.rtp_ports.split('-')))

    local_ip = args.local_ip if args.local_ip else get_local_ip()

    client = VoIPClient(
        args.server,
        5060,
        username=args.username,
        password=args.password,
        rtp_port_range=rtp_port_range,
    )
    client.start()

    try:
        call = client.make_call(args.callee)
        if not call:
            logging.error("Failed to create call")
            return

        while call.state != CallState.ANSWERED:
            if call.state == CallState.ENDED:
                logging.error("Call ended before it was answered")
                return
            time.sleep(0.1)

        logging.info(f"Playing audio file: {args.audio_file} and sending to RTP stream")
        try:
            with wave.open(args.audio_file, 'rb') as f:
                frames = f.getnframes()
                data = f.readframes(frames)

            call.write_audio(data)

            stop = time.time() + (frames / 8000)

            while time.time() <= stop and call.state == CallState.ANSWERED:
                time.sleep(0.1)

        except Exception as e:
            logging.error(f"Error playing audio file: {e}")

    finally:
        client.stop()

if __name__ == "__main__":
    main()
