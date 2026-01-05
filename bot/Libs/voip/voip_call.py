"""
VoIP Call
SIP call implementation
"""

import logging
import pjsua2 as pj
import threading
import queue
from typing import Optional, Callable


class VoIPCall(pj.Call):
    """
    SIP call implementation.
    Handles call state, media, and audio playback/recording.
    """
    
    def __init__(self, acc, call_id=pj.PJSUA_INVALID_ID, 
                 logger: Optional[logging.Logger] = None,
                 **kwargs):
        """
        Initialize SIP call.
        
        Args:
            acc: SIP account instance
            call_id: Call ID
            logger: Logger instance
            **kwargs: Additional call parameters
        """
        super().__init__(acc, call_id)
        self.logger = logger or logging.getLogger(__name__)
        
        # Media components
        self.playback_port = None
        self.recorder = None
        
        # Call state
        self.timer = None
        self.hangup_queue = queue.Queue()
        
        # Custom handlers
        self.state_change_handler = None
        self.media_state_handler = None
    
    def onCallState(self, prm):
        """
        Called when call state changes.
        
        Args:
            prm: Call state parameter
        """
        try:
            ci = self.getInfo()
            self.logger.info(f"Call state: {ci.stateText}")
            
            # Handle disconnect
            if ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.logger.info("Call disconnected")
                self._cleanup()
            
            # Call custom handler if set
            if self.state_change_handler:
                self.state_change_handler(self, ci, prm)
                
        except Exception as e:
            self.logger.error(f"Error in onCallState: {e}")
    
    def onCallMediaState(self, prm):
        """
        Called when call media state changes.
        
        Args:
            prm: Media state parameter
        """
        try:
            self.logger.info("Media state changed")
            ci = self.getInfo()
            
            # Process audio media
            for mi in ci.media:
                if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    self._setup_audio_media(mi)
            
            # Call custom handler if set
            if self.media_state_handler:
                self.media_state_handler(self, ci, prm)
                
        except Exception as e:
            self.logger.error(f"Error in onCallMediaState: {e}", exc_info=True)
    
    def _setup_audio_media(self, media_info):
        """
        Setup audio media for call.
        Override this method in subclasses to implement custom audio handling.
        
        Args:
            media_info: Media information
        """
        try:
            audio_media = self.getAudioMedia(media_info.index)
            self.logger.info(f"Audio media setup: port ID {audio_media.getPortId()}")
            
            # Create recorder by default
            self.recorder = pj.AudioMediaRecorder()
            self.recorder.createRecorder("captured_audio.wav")
            audio_media.startTransmit(self.recorder)
            self.logger.info("Recording enabled")
            
        except Exception as e:
            self.logger.error(f"Error setting up audio media: {e}")
    
    def _cleanup(self):
        """Cleanup call resources."""
        try:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            
            if self.recorder:
                try:
                    self.logger.info("Recording saved")
                except Exception as e:
                    self.logger.error(f"Error with recording: {e}")
                self.recorder = None
            
            if self.playback_port:
                self.playback_port = None
                
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    def play_audio_file(self, file_path: str, audio_media: pj.AudioMedia) -> bool:
        """
        Play audio file to call.
        
        Args:
            file_path: Path to audio file
            audio_media: Audio media instance
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.playback_port = pj.AudioMediaPlayer()
            self.playback_port.createPlayer(file_path, 0)
            self.playback_port.startTransmit(audio_media)
            
            self.logger.info(f"Audio playback started: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error playing audio file: {e}")
            return False
    
    def schedule_hangup(self, delay_seconds: float):
        """
        Schedule automatic hangup after delay.
        
        Args:
            delay_seconds: Delay in seconds
        """
        try:
            if self.timer:
                self.timer.cancel()
            
            self.timer = threading.Timer(delay_seconds, self._on_hangup_timer)
            self.timer.start()
            
            self.logger.info(f"Hangup scheduled in {delay_seconds} seconds")
            
        except Exception as e:
            self.logger.error(f"Error scheduling hangup: {e}")
    
    def _on_hangup_timer(self):
        """Called when hangup timer expires."""
        try:
            self.timer = None
            self.logger.info("Hangup timer expired, queuing hangup")
            self.hangup_queue.put(True)
        except Exception as e:
            self.logger.error(f"Error in hangup timer: {e}")
    
    def process_hangup_queue(self) -> bool:
        """
        Process hangup queue and hangup if signal received.
        Should be called from main thread.
        
        Returns:
            True if hangup was processed, False otherwise
        """
        try:
            if not self.hangup_queue.empty():
                self.hangup_queue.get_nowait()
                if self.isActive():
                    self.logger.info("Processing queued hangup")
                    prm = pj.CallOpParam()
                    prm.statusCode = pj.PJSIP_SC_OK
                    self.hangup(prm)
                    return True
        except Exception as e:
            self.logger.error(f"Error processing hangup queue: {e}")
        
        return False
    
    def set_state_change_handler(self, handler: Callable):
        """
        Set custom handler for state changes.
        
        Args:
            handler: Function to call when state changes
                     Signature: handler(call, call_info, param)
        """
        self.state_change_handler = handler
    
    def set_media_state_handler(self, handler: Callable):
        """
        Set custom handler for media state changes.
        
        Args:
            handler: Function to call when media state changes
                     Signature: handler(call, call_info, param)
        """
        self.media_state_handler = handler
    
    def isActive(self) -> bool:
        """Check if call is active."""
        try:
            ci = self.getInfo()
            return ci.state != pj.PJSIP_INV_STATE_DISCONNECTED
        except:
            return False
