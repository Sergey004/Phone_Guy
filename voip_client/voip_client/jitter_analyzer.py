# jitter_analyzer.py
"""
Jitter analysis and compensation for RTP streams.
Implements packet timing analysis and jitter buffer management.
"""

import time
from collections import deque
import logging
import statistics
from .config import DEFAULT_RTP_PORT_RANGE, AUDIO_FRAME_SIZE, RTP_PAYLOAD_TYPE_PCMU, RTP_SAMPLE_RATE, RTP_PACKETIZATION_INTERVAL, RTP_MAX_JITTER_BUFFER_MS, RTP_MIN_JITTER_BUFFER_MS


class JitterAnalyzer:
    def __init__(self, target_jitter_ms=100):  # Increased target
        self.target_jitter_ms = target_jitter_ms
        self.jitter_buffer = deque(maxlen=200)  # Увеличиваем размер буфера истории
        self.jitter_window = deque(maxlen=50)  # Окно для расчета текущего джиттера
        self.min_buffer_ms = RTP_MIN_JITTER_BUFFER_MS
        self.max_buffer_ms = RTP_MAX_JITTER_BUFFER_MS
        self.safety_factor = 3.0  # Increased safety factor for more aggressive buffering
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
            self.jitter_window.append(jitter)
            # Обновляем текущий джиттер используя фильтр RFC 3550
            self.current_jitter = self.current_jitter + (abs(jitter - self.current_jitter) / 16.0)
            
            # Обновляем статистику
            self.min_jitter = min(self.min_jitter, jitter)
            self.max_jitter = max(self.max_jitter, jitter)
            
            # Обновляем время последнего пакета
            self.last_arrival_time = arrival_time
            self.last_sequence = sequence_number
            self.total_packets += 1

    def get_required_buffer_size(self):
        """
        Рассчитывает рекомендуемый размер буфера на основе статистики джиттера.
        Returns:
            float: Рекомендуемый размер буфера в миллисекундах
        """
        if not self.jitter_window:
            return self.target_jitter_ms
            
        try:
            # Используем 95-й перцентиль джиттера для определения размера буфера
            jitter_values = sorted(self.jitter_window)
            percentile_95 = jitter_values[int(len(jitter_values) * 0.95)]
            
            # Добавляем запас для компенсации
            buffer_size = percentile_95 * 1000 * self.safety_factor  # Конвертируем в мс и умножаем на safety
            
            # Ограничиваем размер буфера
            return max(self.min_buffer_ms, min(self.max_buffer_ms, buffer_size))
        except Exception as e:
            logging.error(f"Error calculating required buffer: {e}")
            return self.target_jitter_ms

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