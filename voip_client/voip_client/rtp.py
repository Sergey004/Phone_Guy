"""
RTP Handling module for VoIP client.
Implements RTP packet processing, jitter buffer, and sequence management.
"""

import socket
import struct
import threading
import queue
import time
import logging
import random
import audioop
import io
from collections import deque

from .jitter_analyzer import JitterAnalyzer
from .config import DEFAULT_RTP_PORT_RANGE, AUDIO_FRAME_SIZE, RTP_PAYLOAD_TYPE_PCMU, RTP_PAYLOAD_TYPE_PCMA, RTP_SAMPLE_RATE, RTP_PACKETIZATION_INTERVAL, RTP_MAX_JITTER_BUFFER_MS, RTP_MIN_JITTER_BUFFER_MS
from .rtp_diagnostics import RTPDiagnostics, AudioQualityMonitor

class RTPPacketManager:
    def __init__(self, max_buffer_size=8192):
        self.buffer = io.BytesIO()
        self.bufferLock = threading.Lock()
        self.last_read_time = time.time()
        self.max_buffer_size = max_buffer_size
        self.total_written = 0
        self.total_read = 0
        self.underrun_count = 0
        self.overrun_count = 0
        
    def read(self, length: int = 320) -> bytes:
        with self.bufferLock:
            current_pos = self.buffer.tell()
            self.buffer.seek(0, io.SEEK_END)
            buffer_end = self.buffer.tell()
            
            # Проверяем, достаточно ли данных
            available_data = max(0, buffer_end - current_pos)
            
            if available_data < length:
                # Зафиксировать underrun
                self.underrun_count += 1
                if self.underrun_count % 100 == 1:  # Логируем каждые 100 underrun
                    logging.warning(f"RTPPacketManager underrun: available={available_data}, requested={length}")
                
                # Читаем все доступные данные
                self.buffer.seek(current_pos)
                data = self.buffer.read(available_data)
                
                # Дополняем тишиной
                data = data + (b"\x80" * (length - len(data)))
                
                # Перемещаем указатель в конец (очищаем буфер)
                self.buffer.seek(0, io.SEEK_END)
                self.buffer.truncate()
                
            else:
                # Нормальное чтение
                self.buffer.seek(current_pos)
                data = self.buffer.read(length)
                
                # Удаляем прочитанные данные из буфера
                remaining_data = self.buffer.read()
                self.buffer.seek(0)
                self.buffer.truncate()
                self.buffer.write(remaining_data)
                self.buffer.seek(0)
            
            self.last_read_time = time.time()
            self.total_read += len(data)
            return data
            
    def write_seq(self, data: bytes, timestamp: float = None) -> None:
        if not data:
            return
            
        with self.bufferLock:
            # Проверяем размер буфера перед записью
            current_pos = self.buffer.tell()
            self.buffer.seek(0, io.SEEK_END)
            current_size = self.buffer.tell()
            
            # Если буфер слишком большой, удаляем старые данные
            if current_size > self.max_buffer_size:
                self.overrun_count += 1
                if self.overrun_count % 100 == 1:  # Логируем каждые 100 overrun
                    logging.warning(f"RTPPacketManager overrun: size={current_size}, max={self.max_buffer_size}")
                
                # Читаем все данные и удаляем половину
                self.buffer.seek(0)
                all_data = self.buffer.read()
                half_point = len(all_data) // 2
                self.buffer.seek(0)
                self.buffer.truncate()
                self.buffer.write(all_data[half_point:])
                current_size = len(all_data) - half_point
            
            # Записываем новые данные в конец
            self.buffer.write(data)
            self.total_written += len(data)
            
            # Восстанавливаем позицию чтения (в начало, если мы читали)
            if current_pos == 0:
                self.buffer.seek(0)
            else:
                # Сохраняем относительную позицию
                self.buffer.seek(min(current_pos, current_size))
    
    def available(self) -> int:
        with self.bufferLock:
            current_pos = self.buffer.tell()
            self.buffer.seek(0, io.SEEK_END)
            end_pos = self.buffer.tell()
            self.buffer.seek(current_pos)
            return max(0, end_pos - current_pos)
    
    def get_stats(self) -> dict:
        """Возвращает статистику буфера."""
        with self.bufferLock:
            return {
                'total_written': self.total_written,
                'total_read': self.total_read,
                'available': self.available(),
                'underruns': self.underrun_count,
                'overruns': self.overrun_count
            }

