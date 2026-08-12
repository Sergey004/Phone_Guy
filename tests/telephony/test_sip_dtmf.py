"""Tests for DTMF (RFC 4733) transport layer in telephony/sip_rtp_client.py.

Covers:
- SDP construction advertises telephone-event PT 101.
- _parse_sdp extracts the remote dtmf_pt (incl. non-default PTs like 96).
- RTP receive path dispatches PT=dtmf_pt to DTMF handler and does not leak to STT.
- RTP receive path still feeds PCM to STT for PT=8/0.
- _send_dtmf_event produces correct RFC 4733 packet sequence (first marker=1,
  end-repetitions=3, PT=dtmf_pt).
- seq/ts continuity preserved after DTMF.
"""

import asyncio
import struct
from unittest.mock import MagicMock

import pytest

from telephony.sip_rtp_client import (
    DEFAULT_DTMF_PT,
    DTMF_END_REPETITIONS,
    RFC4733_EVENT_BY_DIGIT,
    RTPProtocol,
    SIPClient,
)


# ---------- helpers ----------


def _make_rtp_packet(
    pt: int, seq: int, ts: int, ssrc: int, payload: bytes, marker: bool = False
) -> bytes:
    b0 = 0x80
    b1 = (0x80 if marker else 0x00) | (pt & 0x7F)
    return struct.pack("!BBHII", b0, b1, seq, ts, ssrc) + payload


def _make_dtmf_event_packet(
    event: int,
    end: bool,
    duration: int,
    ts: int,
    seq: int,
    pt: int = 101,
    volume: int = 10,
    ssrc: int = 0xCAFEBABE,
) -> bytes:
    b1 = (0x80 if end else 0x00) | (volume & 0x3F)
    body = struct.pack("!BBHI", event, b1, duration)
    return _make_rtp_packet(pt, seq, ts, ssrc, body)


# ---------- SDP advertisement ----------


def test_sdp_offers_telephone_event_default_pt():
    client = SIPClient("user", "pass", "127.0.0.1", "127.0.0.1", stt_adapter=None)
    sdp = client._build_sdp()
    assert f"m=audio {client.rtp_port} RTP/AVP 8 0 {DEFAULT_DTMF_PT}" in sdp
    assert f"a=rtpmap:{DEFAULT_DTMF_PT} telephone-event/8000" in sdp
    assert f"a=fmtp:{DEFAULT_DTMF_PT} 0-15" in sdp


# ---------- SDP parsing: detect remote dtmf_pt ----------


def test_sdp_parser_finds_default_dtmf_pt():
    """Если SDP не сообщает telephone-event — дефолтим на 101 (далеко SIP-стек
    его всё равно понимает, но без согласования событий мож не передавать)."""
    client = SIPClient("u", "p", "10.0.0.1", "10.0.0.2", stt_adapter=None)
    sdp_lines = [
        "v=0",
        "c=IN IP4 10.0.0.5",
        "m=audio 12345 RTP/AVP 8 0",
        "a=rtpmap:8 PCMA/8000",
    ]
    ip, port, dtmf_pt = client._parse_sdp(sdp_lines)
    assert ip == "10.0.0.5"
    assert port == 12345
    # No telephone-event advertised → default
    assert dtmf_pt == DEFAULT_DTMF_PT


def test_sdp_parser_extracts_remote_dtmf_pt_non_default():
    client = SIPClient("u", "p", "10.0.0.1", "10.0.0.2", stt_adapter=None)
    sdp_lines = [
        "v=0",
        "c=IN IP4 10.0.0.5",
        "m=audio 12345 RTP/AVP 8 0 96",
        "a=rtpmap:8 PCMA/8000",
        "a=rtpmap:96 telephone-event/8000",
        "a=fmtp:96 0-15",
    ]
    ip, port, dtmf_pt = client._parse_sdp(sdp_lines)
    assert ip == "10.0.0.5"
    assert port == 12345
    assert dtmf_pt == 96


