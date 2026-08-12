import asyncio
import random
import hashlib
import time
import struct
import string
import audioop
import socket
import logging

logger = logging.getLogger(__name__)

# RFC 4733 / RFC 2833 DTMF event codes (0-15). Используется и на приём,
# и на отправку, а также в SIPClient.send_dtmf().
RFC4733_EVENT_BY_DIGIT = {
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "*": 10,
    "#": 11,
    "A": 12,
    "B": 13,
    "C": 14,
    "D": 15,
}
RFC4733_DIGIT_BY_EVENT = {v: k for k, v in RFC4733_EVENT_BY_DIGIT.items()}

# Значения по умолчанию (перекрываются из SDP / конфига).
DEFAULT_DTMF_PT = 101  # динамический payload type для telephone-event
DEFAULT_DTMF_DURATION_MS = 100  # длительность одного события (RFC 4733)
DEFAULT_DTMF_VOLUME = 10  # уровень в -dBm0 (RFC рекомендует 0..19)
DEFAULT_DTMF_GAP_MS = 70  # пауза между DTMF-событиями
DTMF_END_REPETITIONS = 3  # сколько End-пакетов шлёт отправитель (RFC 4733 §2.5.1.3)

# A-law silence byte (используется для DTMF-gap фреймов)
ALAW_SILENCE_BYTE = 0xD5


