#!/usr/bin/env python3
"""
example_call_with_audio_and_tts.py - Тест звонка с аудио и TTS

Функции:
- Регистрация на Asterisk PBX
- Звонок на номер 1001
- Воспроизведение аудио файла output_phone.wav
- Синтез и воспроизведение TTS текста

Настройки TTS (читаются из переменных окружения или файла):
    TTS_ENGINE: turbo (по умолчанию), multilingual, standard
    TTS_DEVICE: cuda (по умолчанию), cpu
    TTS_LANGUAGE_ID: en для английского, ru для русского
    TTS_AUDIO_PROMPT_PATH: путь к аудио-примеру голоса
    TTS_RVC_ENABLED: True/False
    TTS_RVC_MODEL_PATH: путь к модели RVC
"""

import sys
import asyncio
import time
import os
import wave
import numpy as np
import torch
from datetime import datetime

sys.path.insert(0, '/home/user/Test_Phone_new')
sys.path.insert(0, '/home/user/Test_Phone_new/AI')
sys.path.insert(0, '/home/user/Test_Phone_new/pjsip_python')

from pjsip_python import Ua, UaConfig, CallState, RegState
from pjsip_python.pjsua.acc import AccountConfig
from pjsip_python.pjmedia.codec import G711Codec
from pjsip_python.audio import create_silence, write_wav, read_wav, AudioFormat
from AI.tts_adapter_simple import SimpleTTSAdapter

import logging


PBX_CONFIG = {
    'domain': '192.168.1.176',
    'port': 5060,
    'user': '555533',
    'password': 'Test1234',
    'target': '1001',
}

AUDIO_FILE = 'output_phone.wav'
TTS_TEXT = "If you can hear this without stuttering, the library works perfectly."


