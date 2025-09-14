from enum import Enum
from threading import Timer, Thread
from typing import Callable, Dict, Optional, Union
import audioop
import io
from .debug import debug
import random
import socket
import threading
import time
import struct
import warnings
import subprocess
import queue
import pyaudio


__all__ = [
    "add_bytes",
    "byte_to_bits",
    "DynamicPayloadType",
    "PayloadType",
    "RTPParseError",
    "RTPProtocol",
    "RTPPacketManager",
    "RTPClient",
    "TransmitType",
]




def byte_to_bits(byte: bytes) -> str:
    nbyte = bin(ord(byte)).lstrip("-0b")
    nbyte = ("0" * (8 - len(nbyte))) + nbyte
    return nbyte


def add_bytes(byte_string: bytes) -> int:
    binary = ""
    for byte in byte_string:
        nbyte = bin(byte).lstrip("-0b")
        nbyte = ("0" * (8 - len(nbyte))) + nbyte
        binary += nbyte
    return int(binary, 2)


class DynamicPayloadType(Exception):
    pass


class RTPParseError(Exception):
    pass


class RTPProtocol(Enum):
    UDP = "udp"
    AVP = "RTP/AVP"
    SAVP = "RTP/SAVP"


class TransmitType(Enum):
    RECVONLY = "recvonly"
    SENDRECV = "sendrecv"
    SENDONLY = "sendonly"
    INACTIVE = "inactive"

    def __str__(self):
        return self.value


class PayloadType(Enum):
    def __new__(
        cls,
        value: Union[int, str],
        clock: int = 0,
        channel: int = 0,
        description: str = "",
    ):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.rate = clock
        obj.channel = channel
        obj.description = description
        return obj

    @property
    def rate(self) -> int:
        return self._rate

    @rate.setter
    def rate(self, value: int) -> None:
        self._rate = value

    @property
    def channel(self) -> int:
        return self._channel

    @channel.setter
    def channel(self, value: int) -> None:
        self._channel = value

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str) -> None:
        self._description = value

    # Audio
    PCMU = (0, 8000, 1, "ITU-T G.711 PCM μ-Law")
    GSM = (3, 8000, 1, "European GSM")
    G723 = (4, 8000, 1, "ITU-T G.723.1")
    DVI4_8K = (5, 8000, 1, "IMA ADPCM 8kHz")
    DVI4_16K = (6, 16000, 1, "IMA ADPCM 16kHz")
    LPC = (7, 8000, 1, "Experimental Linear Predictive Coding")
    PCMA = (8, 8000, 1, "ITU-T G.711 PCM A-Law")
    G722 = (9, 8000, 1, "ITU-T G.722")
    L16_STEREO = (10, 44100, 2, "Linear PCM 16-bit Stereo 44.1kHz")
    L16_MONO = (11, 44100, 1, "Linear PCM 16-bit Mono 44.1kHz")
    QCELP = (12, 8000, 1, "Qualcomm Code Excited Linear Prediction")
    CN = (13, 8000, 1, "Comfort Noise")
    MPA = (14, 90000, 1, "MPEG-1 or MPEG-2 Audio only")
    G728 = (15, 8000, 1, "ITU-T G.728")
    DVI4_11K = (16, 11025, 1, "IMA ADPCM 11.025kHz")
    DVI4_22K = (17, 22050, 1, "IMA ADPCM 22.05kHz")
    G729 = (18, 8000, 1, "ITU-T G.729")

    # Video
    CELB = (25, 90000, 1, "Sun CellB")
    JPEG = (26, 90000, 1, "JPEG")
    NV = (28, 90000, 1, "Xerox PARC Network Video")
    H261 = (31, 90000, 1, "ITU-T H.261")
    MPV = (32, 90000, 1, "MPEG-1 and MPEG-2 Video")
    MP2T = (33, 90000, 1, "MPEG-2 Transport Stream")
    H263 = (34, 90000, 1, "ITU-T H.263")

    # DTMF
    EVENT = (101, 8000, 1, "DTMF Touch Tones")


class RTPPacketManager:
    def __init__(self):
        # Implementation would go here
        pass