class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        audio_source,
        dest_ip,
        dest_port,
        stt_adapter=None,
        dtmf_pt: int = DEFAULT_DTMF_PT,
        on_dtmf_callback=None,
    ):
        self.audio_source = audio_source
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.stt_adapter = stt_adapter
        self.dtmf_pt = dtmf_pt
        # async callback: async (digit: str) -> None — вызывается при приёме DTMF
        self.on_dtmf_callback = on_dtmf_callback
        self.transport = None
        self.sequence = 0
        self.timestamp = 0
        self.ssrc = random.randint(0, 0xFFFFFFFF)
        self.running = False
        self._last_register_cseq = -1
        # Очередь цифр на отправку (драпируется из stream_audio с приоритетом над аудио)
        self._dtmf_out_queue: asyncio.Queue[str] = asyncio.Queue()
        # Состояние приёмника RFC 4733: отслеживание End-of-event repetitions
        self._dtmf_in_state = {"event": None, "end_count": 0, "last_seq": None}

    def connection_made(self, transport):
        self.transport = transport
        self.running = True
        print(f"[RTP] Stream started -> {self.dest_ip}:{self.dest_port}")
        asyncio.create_task(self.stream_audio())

    # Приём RTP. Диспетчеризация по payload type (PT).
    # PT=dtmf_pt      -> DTMF-событие (RFC 4733)
    # PT=8 (PCMA)    -> STT
    # PT=0 (PCMU)    -> STT
    # остальные       -> игнорируем (фикс: ранее любой PT попадал в alaw2lin)
    def datagram_received(self, data, addr):
        if len(data) < 12 or (data[0] & 0xC0) != 0x80:
            return
        pt = data[1] & 0x7F
        # Пропускаем CSRC list (4 байта на каждый) и header extension (RFC 3550)
        offset = 12 + 4 * (data[0] & 0x0F)
        if (data[0] & 0x10) and len(data) >= offset + 4:
            ext_len = struct.unpack_from("!H", data, offset + 2)[0]
            offset += 4 + 4 * ext_len
        if offset >= len(data):
            return

        if pt == self.dtmf_pt:
            self._handle_dtmf_in(data, offset)
            return
        if self.stt_adapter is None:
            return
        try:
            if pt == 8:
                pcm = audioop.alaw2lin(data[offset:], 2)
            elif pt == 0:
                pcm = audioop.ulaw2lin(data[offset:], 2)
            else:
                return
            self.stt_adapter.enqueue_frame(pcm)
        except Exception:
            pass

    def _handle_dtmf_in(self, data: bytes, offset: int) -> None:
        """Разбирает одно 4-байтное тело события RFC 4733 и детектирует завершение события.

        Реализована стандартная эвристика: пакет с флагом End=1 считается концом
        события, но RFC 4733 §2.5.1.3 требует, чтобы отправитель повторил End-пакет
        не менее 3 раз. Мы засчитываем событие либо при получении End=1 и смене
        sequence/event/timestamp (следующий пакет отличный), либо при 3 End-пакетах
        подряд — это покрывает Asterisk и freeswitch.
        """
        if len(data) < offset + 4:
            return
        event = data[offset]
        b1 = data[offset + 1]
        end = (b1 >> 7) & 0x01
        volume = b1 & 0x3F  # noqa: F841 — оставлено для отладки
        seq = struct.unpack_from("!H", data, 2)[0]
        st = self._dtmf_in_state

        if st["event"] is None:
            if end:
                # Короткий одиночный End без pre-roll — засчитываем сразу
                # (некоторые шлюзы шлют так для мгновенных событий).
                self._emit_dtmf_event(event)
                st.update({"event": None, "end_count": 0, "last_seq": None})
            else:
                st.update({"event": event, "end_count": 0, "last_seq": seq})
            return

        if end:
            st["end_count"] += 1
            st["last_seq"] = seq
            if st["end_count"] >= DTMF_END_REPETITIONS:
                self._emit_dtmf_event(st["event"])
                st.update({"event": None, "end_count": 0, "last_seq": None})
            return

        # Mid-event пакет без End: либо продолжение того же события, либо новое
        if event != st["event"] or seq != st["last_seq"] + 1:
            # Предыдущее событие не завершилось корректно (пакеты потеряны),
            # но начинаем новое — засчитываем предыдущее по Best-effort.
            self._emit_dtmf_event(st["event"])
            st.update({"event": event, "end_count": 0, "last_seq": seq})
        else:
            st["last_seq"] = seq

    def _emit_dtmf_event(self, event: int) -> None:
        digit = RFC4733_DIGIT_BY_EVENT.get(event)
        if digit is None:
            logger.debug("Unknown RFC 4733 event code: %d", event)
            return
        logger.info("🔔 DTMF received: %s (event=%d)", digit, event)
        if self.on_dtmf_callback is not None:
            asyncio.create_task(self.on_dtmf_callback(digit))

    async def stream_audio(self):
        FRAME_MS = 20
        SAMPLES_PER_FRAME = 160
        next_time = time.time()

        while self.running:
            # Приоритет: DTMF-событие из очереди (блокирует аудио на время отправки)
            if not self._dtmf_out_queue.empty():
                digit = self._dtmf_out_queue.get_nowait()
                await self._send_dtmf_event(digit)
            else:
                payload = self.audio_source.get_frame(SAMPLES_PER_FRAME)
                header = struct.pack(
                    "!BBHII", 0x80, 8, self.sequence, self.timestamp, self.ssrc
                )
                if self.transport and not self.transport.is_closing():
                    self.transport.sendto(
                        header + payload, (self.dest_ip, self.dest_port)
                    )
                else:
                    break
                self.sequence = (self.sequence + 1) % 65536
                self.timestamp = (self.timestamp + SAMPLES_PER_FRAME) % (1 << 32)
            next_time += FRAME_MS / 1000.0
            delay = next_time - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

    async def _send_dtmf_event(self, digit: str) -> None:
        """Отправляет одно DTMF-событие как серию RTP-пакетов PT=dtmf_pt (RFC 4733).

        Структура:
          * несколько «in-progress» пакетов (Marker=1 у первого, End=0) до достижения
            длительности DEFAULT_DTMF_DURATION_MS;
          * DTMF_END_REPETITIONS «End-of-event» пакетов (End=1, Marker=0) с одним
            timestamp/duration;
          * кадр-пауза DEFAULT_DTMF_GAP_MS silence (PCMA 0xD5 × 160 на 20ms).
        sequence и timestamp разделяются с аудио-петлёй — монотонно растут.
        """
        event = RFC4733_EVENT_BY_DIGIT.get(digit)
        if event is None:
            logger.warning("Cannot send DTMF: bad digit %r", digit)
            return
        if self.transport is None or self.transport.is_closing():
            return

        FRAME_MS = 20
        SAMPLES_PER_FRAME = 160
        # Количество in-progress пакетов: ceil(duration_ms / 20ms), минимум 1.
        n_progress = max(1, (DEFAULT_DTMF_DURATION_MS + FRAME_MS - 1) // FRAME_MS)
        ts_start = self.timestamp
        base_seq = self.sequence

        # --- in-progress пакеты ---
        for step in range(n_progress):
            marker = 1 if step == 0 else 0
            duration = (step + 1) * FRAME_MS * 8  # в timestamp-единицах (8000 Hz)
            body = struct.pack("!BBHI", event, DEFAULT_DTMF_VOLUME, duration)
            header = struct.pack(
                "!BBHII",
                0x80,
                (marker << 7) | self.dtmf_pt,
                base_seq,
                ts_start,
                self.ssrc,
            )
            self.transport.sendto(header + body, (self.dest_ip, self.dest_port))
            base_seq = (base_seq + 1) % 65536
            await asyncio.sleep(FRAME_MS / 1000.0)

        # --- End-of-event репликации (одинаковый ts/duration, End=1, M=0) ---
        final_duration = n_progress * FRAME_MS * 8
        for _ in range(DTMF_END_REPETITIONS):
            body = struct.pack(
                "!BBHI", event, (1 << 7) | DEFAULT_DTMF_VOLUME, final_duration
            )
            header = struct.pack(
                "!BBHII", 0x80, self.dtmf_pt, base_seq, ts_start, self.ssrc
            )
            self.transport.sendto(header + body, (self.dest_ip, self.dest_port))
            base_seq = (base_seq + 1) % 65536
            await asyncio.sleep(FRAME_MS / 1000.0)

        # --- gap: DEFAULT_DTMF_GAP_MS тишины ---
        gap_frames = max(1, DEFAULT_DTMF_GAP_MS // FRAME_MS)
        for _ in range(gap_frames):
            body = bytes([ALAW_SILENCE_BYTE] * SAMPLES_PER_FRAME)
            header = struct.pack("!BBHII", 0x80, 8, base_seq, self.timestamp, self.ssrc)
            self.transport.sendto(header + body, (self.dest_ip, self.dest_port))
            base_seq = (base_seq + 1) % 65536
            self.timestamp = (self.timestamp + SAMPLES_PER_FRAME) % (1 << 32)
            await asyncio.sleep(FRAME_MS / 1000.0)

        # Синхронизируем sequence и timestamp с тем, что мы послали.
        self.sequence = base_seq

    def stop(self):
        self.running = False
        if self.transport:
            self.transport.close()


def get_local_ip_for(server_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((server_ip, 5060))
        return s.getsockname()[0]
    finally:
        s.close()


class SIPClient(asyncio.DatagramProtocol):
    def __init__(self, username, password, server_ip, local_ip, stt_adapter=None):
        self.username = username
        self.password = password
        self.server_ip = server_ip
        self.local_ip = local_ip
        self.rtp_ip = get_local_ip_for(server_ip)
        self.stt_adapter = stt_adapter

        self.transport = None
        self.sip_port = 5065
        self.rtp_port = 10000 + random.randint(0, 5000)

        self.call_id = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=16)
        )
        self.local_tag = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=10)
        )
        self.remote_tag = None
        self.branch = "z9hG4bK" + "".join(
            random.choices(string.ascii_lowercase + string.digits, k=10)
        )
        self.cseq = 1
        self.sess_id = random.randint(1, 999999999)
        self.sess_version = 1

        self.registered = False
        self.in_call = False
        self.current_target = None
        self.remote_number = None

        self.rtp_protocol = None
        self.audio_source = None
        self.call_connected_event = asyncio.Event()
        # Выставляется при CANCEL/BYE/ошибке — прерывает prepare_audio_callback
        self.call_abort_event = asyncio.Event()
        self.prepare_audio_callback = None
        # async callback: (digit: str) -> None — вызывается при приёме DTMF (RFC 4733)
        self.dtmf_received_callback = None

    def connection_made(self, transport):
        self.transport = transport
        print(f"✅ [SIP] Socket Bound on {self.local_ip}:{self.sip_port}")
        asyncio.create_task(self._keep_alive())

    def datagram_received(self, data, addr):
        msg = data.decode("utf-8", errors="ignore")
        asyncio.create_task(self.handle_sip_message(msg, addr))

    async def _keep_alive(self):
        while True:
            await asyncio.sleep(45)
            if self.registered:
                self.registered = False  # сбрасываем до отправки
            self.cseq += 1
            self.branch = "z9hG4bK" + "".join(
                random.choices(string.ascii_lowercase + string.digits, k=10)
            )
            await self.register()
            await asyncio.sleep(5)
            if not self.registered:
                print("⚠️ [SIP] Re-registration failed — PBX unreachable?")

    def set_audio_source(self, source):
        self.audio_source = source

    def set_prepare_callback(self, callback):
        self.prepare_audio_callback = callback

    def send_raw(self, msg, dest=None):
        target = dest if dest else (self.server_ip, 5060)
        if self.transport:
            self.transport.sendto(msg.encode(), target)

    async def register(self):
        self.branch = "z9hG4bK" + "".join(
            random.choices(string.ascii_lowercase + string.digits, k=10)
        )
        req = self._build_register_packet()
        self.send_raw(req)

    async def invite(self, target_number):
        print(f"[SIP] Calling outbound -> {target_number}")
        self.current_target = target_number
        self.remote_number = target_number  # Запоминаем, кому звоним
        self.cseq += 1
        self.call_connected_event.clear()
        req = self._build_invite_packet(target_number)
        self.send_raw(req)

    async def bye(self):
        print("[SIP] Sending BYE")
        self.cseq += 1
        target = self.current_target if self.current_target else self.username
        to_hdr = f"<sip:{target}@{self.server_ip}>"
        if self.remote_tag:
            to_hdr += f";tag={self.remote_tag}"
        msg = f"BYE sip:{target}@{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: {to_hdr}\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} BYE\r\nMax-Forwards: 70\r\nContent-Length: 0\r\n\r\n"
        self.send_raw(msg)
        self._stop_rtp()
        self.in_call = False

    def _stop_rtp(self):
        if self.rtp_protocol:
            self.rtp_protocol.stop()
            self.rtp_protocol = None

    def _reset_call_state(self):
        """Сброс состояния после завершения/отмены звонка."""
        self._stop_rtp()
        self.in_call = False
        self.call_connected_event.clear()
        self.call_abort_event.set()  # Прерывает prepare_audio_callback если висит

    async def _start_rtp(self, remote_ip, remote_port, dtmf_pt: int = DEFAULT_DTMF_PT):
        if not self.audio_source:
            return
        print(f"[SIP] Starting RTP -> {remote_ip}:{remote_port} (DTMF PT={dtmf_pt})")
        loop = asyncio.get_running_loop()
        _, protocol = await loop.create_datagram_endpoint(
            lambda: RTPProtocol(
                self.audio_source,
                remote_ip,
                remote_port,
                self.stt_adapter,
                dtmf_pt=dtmf_pt,
                on_dtmf_callback=self.dtmf_received_callback,
            ),
            local_addr=("0.0.0.0", self.rtp_port),
        )
        self.rtp_protocol = protocol
        self.in_call = True
        self.call_connected_event.set()

    async def send_dtmf(self, digit: str) -> bool:
        """Поставить DTMF-цифру в очередь отправки. Возвращает False, если нет активного RTP."""
        if self.rtp_protocol is None or not self.in_call:
            return False
        if digit not in RFC4733_EVENT_BY_DIGIT:
            raise ValueError(f"Bad DTMF digit: {digit!r}")
        self.rtp_protocol._dtmf_out_queue.put_nowait(digit)
        return True

    # --- Helpers ---
    def _extract_header(self, lines, name):
        name = name.lower()
        for line in lines:
            if line.lower().startswith(name + ":"):
                return line[len(name) + 1 :].strip()
        return None

    def _extract_number_from_uri(self, uri):
        """Парсит sip:1001@ip"""
        try:
            if "sip:" in uri:
                return uri.split("sip:")[1].split("@")[0]
            return "unknown"
        except Exception:
            return "unknown"

    def _build_register_packet(self, auth=None):
        msg = f"REGISTER sip:{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch};rport\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: <sip:{self.username}@{self.server_ip}>\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} REGISTER\r\nContact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\nMax-Forwards: 70\r\nUser-Agent: PhoneGuyBot/1.0\r\n"
        if auth:
            msg += f"{auth}\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return msg

    def _build_invite_packet(self, target, auth=None):
        self.sess_version += 1
        sdp = self._build_sdp()
        msg = f"INVITE sip:{target}@{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: <sip:{target}@{self.server_ip}>\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} INVITE\r\nContact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\nContent-Type: application/sdp\r\n"
        if auth:
            msg += f"{auth}\r\n"
        msg += f"Content-Length: {len(sdp)}\r\n\r\n{sdp}"
        return msg

    def _build_180_ringing(self, lines):
        via = self._extract_header(lines, "Via")
        from_hdr = self._extract_header(lines, "From")
        to_hdr = self._extract_header(lines, "To")
        call_id = self._extract_header(lines, "Call-ID")
        cseq = self._extract_header(lines, "CSeq")
        if "tag=" not in to_hdr:
            to_hdr += f";tag={self.local_tag}"
        return f"SIP/2.0 180 Ringing\r\nVia: {via}\r\nFrom: {from_hdr}\r\nTo: {to_hdr}\r\nCall-ID: {call_id}\r\nCSeq: {cseq}\r\nContact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\nContent-Length: 0\r\n\r\n"

    def _build_200_ok(self, lines):
        via = self._extract_header(lines, "Via")
        from_hdr = self._extract_header(lines, "From")
        to_hdr = self._extract_header(lines, "To")
        call_id = self._extract_header(lines, "Call-ID")
        cseq = self._extract_header(lines, "CSeq")
        if "tag=" not in to_hdr:
            to_hdr += f";tag={self.local_tag}"
        sdp = self._build_sdp()
        return f"SIP/2.0 200 OK\r\nVia: {via}\r\nFrom: {from_hdr}\r\nTo: {to_hdr}\r\nCall-ID: {call_id}\r\nCSeq: {cseq}\r\nContact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\nContent-Type: application/sdp\r\nContent-Length: {len(sdp)}\r\n\r\n{sdp}"

    def _build_sdp(self):
        return (
            f"v=0\r\n"
            f"o=- {self.sess_id} {self.sess_version} IN IP4 {self.rtp_ip}\r\n"
            f"s=-\r\n"
            f"c=IN IP4 {self.rtp_ip}\r\n"
            f"t=0 0\r\n"
            f"m=audio {self.rtp_port} RTP/AVP 8 0 {DEFAULT_DTMF_PT}\r\n"
            f"a=rtpmap:8 PCMA/8000\r\n"
            f"a=rtpmap:0 PCMU/8000\r\n"
            f"a=rtpmap:{DEFAULT_DTMF_PT} telephone-event/8000\r\n"
            f"a=fmtp:{DEFAULT_DTMF_PT} 0-15\r\n"
            f"a=sendrecv\r\n"
        )

    def _generate_auth(self, nonce, realm, method, uri):
        ha1 = hashlib.md5(
            f"{self.username}:{realm}:{self.password}".encode()
        ).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        return hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

    def _parse_sdp(self, lines):
        """Парсит remote SDP и возвращает (ip, port, dtmf_pt).

        dtmf_pt определяется по наличию a=rtpmap:N telephone-event/8000 среди
        payload-type'ов из m=audio. Дефолт — DEFAULT_DTMF_PT (101).
        """
        ip = self.server_ip
        port = 10000
        payload_in_m = []
        rtpmap_seen: dict[int, str] = {}
        for line in lines:
            if line.startswith("c=IN"):
                ip = line.split()[-1]
            elif line.startswith("m=audio"):
                payload_in_m = line.split()[3:]
            elif line.startswith("a=rtpmap:"):
                try:
                    pt_str, rest = line[len("a=rtpmap:") :].split(" ", 1)
                    rtpmap_seen[int(pt_str)] = rest
                except Exception:
                    pass
        dtmf_pt = DEFAULT_DTMF_PT
        for pt_str in payload_in_m:
            try:
                pt = int(pt_str)
            except Exception:
                continue
            if "telephone-event" in rtpmap_seen.get(pt, ""):
                dtmf_pt = pt
                break
        return ip, port, dtmf_pt

    async def handle_sip_message(self, msg, addr):
        lines = msg.splitlines()
        if not lines:
            return
        first = lines[0]

        if first.startswith("OPTIONS"):
            via = self._extract_header(lines, "Via")
            from_h = self._extract_header(lines, "From")
            to_h = self._extract_header(lines, "To")
            call_id = self._extract_header(lines, "Call-ID")
            cseq = self._extract_header(lines, "CSeq")
            response = f"SIP/2.0 200 OK\r\nVia: {via}\r\nFrom: {from_h}\r\nTo: {to_h}\r\nCall-ID: {call_id}\r\nCSeq: {cseq}\r\nContact: <sip:{self.username}@{self.local_ip}:{self.sip_port}>\r\nContent-Length: 0\r\n\r\n"
            self.send_raw(response, dest=addr)

        elif first.startswith("CANCEL"):
            print("❌ [SIP] Call CANCELLED by remote during ringing")
            via = self._extract_header(lines, "Via")
            from_h = self._extract_header(lines, "From")
            to_h = self._extract_header(lines, "To")
            call_id = self._extract_header(lines, "Call-ID")
            cseq = self._extract_header(lines, "CSeq")
            # RFC 3261: ответить 200 OK на CANCEL, затем 487 на оригинальный INVITE
            self.send_raw(
                f"SIP/2.0 200 OK\r\nVia: {via}\r\nFrom: {from_h}\r\nTo: {to_h}\r\n"
                f"Call-ID: {call_id}\r\nCSeq: {cseq}\r\nContent-Length: 0\r\n\r\n",
                dest=addr,
            )
            self.send_raw(
                f"SIP/2.0 487 Request Terminated\r\nVia: {via}\r\nFrom: {from_h}\r\nTo: {to_h}\r\n"
                f"Call-ID: {call_id}\r\nCSeq: {cseq.replace('CANCEL', 'INVITE')}\r\nContent-Length: 0\r\n\r\n",
                dest=addr,
            )
            self._reset_call_state()

        elif first.startswith("INVITE"):
            print(f"🔔 [SIP] Incoming Call from {addr}")
            self.call_id = self._extract_header(lines, "Call-ID")
            from_h = self._extract_header(lines, "From")
            if "tag=" in from_h:
                self.remote_tag = from_h.split("tag=")[1].split(";")[0]

            self.remote_number = self._extract_number_from_uri(from_h)
            print(f"📞 Identified Remote Caller: {self.remote_number}")

            # Сбрасываем abort перед новым звонком
            self.call_abort_event.clear()

            print("[SIP] Sending 180 Ringing...")
            self.send_raw(self._build_180_ringing(lines), dest=addr)

            if self.prepare_audio_callback:
                print("[SIP] Preparing AI greeting...")
                await self.prepare_audio_callback()
            else:
                await asyncio.sleep(2)

            # Проверяем — не отменили ли звонок пока мы генерировали
            if self.call_abort_event.is_set():
                print(
                    "⚠️ [SIP] Call was cancelled during greeting generation — ignoring"
                )
                return

            print("[SIP] Answering Call...")
            self.send_raw(self._build_200_ok(lines), dest=addr)
            rip, rport, dtmf_pt = self._parse_sdp(lines)
            await self._start_rtp(rip, rport, dtmf_pt)

        elif "401" in first or "407" in first:
            cseq_line = self._extract_header(lines, "CSeq")
            method = cseq_line.split()[1] if cseq_line else "REGISTER"
            nonce, realm = "", ""
            auth_line = self._extract_header(
                lines, "WWW-Authenticate"
            ) or self._extract_header(lines, "Proxy-Authenticate")
            if auth_line:
                for p in auth_line.split(","):
                    if 'nonce="' in p:
                        nonce = p.split('nonce="')[1].split('"')[0]
                    if 'realm="' in p:
                        realm = p.split('realm="')[1].split('"')[0]
            self.cseq += 1
            self.branch = "z9hG4bK" + "".join(
                random.choices(string.ascii_lowercase + string.digits, k=10)
            )
            uri = (
                f"sip:{self.server_ip}"
                if method == "REGISTER"
                else f"sip:{self.current_target}@{self.server_ip}"
            )
            resp = self._generate_auth(nonce, realm, method, uri)
            auth_h = f'Authorization: Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{resp}", algorithm=MD5'
            if method == "REGISTER":
                self.send_raw(self._build_register_packet(auth_h))
            elif method == "INVITE":
                self.send_raw(self._build_invite_packet(self.current_target, auth_h))

        elif "200 OK" in first and "REGISTER" in (
            self._extract_header(lines, "CSeq") or ""
        ):
            cseq_val = self._extract_header(lines, "CSeq") or ""
            if not self.registered:
                print("✅ [SIP] Registered Successfully!")
            self.registered = True

        elif "200 OK" in first and "INVITE" in (
            self._extract_header(lines, "CSeq") or ""
        ):
            print("✅ [SIP] Outbound Call Accepted")
            to_h = self._extract_header(lines, "To")
            if "tag=" in to_h:
                self.remote_tag = to_h.split("tag=")[1].split(";")[0]
            ack = f"ACK sip:{self.current_target}@{self.server_ip} SIP/2.0\r\nVia: SIP/2.0/UDP {self.local_ip}:{self.sip_port};branch={self.branch}\r\nFrom: <sip:{self.username}@{self.server_ip}>;tag={self.local_tag}\r\nTo: {to_h}\r\nCall-ID: {self.call_id}\r\nCSeq: {self.cseq} ACK\r\nContent-Length: 0\r\n\r\n"
            self.send_raw(ack)
            rip, rport, dtmf_pt = self._parse_sdp(lines)
            await self._start_rtp(rip, rport, dtmf_pt)

        elif "BYE" in first:
            print("📴 [SIP] Call Ended")
            self._reset_call_state()
            self.send_raw(
                f"SIP/2.0 200 OK\r\nVia: {self._extract_header(lines, 'Via')}\r\n"
                f"From: {self._extract_header(lines, 'From')}\r\n"
                f"To: {self._extract_header(lines, 'To')}\r\n"
                f"Call-ID: {self._extract_header(lines, 'Call-ID')}\r\n"
                f"CSeq: {self._extract_header(lines, 'CSeq')}\r\nContent-Length: 0\r\n\r\n",
                dest=addr,
            )

        elif any(code in first for code in ("486 ", "480 ", "503 ", "408 ", "404 ")):
            print(f"⚠️ [SIP] Call error: {first.strip()}")
            self._reset_call_state()
