#!/usr/bin/env python3
"""
packet_capture.py - Утилита для захвата SIP пакетов

Usage:
    python3 packet_capture.py --capture --port 5060
    python3 packet_capture.py --send --host 192.168.1.176 --port 5060
"""

import sys
import socket
import argparse
import time
from datetime import datetime

sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.pjsip.sip_msg import SipMessage, SipMethod
from pjsip_python.pjsip.sip_uri import parse_sip_uri
from pjsip_python.pjsip.sip_util import create_via_header, create_contact_header, generate_call_id, generate_branch, generate_tag


def log(msg: str):
    """Логирование."""
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}")


def build_register(
    local_ip: str,
    local_port: int,
    remote_ip: str,
    remote_port: int,
    user: str,
    realm: str
) -> SipMessage:
    """Собрать REGISTER запрос."""
    call_id = generate_call_id()
    from_tag = generate_tag()
    branch = generate_branch()
    
    local_uri = f"sip:{user}@{local_ip}:{local_port}"
    registrar_uri = f"sip:{remote_ip}:{remote_port}"
    
    via = create_via_header(local_ip, local_port, branch=branch)
    contact = create_contact_header(f"sip:{user}@{local_ip}:{local_port}")
    
    msg = SipMessage.build_request(
        method=SipMethod.REGISTER,
        uri=registrar_uri,
        from_uri=local_uri,
        to_uri=local_uri,
        call_id=call_id,
        cseq=1,
        via=via,
        contact=contact,
        extra_headers={
            'Expires': '3600',
            'Allow': 'INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE'
        }
    )
    
    return msg


def capture_packets(port: int, timeout: float = 5.0):
    """Перехват SIP пакетов на порту."""
    log(f"Захват пакетов на порту {port}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.settimeout(timeout)
    
    packets = []
    start_time = time.time()
    
    try:
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(4096)
                packets.append((addr, data))
                log(f"Получено от {addr[0]}:{addr[1]}: {len(data)} байт")
                log(f"  {data[:200].decode('utf-8', errors='replace')}")
            except socket.timeout:
                pass
    finally:
        sock.close()
    
    log(f"Перехвачено {len(packets)} пакетов")
    return packets


def send_register(
    local_ip: str,
    local_port: int,
    remote_ip: str,
    remote_port: int,
    user: str,
    realm: str
):
    """Отправить REGISTER и захватить ответ."""
    log(f"Отправка REGISTER на {remote_ip}:{remote_port}")
    log(f"  Local: {local_ip}:{local_port}")
    log(f"  User: {user}@{realm}")
    
    msg = build_register(local_ip, local_port, remote_ip, remote_port, user, realm)
    data = msg.build()
    
    log(f"  Request: {data[:200]}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', local_port))
    sock.settimeout(3.0)
    
    try:
        sock.sendto(data, (remote_ip, remote_port))
        log("Запрос отправлен")
        
        try:
            response_data, addr = sock.recvfrom(4096)
            log(f"Ответ от {addr[0]}:{addr[1]}: {len(response_data)} байт")
            log(f"  {response_data.decode('utf-8', errors='replace')}")
        except socket.timeout:
            log("Таймаут ожидания ответа")
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser(
        description='Утилита для захвата и отправки SIP пакетов',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    %(prog)s --capture --port 5061
    %(prog)s --send --host 192.168.1.176 --port 5060 --user 555533 --realm 192.168.1.176
        """
    )

    parser.add_argument('--capture', action='store_true',
                        help='Перехватывать пакеты на порту')
    parser.add_argument('--send', action='store_true',
                        help='Отправить REGISTER запрос')
    parser.add_argument('--port', type=int, default=5060,
                        help='Локальный/удалённый порт')
    parser.add_argument('--host', type=str, default='192.168.1.176',
                        help='Удалённый хост')
    parser.add_argument('--user', type=str, default='555533',
                        help='SIP пользователь')
    parser.add_argument('--realm', type=str, default='192.168.1.176',
                        help='SIP realm')
    parser.add_argument('--local-ip', type=str, default='127.0.0.1',
                        help='Локальный IP')
    parser.add_argument('--timeout', type=float, default=5.0,
                        help='Таймаут захвата')

    args = parser.parse_args()

    if args.capture:
        capture_packets(args.port, args.timeout)
    elif args.send:
        send_register(
            args.local_ip,
            args.port,
            args.host,
            args.port,
            args.user,
            args.realm
        )
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