class RtpPacket:
    """Represents an RTP packet with header and payload."""
    
    def __init__(self, payload_type=0, sequence=0, timestamp=0, ssrc=0, payload=b''):
        self.version = 2
        self.padding = 0
        self.extension = 0
        self.csrc_count = 0
        self.marker = 0
        self.payload_type = payload_type
        self.sequence = sequence
        self.timestamp = timestamp
        self.ssrc = ssrc
        self.payload = payload

    @classmethod
    def from_bytes(cls, data):
        if len(data) < 12:
            raise ValueError("RTP packet too short")
        
        header = struct.unpack('!BBHII', data[:12])
        version = (header[0] >> 6) & 0x3
        padding = (header[0] >> 5) & 0x1
        extension = (header[0] >> 4) & 0x1
        csrc_count = header[0] & 0xF
        marker = (header[1] >> 7) & 0x1
        payload_type = header[1] & 0x7F
        sequence = header[2]
        timestamp = header[3]
        ssrc = header[4]
        payload = data[12:]
        
        return cls(payload_type, sequence, timestamp, ssrc, payload)

    def to_bytes(self):
        header = bytearray(12)
        header[0] = (self.version << 6) | (self.padding << 5) | (self.extension << 4) | self.csrc_count
        header[1] = (self.marker << 7) | self.payload_type
        struct.pack_into('!HII', header, 2, self.sequence, self.timestamp, self.ssrc)
        return bytes(header) + self.payload

    def is_rtcp(self):
        return 200 <= self.payload_type <= 204

