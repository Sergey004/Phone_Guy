"""
Класс для мониторинга RTP пакетов
"""

class RtpMonitor:
    def __init__(self):
        self.expected_seq = None
        self.lost_packets = 0
        self.total_packets = 0
        self.last_seq = None
        
    def process_packet(self, seq):
        if self.expected_seq is None:
            self.expected_seq = seq
            self.last_seq = seq
            self.total_packets = 1
            return
            
        # Проверяем порядок и потери
        if seq > self.expected_seq:
            lost = seq - self.expected_seq
            self.lost_packets += lost
            print(f"Потеряно {lost} пакетов между {self.expected_seq} и {seq}")
            
        self.expected_seq = (seq + 1) % 65536
        self.last_seq = seq
        self.total_packets += 1
        
    def get_stats(self):
        if self.total_packets == 0:
            return "Нет данных о пакетах"
            
        loss_percent = (self.lost_packets / (self.total_packets + self.lost_packets)) * 100
        return f"Всего пакетов: {self.total_packets}, Потеряно: {self.lost_packets} ({loss_percent:.1f}%)"