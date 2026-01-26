#!/usr/bin/env python3
import sys
import time
sys.path.insert(0, '/home/user/Test_Phone_new')

from pyVoIP import VoIP, SIP, RTP
import wave
import numpy as np
import audioop
from threading import Timer

PBX_CONFIG = {
    'domain': '192.168.1.176',
    'port': 5060,
    'user': '555533',
    'password': 'Test1234',
}

AUDIO_FILE = '/home/user/Test_Phone_new/output_phone.wav'


def log(msg: str):
    """Логирование."""
    timestamp = time.strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}")


def load_audio_file(filepath: str, target_sample_rate: int = 8000) -> bytes:
    """Загрузка аудио файла (возвращает 8-bit unsigned PCM)."""
    if filepath:
        try:
            with wave.open(filepath, 'rb') as wf:
                original_sr = wf.getframerate()
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                n_frames = wf.getnframes()
                audio_data = wf.readframes(n_frames)

            log(f"Аудио: {original_sr}Hz, {channels} ch, {sampwidth} B, {n_frames} frames")

            if sampwidth == 2:
                pcm16 = audio_data
            else:
                log(f"Неподдерживаемый формат: {sampwidth} байт")
                return b''

            if channels == 2:
                samples = np.frombuffer(pcm16, dtype=np.int16)
                pcm16 = samples[::2].tobytes()

            if original_sr != target_sample_rate:
                import torchaudio
                import torch
                audio_tensor = torch.tensor(np.frombuffer(pcm16, dtype=np.int16), dtype=torch.float32)
                audio_resampled = torchaudio.functional.resample(
                    audio_tensor, original_sr, target_sample_rate
                )
                pcm16 = (audio_resampled / 32767 * 32767).clamp(-32768, 32767).short().numpy().tobytes()

            log(f"PCM16 размер: {len(pcm16)} байт")

            # Convert 16-bit PCM → 8-bit unsigned PCM (pyVoIP format)
            # pyVoIP ожидает: 8-bit unsigned (0-255), bias +128 (80 = silence)
            bias_pcm = audioop.bias(pcm16, 2, -32768)
            pcm8 = audioop.lin2lin(bias_pcm, 2, 1)
            pcm8_unsigned = audioop.bias(pcm8, 1, 128)

            log(f"PCM8 unsigned размер: {len(pcm8_unsigned)} байт")
            return pcm8_unsigned

        except Exception as e:
            log(f"Ошибка загрузки: {e}")
            import traceback
            traceback.print_exc()
            return b''

    return b''


def call_callback(call):
    """Обработчик входящего звонка."""
    log("Входящий звонок!")


def main():
    log("=" * 60)
    log("  ТЕСТ: pyVoIP Звонок с аудио")
    log("=" * 60)
    log(f"  PBX: {PBX_CONFIG['domain']}:{PBX_CONFIG['port']}")
    log(f"  Номер: {PBX_CONFIG['user']}")
    log(f"  Звонок на: 1001")
    log(f"  Аудио: {AUDIO_FILE}")
    log("=" * 60)

    log("Создание телефона...")
    phone = VoIP.VoIPPhone(
        server=PBX_CONFIG['domain'],
        port=PBX_CONFIG['port'],
        username=PBX_CONFIG['user'],
        password=PBX_CONFIG['password'],
        myIP='192.168.1.181',
        sipPort=5063,
        rtpPortLow=10000,
        rtpPortHigh=20000,
        callCallback=call_callback
    )

    try:
        log("Запуск телефона...")
        phone.start()

        # Ожидание регистрации
        log("Ожидание регистрации...")
        for _ in range(100):
            if phone.get_status() == VoIP.PhoneStatus.REGISTERED:
                log("Зарегистрирован!")
                break
            time.sleep(0.1)
        else:
            log("Ошибка регистрации")
            return 1

        log("Загрузка аудио файла...")
        audio_data = load_audio_file(AUDIO_FILE)
        if not audio_data:
            log("Не удалось загрузить аудио")
            return 1

        log("Звонок на 1001...")
        call = phone.call("1001")

        log("Ожидание ответа...")
        call_start_time = time.time()
        max_call_duration = 30
        audio_played = False

        while time.time() - call_start_time < max_call_duration:
            if call.state == VoIP.CallState.ANSWERED:
                log("Звонок соединён!")

                # Воспроизведение аудио
                if not audio_played:
                    log("=" * 60)
                    log("ВОСПРОИЗВЕДЕНИЕ АУДИО")
                    log("=" * 60)

                    frame_size = 160  # 20ms at 8kHz
                    frames_sent = 0

                    for i in range(0, len(audio_data), frame_size):
                        frame = audio_data[i:i + frame_size]
                        if len(frame) < frame_size:
                            frame = frame + b'\x80' * (frame_size - len(frame))

                        # pyVoIP ожидает 8-bit unsigned PCM (0-255)
                        call.write_audio(frame)
                        frames_sent += 1

                        if frames_sent % 50 == 0:
                            log(f"Отправлено {frames_sent} фреймов ({frames_sent / 50:.1f} сек)")

                        time.sleep(0.020)  # 20ms

                    duration = frames_sent / 50.0
                    log(f"Воспроизведено {frames_sent} фреймов ({duration:.1f} сек)", flush=True)
                    log("=" * 60)

                    audio_played = True

                if audio_played:
                    log("Аудио воспроизведено. Завершение...")
                    time.sleep(1)
                    break

            elif call.state == VoIP.CallState.ENDED:
                log("Звонок завершён")
                break

            time.sleep(0.1)

        if call.state == VoIP.CallState.ANSWERED and not audio_played:
            log("Звонок не был принят или нет аудио")

        log("Завершение звонка...")
        call.hangup()

        log("Остановка телефона...")
        phone.stop()

        log("ТЕСТ ЗАВЕРШЁН!")
        return 0

    except Exception as e:
        log(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
