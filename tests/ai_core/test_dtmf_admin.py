"""Tests for ai_core/dtmf_admin.py state machine (IVR admin menu via DTMF)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_core.dtmf_admin import DtmfAdminController, DEFAULT_PROMPTS


# ---------- fixtures ----------


def _make_controller(
    *,
    admin_pin: str = "1234",
    enter_prefix: str = "#9",
    dial_delay_sec: float = 0.01,
    menu_timeout_sec: float = 100.0,
    collect_timeout_sec: float = 100.0,
    on_dial_request=None,
):
    bridge = MagicMock()
    bridge.buffer = MagicMock()
    bridge.buffer.clear = MagicMock()

    tts = MagicMock()
    tts.speak = AsyncMock()

    stt = MagicMock()
    stt.pause = MagicMock()
    stt.resume = MagicMock()

    sip = MagicMock()
    sip.bye = AsyncMock()

    if on_dial_request is None:
        on_dial_request = AsyncMock()

    ctrl = DtmfAdminController(
        sip,
        bridge=bridge,
        tts=tts,
        stt=stt,
        admin_pin=admin_pin,
        enter_prefix=enter_prefix,
        dial_delay_sec=dial_delay_sec,
        menu_timeout_sec=menu_timeout_sec,
        collect_timeout_sec=collect_timeout_sec,
        on_dial_request=on_dial_request,
    )
    return ctrl, sip, bridge, tts, stt


async def _feed(ctrl, digits, sleep_between=0.001):
    for d in digits:
        await ctrl.handle_digit(d)
        await asyncio.sleep(sleep_between)


# ---------- IDLE -> EXPECT_9 (via prefix) ----------


@pytest.mark.asyncio
async def test_first_prefix_digit_mutes_bot():
    ctrl, _, _, _, stt = _make_controller()
    await ctrl.handle_digit("#")
    assert (
        ctrl._state == "IDLE"
    )  # secret incomplete; mute but stay IDLE until full prefix
    assert ctrl._prefix_idx == 1
    stt.pause.assert_called_once()
    # bridge buffer cleared when entering mute
    ctrl.bridge.buffer.clear.assert_called()


@pytest.mark.asyncio
async def test_wrong_prefix_digit_resets_and_resumes_stt():
    ctrl, _, _, _, stt = _make_controller()
    await ctrl.handle_digit("#")
    assert ctrl._prefix_idx == 1
    stt.pause.assert_called_once()
    # Wrong second digit
    await ctrl.handle_digit("5")  # not '9'
    assert ctrl._state == "IDLE"
    assert ctrl._prefix_idx == 0
    stt.resume.assert_called()


# ---------- COLLECT_PIN ----------


@pytest.mark.asyncio
async def test_full_secret_sequence_enters_menu():
    ctrl, _, _, tts, _ = _make_controller()
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4"])
    assert ctrl._state == "ADMIN_MENU"
    tts.speak.assert_called_once()
    # First prompt should be the menu prompt
    first_arg = tts.speak.call_args_list[0].args[0]
    assert "Admin menu" in first_arg


@pytest.mark.asyncio
async def test_wrong_pin_returns_to_idle_and_says_bad_pin():
    ctrl, _, _, tts, _ = _make_controller(admin_pin="1234")
    await _feed(
        ctrl, ["#", "9", "9", "9", "9", "9"]
    )  # 5th digit triggers check (admin_pin len=4)
    assert ctrl._state == "IDLE"
    # bad_pin prompt was spoken
    spoken = [c.args[0] for c in tts.speak.call_args_list if c.args]
    assert any("Incorrect PIN" in t for t in spoken)


@pytest.mark.asyncio
async def test_expect_9_other_digit_aborts_to_idle():
    ctrl, _, _, _, stt = _make_controller(enter_prefix="#")
    # enter_prefix is just "#" → after '#' we're in COLLECT_PIN? No: '#9' means '# then 9'.
    # When enter_prefix length=2 we go via _on_idle directly to COLLECT_PIN if both match.
    # But if user enters '#5' instead of '#9' -> abort.
    await ctrl.handle_digit("#")  # matches first prefix char
    await ctrl.handle_digit("5")  # not '9' -> reset
    assert ctrl._state == "IDLE"
    stt.resume.assert_called()


# ---------- ADMIN_MENU ----------


@pytest.mark.asyncio
async def test_menu_zero_hangup():
    ctrl, sip, _, _, _ = _make_controller()
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4", "0"])
    sip.bye.assert_awaited_once()
    assert ctrl._state == "IDLE"


@pytest.mark.asyncio
async def test_menu_hash_exits():
    ctrl, _, _, tts, stt = _make_controller()
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4", "#"])
    assert ctrl._state == "IDLE"
    stt.resume.assert_called()
    spoken = [c.args[0] for c in tts.speak.call_args_list if c.args]
    assert any("Exiting admin menu" in t for t in spoken)


@pytest.mark.asyncio
async def test_menu_star_repeats_menu_prompt():
    ctrl, _, _, tts, _ = _make_controller()
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4", "*"])
    # Burger: '*' repeats menu — speak("menu") twice (once at entry, once via '*')
    menu_calls = [
        c for c in tts.speak.call_args_list if c.args and "Admin menu" in c.args[0]
    ]
    assert len(menu_calls) == 2


# ---------- COLLECT_NUMBER ----------


@pytest.mark.asyncio
async def test_menu_dial_9_collects_until_hash():
    dial_calls = []
    on_dial = AsyncMock(side_effect=lambda n: dial_calls.append(n))
    ctrl, _, _, _, _ = _make_controller(on_dial_request=on_dial, dial_delay_sec=0.01)
    digits = ["#", "9", "1", "2", "3", "4", "9", "5", "6", "7", "8", "9", "#"]
    await _feed(ctrl, digits)
    # Let dial_delay elapse
    await asyncio.sleep(0.05)
    assert ctrl._state == "PENDING_DIAL"
    on_dial.assert_awaited_once_with("56789")
    assert dial_calls == ["56789"]


@pytest.mark.asyncio
async def test_menu_dial_confirm_prompt_contains_number():
    on_dial = AsyncMock()
    ctrl, _, _, tts, _ = _make_controller(on_dial_request=on_dial, dial_delay_sec=0.01)
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4", "9", "5", "7", "8", "2", "#"])
    await asyncio.sleep(0.05)
    spoken = [c.args[0] for c in tts.speak.call_args_list if c.args]
    assert any("Okay, I will call to 5782 after hung-up" in t for t in spoken)


@pytest.mark.asyncio
async def test_menu_dial_star_cancels_back_to_menu():
    on_dial = AsyncMock()
    ctrl, _, _, _, _ = _make_controller(on_dial_request=on_dial)
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4", "9", "5", "6", "*"])
    assert ctrl._state == "ADMIN_MENU"
    on_dial.assert_not_awaited()


@pytest.mark.asyncio
async def test_menu_dial_hash_with_no_digits_re_prompts():
    on_dial = AsyncMock()
    ctrl, _, _, tts, _ = _make_controller(on_dial_request=on_dial)
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4", "9", "#"])
    # No digits collected -> re-prompt with "enter_num"
    spoken = [c.args[0] for c in tts.speak.call_args_list if c.args]
    assert sum("Enter the number" in t for t in spoken) >= 2
    on_dial.assert_not_awaited()
    assert ctrl._state == "COLLECT_NUMBER"


# ---------- timeouts ----------


@pytest.mark.asyncio
async def test_admin_menu_timeout_returns_to_idle():
    ctrl, _, _, tts, stt = _make_controller(menu_timeout_sec=0.05)
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4"])  # enter ADMIN_MENU
    assert ctrl._state == "ADMIN_MENU"
    await asyncio.sleep(0.15)  # watchdog fires
    assert ctrl._state == "IDLE"
    stt.resume.assert_called()
    spoken = [c.args[0] for c in tts.speak.call_args_list if c.args]
    assert any("Menu timeout" in t for t in spoken)


@pytest.mark.asyncio
async def test_collect_number_timeout_returns_to_menu():
    ctrl, _, _, tts, _ = _make_controller(
        collect_timeout_sec=0.05, menu_timeout_sec=5.0
    )
    await _feed(ctrl, ["#", "9", "1", "2", "3", "4", "9", "5"])  # in COLLECT_NUMBER
    assert ctrl._state == "COLLECT_NUMBER"
    await asyncio.sleep(0.15)
    assert ctrl._state == "ADMIN_MENU"


# ---------- reset ----------


def test_reset_clears_state_and_resumes_stt():
    ctrl, _, _, _, stt = _make_controller()
    ctrl._state = "ADMIN_MENU"
    ctrl._buf = ["1", "2"]
    ctrl._prefix_idx = 2
    ctrl.reset()
    assert ctrl._state == "IDLE"
    assert ctrl._buf == []
    assert ctrl._prefix_idx == 0
    stt.resume.assert_called()


# ---------- prompts dictionary defaults ----------


def test_default_prompts_have_required_keys():
    for k in ("menu", "enter_num", "confirm", "bad_pin", "exit", "timeout"):
        assert k in DEFAULT_PROMPTS
    assert "{number}" in DEFAULT_PROMPTS["confirm"]
