"""
Jitter analysis and compensation for RTP streams.
Implements packet timing analysis and jitter buffer management.
"""

import time
from collections import deque
import logging
import statistics

class JitterAnalyzer:
    def __init__(self, target_jitter_ms=50):
        self.target_jitter_ms = target_jitter_ms
        self.jitter_buffer = deque()  # Буфер для хранения задержек
        self.max_buffer_size = 100  # Максимальный размер буфера истории
        self.last_arrival_time = None
        self.last_sequence = None
        self.current_jitter = 0
        self.min_jitter = float('inf')
        self.max_jitter = 0
        self.total_packets = 0
        self.lost_packets = 0
        self.late_packets = 0
        
    def analyze_packet(self, sequence_number, arrival_time):
        """
        Анализирует время прибытия пакета и обновляет статистику джиттера
        
        Args:
            sequence_number (int): Порядковый номер RTP пакета
            arrival_time (float): Время получения пакета (time.time())
        """
        if self.last_arrival_time is None or self.last_sequence is None:
            self.last_arrival_time = arrival_time
            self.last_sequence = sequence_number
            return
            
        # Вычисляем ожидаемый интервал между пакетами
        expected_interval = 0.02  # 20мс для стандартного RTP
        
        # Вычисляем реальную задержку
        actual_delay = arrival_time - self.last_arrival_time
        sequence_diff = sequence_number - self.last_sequence
        
        if sequence_diff > 1:
            self.lost_packets += sequence_diff - 1
            
        # Вычисляем джиттер (отклонение от ожидаемого интервала)
        if sequence_diff > 0:
            jitter = abs(actual_delay - (expected_interval * sequence_diff))
            self.jitter_buffer.append(jitter)
            
            # Обновляем статистику
            self.min_jitter = min(self.min_jitter, jitter)
            self.max_jitter = max(self.max_jitter, jitter)
            
            # Поддерживаем размер буфера
            if len(self.jitter_buffer) > self.max_buffer_size:
                self.jitter_buffer.popleft()
                
            # Обновляем текущий джиттер (средний по буферу)
            self.current_jitter = statistics.mean(self.jitter_buffer)
            
        self.total_packets += 1
        self.last_arrival_time = arrival_time
        self.last_sequence = sequence_number

    def get_required_buffer_size(self):
        """
        Возвращает рекомендуемый размер джиттер-буфера в миллисекундах
        """
        if not self.jitter_buffer:
            return self.target_jitter_ms
            
        # Используем текущий джиттер и целевое значение для расчета размера буфера
        required_size = self.current_jitter * 1000 * 2  # Преобразуем в мс и умножаем на 2
        
        # Ограничиваем минимальным и максимальным значением
        min_buffer = 20  # Минимум 20мс
        max_buffer = 200  # Максимум 200мс
        
        return max(min_buffer, min(required_size, max_buffer))
        
    def get_stats(self):
        """
        Возвращает текущую статистику джиттера
        """
        return {
            'current_jitter_ms': self.current_jitter * 1000,
            'min_jitter_ms': self.min_jitter * 1000 if self.min_jitter != float('inf') else 0,
            'max_jitter_ms': self.max_jitter * 1000,
            'buffer_size_ms': self.get_required_buffer_size(),
            'total_packets': self.total_packets,
            'lost_packets': self.lost_packets,
            'loss_rate': (self.lost_packets / self.total_packets * 100) if self.total_packets > 0 else 0
        }