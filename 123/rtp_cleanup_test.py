import logging
import time
import threading
from Sippy.audio_handler import AudioHandler
from Sippy.rtp_protocol import RTPHandler

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('RTPCleanupTest')

def test_rtp_cleanup():
    logger.info("Starting RTP cleanup test")
    
    # Create minimal config
    config = {
        'rtp': {
            'payload_type': 0,
            'local_port': 4000,
            'jitter_ms': 200,
            'preferred_codecs': ["PCMU", "PCMA"]
        },
        'audio': {
            'sample_rate': 8000,
            'frame_ms': 20
        },
        'debug': True
    }
    
    # Create audio handler and RTP handler
    audio_handler = AudioHandler(config, logger)
    rtp_handler = RTPHandler(config, logger, audio_handler)
    
    # Start RTP
    logger.info("Starting RTP handler")
    rtp_handler.start_rtp("127.0.0.1", ("127.0.0.1", 4002))
    
    # Let it run for a moment
    logger.info("RTP running for 2 seconds...")
    time.sleep(2)
    
    # Get thread IDs before stopping
    thread_ids = {}
    for thread_name in ['send_thread', 'recv_thread', 'playout_thread']:
        if hasattr(rtp_handler, thread_name) and getattr(rtp_handler, thread_name) is not None:
            thread = getattr(rtp_handler, thread_name)
            thread_ids[thread_name] = thread.ident
            logger.info(f"Thread {thread_name} is running with ID {thread.ident}")
    
    # Stop RTP and verify cleanup
    logger.info("Stopping RTP handler")
    start_time = time.time()
    rtp_handler.stop()
    stop_duration = time.time() - start_time
    logger.info(f"RTP stop() completed in {stop_duration:.3f} seconds")
    
    # Verify RTP is stopped
    if rtp_handler.rtp_running:
        logger.error("RTP is still running after stop() call")
    else:
        logger.info("RTP running flag successfully set to False")
    
    # Check if socket is closed
    if hasattr(rtp_handler, 'rtp_sock') and rtp_handler.rtp_sock is not None:
        try:
            # Try to use the socket - if it's closed this will raise an exception
            rtp_handler.rtp_sock.getsockname()
            logger.error("RTP socket still open after stop() call")
        except Exception:
            logger.info("RTP socket successfully closed")
    else:
        logger.info("RTP socket reference successfully cleared")
    
    # Check if threads are stopped
    threads_running = False
    for thread_name in ['send_thread', 'recv_thread', 'playout_thread']:
        if hasattr(rtp_handler, thread_name) and getattr(rtp_handler, thread_name) is not None:
            thread = getattr(rtp_handler, thread_name)
            if thread.is_alive():
                logger.error(f"RTP {thread_name} still running after stop() call")
                threads_running = True
        else:
            logger.info(f"RTP {thread_name} reference successfully cleared")
    
    # Check if thread IDs are still active in the system
    for thread_name, thread_id in thread_ids.items():
        if thread_id in [t.ident for t in threading.enumerate()]:
            logger.warning(f"Thread ID {thread_id} ({thread_name}) still exists in system thread list")
        else:
            logger.info(f"Thread ID {thread_id} ({thread_name}) no longer exists in system thread list")
    
    if not threads_running:
        logger.info("All RTP threads successfully stopped")
    
    # Check if jitter queue is empty
    if hasattr(rtp_handler, 'jitter_queue') and rtp_handler.jitter_queue is not None:
        if rtp_handler.jitter_queue.empty():
            logger.info("Jitter queue successfully emptied")
        else:
            logger.warning("Jitter queue still contains items after cleanup")
    
    logger.info("RTP cleanup test completed successfully")

if __name__ == "__main__":
    test_rtp_cleanup()