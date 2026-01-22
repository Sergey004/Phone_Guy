"""
PJSUA2 Endpoint Manager with PCM Media integration.
Handles proper initialization and lifecycle management.
"""

import pjsua2 as pj
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)


class EndpointManager:
    """
    Manages PJSUA2 Endpoint lifecycle and provides PCM Media integration.
    
    This class ensures proper initialization order:
    1. libCreate() - создать библиотеку
    2. libInit() - инициализировать с конфигом
    3. libStart() - запустить
    4. Создать PCM Media
    5. Создать учётные записи и звонки
    """
    
    def __init__(self, log_level: int = 3, debug_enabled: bool = True):
        """
        Initialize Endpoint Manager.
        
        Args:
            log_level: PJSUA2 log level (0-5, higher = more verbose)
            debug_enabled: Enable debug output
        """
        self.endpoint: Optional[pj.Endpoint] = None
        self.log_level = log_level
        self.debug_enabled = debug_enabled
        self._initialized = False
        self._started = False
        
        logger.info(f"EndpointManager created (log_level={log_level}, debug={debug_enabled})")
    
    def initialize(self) -> 'EndpointManager':
        """
        Initialize PJSUA2 library.
        
        Returns:
            self for chaining
        """
        if self._initialized:
            logger.warning("Endpoint already initialized")
            return self
        
        try:
            logger.info("Creating PJSUA2 Endpoint...")
            self.endpoint = pj.Endpoint()
            
            logger.info("Creating library...")
            self.endpoint.libCreate()
            
            logger.info("Initializing library with config...")
            ep_cfg = pj.EpConfig()
            ep_cfg.logConfig.level = self.log_level
            ep_cfg.logConfig.consoleLevel = self.log_level
            
            self.endpoint.libInit(ep_cfg)
            
            self._initialized = True
            logger.info("✓ Endpoint initialized successfully")
            
        except Exception as e:
            logger.error(f"✗ Failed to initialize Endpoint: {e}")
            raise
        
        return self
    
    def start(self) -> 'EndpointManager':
        """
        Start PJSUA2 library.
        
        Returns:
            self for chaining
        """
        if not self._initialized:
            raise RuntimeError("Endpoint not initialized. Call initialize() first")
        
        if self._started:
            logger.warning("Endpoint already started")
            return self
        
        try:
            logger.info("Starting Endpoint...")
            self.endpoint.libStart()
            self._started = True
            logger.info("✓ Endpoint started successfully")
            
        except Exception as e:
            logger.error(f"✗ Failed to start Endpoint: {e}")
            raise
        
        return self
    
    def stop(self):
        """Stop PJSUA2 library."""
        if not self._started:
            return
        
        try:
            logger.info("Stopping Endpoint...")
            self.endpoint.libDestroy()
            self._started = False
            logger.info("✓ Endpoint stopped")
        except Exception as e:
            logger.error(f"✗ Error stopping Endpoint: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        return self.initialize().start()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
    
    def create_pcm_media(self, clock_rate=16000, channels=1, samples_per_frame=160):
        """
        Create and initialize PCM Media port.
        
        IMPORTANT: Endpoint must be started before calling this!
        
        Args:
            clock_rate: Audio sampling rate (Hz)
            channels: Number of channels (1=mono, 2=stereo)
            samples_per_frame: Samples per audio frame
        
        Returns:
            PcmMedia instance
        
        Raises:
            RuntimeError: If Endpoint not started
        """
        if not self._started:
            raise RuntimeError(
                "Endpoint not started. Call start() before creating PCM Media"
            )
        
        try:
            # Try different import paths
            try:
                from native import PcmMedia
            except ImportError:
                # If running from bot/Test_TTS or similar, use absolute import
                import sys
                import os
                native_path = os.path.join(os.path.dirname(__file__), '../../native')
                if native_path not in sys.path:
                    sys.path.insert(0, native_path)
                from native import PcmMedia
            
            logger.info(
                f"Creating PCM Media (rate={clock_rate}, channels={channels}, "
                f"samples={samples_per_frame})..."
            )
            
            pcm = PcmMedia(clock_rate, channels, samples_per_frame)
            pcm.initialize()
            
            logger.info("✓ PCM Media created and initialized")
            return pcm
            
        except Exception as e:
            logger.error(f"✗ Failed to create PCM Media: {e}")
            raise
    
    def is_running(self) -> bool:
        """Check if Endpoint is running."""
        return self._started and self._initialized
    
    def get_endpoint(self) -> pj.Endpoint:
        """Get the Endpoint instance."""
        if self.endpoint is None:
            raise RuntimeError("Endpoint not created")
        return self.endpoint


class AudioCallManager:
    """
    Manages audio calls with PCM Media integration.
    """
    
    def __init__(self, endpoint_mgr: EndpointManager):
        """
        Initialize Audio Call Manager.
        
        Args:
            endpoint_mgr: EndpointManager instance
        """
        self.endpoint_mgr = endpoint_mgr
        self.pcm_media = None
        self.current_call = None
        
        if not endpoint_mgr.is_running():
            raise RuntimeError("Endpoint must be started before creating AudioCallManager")
    
    def setup_pcm_media(self, clock_rate=16000) -> 'AudioCallManager':
        """
        Setup PCM Media for audio processing.
        
        Args:
            clock_rate: Audio sampling rate (Hz)
        
        Returns:
            self for chaining
        """
        try:
            self.pcm_media = self.endpoint_mgr.create_pcm_media(
                clock_rate=clock_rate,
                channels=1,
                samples_per_frame=160
            )
            self.pcm_media.start()
            logger.info("✓ PCM Media setup and started")
            
        except Exception as e:
            logger.error(f"✗ Failed to setup PCM Media: {e}")
            raise
        
        return self
    
    def send_audio(self, audio_data: bytes):
        """
        Send audio through PCM Media.
        
        Args:
            audio_data: Audio bytes in PCM16 format
        """
        if self.pcm_media is None:
            raise RuntimeError("PCM Media not setup. Call setup_pcm_media() first")
        
        try:
            self.pcm_media.push(audio_data)
            
        except Exception as e:
            logger.error(f"✗ Failed to send audio: {e}")
            raise
    
    def get_receive_buffer_size(self) -> int:
        """Get size of receive buffer in samples."""
        if self.pcm_media is None:
            return 0
        return self.pcm_media.getReceiveBufferSize()
    
    def cleanup(self):
        """Clean up audio resources."""
        if self.pcm_media:
            try:
                self.pcm_media.stop()
            except:
                pass
        self.pcm_media = None


def setup_endpoint(log_level=3, debug=True) -> EndpointManager:
    """
    Quick setup function to initialize PJSUA2 Endpoint.
    
    Args:
        log_level: PJSUA2 log level (0-5)
        debug: Enable debug output
    
    Returns:
        Initialized and started EndpointManager
    
    Example:
        endpoint_mgr = setup_endpoint()
        pcm = endpoint_mgr.create_pcm_media()
        endpoint_mgr.stop()
    """
    mgr = EndpointManager(log_level=log_level, debug_enabled=debug)
    return mgr.initialize().start()


__all__ = ['EndpointManager', 'AudioCallManager', 'setup_endpoint']
