#!/usr/bin/env python3
"""
simple_register.py - Простой тест REGISTER с чистым socket

Этот скрипт использует чистый socket для отправки REGISTER запроса
и получения ответа от Asterisk.
"""

import socket
import sys
import time
from datetime import datetime

sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.pjsip.sip_msg import SipMessage, SipMethod
from pjsip_python.pjsip.sip_util import create_via_header, create_contact_header, generate_call_id, generate_branch, generate_tag


PBX_HOST = '192.168.1.176'
PBX_PORT = 5060
LOCAL_IP = '127.0.0.1'
LOCAL_PORT = 5063
USER = '555533'
REALM = 'asterisk'
PASSWORD = 'Test1234'


def log(msg: str):
    """Логирование."""
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")


def build_register_request() -> tuple:
    """Собрать REGISTER запрос."""
    call_id = generate_call_id()
    from_tag = generate_tag()
    branch = generate_branch()

    local_uri = f"sip:{USER}@{LOCAL_IP}"
    registrar_uri = f"sip:{PBX_HOST}:{PBX_PORT}"

    via = create_via_header(LOCAL_IP, LOCAL_PORT, branch=branch)
    contact = create_contact_header(f"sip:{USER}@{LOCAL_IP}:{LOCAL_PORT}")

    msg = f"REGISTER {registrar_uri} SIP/2.0\r\n"
    msg += f"Via: {via}\r\n"
    msg += f"Max-Forwards: 70\r\n"
    msg += f"From: <{local_uri}>;tag={from_tag}\r\n"
    msg += f"To: <{local_uri}>\r\n"
    msg += f"Call-ID: {call_id}\r\n"
    msg += f"CSeq: 1 REGISTER\r\n"
    msg += f"User-Agent: pjsip_python/1.0\r\n"
    msg += f"Contact: {contact}\r\n"
    msg += f"Expires: 3600\r\n"
    msg += f"Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REGISTER, REFER, NOTIFY, MESSAGE, INFO\r\n"
    msg += f"Content-Length: 0\r\n"
    msg += f"\r\n"

    return msg, call_id, from_tag


def parse_response(data: bytes) -> dict:
    """Разобрать SIP ответ."""
    try:
        text = data.decode('utf-8', errors='replace')
        lines = text.split('\r\n')

        # Status-Line: SIP/2.0 401 Unauthorized
        status_line = lines[0]
        parts = status_line.split(' ', 2)
        status_code = int(parts[1])

        headers = {}
        for line in lines[1:]:
            if ':' in line and not line.startswith(' '):
                key, value = line.split(':', 1)
                headers[key.strip().lower()] = value.strip()

        return {
            'status_code': status_code,
            'status_text': parts[2] if len(parts) > 2 else '',
            'headers': headers,
            'raw': text
        }
    except Exception as e:
        log(f"Ошибка парсинга ответа: {e}")
        return {}


def build_auth_register(original_request: str, call_id: str, from_tag: str, auth_header: str) -> str:
    """Собрать REGISTER с авторизацией."""
    local_uri = f"sip:{USER}@{LOCAL_IP}"
    registrar_uri = f"sip:{PBX_HOST}:{PBX_PORT}"
    branch = generate_branch()

    via = create_via_header(LOCAL_IP, LOCAL_PORT, branch=branch)

    msg = f"REGISTER {registrar_uri} SIP/2.0\r\n"
    msg += f"Via: {via}\r\n"
    msg += f"Max-Forwards: 70\r\n"
    msg += f"From: <{local_uri}>;tag={from_tag}\r\n"
    msg += f"To: <{local_uri}>\r\n"
    msg += f"Call-ID: {call_id}\r\n"
    msg += f"CSeq: 2 REGISTER\r\n"
    msg += f"User-Agent: pjsip_python/1.0\r\n"
    msg += f"Contact: <sip:{USER}@{LOCAL_IP}:{LOCAL_PORT}>\r\n"
    msg += f"Expires: 3600\r\n"
    msg += f"Authorization: {auth_header}\r\n"
    msg += f"Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REGISTER, REFER, NOTIFY, MESSAGE, INFO\r\n"
    msg += f"Content-Length: 0\r\n"
    msg += f"\r\n"

    return msg


