"""
Тест для анализа UDP трафика
"""

import socket
import time
import struct

def analyze_udp_traffic(local_ip, local_port, duration=10):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((local_ip, local_port))
    sock.settimeout(0.1)
    
    packets = []
    start_time = time.time()
    
    print(f"Слушаем UDP на {local_ip}:{local_port}...")
    
    while time.time() - start_time < duration:
        try:
            data, addr = sock.recvfrom(4096)
            packets.append({
                'time': time.time(),
                'size': len(data),
                'source': addr
            })
        except socket.timeout:
            continue
            
    if not packets:
        print("Не получено ни одного пакета!")
        return
        
    # Анализируем интервалы
    intervals = []
    for i in range(1, len(packets)):
        interval = (packets[i]['time'] - packets[i-1]['time']) * 1000  # в миллисекундах
        intervals.append(interval)
    
    # Статистика
    if intervals:
        avg_interval = sum(intervals) / len(intervals)
        max_interval = max(intervals)
        min_interval = min(intervals)
        
        print(f"\nСтатистика пакетов:")
        print(f"Всего пакетов: {len(packets)}")
        print(f"Средний интервал: {avg_interval:.2f} мс")
        print(f"Мин интервал: {min_interval:.2f} мс")
        print(f"Макс интервал: {max_interval:.2f} мс")
        print(f"Средний размер пакета: {sum(p['size'] for p in packets)/len(packets):.1f} байт")
        
        # Анализ больших интервалов
        large_gaps = [i for i in intervals if i > 40]  # интервалы больше 40мс
        if large_gaps:
            print(f"\nОбнаружено {len(large_gaps)} больших интервалов:")
            for gap in large_gaps[:5]:  # показываем первые 5
                print(f"- {gap:.1f} мс")

if __name__ == "__main__":
    analyze_udp_traffic("192.168.1.181", 10000)  # Используйте свой IP и порт