class JitterBuffer:
    """Адаптивный jitter buffer с динамической настройкой размера."""
    
    def __init__(self, max_delay_ms=100, sample_rate=8000, max_sequence_gap=5, initial_max_buffer_size=50, initial_min_buffer_size=10, target_jitter_ms=50, adaptation_factor=0.1, adaptation_interval_sec=5, get_next_packet_timeout=0.02):
        self.max_delay_ms = max_delay_ms
        self.sample_rate = sample_rate
        self.packets = {}  # sequence -> packet
        self.lock = threading.Lock()
        self.next_sequence = None
        self.max_buffer_size = initial_max_buffer_size
        self.min_buffer_size = initial_min_buffer_size
        self.stats = {
            'received': 0,
            'lost': 0,
            'late': 0,
            'out_of_order': 0
        }
        self.last_stats_time = time.time()
        
        # Адаптивные параметры
        self.packet_arrival_times = []  # Времена прибытия пакетов
        self.max_arrival_history = 100
        self.current_jitter_ms = 0
        self.target_jitter_ms = target_jitter_ms
        self.adaptation_factor = adaptation_factor
        self.last_adaptation_time = time.time()
        self.max_sequence_gap = max_sequence_gap
        self.adaptation_interval_sec = adaptation_interval_sec

    def _calculate_jitter(self):
        """Рассчитывает текущий джиттер на основе времен прибытия пакетов."""
        if len(self.packet_arrival_times) < 3:
            return 0
            
        # Рассчитываем отклонения от ожидаемого интервала (20мс)
        expected_interval = 0.020  # 20ms
        deviations = []
        
        for i in range(1, len(self.packet_arrival_times)):
            actual_interval = self.packet_arrival_times[i][0] - self.packet_arrival_times[i-1][0]
            sequence_diff = (self.packet_arrival_times[i][1] - self.packet_arrival_times[i-1][1]) % 65536
            
            if sequence_diff > 0 and sequence_diff < 32768:  # Нормальный порядок
                expected = expected_interval * sequence_diff
                deviation = abs(actual_interval - expected)
                deviations.append(deviation)
        
        if deviations:
            # Используем среднее отклонение как оценку джиттера
            return sum(deviations) / len(deviations)
        return 0
        
    def _adapt_buffer_size(self):
        """Адаптирует размер буфера на основе текущего джиттера."""
        now = time.time()
        if now - self.last_adaptation_time < self.adaptation_interval_sec:
            return
            
        self.last_adaptation_time = now
        
        # Рассчитываем текущий джиттер
        current_jitter = self._calculate_jitter()
        self.current_jitter_ms = current_jitter * 1000
        
        # Адаптируем размер буфера
        if self.current_jitter_ms > self.target_jitter_ms * 1.2:  # Увеличиваем буфер, если джиттер значительно выше цели
            # Увеличиваем max_buffer_size, но не выше initial_max_buffer_size
            new_max_buffer_size = min(self.initial_max_buffer_size, self.max_buffer_size + int(self.adaptation_factor * 10))
            if new_max_buffer_size > self.max_buffer_size:
                logging.info(f"Adapting buffer size up: {self.max_buffer_size} -> {new_max_buffer_size} (jitter={self.current_jitter_ms:.1f}ms)")
                self.max_buffer_size = new_max_buffer_size
        elif self.current_jitter_ms < self.target_jitter_ms * 0.8:  # Уменьшаем буфер, если джиттер значительно ниже цели
            # Уменьшаем max_buffer_size, но не ниже initial_min_buffer_size
            new_max_buffer_size = max(self.initial_min_buffer_size, self.max_buffer_size - int(self.adaptation_factor * 10))
            if new_max_buffer_size < self.max_buffer_size:
                logging.info(f"Adapting buffer size down: {self.max_buffer_size} -> {new_max_buffer_size} (jitter={self.current_jitter_ms:.1f}ms)")
                self.max_buffer_size = new_max_buffer_size
        
    def add_packet(self, packet):
        with self.lock:
            current_time = time.time()
            self.stats['received'] += 1
            
            # Отслеживаем время прибытия пакета для анализа джиттера
            self.packet_arrival_times.append((current_time, packet.sequence))
            if len(self.packet_arrival_times) > self.max_arrival_history:
                self.packet_arrival_times.pop(0)
            
            # Инициализация начальной последовательности
            if self.next_sequence is None:
                self.next_sequence = packet.sequence
                logging.info(f"JitterBuffer: Initialized with sequence {packet.sequence}")
            
            # Проверяем, не поздний ли это пакет
            seq_diff = (packet.sequence - self.next_sequence) % 65536
            if seq_diff > 32768:  # Пакет из прошлого
                self.stats['late'] += 1
                logging.debug(f"Late packet: seq={packet.sequence}, expected={self.next_sequence}")
                return False
            
            # Сохраняем пакет
            self.packets[packet.sequence] = packet
            
            # Проверяем переполнение буфера
            if len(self.packets) > self.max_buffer_size:
                # Удаляем самый старый пакет
                oldest_seq = min(self.packets.keys())
                del self.packets[oldest_seq]
                logging.debug(f"Buffer overflow, dropped packet {oldest_seq}")
            
            # Адаптируем размер буфера на основе текущего джиттера
            self._adapt_buffer_size()
            
            self._log_stats()
            return True
    
    def get_next_packet(self, timeout=0.02):
        """Получает следующий пакет в правильной последовательности с учетом времени."""
        start_time = time.time()
        
        with self.lock:
            if self.next_sequence is None:
                return None
            
            # Ждем нужный пакет в течение таймаута
            while (time.time() - start_time) < timeout:
                # Проверяем, есть ли нужный пакет
                if self.next_sequence in self.packets:
                    packet = self.packets.pop(self.next_sequence)
                    self.next_sequence = (self.next_sequence + 1) % 65536
                    return packet
                
                # Проверяем, не опаздывает ли пакет слишком сильно
                current_time = time.time()
                max_delay = self.max_delay_ms / 1000.0
                
                # Смотрим самый старый пакет в буфере
                if self.packets:
                    oldest_seq = min(self.packets.keys())
                    seq_diff = (self.next_sequence - oldest_seq) % 65536
                    
                    # Если самый старый пакет намного новее ожидаемого, значит пакет действительно потерян
                    # Используем настраиваемый порог для определения потери пакета
                    if seq_diff > self.max_sequence_gap and seq_diff < 32768:
                        self.stats['lost'] += 1
                        lost_seq = self.next_sequence
                        self.next_sequence = (self.next_sequence + 1) % 65536
                        logging.debug(f"Lost packet: {lost_seq}")
                        return None
                    elif seq_diff > 32768:  # Старый пакет, пропускаем
                        old_packet = self.packets.pop(oldest_seq)
                        self.stats['late'] += 1
                        continue
                
                # Небольшая задержка перед следующей проверкой
                time.sleep(0.001)
            
            # Таймаут истек, возвращаем None (без увеличения счетчика потерь)
            return None
    
    def _log_stats(self):
        now = time.time()
        if now - self.last_stats_time > 10.0:  # Каждые 10 секунд
            logging.info(f"JitterBuffer stats: received={self.stats['received']}, "
                        f"lost={self.stats['lost']}, late={self.stats['late']}, "
                        f"buffer_size={len(self.packets)}")
            self.last_stats_time = now

