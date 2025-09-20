"""
Модуль для анализа джиттера и статистики RTP
"""

import time
from collections import deque
import statistics
import logging

class JitterAnalyzer:
    def __init__(self, window_size=50):
        self.packet_times = deque(maxlen=window_size)
        self.intervals = deque(maxlen=window_size-1)
        self.last_packet_time = None
        
    def add_packet(self, timestamp=None):
        current_time = timestamp or time.time()
        
        if self.last_packet_time is not None:
            interval = current_time - self.last_packet_time
            if interval > 0:  # Игнорируем отрицательные интервалы
                self.intervals.append(interval)
                
        self.packet_times.append(current_time)
        self.last_packet_time = current_time
        
    def get_stats(self):
        if len(self.intervals) < 2:
            return None
            
        stats = {
            'mean': statistics.mean(self.intervals),
            'stdev': statistics.stdev(self.intervals) if len(self.intervals) > 1 else 0,
            'min': min(self.intervals),
            'max': max(self.intervals)
        }
        
        return stats
        
    def get_recommended_buffer(self):
        stats = self.get_stats()
        if not stats:
            return 3200  # Значение по умолчанию
            
        # Базовый размер + запас на основе джиттера
        base_size = 3200  # 20ms при 8kHz/16-bit
        jitter_margin = int(stats['stdev'] * 8000 * 2)  # Преобразуем время в байты
        
        # Ограничиваем размер буфера
        buffer_size = min(max(base_size + jitter_margin, 1600), 6400)
        
        return buffer_size