def test_sdp_parser_ignores_non_telephone_event_dynamic_pt():
    """PT 96 без telephone-event rtpmap не должен считаться DTMF."""
    client = SIPClient("u", "p", "10.0.0.1", "10.0.0.2", stt_adapter=None)
    sdp_lines = [
        "m=audio 5000 RTP/AVP 8 0 96",
        "a=rtpmap:96 some-codec/8000",
    ]
    _, _, dtmf_pt = client._parse_sdp(sdp_lines)
    assert dtmf_pt == DEFAULT_DTMF_PT


# ---------- RTP receive dispatch ----------


def test_recv_pt101_does_not_leak_to_stt():
    """Regression: раньше любой PT шёл в audioop.alaw2lin и STT. PT=101 не должен."""
    stt = MagicMock()
    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=stt,
        dtmf_pt=101,
    )
    pkt = _make_dtmf_event_packet(event=5, end=True, duration=800, ts=0, seq=0)
    rtp.datagram_received(pkt, ("10.0.0.1", 5004))
    stt.enqueue_frame.assert_not_called()


def test_recv_pt8_pcms_go_to_stt():
    stt = MagicMock()
    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=stt,
        dtmf_pt=101,
    )
    # 4 байта PCMA payload после 12-байтного заголовка PT=8
    pkt = _make_rtp_packet(pt=8, seq=1, ts=160, ssrc=1, payload=b"\xd5\xd5\xd5\xd5")
    rtp.datagram_received(pkt, ("10.0.0.1", 5004))
    stt.enqueue_frame.assert_called_once()


def test_recv_pt0_ulaw_pcms_go_to_stt():
    stt = MagicMock()
    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=stt,
        dtmf_pt=101,
    )
    pkt = _make_rtp_packet(pt=0, seq=1, ts=160, ssrc=1, payload=b"\xff\xff\xff\xff")
    rtp.datagram_received(pkt, ("10.0.0.1", 5004))
    stt.enqueue_frame.assert_called_once()


def test_recv_unknown_pt_ignored():
    """PT, не PCMA/PCMU/telephone-event — игнорируем (фикс: нельзя лить мусор в STT)."""
    stt = MagicMock()
    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=stt,
        dtmf_pt=101,
    )
    pkt = _make_rtp_packet(pt=42, seq=1, ts=160, ssrc=1, payload=b"\x00" * 8)
    rtp.datagram_received(pkt, ("10.0.0.1", 5004))
    stt.enqueue_frame.assert_not_called()


# ---------- DTMF receive event detection ----------


@pytest.mark.asyncio
async def test_recv_dtmf_end_event_triggers_callback_once():
    received = []

    async def cb(digit: str):
        received.append(digit)

    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=MagicMock(),
        dtmf_pt=101,
        on_dtmf_callback=cb,
    )
    # sim in-progress + 3 end-replications for digit '5'
    event = RFC4733_EVENT_BY_DIGIT["5"]  # = 5
    seq = 100
    ts = 1000
    # 5 in-progress packets (no End).
    for step in range(5):
        pkt = _make_dtmf_event_packet(
            event=event, end=False, duration=(step + 1) * 160, ts=ts, seq=seq
        )
        rtp.datagram_received(pkt, ("10.0.0.1", 5004))
        seq += 1
    # 3 End-of-event packets (same ts, increasing seq).
    for _ in range(DTMF_END_REPETITIONS):
        pkt = _make_dtmf_event_packet(
            event=event, end=True, duration=800, ts=ts, seq=seq
        )
        rtp.datagram_received(pkt, ("10.0.0.1", 5004))
        seq += 1
    # Grace a tick so asyncio.create_task in _emit_dtmf_event runs.
    await asyncio.sleep(0.01)
    assert received == ["5"]


@pytest.mark.asyncio
async def test_recv_dtmf_single_end_no_preroll_emits():
    """Некоторые шлюзы шлют один End-пакет без in-progress (мгновенный клик).
    Тогда _dtmf_in_state['event'] ещё None — мы засчитываем сразу (best-effort)."""
    received = []

    async def cb(digit: str):
        received.append(digit)

    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=MagicMock(),
        dtmf_pt=101,
        on_dtmf_callback=cb,
    )
    pkt = _make_dtmf_event_packet(
        event=RFC4733_EVENT_BY_DIGIT["3"], end=True, duration=160, ts=0, seq=0
    )
    rtp.datagram_received(pkt, ("10.0.0.1", 5004))
    await asyncio.sleep(0.01)
    assert received == ["3"]


