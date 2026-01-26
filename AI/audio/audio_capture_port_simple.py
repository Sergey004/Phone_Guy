"""
Simple Audio Capture Port - Pure Python implementation
No PJSIP dependencies - uses standard library only
"""

import asyncio
import logging
import queue
from typing import Optional, Callable
from .audio_format_handler import AudioFormatHandler, AudioFormat

class SimpleAudioCapturePort:
    """
    Simple audio capture port that works without PJSIP.
    Uses asyncio and standard library for audio capture.
    """
    
    def __init__(self, 
                 sample_rate: int = 8000,
                 frame_size_ms: int = 20,
                 logger: logging.Logger = None):
        self.sample_rate = sample_rate
        self.frame_size_ms = frame_size_ms
        self.frame_size = int(sample_rate * frame_size_ms / 1000 * 2)  # 16-bit samples
        self.logger = logger or logging.getLogger(__name__)
        
        # Format handler for conversion
        self.format_handler = AudioFormatHandler(self.logger)
        
        # Thread-safe queue for captured frames
        self.frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        
        # Statistics
        self.frames_captured = 0
        self.frames_dropped = 0
        self.errors = 0
        self.last_error = None
        
        # Configuration
        self.auto_convert = True
        self.validate_frames = True
        
        # Callback for audio capture
        self.capture_callback: Optional[Callable] = None
        
        self.logger.info(f"SimpleAudioCapturePort initialized: {sample_rate}Hz, {frame_size_ms}ms frames")
    
    def set_capture_callback(self, callback: Callable[[bytes], None]):
        """Set callback function for audio capture."""
        self.capture_callback = callback
    
    def put_frame(self, audio_data: bytes) -> bool:
        """
        Put audio frame into queue.
        
        Args:
            audio_data: Raw audio bytes
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Validate frame size
            if len(audio_data) != self.frame_size:
                self.logger.warning(f"Frame size mismatch: expected {self.frame_size}, got {len(audio_data)}")
                self.errors += 1
                return False
            
            # Convert to PCM-16 if needed
            if self.auto_convert:
                audio_data, detected_format = self.format_handler.convert_to_pcm16(
                    audio_data, 
                    sample_rate=self.sample_rate
                )
                
                if detected_format != AudioFormat.PCM_16:
                    self.logger.debug(f"Converted audio from {detected_format.value} to PCM-16")
            
            # Validate frame integrity
            if self.validate_frames and not self.format_handler.validate_pcm16(audio_data):
                self.logger.warning("Invalid PCM-16 frame received, skipping")
                self.errors += 1
                return False
            
            # Queue the frame (non-blocking)
            try:
                self.frame_queue.put_nowait(audio_data)
                self.frames_captured += 1
                
                # Call capture callback if set
                if self.capture_callback:
                    try:
                        self.capture_callback(audio_data)
                    except Exception as e:
                        self.logger.error(f"Error in capture callback: {e}")
                
                return True
            except queue.Full:
                self.frames_dropped += 1
                if self.frames_dropped % 10 == 0:
                    self.logger.warning(f"Frame queue full, dropped {self.frames_dropped} frames")
                return False
                
        except Exception as e:
            self.errors += 1
            self.last_error = str(e)
            self.logger.error(f"Error in put_frame: {e}", exc_info=True)
            return False
    
    def get_frame(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        Get the next audio frame from the queue.
        
        Args:
            timeout: Maximum time to wait for frame in seconds
            
        Returns:
            Audio frame bytes or None if timeout
        """
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def get_frame_nowait(self) -> Optional[bytes]:
        """
        Get the next audio frame without blocking.
        
        Returns:
            Audio frame bytes or None if queue is empty
        """
        try:
            return self.frame_queue.get_nowait()
        except queue.Empty:
            return None
    
    def clear_queue(self):
        """Clear all pending frames from the queue."""
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
    
    def get_stats(self) -> dict:
        """
        Get capture statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'frames_captured': self.frames_captured,
            'frames_dropped': self.frames_dropped,
            'errors': self.errors,
            'last_error': self.last_error,
            'queue_size': self.frame_queue.qsize(),
            'queue_max_size': self.frame_queue.maxsize
        }
    
    def reset_stats(self):
        """Reset capture statistics."""
        self.frames_captured = 0
        self.frames_dropped = 0
        self.errors = 0
        self.last_error = None