class RtpSession:
    """Manages RTP session for a single call."""
    
    def __init__(self, local_ip, local_port, remote_ip, remote_port, payload_type=0, enable_diagnostics=True):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.payload_type = payload_type
        self.enable_diagnostics = enable_diagnostics
        
        # Создаем сокет
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((local_ip, local_port))
        self.sock.settimeout(0.1)
        
        # RTP параметры
        self.seq = random.randint(0, 65535)
        self.timestamp = random.randint(0, 2**32 - 1)
        self.ssrc = random.randint(1, 2**32 - 1)
        
        # Буферы и обработка
        self.jitter_buffer = JitterBuffer(
            max_delay_ms=80,
            initial_max_buffer_size=RTP_MAX_JITTER_BUFFER_MS,
            initial_min_buffer_size=RTP_MIN_JITTER_BUFFER_MS,
            target_jitter_ms=50,  # Default value, can be made configurable in config.py
            adaptation_factor=0.1,  # Default value, can be made configurable in config.py
            adaptation_interval_sec=5,  # Default value, can be made configurable in config.py
            get_next_packet_timeout=0.02 # Default value, can be made configurable in config.py
        )
        self.pcm_manager = RTPPacketManager()
        
        # Диагностика
        if self.enable_diagnostics:
            self.diagnostics = RTPDiagnostics()
            self.audio_monitor = AudioQualityMonitor()
        else:
            self.diagnostics = None
            self.audio_monitor = None
        
        # Потоки
        self.running = False
        self.recv_thread = None
        self.decode_thread = None
        self.send_thread = None
        self.send_queue = queue.Queue()
        
        # Блокировки
        self.send_lock = threading.Lock()
        
        # Статистика
        self.last_packet_time = time.time()
        self.packet_count = 0
        
        logging.info(f"RtpSession created: {local_ip}:{local_port} -> {remote_ip}:{remote_port}")

    def start(self):
        if self.running:
            return
            
        self.running = True
        
        # Поток приема пакетов
        self.recv_thread = threading.Thread(target=self._receive_loop, name="rtp_recv")
        self.recv_thread.daemon = True
        self.recv_thread.start()
        
        # Поток декодирования и буферизации
        self.decode_thread = threading.Thread(target=self._decode_loop, name="rtp_decode")
        self.decode_thread.daemon = True
        self.decode_thread.start()
        
        # Поток отправки
        self.send_thread = threading.Thread(target=self._send_loop, name="rtp_send")
        self.send_thread.daemon = True
        self.send_thread.start()
        
        logging.info("RtpSession started")

    def stop(self):
        if not self.running:
            return
            
        logging.info("Stopping RtpSession...")
        self.running = False
        
        # Останавливаем поток отправки
        try:
            self.send_queue.put(None)  # Сигнал завершения
        except:
            pass
        
        # Закрываем сокет
        try:
            self.sock.close()
        except:
            pass
        
        # Ждем завершения потоков
        threads = [self.recv_thread, self.decode_thread, self.send_thread]
        for thread in threads:
            if thread and thread.is_alive():
                thread.join(timeout=1.0)
        
        logging.info("RtpSession stopped")

    def _receive_loop(self):
        """Поток приема RTP пакетов."""
        logging.info("RTP receive thread started")
        consecutive_timeouts = 0
        
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                consecutive_timeouts = 0
                
                if len(data) < 12:
                    continue
                
                packet = RtpPacket.from_bytes(data)
                
                # Игнорируем RTCP пакеты
                if packet.is_rtcp():
                    continue
                
                # Проверяем размер payload
                if not packet.payload or len(packet.payload) == 0:
                    logging.debug("Received packet with empty payload")
                    continue
                
                # Добавляем в jitter buffer и записываем в диагностику
                if self.jitter_buffer.add_packet(packet):
                    self.packet_count += 1
                    self.last_packet_time = time.time()
                    
                    # Записываем информацию о пакете в диагностику
                    if self.diagnostics:
                        self.diagnostics.record_packet_arrival(
                            sequence=packet.sequence,
                            timestamp=packet.timestamp,
                            payload_size=len(packet.payload),
                            arrival_time=time.time()
                        )
                
            except socket.timeout:
                consecutive_timeouts += 1
                if consecutive_timeouts > 100:  # 10 секунд без пакетов
                    logging.warning("No RTP packets received for 10 seconds")
                    consecutive_timeouts = 0
                continue
            except Exception as e:
                if self.running:
                    logging.error(f"RTP receive error: {e}")
                break
        
        logging.info("RTP receive thread stopped")

    def _decode_loop(self):
        """Поток декодирования пакетов из jitter buffer с адаптивной синхронизацией."""
        logging.info("RTP decode thread started")
        
        # Параметры синхронизации
        last_packet_time = time.time()
        expected_frame_time = 0.020  # 20ms для G.711
        consecutive_timeouts = 0
        max_consecutive_timeouts = 10
        
        while self.running:
            try:
                # Получаем пакет из jitter buffer с адаптивным таймаутом
                timeout = expected_frame_time * 0.8  # 80% от времени кадра
                packet = self.jitter_buffer.get_next_packet(self.jitter_buffer.get_next_packet_timeout)
                
                current_time = time.time()
                
                if packet is None:
                    # Нет пакета - адаптивная генерация тишины
                    consecutive_timeouts += 1
                    
                    # Рассчитываем сколько тишины нужно сгенерировать
                    time_since_last_packet = current_time - last_packet_time
                    frames_needed = int(time_since_last_packet / expected_frame_time)
                    
                    if frames_needed > 0:
                        silence = b'\x00' * (320 * frames_needed)
                        self.pcm_manager.write_seq(silence)
                        
                        if self.audio_monitor:
                            self.audio_monitor.record_audio_frame(silence, is_silence=True, arrival_time=current_time)
                        
                        logging.debug(f"Generated {frames_needed} silence frames due to packet loss.")
                        
                        # Адаптивная задержка: корректируем время сна
                        sleep_time = (frames_needed * expected_frame_time) - (time.time() - current_time)
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                    
                    # Сбрасываем счетчик таймаутов, так как мы сгенерировали тишину
                    consecutive_timeouts = 0
                    continue
                else:
                    # Пакет получен - сбрасываем счетчик таймаутов
                    consecutive_timeouts = 0
                    last_packet_time = current_time
                
                # Декодируем G.711
                try:
                    if self.payload_type == 0:  # PCMU
                        pcm = audioop.ulaw2lin(packet.payload, 2)
                    elif self.payload_type == 8:  # PCMA
                        pcm = audioop.alaw2lin(packet.payload, 2)
                    else:
                        pcm = packet.payload  # Предполагаем PCM
                    
                    if len(pcm) > 0:
                        # Записываем декодированный PCM в буфер
                        self.pcm_manager.write_seq(pcm)
                        
                        # Адаптивная задержка для синхронизации
                        processing_time = time.time() - current_time
                        sleep_time = expected_frame_time - processing_time
                        if sleep_time > 0.001:  # Только если есть смысл спать
                            time.sleep(sleep_time)
                        elif sleep_time < -0.010: # Если сильно отстаем, логируем
                            logging.warning(f"Decode loop falling behind: {sleep_time*1000:.1f}ms")
                except Exception as e:
                    logging.error(f"Decode error: {e}")
                    # В случае ошибки декодирования генерируем тишину
                    silence = b'\x00' * 320
                    self.pcm_manager.write_seq(silence)
                    
                    # Адаптивная задержка после ошибки
                    time.sleep(expected_frame_time)
                
            except Exception as e:
                if self.running:
                    logging.error(f"Decode loop error: {e}")
                time.sleep(0.001)
        
        logging.info("RTP decode thread stopped")

    def _send_loop(self):
        """Поток отправки RTP пакетов."""
        logging.info("RTP send thread started")
        
        while self.running:
            try:
                # Получаем данные для отправки
                data = self.send_queue.get(timeout=0.1)
                
                if data is None:  # Сигнал завершения
                    break
                
                # Создаем RTP пакет
                packet = RtpPacket(
                    payload_type=self.payload_type,
                    sequence=self.seq,
                    timestamp=self.timestamp,
                    ssrc=self.ssrc,
                    payload=data
                )
                
                # Отправляем
                self.sock.sendto(packet.to_bytes(), (self.remote_ip, self.remote_port))
                
                # Обновляем счетчики
                self.seq = (self.seq + 1) % 65536
                self.timestamp = (self.timestamp + len(data)) % (2**32)
                
            except queue.Empty:
                continue
            except Exception as e:
                if self.running:
                    logging.error(f"RTP send error: {e}")
        
        logging.info("RTP send thread stopped")

    def send_audio(self, audio_data):
        """Отправляет аудио данные через RTP."""
        if not self.running or not audio_data:
            return
        
        try:
            # Определяем размер фрейма
            if isinstance(AUDIO_FRAME_SIZE, int) and AUDIO_FRAME_SIZE > 0:
                frame_size = AUDIO_FRAME_SIZE
            else:
                frame_size = 160  # По умолчанию для G.711
            
            # Разбиваем на фреймы
            data = bytes(audio_data)
            offset = 0
            
            while offset < len(data):
                frame = data[offset:offset + frame_size]
                if len(frame) < frame_size:
                    # Дополняем тишиной
                    frame += b'\x80' * (frame_size - len(frame))
                
                # Кодируем в G.711 если нужно
                if self.payload_type == 0:  # PCMU
                    encoded = audioop.lin2ulaw(frame, 2) if len(frame) > frame_size // 2 else audioop.lin2ulaw(frame + b'\x00' * (320 - len(frame)), 2)[:frame_size // 2]
                elif self.payload_type == 8:  # PCMA
                    encoded = audioop.lin2alaw(frame, 2) if len(frame) > frame_size // 2 else audioop.lin2alaw(frame + b'\x00' * (320 - len(frame)), 2)[:frame_size // 2]
                else:
                    encoded = frame
                
                # Добавляем в очередь отправки
                try:
                    self.send_queue.put_nowait(encoded)
                except queue.Full:
                    # Если очередь полная, пропускаем
                    logging.warning("Send queue full, dropping packet")
                
                offset += frame_size
                
        except Exception as e:
            logging.error(f"send_audio error: {e}")

    def get_audio(self, timeout=0.1, blocking=True):
        """Получает декодированные аудио данные."""
        try:
            # Определяем размер чанка
            chunk_size = 320  # 160 сэмплов * 2 байта
            
            if blocking:
                # Ждем данные
                start_time = time.time()
                while self.running and (time.time() - start_time < timeout):
                    if self.pcm_manager.available() >= chunk_size:
                        break
                    time.sleep(0.001)
            
            # Читаем данные
            pcm = self.pcm_manager.read(chunk_size)
            
            # Проверяем качество данных
            if pcm and len(pcm) == chunk_size:
                return pcm
            else:
                # Возвращаем тишину если данных нет или мало
                return b'\x80' * chunk_size
                
        except Exception as e:
            logging.error(f"get_audio error: {e}")
            return b'\x00' * 320
