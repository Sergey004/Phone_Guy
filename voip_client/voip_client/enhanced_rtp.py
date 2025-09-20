"""
Улучшенный менеджер RTP пакетов с адаптивной буферизацией
"""

import io
import time
import threading
import logging
from typing import Dict, Tuple, Optional

class EnhancedRTPPacketManager:
    def __init__(self):
        self.offset = 4294967296  # Максимальное 4-байтное число + 1
        self.buffer = io.BytesIO()
        self.bufferLock = threading.Lock()
        self.packets: Dict[int, Tuple[bytes, float]] = {}  # timestamp -> (data, arrival_time)
        self.rebuilding = False
        self.last_cleanup = time.time()
        
        # Настройки буфера
        self.max_packet_age = 5.0  # Максимальное время хранения пакета (сек)
        self.rebuild_threshold = 50  # Количество старых пакетов для запуска перестройки
        self.min_packets_for_stats = 10  # Минимум пакетов для расчета статистики
        
        # Статистика
        self.arrival_intervals = []
        self.last_arrival = None
        self.jitter = 0.0
        self.packet_loss = 0
        self.total_packets = 0
        
    def write(self, timestamp: int, data: bytes) -> None:
        """Записывает пакет с учетом временных меток."""
        now = time.time()
        
        with self.bufferLock:
            # Обновляем статистику
            self._update_stats(timestamp, now)
            
            # Сохраняем пакет
            self.packets[timestamp] = (data, now)
            self.buffer.seek(0, io.SEEK_END)
            self.buffer.write(data)
            
            # Периодическая очистка
            if now - self.last_cleanup > 1.0:
                self._cleanup_old_packets(now)
                
    def read(self, length: int = 160) -> bytes:
        """Читает данные из буфера с проверкой на перестройку."""
        while self.rebuilding:
            time.sleep(0.001)
            
        with self.bufferLock:
            data = self.buffer.read(length)
            if len(data) < length:
                # Дополняем тишиной если недостаточно данных
                data = data + (b"\x00" * (length - len(data)))
            return data
            
    def _update_stats(self, timestamp: int, now: float) -> None:
        """Обновляет статистику по пакетам."""
        self.total_packets += 1
        
        if self.last_arrival is not None:
            interval = now - self.last_arrival
            self.arrival_intervals.append(interval)
            
            # Ограничиваем размер истории
            if len(self.arrival_intervals) > 100:
                self.arrival_intervals.pop(0)
                
            # Обновляем джиттер
            if len(self.arrival_intervals) >= 2:
                deviation = abs(interval - sum(self.arrival_intervals) / len(self.arrival_intervals))
                self.jitter = self.jitter * 0.9 + deviation * 0.1
        
        self.last_arrival = now
            
    def _cleanup_old_packets(self, now: float) -> None:
        """Очищает старые пакеты из истории."""
        old_packets = []
        for ts, (_, arrival_time) in self.packets.items():
            if now - arrival_time > self.max_packet_age:
                old_packets.append(ts)
                
        for ts in old_packets:
            del self.packets[ts]
            
        self.last_cleanup = now
        
        # Запускаем перестройку если накопилось много старых пакетов
        if len(old_packets) > self.rebuild_threshold:
            self._rebuild_buffer()
            
    def _rebuild_buffer(self) -> None:
        """Перестраивает буфер из сохраненных пакетов."""
        self.rebuilding = True
        try:
            # Запоминаем текущую позицию
            current_pos = self.buffer.tell()
            
            # Создаем новый буфер
            new_buffer = io.BytesIO()
            
            # Сортируем пакеты по временным меткам
            sorted_packets = sorted(self.packets.items())
            
            # Записываем пакеты в новый буфер
            for ts, (data, _) in sorted_packets:
                new_buffer.write(data)
                
            # Заменяем старый буфер
            self.buffer = new_buffer
            self.buffer.seek(current_pos)
            
        finally:
            self.rebuilding = False
            
    def get_stats(self) -> dict:
        """Возвращает текущую статистику буфера."""
        stats = {
            'total_packets': self.total_packets,
            'buffer_size': self.buffer.tell(),
            'packet_count': len(self.packets),
            'jitter_ms': self.jitter * 1000,
            'average_interval': sum(self.arrival_intervals) / len(self.arrival_intervals) if self.arrival_intervals else 0
        }
        return stats