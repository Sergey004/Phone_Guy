import logging
import wave
import time
import argparse
import socket
import os
import tempfile

import ffmpeg

from voip_client.config import CODEC_PCMU, AUDIO_FRAME_SIZE
from voip_client import CallState, VoIPClient

logging.basicConfig(
    level=logging.DEBUG,
    filename='myapp.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def handle_incoming_call(call):
    logging.info(f"Incoming call from {getattr(call, 'remote_uri', 'unknown')}")
    # Используем новый метод приёма звонка
    if hasattr(call, 'accept_call'):
        call.accept_call()
        logging.info("Call accepted (using accept_call)")
    else:
        call.answer()
        logging.info("Call answered (legacy answer())")
    
    # Добавляем диагностику во время звонка
    start_time = time.time()
    while time.time() - start_time < 5:  # Keep the call open for 5 seconds
        if hasattr(call, 'rtp_session') and hasattr(call.rtp_session, 'diagnostics'):
            diagnostics = call.rtp_session.diagnostics.get_diagnostics()
            logging.info(f"Incoming call diagnostics: {diagnostics}")
        time.sleep(1)
    
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


def _convert_to_pcm16_mono_8k(input_path: str) -> str:
    """Convert arbitrary audio file to 8kHz mono 16-bit PCM WAV using ffmpeg.
    Returns path to a temporary WAV file.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp_path = tmp.name
    tmp.close()
    try:
        (
            ffmpeg
            .input(input_path)
            .output(tmp_path, acodec='pcm_s16le', ac=1, ar='8000', loglevel='error')
            .overwrite_output()
            .run()
        )
        logging.info(f"Converted '{input_path}' to PCM16 mono 8kHz WAV at '{tmp_path}'")
        return tmp_path
    except Exception as e:
        # Clean up on failure
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise RuntimeError(f"ffmpeg conversion failed: {e}")


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
        args.port,
        username=args.username,
        password=args.password,
        local_ip=local_ip,
        local_port=args.local_port,
        rtp_port_range=rtp_port_range,
    )
    # Регистрируем обработчик входящего звонка
    client.on_incoming_call = handle_incoming_call
    client.start()

    temp_converted = None
    try:
        call = client.make_call(args.callee)
        if not call:
            logging.error("Failed to create call")
            return

        # Wait until answered or ended
        while call.state != CallState.ANSWERED:
            if call.state == CallState.ENDED:
                logging.error("Call ended before it was answered")
                return
            time.sleep(0.1)

        logging.info(f"Playing audio file: {args.audio_file} and sending to RTP stream")
        try:
            audio_path = args.audio_file
            logging.info(f"Attempting to open audio file: {audio_path}")
            # First, try to open with wave — this only supports PCM/Extensible.
            try:
                with wave.open(audio_path, 'rb') as f:
                    nchannels = f.getnchannels()
                    sampwidth = f.getsampwidth()
                    framerate = f.getframerate()
                    needs_convert = (nchannels != 1 or sampwidth != 2 or framerate != 8000)
                    logging.info(f"Original audio file properties: channels={nchannels}, sampwidth={sampwidth}, framerate={framerate}")
            except wave.Error as we:
                logging.warning(f"wave cannot open '{audio_path}' ({we}), attempting ffmpeg conversion to PCM16 mono 8kHz...")
                try:
                    temp_converted = _convert_to_pcm16_mono_8k(audio_path)
                    audio_path = temp_converted
                    needs_convert = False  # Already converted
                    logging.info(f"ffmpeg conversion successful. New audio path: {audio_path}")
                except RuntimeError as re_exc:
                    logging.error(f"ffmpeg conversion failed: {re_exc}")
                    raise # Re-raise to stop processing if conversion fails

            if needs_convert:
                logging.warning("Expected 8kHz mono 16-bit PCM WAV; converting with ffmpeg...")
                temp_converted = _convert_to_pcm16_mono_8k(audio_path)
                audio_path = temp_converted

            with wave.open(audio_path, 'rb') as f:
                # At this point the file should be 8kHz mono s16le WAV
                # 20ms = 160 samples = 320 bytes per frame at 8kHz 16-bit mono
                # Determine chunk size: if AUDIO_FRAME_SIZE is a positive int, use it; otherwise default to 160 frames (20ms)
                chunk_frames = AUDIO_FRAME_SIZE if isinstance(AUDIO_FRAME_SIZE, int) and AUDIO_FRAME_SIZE > 0 else 160
                frame_count = 0
                while True:
                    data = f.readframes(chunk_frames)
                    if not data:
                        break
                    logging.debug(f"Sending {len(data)} bytes of PCM audio data.")
                    # send PCM bytes; Call will encode to PCMU
                    call.send_audio(data)
                    # Sleep to approximate real-time playback: frames_read / 8000 seconds
                    frames_read = len(data) // 2  # 2 bytes per sample at 16-bit mono
                    if frames_read > 0:
                        time.sleep(frames_read / 8000.0)
                    
                    # Периодическая диагностика во время отправки
                    frame_count += 1
                    if frame_count % 50 == 0:  # Каждые ~1 сек (50*20ms=1s)
                        if hasattr(call, 'rtp_session') and hasattr(call.rtp_session, 'diagnostics'):
                            diagnostics = call.rtp_session.diagnostics.get_diagnostics()
                            logging.info(f"Outgoing call diagnostics: {diagnostics}")

            # Keep call for a short tail to flush buffers
            tail = time.time() + 0.5
            while time.time() < tail and call.state == CallState.ANSWERED:
                time.sleep(0.05)

        except Exception as e:
            logging.error(f"Error playing audio file: {e}")

    finally:
        try:
            client.stop()
        finally:
            if temp_converted and os.path.exists(temp_converted):
                try:
                    os.unlink(temp_converted)
                except Exception:
                    pass

if __name__ == "__main__":
    main()