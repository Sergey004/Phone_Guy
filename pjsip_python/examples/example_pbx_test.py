#!/usr/bin/env python3
"""
example_pbx_test.py - Тестирование SIP/RTP с Asterisk PBX

Подключение к удалённому серверу Asterisk:
    SIP_DOMAIN: 192.168.1.176
    SIP_PORT:   5060
    SIP_USER:   555533
    SIP_PASS:   Test1234
    TARGET:     1001

Usage:
    python3 example_pbx_test.py --register-test
    python3 example_pbx_test.py --call-test --duration 5
    python3 example_pbx_test.py --full-test
"""

import sys
import asyncio
import argparse
import time
from datetime import datetime

sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python import Ua, UaConfig, CallState
from pjsip_python.pjsua.acc import AccountConfig, RegState
from pjsip_python.pjmedia.rtp import RtpSession
from pjsip_python.audio import create_silence, create_tone, AudioData, AudioFormat
from pjsip_python.pjmedia.codec import G711Codec
import numpy as np


PBX_CONFIG = {
    'domain': '192.168.1.176',
    'port': 5060,
    'user': '555533',
    'password': 'Test1234',
    'target': '1001',
}


def log(msg: str, level: str = 'INFO'):
    """Логирование."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    symbols = {'INFO': '[+]', 'ERROR': '[!]', 'SUCCESS': '[✓]', 'WARN': '[-]'}
    print(f"{symbols.get(level, '[?]')} [{timestamp}] {msg}")


async def test_registration():
    """Тест SIP регистрации."""
    log("Создание User Agent...")
    
    config = UaConfig()
    config.user_agent = 'pjsip_python/1.0'
    config.local_ip = '0.0.0.0'  # Слушать на всех интерфейсах
    config.local_port = 5061
    
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
    
    log(f"Регистрация на {server_uri}...")
    log(f"User: {PBX_CONFIG['user']}")
    
    account = await ua.create_account({
        'id': acc_config.id,
        'reg_uri': acc_config.reg_uri,
        'username': acc_config.username,
        'password': acc_config.password,
        'realm': acc_config.realm,
        'contact': acc_config.contact
    })

    if account is None:
        log("Ошибка создания аккаунта", 'ERROR')
        await ua.destroy()
        return False

    log("Ожидание регистрации...", 'INFO')

    await account.register()
    start_time = time.time()
    registered = False
    
    while time.time() - start_time < 15.0:
        if account.reg_state == RegState.REGISTERED:
            registered = True
            log(f"Зарегистрирован! Expires: {account.info.reg_expires}s", 'SUCCESS')
            break
        elif account.reg_state == RegState.FAILED:
            log("Ошибка регистрации", 'ERROR')
            break
        await asyncio.sleep(0.1)
    
    if not registered:
        log(f"Состояние: {account.reg_state.name}", 'WARN')
    
    log("Отмена регистрации...")
    await account.unregister()
    
    await ua.destroy()
    log("UA остановлен")
    
    return registered


async def test_call(duration: float = 5.0):
    """Тест исходящего звонка."""
    log("Создание User Agent...")
    
    config = UaConfig()
    config.user_agent = 'pjsip_python/1.0'
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
    
    log(f"Регистрация...")
    account = await ua.create_account({
        'id': acc_config.id,
        'reg_uri': acc_config.reg_uri,
        'username': acc_config.username,
        'password': acc_config.password,
        'realm': acc_config.realm,
        'contact': acc_config.contact
    })
    
    registered = False
    start_time = time.time()
    while time.time() - start_time < 10.0:
        if account.reg_state == RegState.REGISTERED:
            registered = True
            break
        await asyncio.sleep(0.1)
    
    if not registered:
        log("Не удалось зарегистрироваться", 'ERROR')
        await ua.destroy()
        return False
    
    log(f"Зарегистрирован. Звонок на {PBX_CONFIG['target']}...")
    
    target_uri = f"sip:{PBX_CONFIG['target']}@{PBX_CONFIG['domain']}:{PBX_CONFIG['port']}"
    
    log(f"Создание звонка: {target_uri}")
    call = await ua.call(target_uri)
    
    if call is None:
        log("Ошибка создания звонка", 'ERROR')
        await account.unregister()
        await ua.destroy()
        return False
    
    log(f"Звонок создан, состояние: {call.state.name}")
    
    codec = G711Codec(a_law=True)
    rtp = None
    call_duration = 0
    
    try:
        rtp = RtpSession(ssrc=0x12345678, payload_type=8)
        rtp.set_clock_rate(8000)
        log("RTP сессия создана", 'SUCCESS')
    except Exception as e:
        log(f"Ошибка RTP: {e}", 'WARN')
    
    log(f"Разговор {duration} секунд...", 'INFO')
    
    while call_duration < duration:
        if call.state == CallState.CONFIRMED:
            call_duration += 0.1
            
            if rtp:
                silence = create_silence(0.02, 8000)
                pcm = silence.to_numpy()
                g711 = codec.encode(pcm.tobytes())
                rtp.encode_rtp(g711)
        elif call.state == CallState.DISCONNECTED:
            log(f"Звонок завершён: {call.state.name}", 'WARN')
            break
        
        await asyncio.sleep(0.1)
    
    log("Завершение звонка...")
    await call.hangup()
    
    log("Отмена регистрации...")
    await account.unregister()
    
    await ua.destroy()
    log("Тест звонка завершён", 'SUCCESS')
    
    return True


async def test_full():
    """Полный тест: регистрация + звонок."""
    print("=" * 60)
    print("  ПОЛНЫЙ ТЕСТ: Регистрация + Звонок")
    print("=" * 60)
    print()
    
    results = {'register': False, 'call': False}
    
    log("=== Этап 1: Регистрация ===")
    results['register'] = await test_registration()
    print()
    
    if results['register']:
        log("=== Этап 2: Исходящий звонок ===")
        results['call'] = await test_call(duration=5.0)
        print()
    else:
        log("Пропуск звонка - нет регистрации", 'WARN')
    
    return all(results.values())


def main():
    parser = argparse.ArgumentParser(
        description='Тестирование SIP/RTP с Asterisk PBX',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    %(prog)s --register-test    Тест регистрации
    %(prog)s --call-test        Звонок на 5 секунд
    %(prog)s --full-test        Полный тест
        """
    )

    parser.add_argument('--register-test', action='store_true',
                        help='Тест SIP регистрации')
    parser.add_argument('--call-test', action='store_true',
                        help='Тест исходящего звонка')
    parser.add_argument('--full-test', action='store_true',
                        help='Полный тест (регистрация + звонок)')
    parser.add_argument('--duration', type=float, default=5.0,
                        help='Длительность звонка в секундах (по умолчанию: 5)')

    args = parser.parse_args()

    print("=" * 60)
    print("  pjsip_python - Тест Asterisk PBX")
    print("=" * 60)
    print(f"  Сервер: {PBX_CONFIG['domain']}:{PBX_CONFIG['port']}")
    print(f"  Пользователь: {PBX_CONFIG['user']}")
    print(f"  Целевой номер: {PBX_CONFIG['target']}")
    print("=" * 60)
    print()

    if not any([args.register_test, args.call_test, args.full_test]):
        parser.print_help()
        print("\n" + "=" * 60)
        print("Запускаю полный тест...")
        print("=" * 60 + "\n")
        result = asyncio.run(test_full())
    elif args.register_test:
        print("\n[ТЕСТ] Регистрация на PBX\n")
        result = asyncio.run(test_registration())
    elif args.call_test:
        print(f"\n[ТЕСТ] Исходящий звонок ({args.duration} сек)\n")
        result = asyncio.run(test_call(args.duration))
    elif args.full_test:
        print("\n[ТЕСТ] Полный тест\n")
        result = asyncio.run(test_full())
    else:
        result = False

    print("\n" + "=" * 60)
    if result:
        print("  ТЕСТ ПРОЙДЕН ✓")
    else:
        print("  ТЕСТ НЕ ПРОЙДЕН ✗")
    print("=" * 60)

    return 0 if result else 1


if __name__ == '__main__':
    sys.exit(main())
