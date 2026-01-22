"""
Audio Capture Port
Safely captures audio from PJSIP with format conversion and error handling.
Replaces the unsafe file-tailing approach with direct frame capture.
"""

import pjsua2 as pj
import logging
import queue
import threading
from typing import Optional, Callable
from .audio_format_handler import AudioFormatHandler, AudioFormat

class AudioCapturePort(pj.AudioMediaPort):
    """
    Safe audio capture port that handles format conversion and prevents crashes.
    Called from C++ code, so all exceptions must be caught internally.
    """
    
    def __init__(self, 
                 sample_rate: int = 8000,
                 frame_size_ms: int = 20,
                 logger: logging.Logger = None):
        super().__init__()
        self.sample_rate = sample_rate
        self.frame_size_ms = frame_size_ms
        self.frame_size = int(sample_rate * frame_size_ms / 1000 * 2)  # 16-bit samples
        self.logger = logger or logging.getLogger(__name__)
        
        # Format handler for conversion
        self.format_handler = AudioFormatHandler(self.logger)
        
        # Thread-safe queue for captured frames
        self.frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        
        # Statistics and error tracking
        self.frames_captured = 0
        self.frames_dropped = 0
        self.errors = 0
        self.last_error = None
        
        # Configuration
        self.auto_convert = True  # Auto-convert to PCM-16
        self.validate_frames = True  # Validate frame integrity
        self.conf_port_id = -1
        
        self.logger.info(f"AudioCapturePort initialized: {sample_rate}Hz, {frame_size_ms}ms frames")
    
    def register_with_conf(self, ep: pj.Endpoint) -> bool:
        """
        Register the port with PJSIP conference bridge.
        
        Args:
            ep: PJSIP Endpoint instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            audio_format = pj.MediaFormatAudio()
            audio_format.type = pj.PJMEDIA_TYPE_AUDIO
            audio_format.clockRate = self.sample_rate
            audio_format.channelCount = 1
            audio_format.bitsPerSample = 16
            audio_format.frameTimeUsec = self.frame_size_ms * 1000
            
            self.createPort("audio_capture_port", audio_format)
            self.conf_port_id = self.getPortId()
            
            if self.conf_port_id < 0:
                self.logger.error(f"Failed to register port: getPortId returned {self.conf_port_id}")
                return False
            
            self.logger.info(f"AudioCapturePort registered with conf port ID: {self.conf_port_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error registering AudioCapturePort: {e}", exc_info=True)
            return False
    
    def putFrame(self, frame: pj.MediaFrame) -> int:
        """
        Called by PJSIP C++ code to deliver audio frames.
        MUST NOT raise exceptions - all errors handled internally.
        
        Args:
            frame: PJSIP MediaFrame containing audio data
            
        Returns:
            pj.PJ_SUCCESS on success, error code on failure
        """
        try:
            # Validate frame
            if not frame or frame.size <= 0:
                return pj.PJ_SUCCESS  # Skip empty frames
            
            # Extract audio data safely
            audio_data = self._extract_audio_data(frame)
            if not audio_data:
                return pj.PJ_SUCCESS
            
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
                self.logger.warning(f"Invalid PCM-16 frame received, skipping")
                self.errors += 1
                return pj.PJ_EUNKNOWN
            
            # Queue the frame (non-blocking)
            try:
                self.frame_queue.put_nowait(audio_data)
                self.frames_captured += 1
                return pj.PJ_SUCCESS
            except queue.Full:
                self.frames_dropped += 1
                if self.frames_dropped % 10 == 0:  # Log every 10 drops
                    self.logger.warning(f"Frame queue full, dropped {self.frames_dropped} frames")
                return pj.PJ_SUCCESS  # Don't fail, just drop
                
        except Exception as e:
            self.errors += 1
            self.last_error = str(e)
            self.logger.error(f"Error in putFrame: {e}", exc_info=True)
            return pj.PJ_EUNKNOWN  # Return error code but don't crash
    
    def _extract_audio_data(self, frame: pj.MediaFrame) -> Optional[bytes]:
        """
        Safely extract audio data from PJSIP MediaFrame.
        
        Args:
            frame: PJSIP MediaFrame
            
        Returns:
            Audio bytes or None if extraction fails
        """
        try:
            # Check if frame has buf attribute
            if not hasattr(frame, 'buf') or not frame.buf:
                return None
            
            # Extract samples from frame.buf (list of integers)
            samples = frame.buf if isinstance(frame.buf, list) else []
            
            if not samples:
                return None
            
            # Convert samples to bytes (little-endian 16-bit)
            import struct
            audio_data = struct.pack("<" + "h" * len(samples), *samples)
            
            return audio_data
            
        except Exception as e:
            self.logger.error(f"Error extracting audio data: {e}")
            return None
    
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
