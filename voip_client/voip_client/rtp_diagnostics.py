# rtp_diagnostics.py (unchanged, but integrated in rtp.py)
"""
Comprehensive RTP diagnostics and monitoring system.
Tracks packet loss, jitter, latency, and audio quality metrics.
"""

import time
import logging
import threading
from collections import deque, defaultdict
from typing import Dict, List, Optional, Tuple

from .config import DEFAULT_RTP_PORT_RANGE, AUDIO_FRAME_SIZE, RTP_PAYLOAD_TYPE_PCMU, RTP_SAMPLE_RATE, RTP_PACKETIZATION_INTERVAL, RTP_MAX_JITTER_BUFFER_MS, RTP_MIN_JITTER_BUFFER_MS


class RTPDiagnostics:
    """Advanced RTP diagnostics with real-time monitoring and reporting."""
    
    def __init__(self, window_size=1000):
        self.window_size = window_size
        
        # Packet tracking
        self.packets_received = 0
        self.packets_lost = 0
        self.packets_late = 0
        self.packets_out_of_order = 0
        
        # Timing and jitter
        self.arrival_times = deque(maxlen=window_size)
        self.inter_arrival_jitter = 0.0
        self.last_arrival_time = None
        self.last_sequence = None
        
        # Audio quality metrics
        self.audio_underruns = 0
        self.audio_overruns = 0
        self.consecutive_silence_frames = 0
        self.max_consecutive_silence = 0
        
        # Buffer statistics
        self.buffer_occupancy = deque(maxlen=100)  # Last 100 buffer states
        self.jitter_buffer_size = deque(maxlen=100)
        
        # Network metrics
        self.round_trip_times = deque(maxlen=100)
        self.packet_sizes = deque(maxlen=window_size)
        
        # Quality scores
        self.mos_score = 4.5  # Mean Opinion Score (1-5)
        self.r_factor = 93.0   # R-factor (0-100)
        
        # Thread safety
        self.lock = threading.Lock()
        
        # Logging
        self.last_report_time = time.time()
        self.report_interval = 10.0  # Report every 10 seconds
        
        logging.info("RTP Diagnostics initialized")
    
    def record_packet_arrival(self, sequence: int, timestamp: float, payload_size: int, 
                            arrival_time: Optional[float] = None) -> None:
        """Record arrival of an RTP packet for analysis."""
        if arrival_time is None:
            arrival_time = time.time()
            
        with self.lock:
            self.packets_received += 1
            self.packet_sizes.append(payload_size)
            
            # Track sequence gaps (packet loss)
            if self.last_sequence is not None:
                expected_seq = (self.last_sequence + 1) % 65536
                if sequence != expected_seq:
                    gap = (sequence - expected_seq) % 65536
                    if gap < 32768:  # Forward gap = packet loss
                        self.packets_lost += gap
                        logging.debug(f"Packet loss detected: {gap} packets lost between {self.last_sequence} and {sequence}")
                    else:  # Backward gap = out of order
                        self.packets_out_of_order += 1
                        logging.debug(f"Out of order packet: expected {expected_seq}, got {sequence}")
            
            self.last_sequence = sequence
            
            # Calculate inter-arrival jitter (RFC 3550)
            if self.last_arrival_time is not None:
                arrival_interval = arrival_time - self.last_arrival_time
                self.arrival_times.append((arrival_time, arrival_interval))
                
                # Update jitter using RFC 3550 formula
                if len(self.arrival_times) >= 2:
                    expected_interval = 0.020  # 20ms for G.711
                    deviation = abs(arrival_interval - expected_interval)
                    self.inter_arrival_jitter = self.inter_arrival_jitter * 0.9 + deviation * 0.1
            
            self.last_arrival_time = arrival_time
            
            # Update quality metrics
            self._update_quality_metrics()
            
            # Periodic reporting
            self._check_report_time()
    
    def record_audio_buffer_state(self, buffer_occupancy: int, jitter_buffer_size: int,
                                underrun: bool = False, overrun: bool = False) -> None:
        """Record audio buffer state for quality analysis."""
        with self.lock:
            self.buffer_occupancy.append(buffer_occupancy)
            self.jitter_buffer_size.append(jitter_buffer_size)
            
            if underrun:
                self.audio_underruns += 1
                self.consecutive_silence_frames += 1
                self.max_consecutive_silence = max(self.max_consecutive_silence, 
                                                   self.consecutive_silence_frames)
            else:
                self.consecutive_silence_frames = 0
                
            if overrun:
                self.audio_overruns += 1
    
    def record_round_trip_time(self, rtt_ms: float) -> None:
        """Record round-trip time measurement."""
        with self.lock:
            self.round_trip_times.append(rtt_ms)
    
    def _update_quality_metrics(self) -> None:
        """Update MOS and R-factor based on current stats."""
        with self.lock:
            if self.packets_received > 0:
                loss_rate = self.packets_lost / self.packets_received
                effective_latency = self.inter_arrival_jitter * 1000 + 10  # ms
                self.r_factor = 93.2 - (loss_rate * 100 * 0.1) - (effective_latency / 40)
                self.mos_score = 1 + (0.035 * self.r_factor) + (0.000007 * self.r_factor * (self.r_factor - 60) * (100 - self.r_factor))
                self.mos_score = max(1, min(5, self.mos_score))
    
    def _check_report_time(self) -> None:
        """Log diagnostics if report interval has passed."""
        current_time = time.time()
        if current_time - self.last_report_time >= self.report_interval:
            logging.info(f"RTP Diagnostics: {self.get_diagnostics()}")
            self.last_report_time = current_time
    
    def get_diagnostics(self) -> Dict:
        """Get current diagnostics metrics."""
        with self.lock:
            avg_packet_size = sum(self.packet_sizes) / len(self.packet_sizes) if self.packet_sizes else 0
            avg_rtt = sum(self.round_trip_times) / len(self.round_trip_times) if self.round_trip_times else 0
            loss_rate = (self.packets_lost / self.packets_received * 100) if self.packets_received > 0 else 0
            
            return {
                'packets_received': self.packets_received,
                'packets_lost': self.packets_lost,
                'loss_rate_percent': loss_rate,
                'packets_out_of_order': self.packets_out_of_order,
                'inter_arrival_jitter_ms': self.inter_arrival_jitter * 1000,
                'avg_packet_size': avg_packet_size,
                'avg_rtt_ms': avg_rtt,
                'mos_score': self.mos_score,
                'r_factor': self.r_factor,
                'audio_underruns': self.audio_underruns,
                'audio_overruns': self.audio_overruns,
                'buffer_occupancy': list(self.buffer_occupancy)[-10:] if self.buffer_occupancy else [],
                'jitter_buffer_size': list(self.jitter_buffer_size)[-10:] if self.jitter_buffer_size else []
            }
    
    def reset_stats(self) -> None:
        """Reset all statistics (useful for testing)."""
        with self.lock:
            self.packets_received = 0
            self.packets_lost = 0
            self.packets_late = 0
            self.packets_out_of_order = 0
            self.audio_underruns = 0
            self.audio_overruns = 0
            self.consecutive_silence_frames = 0
            self.max_consecutive_silence = 0
            
            self.arrival_times.clear()
            self.buffer_occupancy.clear()
            self.jitter_buffer_size.clear()
            self.packet_sizes.clear()
            self.round_trip_times.clear()
            
            self.inter_arrival_jitter = 0.0
            self.mos_score = 4.5
            self.r_factor = 93.0
            
            logging.info("RTP Diagnostics statistics reset")

