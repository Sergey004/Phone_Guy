"""DTMF admin-menu controller for remote bot management.

State machine:
    IDLE
      | '#' -> EXPECT_9
    EXPECT_9
      | '9' -> COLLECT_PIN (asks 4-digit PIN over DTMF)
      | иное / timeout -> IDLE (resume STT)
    COLLECT_PIN
      | 4 верных цифры -> ADMIN_MENU
      | неверный PIN / timeout -> IDLE (resume, say BAD_PIN)
    ADMIN_MENU
      | '9' -> COLLECT_NUMBER
      | '0' -> bye()+IDLE
      | '#' -> IDLE (resume, say EXIT)
      | '*' -> repeat menu prompt
      | timeout -> IDLE (resume, say TIMEOUT)
    COLLECT_NUMBER
      | digit -> append
      | '#' -> PENDING_DIAL (say CONFIRM with number) -> после задержки on_dial_request(number)
      | '*' -> ADMIN_MENU (cancel)
      | timeout -> ADMIN_MENU

Во время IDLE -> '.. -> ADMIN_MENU' STT стоит на паузе (звонящий может
говорить, но Whisper его игнорирует), а bridge buffer очищается — бот молчит.
При откате в IDLE STT.resume() вызывается всегда.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# Английские TTS-промпты (TTS адаптер умеет только en).
DEFAULT_PROMPTS: dict[str, str] = {
    "menu": "Admin menu. Press 9 to dial a number, 0 to hang up, hash to exit.",
    "enter_num": "Enter the number, then press hash.",
    "confirm": "Okay, I will call to {number} after hung-up.",
    "bad_pin": "Incorrect PIN. Exiting.",
    "exit": "Exiting admin menu.",
    "timeout": "Menu timeout.",
}


class DtmfAdminController:
    """Удалённое управление ботом через DTMF (RFC 4733).

    Привязывается к SIPClient.dtmf_received_callback. Никакой SIP-логики тут
    нет — hangup/новый звонок делегируются через `on_dial_request(number)`,
    который реализуется в main_integration.
    """

    def __init__(
        self,
        sip_client,
        *,
        bridge,
        tts,
        stt,
        admin_pin: str = "1234",
        enter_prefix: str = "#9",
        dial_delay_sec: float = 2.5,
        menu_timeout_sec: float = 5.0,
        collect_timeout_sec: float = 8.0,
        prompts: Optional[dict[str, str]] = None,
        on_dial_request: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.sip = sip_client
        self.bridge = bridge
        self.tts = tts
        self.stt = stt
        self.admin_pin = admin_pin
        self.enter_prefix = (
            enter_prefix  # ожидаемая последовательность входа, напр. "#9"
        )
        self.dial_delay_sec = dial_delay_sec
        self.menu_timeout_sec = menu_timeout_sec
        self.collect_timeout_sec = collect_timeout_sec
        self.prompts = {**DEFAULT_PROMPTS, **(prompts or {})}
        self.on_dial_request = on_dial_request

        # State machine
        self._state = "IDLE"
        self._buf: list[str] = []  # буфер ввода (PIN или number)
        self._prefix_idx = 0  # сколько символов enter_prefix уже введено
        self._last_digit_at = 0.0
        self._watchdog_task: Optional[asyncio.Task] = None

    # ----- public -----

    async def handle_digit(self, digit: str) -> None:
        """Главный колбэк; привязывается к sip_client.dtmf_received_callback."""
        logger.debug("DTMF digit %r in state %s", digit, self._state)
        self._last_digit_at = time.time()
        self._kick_watchdog()

        await self._dispatch(digit)

    def reset(self) -> None:
        """Принудительный сброс в IDLE — вызывается orchestrator'ом после bye()."""
        self._state = "IDLE"
        self._buf = []
        self._prefix_idx = 0
        self._cancel_watchdog()
        try:
            self.stt.resume()
        except Exception:
            pass

    # ----- state dispatch -----

    async def _dispatch(self, digit: str) -> None:
        s = self._state
        if s == "IDLE":
            await self._on_idle(digit)
        elif s == "EXPECT_9":
            await self._on_expect_9(digit)
        elif s == "COLLECT_PIN":
            await self._on_collect_pin(digit)
        elif s == "ADMIN_MENU":
            await self._on_admin_menu(digit)
        elif s == "COLLECT_NUMBER":
            await self._on_collect_number(digit)
        else:
            logger.warning("Unknown DTMF state %r; reset", s)
            self.reset()

    # ----- IDLE: ловим начало секретной последовательности -----

    async def _on_idle(self, digit: str) -> None:
        if not self.enter_prefix:
            return
        expected = self.enter_prefix[self._prefix_idx]
        if digit == expected:
            self._prefix_idx += 1
            if self._prefix_idx == 1:
                # Первый символ секрета — замолчать бота, поставить STT на паузу
                self._mute_bot()
            if self._prefix_idx >= len(self.enter_prefix):
                # Вся секретная последовательность введена -> переход к PIN
                self._state = "COLLECT_PIN"
                self._buf = []
                logger.info(
                    "DTMF admin: secret prefix %s entered, collecting PIN",
                    self.enter_prefix,
                )
        else:
            # Несходство: откат. STT.resume возвращаем только если мы уже начали mute.
            if self._prefix_idx > 0:
                self._unmute_bot()
            self._prefix_idx = 0

    # ----- EXPECT_9 (legacy-режим, если enter_prefix — полный секрет без PIN) -----
    # В текущей схеме enter_prefix="#9" покрывает и '#', и '9'.
    # Если enter_prefix длины 1 (только "#" или "*"), то "9" ловится здесь.
    async def _on_expect_9(self, digit: str) -> None:
        if digit == "9":
            self._state = "COLLECT_PIN"
            self._buf = []
            logger.info("DTMF admin: going to COLLECT_PIN")
        else:
            await self._abort_to_idle(say_bad_pin=False)

    # ----- COLLECT_PIN: ждём 4 цифры -----

    async def _on_collect_pin(self, digit: str) -> None:
        if not digit.isdigit():
            await self._abort_to_idle(say_bad_pin=True)
            return
        self._buf.append(digit)
        if len(self._buf) >= len(self.admin_pin):
            entered = "".join(self._buf)
            if entered == self.admin_pin:
                self._state = "ADMIN_MENU"
                self._buf = []
                logger.info("DTMF admin: PIN OK -> ADMIN_MENU")
                await self._say("menu")
            else:
                await self._abort_to_idle(say_bad_pin=True)

    # ----- ADMIN_MENU -----

    async def _on_admin_menu(self, digit: str) -> None:
        if digit == "9":
            self._state = "COLLECT_NUMBER"
            self._buf = []
            await self._say("enter_num")
            logger.info("DTMF admin: COLLECT_NUMBER started")
        elif digit == "0":
            logger.info("DTMF admin: hangup requested")
            await self._say("exit")
            try:
                await self.sip.bye()
            except Exception as e:
                logger.error("bye() failed: %s", e)
            self.reset()
        elif digit == "#":
            await self._abort_to_idle(say_bad_pin=False, prompt="exit")
        elif digit == "*":
            await self._say("menu")
        else:
            # неизвестная кнопка — повтор меню
            await self._say("menu")

    # ----- COLLECT_NUMBER -----

    async def _on_collect_number(self, digit: str) -> None:
        if digit == "#":
            if not self._buf:
                await self._say("enter_num")
                return
            number = "".join(self._buf)
            self._state = "PENDING_DIAL"
            self._buf = []
            await self._confirm_and_dial(number)
        elif digit == "*":
            self._state = "ADMIN_MENU"
            self._buf = []
            await self._say("menu")
        elif digit.isdigit():
            self._buf.append(digit)
            logger.info("DTMF admin: number buf=%s", self._buf)
        else:
            # игнорируем * и # не в тех состояниях
            pass

    async def _confirm_and_dial(self, number: str) -> None:
        """Произносит CONFIRM prompt, ждёт dial_delay_sec, дёргает on_dial_request."""
        try:
            await self._say_prompt("confirm", number=number)
        except Exception as e:
            logger.error("TTS confirm failed: %s", e)
        logger.info(
            "DTMF admin: dial-out requested to %s (delay %.2fs)",
            number,
            self.dial_delay_sec,
        )
        try:
            await asyncio.sleep(self.dial_delay_sec)
        except asyncio.CancelledError:
            pass
        if self.on_dial_request is not None:
            try:
                await self.on_dial_request(number)
            except Exception as e:
                logger.error("on_dial_request failed: %s", e)
        # Orchestrator сделает bye()+invite(); мы остаёмся в PENDING_DIAL —
        # reset() дёрнется из main_integration после старта нового звонка.

    # ----- helpers -----

    def _mute_bot(self) -> None:
        """Сбросить TTS buffer и поставить STT на паузу."""
        try:
            self.bridge.buffer.clear()
        except Exception:
            pass
        try:
            self.stt.pause()
        except Exception:
            pass

    def _unmute_bot(self) -> None:
        try:
            self.stt.resume()
        except Exception:
            pass

    async def _abort_to_idle(
        self, *, say_bad_pin: bool, prompt: Optional[str] = None
    ) -> None:
        self._state = "IDLE"
        self._buf = []
        self._prefix_idx = 0
        self._cancel_watchdog()
        self._unmute_bot()
        if say_bad_pin:
            await self._say("bad_pin")
        elif prompt is not None:
            await self._say(prompt)

    async def _say(self, key: str) -> None:
        await self._say_prompt(key)

    async def _say_prompt(self, key: str, **fmt) -> None:
        text = self.prompts.get(key, "")
        if fmt:
            try:
                text = text.format(**fmt)
            except Exception as e:
                logger.error("prompt format failed for %r: %s", key, e)
        if not text:
            return
        try:
            await self.tts.speak(text, media_port=self.bridge)
        except Exception as e:
            logger.error("TTS.speak failed (%r): %s", key, e)

    # ----- watchdog: сброс state при отсутствии DTMF -----

    def _kick_watchdog(self) -> None:
        self._cancel_watchdog()
        if self._state in ("IDLE", "PENDING_DIAL"):
            return
        timeout = (
            self.collect_timeout_sec
            if self._state in ("COLLECT_NUMBER", "COLLECT_PIN")
            else self.menu_timeout_sec
        )
        self._watchdog_task = asyncio.create_task(self._watchdog(timeout))

    def _cancel_watchdog(self) -> None:
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
        self._watchdog_task = None

    async def _watchdog(self, timeout: float) -> None:
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        # Сработал таймаут
        logger.warning("DTMF admin: watchdog fired in state %s", self._state)
        if self._state == "COLLECT_NUMBER":
            # Возврат в меню, а не в IDLE — пользователь ещё в меню
            self._state = "ADMIN_MENU"
            self._buf = []
            await self._say("timeout")
            await self._say("menu")
            self._kick_watchdog()
        elif self._state == "ADMIN_MENU":
            # В админ-меню просто продлеваем таймаут, не сбрасываем в IDLE
            # (пользователь всё ещё в меню, просто молчал)
            await self._say("timeout")
            self._kick_watchdog()
        else:
            # COLLECT_PIN / EXPECT_9 -> откат в IDLE
            await self._abort_to_idle(say_bad_pin=False, prompt="timeout")
