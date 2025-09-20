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
        self.jitter_buffer = deque(maxlen=200)  # Увеличиваем размер буфера истории
        self.jitter_window = deque(maxlen=50)  # Окно для расчета текущего джиттера
        self.min_buffer_ms = 20  # Минимальный размер буфера в мс
        self.max_buffer_ms = 200  # Максимальный размер буфера в мс
        self.safety_factor = 2.0  # Коэффициент запаса для размера буфера
        self.last_arrival_time = None
        self.last_sequence = None
        self.current_jitter = 0
        self.min_jitter = float('inf')
        self.max_jitter = 0
        self.total_packets = 0
        self.lost_packets = 0
        self.late_packets = 0

    def get_recommended_buffer(self):
        """
        Рассчитывает рекомендуемый размер буфера на основе статистики джиттера
        
        Returns:
            int: Рекомендуемый размер буфера в байтах
        """
        if len(self.jitter_window) < 10:
            return 640  # Начальный размер буфера (40мс при 8кГц)
            
        # Используем 95-й перцентиль джиттера для определения размера буфера
        jitter_95th = statistics.quantiles(self.jitter_window, n=20)[-1]
        
        # Рассчитываем размер буфера в мс с учетом коэффициента запаса
        buffer_ms = min(
            max(
                self.min_buffer_ms,
                jitter_95th * 1000 * self.safety_factor
            ),
            self.max_buffer_ms
        )
        
        # Конвертируем в байты (16кГц * 16бит * 1канал = 32 байта/мс)
        buffer_size = int(buffer_ms * 32)
        
        # Округляем до ближайшего кратного 160 (размер фрейма G.711)
        return (buffer_size // 160) * 160

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

    def get_recommended_buffer(self):
        """
        Рассчитывает рекомендуемый размер буфера на основе статистики джиттера.
        Returns:
            float: Рекомендуемый размер буфера в миллисекундах
        """
        if not self.jitter_buffer:
            return self.target_jitter_ms
            
        try:
            # Используем 95-й перцентиль джиттера для определения размера буфера
            jitter_values = sorted(self.jitter_buffer)
            percentile_95 = jitter_values[int(len(jitter_values) * 0.95)]
            
            # Добавляем запас для компенсации
            buffer_size = percentile_95 * 1000 * 2  # Конвертируем в мс и умножаем на 2
            
            # Ограничиваем размер буфера
            min_buffer = 20  # Минимум 20 мс
            max_buffer = 200  # Максимум 200 мс
            return max(min_buffer, min(max_buffer, buffer_size))
        except:
            return self.target_jitter_ms
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