def log(msg: str, level: str = 'INFO'):
    """Логирование."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    symbols = {'INFO': '[+]', 'ERROR': '[!]', 'SUCCESS': '[✓]', 'WARN': '[-]'}
    print(f"{symbols.get(level, '[?]')} [{timestamp}] {msg}")


def load_audio_file(filepath: str, target_sample_rate: int = 8000) -> bytes:
    """Загрузка аудио файла и конвертация в PCM 8kHz."""
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

        log(f"Аудио файл: {original_sr}Hz, {channels} каналов, {sampwidth} байт/сэмпл")

        import struct
        if sampwidth == 2:
            samples = struct.unpack(f'{n_frames * channels}h', audio_data)
            if channels == 2:
                samples = samples[::2]
            audio_np = np.array(samples, dtype=np.float32) / 32767.0
        else:
            audio_np = np.frombuffer(audio_data, dtype=np.uint8).astype(np.float32) / 255.0

        if original_sr != target_sample_rate:
            import torchaudio
            audio_tensor = torch.tensor(audio_np).unsqueeze(0)
            audio_resampled = torchaudio.functional.resample(audio_tensor, original_sr, target_sample_rate)
            audio_np = audio_resampled.squeeze().numpy()

        int16 = (audio_np * 32767.0).astype(np.int16)
        return int16.tobytes()

    except Exception as e:
        log(f"Ошибка загрузки аудио: {e}", 'ERROR')
        return b''


async def test_call_with_audio_and_tts(audio_file: str = 'output_phone.wav',
                                        tts_text: str = "If you can hear this without stuttering, the library works perfectly.",
                                        target: str = "1001"):
    """Тест звонка с воспроизведением аудио и TTS."""
    log("=" * 60)
    log("  ТЕСТ: Звонок с аудио + TTS")
    log("=" * 60)
    log(f"  PBX: {PBX_CONFIG['domain']}:{PBX_CONFIG['port']}")
    log(f"  Номер: {PBX_CONFIG['user']}")
    log(f"  Звонок на: {target}")
    log(f"  Аудио файл: {audio_file}")
    log(f"  TTS текст: {tts_text[:50]}...")
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

    log("Зарегистрирован успешно!", 'SUCCESS')

    target_uri = f"sip:{target}@{PBX_CONFIG['domain']}:{PBX_CONFIG['port']}"

    log(f"Звонок на {target_uri}...")
    call = await ua.call(target_uri)

    if call is None:
        log("Ошибка создания звонка", 'ERROR')
        await account.unregister()
        await ua.destroy()
        return False

    log(f"Звонок создан: {call.state.name}")

    codec = G711Codec(a_law=True)
    log("Codec создан", 'SUCCESS')

    log("Ожидание ответа абонента...")

    call_connected = False
    audio_played = False
    tts_played = False
    call_start_time = time.time()
    max_call_duration = 30

    while time.time() - call_start_time < max_call_duration:
        if call.state == CallState.CONFIRMED:
            if not call_connected:
                call_connected = True
                log("Звонок соединён!", 'SUCCESS')

            elapsed = time.time() - call_start_time

            if call_connected and elapsed > 1.0 and not audio_played:
                log("Воспроизведение аудио файла...")
                audio_data = load_audio_file(audio_file)

                if audio_data:
                    # Convert 16-bit PCM to 8-bit PCM for G.711 encoding (pyVoIP compatible)
                    import audioop
                    bias_16bit = audioop.bias(audio_data, 2, -32768)
                    pcm_8bit = audioop.lin2lin(bias_16bit, 2, 1)
                    pcma_data = codec.encode(pcm_8bit)
                    frame_size = 160

                    for i in range(0, len(pcma_data), frame_size):
                        frame = pcma_data[i:i + frame_size]
                        if len(frame) < frame_size:
                            frame = frame + b'\x00' * (frame_size - len(frame))
                        if call._media_stream:
                            call._media_stream.send_g711(frame)
                        await asyncio.sleep(0.02)

                    log(f"Аудио файл воспроизведён: {len(pcm_data)} байт", 'SUCCESS')
                else:
                    log("Не удалось загрузить аудио файл", 'WARN')

                audio_played = True

            if call_connected and elapsed > 5.0 and not tts_played and audio_played:
                log("Синтез TTS и воспроизведение...")

                tts_config = {
                    'tts': {
                        'engine': os.environ.get('TTS_ENGINE', 'turbo'),
                        'device': os.environ.get('TTS_DEVICE', 'cuda'),
                        'language_id': os.environ.get('TTS_LANGUAGE_ID', 'en'),
                        'audio_prompt_path': os.environ.get('TTS_AUDIO_PROMPT_PATH'),
                        'rvc_enabled': os.environ.get('TTS_RVC_ENABLED', 'False').lower() == 'true',
                        'rvc_model_path': os.environ.get('TTS_RVC_MODEL_PATH'),
                    }
                }

                logging.basicConfig(level=logging.INFO)
                logger = logging.getLogger('TTS')

                tts_adapter = SimpleTTSAdapter(tts_config, logger)

                pcm_data = await tts_adapter.synthesize(tts_text)

                if pcm_data:
                    # Convert 16-bit PCM to 8-bit PCM for G.711 encoding (pyVoIP compatible)
                    import audioop
                    bias_16bit = audioop.bias(pcm_data, 2, -32768)
                    pcm_8bit = audioop.lin2lin(bias_16bit, 2, 1)
                    pcma_data = codec.encode(pcm_8bit)
                    frame_size = 160

                    for i in range(0, len(pcma_data), frame_size):
                        frame = pcma_data[i:i + frame_size]
                        if len(frame) < frame_size:
                            frame = frame + b'\x00' * (frame_size - len(frame))
                        if call._media_stream:
                            call._media_stream.send_g711(frame)
                        await asyncio.sleep(0.02)

                    log(f"TTS воспроизведён: {len(pcm_data)} байт", 'SUCCESS')
                else:
                    log("Ошибка синтеза TTS", 'ERROR')

                tts_played = True

            if audio_played and tts_played:
                log("Аудио и TTS воспроизведены. Завершение звонка...", 'INFO')
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
    global_config = {
        'audio': 'output_phone.wav',
        'text': "If you can hear this without stuttering, the library works perfectly.",
        'target': '1001',
    }

    parser = argparse.ArgumentParser(
        description='Тест звонка с аудио и TTS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    %(prog)s                           Запуск теста по умолчанию
    TTS_ENGINE=turbo %(prog)s         Использовать turbo движок TTS
    TTS_LANGUAGE_ID=en %(prog)s       Английский язык TTS
        """
    )
    parser.add_argument('--audio', default=global_config['audio'],
                        help='Аудио файл для воспроизведения (по умолчанию: output_phone.wav)')
    parser.add_argument('--text', default=global_config['text'],
                        help='TTS текст для синтеза')
    parser.add_argument('--target', default=global_config['target'],
                        help='Номер для звонка (по умолчанию: 1001)')

    args = parser.parse_args()

    audio_file = args.audio
    tts_text = args.text
    target = str(args.target)

    result = asyncio.run(test_call_with_audio_and_tts(audio_file, tts_text, target))

    print()
    print("=" * 60)
    if result:
        print("  ТЕСТ ПРОЙДЕН ✓")
    else:
        print("  ТЕСТ НЕ ПРОЙДЕН ✗")
    print("=" * 60)

    return 0 if result else 1


if __name__ == '__main__':
    import argparse
    sys.exit(main())
