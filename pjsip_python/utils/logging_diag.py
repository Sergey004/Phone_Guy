"""
Logging and Diagnostics Utilities

Provides logging, statistics, and debugging tools for pjsip_python.
"""

import logging
import time
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import IntEnum
from collections import defaultdict


class LogLevel(IntEnum):
    """Log level constants."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class DiagnosticCategory(IntEnum):
    """Diagnostic categories."""
    SIP = 1
    RTP = 2
    MEDIA = 3
    NETWORK = 4
    AUDIO = 5
    AUTH = 6
    ALL = 99


@dataclass
class DiagnosticEntry:
    """Single diagnostic entry."""
    timestamp: float
    category: DiagnosticCategory
    level: LogLevel
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "category": self.category.name,
            "level": self.level.name,
            "message": self.message,
            "data": self.data
        }


class DiagnosticsCollector:
    """
    Collect and manage diagnostic entries.
    """
    
    def __init__(self, max_entries: int = 1000):
        self._entries: List[DiagnosticEntry] = []
        self._max_entries = max_entries
        self._callbacks: Dict[DiagnosticCategory, List[callable]] = defaultdict(list)
        self._enabled = True
    
    def log(self, category: DiagnosticCategory, level: LogLevel, 
            message: str, data: Dict[str, Any] = None):
        """Log a diagnostic entry."""
        if not self._enabled:
            return
            
        entry = DiagnosticEntry(
            timestamp=time.time(),
            category=category,
            level=level,
            message=message,
            data=data or {}
        )
        
        self._entries.append(entry)
        
        # Trim old entries
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        
        # Call callbacks
        for cb in self._callbacks.get(category, []):
            try:
                cb(entry)
            except Exception:
                pass
        for cb in self._callbacks.get(DiagnosticCategory.ALL, []):
            try:
                cb(entry)
            except Exception:
                pass
    
    def debug(self, category: DiagnosticCategory, message: str, data: Dict = None):
        self.log(category, LogLevel.DEBUG, message, data)
    
    def info(self, category: DiagnosticCategory, message: str, data: Dict = None):
        self.log(category, LogLevel.INFO, message, data)
    
    def warning(self, category: DiagnosticCategory, message: str, data: Dict = None):
        self.log(category, LogLevel.WARNING, message, data)
    
    def error(self, category: DiagnosticCategory, message: str, data: Dict = None):
        self.log(category, LogLevel.ERROR, message, data)
    
    def critical(self, category: DiagnosticCategory, message: str, data: Dict = None):
        self.log(category, LogLevel.CRITICAL, message, data)
    
    def add_callback(self, category: DiagnosticCategory, callback: callable):
        """Add callback for category."""
        self._callbacks[category].append(callback)
    
    def remove_callback(self, category: DiagnosticCategory, callback: callable):
        """Remove callback."""
        if callback in self._callbacks[category]:
            self._callbacks[category].remove(callback)
    
    def get_entries(self, category: DiagnosticCategory = None, 
                    level: LogLevel = None,
                    limit: int = 100) -> List[DiagnosticEntry]:
        """Get diagnostic entries with optional filters."""
        entries = self._entries
        
        if category is not None:
            entries = [e for e in entries if e.category == category]
        
        if level is not None:
            entries = [e for e in entries if e.level >= level]
        
        return entries[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get diagnostic statistics."""
        if not self._entries:
            return {"total": 0}
        
        by_category = defaultdict(int)
        by_level = defaultdict(int)
        
        for entry in self._entries:
            by_category[entry.category.name] += 1
            by_level[entry.level.name] += 1
        
        return {
            "total": len(self._entries),
            "by_category": dict(by_category),
            "by_level": dict(by_level),
            "oldest_timestamp": self._entries[0].timestamp if self._entries else None,
            "newest_timestamp": self._entries[-1].timestamp if self._entries else None
        }
    
    def export_json(self) -> str:
        """Export entries as JSON."""
        return json.dumps(
            [e.to_dict() for e in self._entries],
            indent=2
        )
    
    def clear(self):
        """Clear all entries."""
        self._entries.clear()
    
    def enable(self):
        """Enable logging."""
        self._enabled = True
    
    def disable(self):
        """Disable logging."""
        self._enabled = False


# Global diagnostics collector
_diagnostics = DiagnosticsCollector()


def get_diagnostics() -> DiagnosticsCollector:
    """Get the global diagnostics collector."""
    return _diagnostics