class RTPClient:
    def __init__(
        self,
        ip: str,
        port: int,
        payload_type: PayloadType,
        transmit: TransmitType = TransmitType.SENDRECV,
        socket_type: RTPProtocol = RTPProtocol.UDP,
        jitter_buffer_length: int = 3,
        buffering: bool = True,
    ):
        self.ip = ip
        self.port = port
        self.payload_type = payload_type
        self.transmit = transmit
        self.socket_type = socket_type
        self.jitter_buffer_length = jitter_buffer_length
        self.buffering = buffering

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ssrc = random.randint(0, 0xFFFFFFFF)
        self.seq = random.randint(0, 0xFFFF)
        self.timestamp = random.randint(0, 0xFFFFFFFF)
        self.marker = False

        self.ffmpeg_proc = None
        self.audio_queue = queue.Queue()
        self.ffmpeg_thread = None
        self.running = False
        self.send_thread = None
        self.capture_thread = None
        self.p = None
        self.stream = None
        self.stt_file = None

    def start(self):
        self.running = True
        self.send_thread = Thread(target=self._send_loop)
        self.send_thread.start()

    def stop(self):
        self.running = False
        if self.send_thread:
            self.send_thread.join()
        if self.capture_thread:
            self.capture_thread.join()
        if self.ffmpeg_proc:
            self.ffmpeg_proc.terminate()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.p:
            self.p.terminate()
        if self.stt_file:
            self.stt_file.close()
        self.sock.close()

    def start_ffmpeg_stream(self, source: str):
        cmd = [
            'ffmpeg',
            '-i', source,
            '-f', 's16le',
            '-ar', '8000',
            '-ac', '1',
            '-'
        ]
        self.ffmpeg_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def read_ffmpeg():
            while self.running:
                data = self.ffmpeg_proc.stdout.read(320)  # 160 samples * 2 bytes s16le
                if not data:
                    break
                self.audio_queue.put(data)

            self.audio_queue.put(None)  # Signal end

        self.ffmpeg_thread = Thread(target=read_ffmpeg)
        self.ffmpeg_thread.start()

    def start_microphone_capture(self, stt_adapter=None, stt_mode='none', file_path=None):
        if self.transmit not in (TransmitType.SENDRECV, TransmitType.SENDONLY):
            raise ValueError("Microphone capture requires SENDRECV or SENDONLY transmit type")

        if stt_mode == 'stream' and not stt_adapter:
            raise ValueError("stt_adapter required for 'stream' mode")
        if stt_mode == 'file' and not file_path:
            raise ValueError("file_path required for 'file' mode")
        if stt_mode not in ('none', 'stream', 'file'):
            raise ValueError("Invalid stt_mode: must be 'none', 'stream', or 'file'")

        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=8000,
            input=True,
            frames_per_buffer=160  # 20ms
        )

        if stt_mode == 'file':
            self.stt_file = open(file_path, 'wb')

        def capture_loop():
            while self.running:
                try:
                    data = self.stream.read(160, exception_on_overflow=False)
                    self.audio_queue.put(data)
                    if stt_mode == 'stream':
                        stt_adapter.feed_pcm(data)
                    elif stt_mode == 'file':
                        self.stt_file.write(data)
                except Exception as e:
                    debug(f"Microphone capture error: {e}")
                    break

        self.capture_thread = Thread(target=capture_loop)
        self.capture_thread.start()

    def stream_pcm(self, pcm_data: bytes):
        frame_size = 320  # 20ms at 8kHz s16le mono
        self.marker = True  # Mark the start of talkspurt
        for i in range(0, len(pcm_data), frame_size):
            frame = pcm_data[i:i + frame_size]
            if len(frame) < frame_size:
                frame += b'\x00' * (frame_size - len(frame))
            self.audio_queue.put(frame)

    def _encode_audio(self, pcm_data: bytes) -> bytes:
        if self.payload_type == PayloadType.PCMU:
            return audioop.lin2ulaw(pcm_data, 2)
        elif self.payload_type == PayloadType.PCMA:
            return audioop.lin2alaw(pcm_data, 2)
        # Add other codecs as needed
        return b''

    def _build_rtp_packet(self, payload: bytes) -> bytes:
        version = 2 << 6
        padding = 0 << 5
        extension = 0 << 4
        csrc_count = 0
        marker = 1 if self.marker else 0
        pt = self.payload_type.value
        header = struct.pack('!BBHII', version | padding | extension | csrc_count, marker << 7 | pt, self.seq, self.timestamp, self.ssrc)
        self.marker = False
        self.seq = (self.seq + 1) % 0x10000
        self.timestamp = (self.timestamp + len(payload)) % 0x100000000
        return header + payload

    def _send_loop(self):
        while self.running:
            try:
                pcm_data = self.audio_queue.get(timeout=0.02)
                if pcm_data is None:
                    break
                encoded = self._encode_audio(pcm_data)
                packet = self._build_rtp_packet(encoded)
                self.sock.sendto(packet, (self.ip, self.port))
            except queue.Empty:
                time.sleep(0.001)
