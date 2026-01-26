"""
Simple Audio Playback Port - Pure Python implementation
No PJSIP dependencies - uses standard library only
"""

import asyncio
import logging
import queue
from typing import Optional
from .audio_format_handler import AudioFormatHandler, AudioFormat

class SimpleAudioPlaybackPort:
    """
    Simple audio playback port that works without PJSIP.
    Uses asyncio and standard library for audio playback.
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
        
        # Queue for playback frames
        self.playback_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        
        # Statistics
        self.frames_played = 0
        self.frames_dropped = 0
        self.errors = 0
        self.last_error = None
        
        # Configuration
        self.auto_convert = True
        self.validate_frames = True
        
        # Playback state
        self.is_playing = False
        self.playback_task: Optional[asyncio.Task] = None
        
        self.logger.info(f"SimpleAudioPlaybackPort initialized: {sample_rate}Hz, {frame_size_ms}ms frames")
    
    def update_playback_data(self, audio_data: bytes, validate: bool = True) -> bool:
        """
        Update playback data.
        
        Args:
            audio_data: Raw audio bytes
            validate: Whether to validate frame integrity
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Split audio into frames
            frames = self._split_into_frames(audio_data)
            
            # Validate and convert frames
            for frame in frames:
                # Validate frame size
                if len(frame) != self.frame_size:
                    self.logger.warning(f"Frame size mismatch: expected {self.frame_size}, got {len(frame)}")
                    continue
                
                # Convert to PCM-16 if needed
                if self.auto_convert:
                    frame, detected_format = self.format_handler.convert_to_pcm16(
                        frame,
                        sample_rate=self.sample_rate
                    )
                    
                    if detected_format != AudioFormat.PCM_16:
                        self.logger.debug(f"Converted audio from {detected_format.value} to PCM-16")
                
                # Validate frame integrity
                if validate and not self.format_handler.validate_pcm16(frame):
                    self.logger.warning("Invalid PCM-16 frame, skipping")
                    self.errors += 1
                    continue
                
                # Queue the frame
                try:
                    self.playback_queue.put_nowait(frame)
                except queue.Full:
                    self.frames_dropped += 1
                    if self.frames_dropped % 10 == 0:
                        self.logger.warning(f"Playback queue full, dropped {self.frames_dropped} frames")
            
            self.logger.info(f"Updated playback data: {len(audio_data)} bytes, {len(frames)} frames")
            return True
            
        except Exception as e:
            self.errors += 1
            self.last_error = str(e)
            self.logger.error(f"Error updating playback data: {e}", exc_info=True)
            return False
    
    def _split_into_frames(self, audio_data: bytes) -> list:
        """
        Split audio data into frames.
        
        Args:
            audio_data: Raw audio bytes
            
        Returns:
            List of frames
        """
        frames = []
        for i in range(0, len(audio_data), self.frame_size):
            frame = audio_data[i:i + self.frame_size]
            if len(frame) < self.frame_size:
                # Pad last frame with zeros (silence)
                frame = frame.ljust(self.frame_size, b'\x00')
            frames.append(frame)
        return frames
    
    def get_next_frame(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        Get the next frame for playback.
        
        Args:
            timeout: Maximum time to wait for frame in seconds
            
        Returns:
            Audio frame bytes or None if timeout
        """
        try:
            frame = self.playback_queue.get(timeout=timeout)
            self.frames_played += 1
            return frame
        except queue.Empty:
            return None
    
    def get_next_frame_nowait(self) -> Optional[bytes]:
        """
        Get the next frame without blocking.
        
        Returns:
            Audio frame bytes or None if queue is empty
        """
        try:
            frame = self.playback_queue.get_nowait()
            self.frames_played += 1
            return frame
        except queue.Empty:
            return None
    
    def clear_queue(self):
        """Clear all pending frames from the queue."""
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break
    
    def get_stats(self) -> dict:
        """
        Get playback statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'frames_played': self.frames_played,
            'frames_dropped': self.frames_dropped,
            'errors': self.errors,
            'last_error': self.last_error,
            'queue_size': self.playback_queue.qsize(),
            'queue_max_size': self.playback_queue.maxsize,
            'duration_seconds': self.frames_played * self.frame_size_ms / 1000
        }
    
    def reset_stats(self):
        """Reset playback statistics."""
        self.frames_played = 0
        self.frames_dropped = 0
        self.errors = 0
        self.last_error = None