class SipLogger:
    """
    SIP-specific logger with structured logging.
    """
    
    def __init__(self, name: str = "pjsip_python"):
        self._logger = logging.getLogger(name)
        self._diagnostics = get_diagnostics()
        
        # Setup default handler if none exists
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)
    
    def set_level(self, level: int):
        """Set log level."""
        self._logger.setLevel(level)
    
    def debug_sip(self, message: str, data: Dict = None):
        self._logger.debug(message)
        self._diagnostics.debug(DiagnosticCategory.SIP, message, data)
    
    def info_sip(self, message: str, data: Dict = None):
        self._logger.info(message)
        self._diagnostics.info(DiagnosticCategory.SIP, message, data)
    
    def warning_sip(self, message: str, data: Dict = None):
        self._logger.warning(message)
        self._diagnostics.warning(DiagnosticCategory.SIP, message, data)
    
    def error_sip(self, message: str, data: Dict = None):
        self._logger.error(message)
        self._diagnostics.error(DiagnosticCategory.SIP, message, data)
    
    def debug_rtp(self, message: str, data: Dict = None):
        self._logger.debug(f"[RTP] {message}")
        self._diagnostics.debug(DiagnosticCategory.RTP, message, data)
    
    def info_rtp(self, message: str, data: Dict = None):
        self._logger.info(f"[RTP] {message}")
        self._diagnostics.info(DiagnosticCategory.RTP, message, data)
    
    def debug_media(self, message: str, data: Dict = None):
        self._logger.debug(f"[MEDIA] {message}")
        self._diagnostics.debug(DiagnosticCategory.MEDIA, message, data)
    
    def info_media(self, message: str, data: Dict = None):
        self._logger.info(f"[MEDIA] {message}")
        self._diagnostics.info(DiagnosticCategory.MEDIA, message, data)
    
    def debug_audio(self, message: str, data: Dict = None):
        self._logger.debug(f"[AUDIO] {message}")
        self._diagnostics.debug(DiagnosticCategory.AUDIO, message, data)
    
    def info_audio(self, message: str, data: Dict = None):
        self._logger.info(f"[AUDIO] {message}")
        self._diagnostics.info(DiagnosticCategory.AUDIO, message, data)


# Global SIP logger
_sip_logger = SipLogger()


def get_sip_logger() -> SipLogger:
    """Get the global SIP logger."""
    return _sip_logger


class CallStats:
    """
    Statistics for a single call.
    """
    
    def __init__(self, call_id: str):
        self.call_id = call_id
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        
        # SIP statistics
        self.messages_sent = 0
        self.messages_received = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        
        # RTP statistics
        self.rtp_packets_sent = 0
        self.rtp_packets_received = 0
        self.rtp_bytes_sent = 0
        self.rtp_bytes_received = 0
        
        # Audio statistics
        self.audio_samples_sent = 0
        self.audio_samples_received = 0
        self.audio_duration_sent = 0.0
        self.audio_duration_received = 0.0
    
    @property
    def duration(self) -> float:
        """Get call duration in seconds."""
        end = self.end_time or time.time()
        return end - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "sip": {
                "messages_sent": self.messages_sent,
                "messages_received": self.messages_received,
                "bytes_sent": self.bytes_sent,
                "bytes_received": self.bytes_received
            },
            "rtp": {
                "packets_sent": self.rtp_packets_sent,
                "packets_received": self.rtp_packets_received,
                "bytes_sent": self.rtp_bytes_sent,
                "bytes_received": self.rtp_bytes_received
            },
            "audio": {
                "samples_sent": self.audio_samples_sent,
                "samples_received": self.audio_samples_received,
                "duration_sent": self.audio_duration_sent,
                "duration_received": self.audio_duration_received
            }
        }


class StatsCollector:
    """
    Collect call and system statistics.
    """
    
    def __init__(self):
        self._calls: Dict[str, CallStats] = {}
        self._global_stats = defaultdict(int)
    
    def create_call(self, call_id: str) -> CallStats:
        """Create stats for a new call."""
        stats = CallStats(call_id)
        self._calls[call_id] = stats
        return stats
    
    def get_call(self, call_id: str) -> Optional[CallStats]:
        """Get stats for a call."""
        return self._calls.get(call_id)
    
    def end_call(self, call_id: str):
        """Mark call as ended."""
        if call_id in self._calls:
            self._calls[call_id].end_time = time.time()
    
    def increment(self, key: str, value: int = 1):
        """Increment global stat."""
        self._global_stats[key] += value
    
    def get_summary(self) -> Dict[str, Any]:
        """Get statistics summary."""
        active_calls = sum(1 for c in self._calls.values() if c.end_time is None)
        total_calls = len(self._calls)
        
        total_rtp_sent = sum(c.rtp_bytes_sent for c in self._calls.values())
        total_rtp_recv = sum(c.rtp_bytes_received for c in self._calls.values())
        
        return {
            "active_calls": active_calls,
            "total_calls": total_calls,
            "global_stats": dict(self._global_stats),
            "total_rtp_sent": total_rtp_sent,
            "total_rtp_recv": total_rtp_recv,
            "rtp_bandwidth_mbps": (total_rtp_sent + total_rtp_recv) / 1_000_000
        }
    
    def export_json(self) -> str:
        """Export as JSON."""
        return json.dumps({
            "summary": self.get_summary(),
            "calls": {cid: cs.to_dict() for cid, cs in self._calls.items()}
        }, indent=2)


# Global stats collector
_stats_collector = StatsCollector()


def get_stats() -> StatsCollector:
    """Get the global stats collector."""
    return _stats_collector


__all__ = [
    'LogLevel', 'DiagnosticCategory',
    'DiagnosticsCollector', 'get_diagnostics',
    'SipLogger', 'get_sip_logger',
    'CallStats', 'StatsCollector', 'get_stats',
]