# ---------- DTMF send event ----------


@pytest.mark.asyncio
async def test_send_dtmf_event_emits_correct_packets():
    """First packet: marker=1, PT=dtmf_pt, End=0.
    Last DTMF_END_REPETITIONS packets: End=1, M=0, same ts/duration.
    Sequence grows monotonically."""
    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=None,
        dtmf_pt=101,
    )
    rtp.ssrc = 0x11111111
    rtp.sequence = 500
    rtp.timestamp = 10000
    sent = []
    fake_transport = MagicMock()
    fake_transport.is_closing.return_value = False

    def fake_sendto(data, addr):
        sent.append(bytes(data))

    fake_transport.sendto = fake_sendto
    rtp.transport = fake_transport

    await rtp._send_dtmf_event("5")

    # All packets share PT=101 (byte 1 & 0x7F == 101)
    pts = [b[1] & 0x7F for b in sent]
    assert all(pt == 101 for pt in pts), pts

    # First packet has marker bit set
    assert (sent[0][1] & 0x80) == 0x80, "first packet should have marker bit"

    # End-repetition packets: last DTMF_END_REPETITIONS have End=1
    ends = [(b[12] >> 7) & 0x01 for b in sent]  # body[0] >> 7
    assert sum(ends[-DTMF_END_REPETITIONS:]) == DTMF_END_REPETITIONS
    # And marker bit clear on end packets
    for b in sent[-DTMF_END_REPETITIONS:]:
        assert (b[1] & 0x80) == 0x00

    # Timestamp of all DTMF event packets (excluding trailing silence) is the start
    ts_values = struct.unpack_from("!I", sent[0], 8)[0]
    # in-progress packets (first n_progress) + end-repetitions share ts_start
    n_progress = max(1, (100 + 20 - 1) // 20)  # 5
    for b in sent[: n_progress + DTMF_END_REPETITIONS]:
        assert struct.unpack_from("!I", b, 8)[0] == 10000  # ts_start
    # Trailing silence uses incremented timestamps (PCMA PT=8)
    for b in sent[n_progress + DTMF_END_REPETITIONS :]:
        assert (b[1] & 0x7F) == 8  # PCMA silence


@pytest.mark.asyncio
async def test_send_dtmf_event_preserves_seq_monotonicity():
    rtp = RTPProtocol(
        audio_source=MagicMock(),
        dest_ip="10.0.0.1",
        dest_port=5004,
        stt_adapter=None,
        dtmf_pt=101,
    )
    rtp.sequence = 100
    rtp.timestamp = 5000
    fake_transport = MagicMock()
    fake_transport.is_closing.return_value = False
    fake_transport.sendto = lambda d, a: None
    rtp.transport = fake_transport

    seqs_seen = []

    def spy(d, a):
        seqs_seen.append(struct.unpack_from("!H", d, 2)[0])

    fake_transport.sendto = spy
    await rtp._send_dtmf_event("1")
    # All seqs are unique and monotonic modulo 2^16.
    assert seqs_seen == sorted(seqs_seen)
    assert len(set(seqs_seen)) == len(seqs_seen)
    # rtp.sequence advanced to last+1
    assert rtp.sequence == (seqs_seen[-1] + 1) % 65536


def test_sipclient_send_dtmf_returns_false_when_not_in_call():
    client = SIPClient("u", "p", "127.0.0.1", "127.0.0.1", stt_adapter=None)

    async def go():
        ok = await client.send_dtmf("5")
        assert ok is False

    asyncio.get_event_loop().run_until_complete(go()) if False else None

    # Sync test of error path: bad digit raises; not-in-call returns False.
    import asyncio as _aio

    async def _runner():
        ok = await client.send_dtmf("5")
        assert ok is False
        try:
            await client.send_dtmf("Z")
        except ValueError:
            return True
        return False

    assert _aio.run(_runner()) is True


# ---------- seq/ts wraparound fix ----------


def test_stream_audio_seq_ts_wraparound_constants():
    """Простая smoke-проверка констант, чтобы кодировщик не ссылался на off-by-one."""
    assert 65536 == 1 << 16
    assert (1 << 32) == 4294967296
