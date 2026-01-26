#!/usr/bin/env python3
"""
example_play_audio_file.py - Simple audio file playback in call

Tests audio file playback without TTS.
"""

import sys
import asyncio
import time
import os
import wave
import numpy as np
import audioop
from datetime import datetime

sys.path.insert(0, '/home/user/Test_Phone_new')
sys.path.insert(0, '/home/user/Test_Phone_new/AI')
sys.path.insert(0, '/home/user/Test_Phone_new/pjsip_python')

from pjsip_python import Ua, UaConfig, CallState, RegState
from pjsip_python.pjsua.acc import AccountConfig
from pjsip_python.pjmedia.codec import G711Codec

import logging

PBX_CONFIG = {
    'domain': '192.168.1.176',
    'port': 5060,
    'user': '555533',
    'password': 'Test1234',
    'target': '1001',
}

AUDIO_FILE = 'output_phone.wav'


def log(msg: str, level: str = 'INFO'):
    """Логирование."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    symbols = {'INFO': '[+]', 'ERROR': '[!]', 'SUCCESS': '[✓]', 'WARN': '[-]'}
    print(f"{symbols.get(level, '[?]')} [{timestamp}] {msg}")


def load_audio_file(filepath: str, target_sample_rate: int = 8000) -> bytes:
    """Загрузка аудио файла (возвращает 16-bit PCM)."""
    if not os.path.exists(filepath):
        log(f"Аудио файл не найден: {filepath}", 'ERROR')
        return b''

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
            log(f"Неподдерживаемый формат: {sampwidth} байт", 'ERROR')
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

        log(f"PCM16 размер: {len(pcm16)} байт", 'SUCCESS')
        return pcm16

    except Exception as e:
        log(f"Ошибка загрузки: {e}", 'ERROR')
        import traceback
        traceback.print_exc()
        return b''


def convert_pcm16_to_g711(pcm16_data: bytes, a_law: bool = True) -> bytes:
    """Конвертируем 16-bit PCM → 8-bit PCM → G.711 (как в pyVoIP)."""
    bias_16 = audioop.bias(pcm16_data, 2, -32768)
    pcm8 = audioop.lin2lin(bias_16, 2, 1)
    bias_8 = audioop.bias(pcm8, 1, -128)
    
    if a_law:
        return audioop.lin2alaw(bias_8, 1)
    return audioop.lin2ulaw(bias_8, 1)


async def test_audio_playback(audio_file: str = 'output_phone.wav', target: str = "1001"):
    """Тест воспроизведения аудио файла."""
    log("=" * 60)
    log("  ТЕСТ: Воспроизведение аудио файла")
    log("=" * 60)
    log(f"  PBX: {PBX_CONFIG['domain']}:{PBX_CONFIG['port']}")
    log(f"  Номер: {PBX_CONFIG['user']}")
    log(f"  Звонок на: {target}")
    log(f"  Аудио: {audio_file}")
    log("=" * 60)

    log("Создание User Agent...")
    config = UaConfig()
    config.user_agent = 'pjsip_python/1.0'
    config.local_ip = '192.168.1.181'
    config.local_port = 5062

    ua = await Ua.create(config)
    if ua is None:
        log("Ошибка создания UA", 'ERROR')
        return False
    log(f"UA создан на {ua.local_ip}:{ua.local_port}")

    server_uri = f"sip:{PBX_CONFIG['domain']}:{PBX_CONFIG['port']}"

    acc_config = AccountConfig(
        id=f"sip:{PBX_CONFIG['user']}@{PBX_CONFIG['domain']}",
        reg_uri=server_uri,
        username=PBX_CONFIG['user'],
        password=PBX_CONFIG['password'],
        realm=PBX_CONFIG['domain'],
        contact=f"sip:{PBX_CONFIG['user']}@{ua.local_ip}:{ua.local_port}"
    )

    log("Регистрация...")
    account = await ua.create_account({
        'id': acc_config.id,
        'reg_uri': acc_config.reg_uri,
        'username': acc_config.username,
        'password': acc_config.password,
        'realm': acc_config.realm,
        'contact': acc_config.contact
    })

    await account.register()

    registered = False
    start_time = time.time()
    while time.time() - start_time < 15.0:
        if account.reg_state == RegState.REGISTERED:
            registered = True
            break
        await asyncio.sleep(0.1)

    if not registered:
        log(f"Не удалось зарегистрироваться: {account.reg_state.name}", 'ERROR')
        await ua.destroy()
        return False
    log("Зарегистрирован!", 'SUCCESS')

    target_uri = f"sip:{target}@{PBX_CONFIG['domain']}:{PBX_CONFIG['port']}"
    log(f"Звонок на {target_uri}...")
    call = await ua.call(target_uri)

    if call is None:
        log("Ошибка создания звонка", 'ERROR')
        await account.unregister()
        await ua.destroy()
        return False
    log(f"Звонок создан: {call.state.name}")

    call_connected = False
    audio_played = False
    call_start_time = time.time()
    max_call_duration = 30

    while time.time() - call_start_time < max_call_duration:
        if call.state == CallState.CONFIRMED:
            if not call_connected:
                call_connected = True
                log("Звонок соединён!", 'SUCCESS')
                log(f"MediaStream exists: {call._media_stream is not None}")
                if call._media_stream:
                    log(f"MediaStream running: {call._media_stream._running}")
                    log(f"MediaStream local: {call._media_stream.local_addr}")
                    log(f"MediaStream remote: {call._media_stream.remote_addr}")
                    if call._media_stream._rtp_client:
                        log(f"RTP client local: {call._media_stream._rtp_client.local_addr}")
                        log(f"RTP client remote: {call._media_stream._rtp_client.remote_ip}:{call._media_stream._rtp_client.remote_port}")
                        log(f"RTP client running: {call._media_stream._rtp_client._running}")

        elapsed = time.time() - call_start_time

        if call_connected and elapsed > 1.0 and not audio_played:
                log("Загрузка аудио файла...")
                pcm16_data = load_audio_file(audio_file)

                if pcm16_data:
                    log(f"PCM16: {len(pcm16_data)} байт")
                    
                    log("Конвертация в G.711...")
                    g711_data = convert_pcm16_to_g711(pcm16_data, a_law=True)
                    log(f"G.711: {len(g711_data)} байт", 'SUCCESS')

                    log("Воспроизведение...")
                    frame_size = 160
                    
                    frames_sent = 0
                    for i in range(0, len(g711_data), frame_size):
                        frame = g711_data[i:i + frame_size]
                        if len(frame) < frame_size:
                            frame = frame + b'\x00' * (frame_size - len(frame))
                        
                        if call._media_stream:
                            call._media_stream.send_g711(frame)
                            frames_sent += 1
                        
                        await asyncio.sleep(0.02)
                    
                    duration = frames_sent / 50.0
                    log(f"Воспроизведено {frames_sent} фреймов ({duration:.1f} сек)", 'SUCCESS')
                else:
                    log("Не удалось загрузить аудио", 'ERROR')

                audio_played = True

        if audio_played:
            log("Аудио воспроизведено. Завершение...", 'INFO')
            await asyncio.sleep(1)
            break

        elif call.state == CallState.DISCONNECTED:
            log(f"Звонок завершён: {call.state.name}")
            break

        await asyncio.sleep(0.1)

    if not call_connected:
        log("Звонок не был соединён", 'WARN')

    log("Завершение звонка...")
    await call.hangup()

    log("Отмена регистрации...")
    await account.unregister()

    await ua.destroy()
    log("UA остановлен", 'SUCCESS')

    return True


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Тест воспроизведения аудио файла')
    parser.add_argument('--audio', default='output_phone.wav', help='Аудио файл')
    parser.add_argument('--target', default='1001', help='Номер для звонка')
    
    args = parser.parse_args()
    
    result = asyncio.run(test_audio_playback(args.audio, args.target))

    print()
    print("=" * 60)
    if result:
        print("  ТЕСТ ПРОЙДЕН ✓")
    else:
        print("  ТЕСТ НЕ ПРОЙДЕН ✗")
    print("=" * 60)

    return 0 if result else 1


if __name__ == '__main__':
    sys.exit(main())