class AudioQualityMonitor:
    """Specialized monitor for audio quality metrics."""
    
    def __init__(self, sample_rate=8000, frame_size=AUDIO_FRAME_SIZE * 2):  # Adjusted for PCM
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.frame_duration_ms = (frame_size / sample_rate) * 1000
        
        # Audio quality metrics
        self.total_frames = 0
        self.silence_frames = 0
        self.clipping_events = 0
        self.noise_floor = 0
        self.signal_power = deque(maxlen=100)
        
        # Timing metrics
        self.frame_timing = deque(maxlen=1000)
        self.expected_frame_interval = self.frame_duration_ms / 1000.0
        
        self.lock = threading.Lock()
    
    def record_audio_frame(self, frame_data: bytes, is_silence: bool = False, 
                          arrival_time: Optional[float] = None) -> None:
        """Record an audio frame for quality analysis."""
        with self.lock:
            self.total_frames += 1
            
            if is_silence:
                self.silence_frames += 1
            
            # Calculate signal power
            if len(frame_data) >= 2:
                power = self._calculate_signal_power(frame_data)
                self.signal_power.append(power)
            
            # Record frame timing
            if arrival_time is not None:
                if len(self.frame_timing) > 0:
                    last_time = self.frame_timing[-1]
                    interval = arrival_time - last_time
                    
                    # Check for timing irregularities
                    if abs(interval - self.expected_frame_interval) > self.expected_frame_interval * 0.5:
                        logging.debug(f"Frame timing irregularity: expected {self.expected_frame_interval*1000:.1f}ms, got {interval*1000:.1f}ms")
                
                self.frame_timing.append(arrival_time)
    
    def _calculate_signal_power(self, frame_data: bytes) -> float:
        """Calculate RMS power of audio frame."""
        if len(frame_data) % 2 != 0:
            return 0.0
            
        samples = len(frame_data) // 2
        if samples == 0:
            return 0.0
            
        # Convert bytes to samples
        import struct
        rms_sum = 0
        for i in range(0, len(frame_data), 2):
            sample = struct.unpack('<h', frame_data[i:i+2])[0]
            rms_sum += sample * sample
        
        return (rms_sum / samples) ** 0.5
    
    def get_audio_quality_metrics(self) -> Dict:
        """Get current audio quality metrics."""
        with self.lock:
            silence_ratio = (self.silence_frames / self.total_frames * 100) if self.total_frames > 0 else 0
            
            # Calculate average signal power
            avg_power = (sum(self.signal_power) / len(self.signal_power)) if self.signal_power else 0
            
            # Estimate audio quality based on metrics
            if silence_ratio < 5:
                quality = "Excellent"
            elif silence_ratio < 10:
                quality = "Good"
            elif silence_ratio < 20:
                quality = "Fair"
            else:
                quality = "Poor"
            
            return {
                'total_frames': self.total_frames,
                'silence_frames': self.silence_frames,
                'silence_ratio': silence_ratio,
                'average_power': avg_power,
                'clipping_events': self.clipping_events,
                'quality': quality,
                'timing_irregularities': max(0, len(self.frame_timing) - self.total_frames)
            }