def extract_auth_params(www_auth: str) -> dict:
    """Извлечь параметры из WWW-Authenticate."""
    params = {}
    for part in www_auth.replace('Digest ', '').split(','):
        part = part.strip()
        if '=' in part:
            key, value = part.split('=', 1)
            value = value.strip('"')
            params[key.strip()] = value.strip()
    return params


def calculate_digest_response(username: str, password: str, realm: str, nonce: str, method: str, uri: str) -> str:
    """Вычислить Digest response."""
    import hashlib

    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

    return response


def main():
    log("=" * 60)
    log("  ПРОСТОЙ ТЕСТ РЕГИСТРАЦИИ")
    log(f"  Сервер: {PBX_HOST}:{PBX_PORT}")
    log(f"  Пользователь: {USER}@{REALM}")
    log("=" * 60)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(3.0)

    try:
        sock.bind(('0.0.0.0', 0))  # Случайный порт
        local_addr = sock.getsockname()
        log(f"Сокет привязан к {local_addr[0]}:{local_addr[1]}")

        request, call_id, from_tag = build_register_request()

        log(f"Отправка REGISTER...")
        log(f"  Call-ID: {call_id}")
        log(f"  From tag: {from_tag}")

        sock.sendto(request.encode(), (PBX_HOST, PBX_PORT))
        log("Запрос отправлен")

        try:
            response_data, addr = sock.recvfrom(4096)
            log(f"Получен ответ от {addr[0]}:{addr[1]} ({len(response_data)} байт)")

            response = parse_response(response_data)
            log(f"  Status: {response.get('status_code')} {response.get('status_text', '')}")

            if response.get('status_code') == 401:
                www_auth = response['headers'].get('www-authenticate', '')
                log(f"  WWW-Authenticate: {www_auth}")

                auth_params = extract_auth_params(www_auth)
                nonce = auth_params.get('nonce', '')
                realm_param = auth_params.get('realm', '')

                response_val = calculate_digest_response(
                    USER, PASSWORD, realm_param, nonce, 'REGISTER', f"sip:{PBX_HOST}:{PBX_PORT}"
                )

                auth_header = f'Digest username="{USER}", realm="{realm_param}", nonce="{nonce}", uri="sip:{PBX_HOST}:{PBX_PORT}", response="{response_val}", algorithm=MD5'

                log(f"Отправка REGISTER с авторизацией...")

                auth_request = build_auth_register(request, call_id, from_tag, auth_header)
                sock.sendto(auth_request.encode(), (PBX_HOST, PBX_PORT))

                try:
                    auth_response_data, addr = sock.recvfrom(4096)
                    log(f"Получен ответ на auth REGISTER: {len(auth_response_data)} байт")

                    auth_response = parse_response(auth_response_data)
                    status = auth_response.get('status_code', 0)
                    log(f"  Status: {status} {auth_response.get('status_text', '')}")

                    if status == 200:
                        contact = auth_response['headers'].get('contact', '')
                        expires = auth_response['headers'].get('expires', '')
                        log(f"  Contact: {contact}")
                        log(f"  Expires: {expires}")
                        log("=" * 60)
                        log("  РЕГИСТРАЦИЯ УСПЕШНА!")
                        log("=" * 60)
                        return 0
                    else:
                        log("РЕГИСТРАЦИЯ НЕ УДАЛАСЬ")
                        return 1
                except socket.timeout:
                    log("Таймаут ожидания ответа на auth REGISTER")
                    return 1

            elif response.get('status_code') == 200:
                contact = response['headers'].get('contact', '')
                expires = response['headers'].get('expires', '')
                log(f"  Contact: {contact}")
                log(f"  Expires: {expires}")
                log("=" * 60)
                log("  РЕГИСТРАЦИЯ УСПЕШНА (без auth)!")
                log("=" * 60)
                return 0
            else:
                log(f"Неожиданный статус: {response.get('status_code')}")
                return 1

        except socket.timeout:
            log("Таймаут ожидания ответа")
            return 1

    except Exception as e:
        log(f"Ошибка: {e}")
        return 1
    finally:
        sock.close()


if __name__ == '__main__':
    sys.exit(main())
