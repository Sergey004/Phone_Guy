"""
Audio Playback Port
Safe audio playback with format validation and error handling.
Refactored from ByteStreamMediaPort with improved stability.
"""

import pjsua2 as pj
import logging
import struct
from threading import Lock
from typing import Optional
from .audio_format_handler import AudioFormatHandler

class AudioPlaybackPort(pj.AudioMediaPort):
    """
    Safe audio playback port that handles PCM-16 audio with proper error handling.
    Replaces ByteStreamMediaPort with improved stability and format validation.
    """
    
    def __init__(self, 
                 pcm_bytes: bytes = b"", 
                 sample_rate: int = 8000,
                 logger: logging.Logger = None):
        super().__init__()
        self.pcm_data: bytes = pcm_bytes
        self.sample_rate: int = sample_rate
        self.position: int = 0
        self._lock = Lock()
        self.conf_port_id: int = -1
        self.frame_size: int = sample_rate // 50 * 2  # 20ms frames, 16-bit samples
        self.logger = logger or logging.getLogger(__name__)
        self.format_handler = AudioFormatHandler(self.logger)
        
        # Playback state
        self.is_playing = False
        self.loop_playback = False
        self.frames_played = 0
        
        self.logger.info(f"AudioPlaybackPort initialized: {sample_rate}Hz, frame_size={self.frame_size}")
    
    def register_with_conf(self, ep: pj.Endpoint) -> bool:
        """
        Register the port with PJSIP conference bridge.
        
        Args:
            ep: PJSIP Endpoint instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create proper audio format for the port
            audio_format = pj.MediaFormatAudio()
            audio_format.type = pj.PJMEDIA_TYPE_AUDIO
            audio_format.clockRate = self.sample_rate
            audio_format.channelCount = 1
            audio_format.bitsPerSample = 16
            audio_format.frameTimeUsec = 20000  # 20ms frames
            
            # Create the audio media port with proper format
            self.createPort("audio_playback_port", audio_format)
            self.conf_port_id = self.getPortId()
            
            if self.conf_port_id < 0:
                self.logger.error(f"Failed to register port: getPortId returned {self.conf_port_id}")
                return False
                
            self.logger.info(f"AudioPlaybackPort registered with conf port ID: {self.conf_port_id}")
            
            # Verify the port is functional
            try:
                test_frame = pj.MediaFrame()
                test_frame.buf = []
                test_frame.size = 0
                result = self.getFrame(test_frame)
                if result != pj.PJ_SUCCESS:
                    self.logger.warning(f"getFrame test returned {result}, but continuing")
            except Exception as test_e:
                self.logger.warning(f"Port functionality test failed: {test_e}, but continuing")
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error registering AudioPlaybackPort: {e}", exc_info=True)
            return False
    
    def getFrame(self, frame: pj.MediaFrame) -> int:
        """
        Called by PJSIP C++ code to get audio frames for playback.
        MUST NOT raise exceptions - all errors handled internally.
        
        Args:
            frame: PJSIP MediaFrame to fill with audio data
            
        Returns:
            pj.PJ_SUCCESS on success
        """
        try:
            with self._lock:
                # Check if we have data to play
                if self.position >= len(self.pcm_data):
                    # Return silence frame when no more data
                    if self.loop_playback and len(self.pcm_data) > 0:
                        # Loop back to beginning
                        self.position = 0
                        self.logger.debug("Looping playback")
                    else:
                        # Send silence
                        frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
                        frame.size = self.frame_size
                        frame.buf = [0] * (self.frame_size // 2)
                        return pj.PJ_SUCCESS

                # Calculate how many bytes to send in this frame
                bytes_to_send = min(self.frame_size, len(self.pcm_data) - self.position)
                
                # Convert bytes to the format expected by PJSIP MediaFrame
                # MediaFrame expects a list/vector of integers (samples)
                pcm_samples = []
                for i in range(0, bytes_to_send, 2):
                    if i + 1 < len(self.pcm_data):
                        # Convert 2 bytes to 16-bit signed integer (little-endian)
                        sample = int.from_bytes(
                            self.pcm_data[self.position + i:self.position + i + 2], 
                            byteorder='little', 
                            signed=True
                        )
                        pcm_samples.append(sample)
                
                frame.buf = pcm_samples
                frame.size = len(pcm_samples) * 2  # Size in bytes
                self.position += bytes_to_send
                self.frames_played += 1
                
                return pj.PJ_SUCCESS
                
        except Exception as e:
            self.logger.error(f"Error in getFrame: {e}", exc_info=True)
            # Return silence on error to prevent crash
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
            frame.size = self.frame_size
            frame.buf = [0] * (self.frame_size // 2)
            return pj.PJ_SUCCESS
    
    def update_playback_data(self, pcm_bytes: bytes, validate: bool = True) -> bool:
        """
        Update the playback data with new PCM audio.
        
        Args:
            pcm_bytes: New PCM-16 audio data
            validate: Whether to validate the audio format
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not pcm_bytes:
                self.logger.warning("Empty PCM data provided")
                return False
            
            # Validate format if requested
            if validate:
                if not self.format_handler.validate_pcm16(pcm_bytes):
                    self.logger.error("Invalid PCM-16 data provided")
                    return False
            
            with self._lock:
                self.pcm_data = pcm_bytes
                self.position = 0
                self.is_playing = True
                self.frames_played = 0
                
            duration = len(pcm_bytes) / (self.sample_rate * 2)
            self.logger.info(f"Updated playback data: {len(pcm_bytes)} bytes, ~{duration:.2f}s")
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating playback data: {e}", exc_info=True)
            return False
    
    def is_playback_done(self) -> bool:
        """
        Check if playback has completed.
        
        Returns:
            True if playback is done
        """
        with self._lock:
            if self.loop_playback:
                return False
            done = self.position >= len(self.pcm_data)
            return done
    
    def reset_playback(self):
        """Reset playback to the beginning."""
        with self._lock:
            self.position = 0
            self.frames_played = 0
            self.is_playing = False
    
    def stop_playback(self):
        """Stop playback and clear audio data."""
        with self._lock:
            self.pcm_data = b""
            self.position = 0
            self.is_playing = False
            self.frames_played = 0
    
    def get_playback_position(self) -> float:
        """
        Get current playback position in seconds.
        
        Returns:
            Position in seconds
        """
        with self._lock:
            if len(self.pcm_data) == 0:
                return 0.0
            return self.position / (self.sample_rate * 2)
    
    def get_duration(self) -> float:
        """
        Get total playback duration in seconds.
        
        Returns:
            Duration in seconds
        """
        with self._lock:
            if len(self.pcm_data) == 0:
                return 0.0
            return len(self.pcm_data) / (self.sample_rate * 2)
    
    def get_stats(self) -> dict:
        """
        Get playback statistics.
        
        Returns:
            Dictionary with statistics
        """
        with self._lock:
            return {
                'is_playing': self.is_playing,
                'loop_playback': self.loop_playback,
                'frames_played': self.frames_played,
                'position': self.position,
                'total_size': len(self.pcm_data),
                'position_seconds': self.get_playback_position(),
                'duration_seconds': self.get_duration(),
                'progress': self.get_playback_position() / self.get_duration() if self.get_duration() > 0 else 0.0
            }
