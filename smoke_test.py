import json
import logging
import time
import threading
from Sippy.sipclient import SIPClient

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('SmokeTest')

def run_smoke_test():
    logger.info("Starting smoke test to verify RTP cleanup on call termination")
    
    # Load config
    with open('Test_config.json', 'r') as f:
        config = json.load(f)
    
    # Create SIP client
    client = SIPClient(config)
    client.connect()
    
    # Start listener thread
    listener_thread = threading.Thread(target=client.listen, daemon=True)
    listener_thread.start()
    
    # Register with SIP server
    logger.info("Registering with SIP server...")
    client.register()
    time.sleep(2)  # Wait for registration to complete
    
    # Make outgoing call
    target = config['sip']['target']
    logger.info(f"Making outgoing call to {target}...")
    client.make_call(target)
    
    # Wait for call to be established
    logger.info("Waiting for call to be established...")
    call_established = client.call_established.wait(timeout=10)
    
    if not call_established:
        logger.error("Call failed to establish within timeout")
        return
    
    logger.info("Call established successfully")
    
    # Let call run for a few seconds
    time.sleep(5)
    
    # Send BYE to end call
    logger.info("Sending BYE to end call")
    client.send_bye()
    
    # Wait for call to be terminated
    time.sleep(2)
    
    # Check if RTP was properly stopped
    if hasattr(client, 'rtp') and client.rtp is not None:
        if hasattr(client.rtp, 'rtp_running') and client.rtp.rtp_running:
            logger.warning("RTP is still running after call termination")
        else:
            logger.info("RTP handler stopped correctly")
    else:
        logger.info("RTP handler properly cleaned up")
    
    # Unregister and disconnect
    logger.info("Unregistering...")
    try:
        client.unregister()
    except Exception as e:
        logger.error(f"Error during unregister: {e}")
    
    time.sleep(1)
    logger.info("Smoke test completed")

if __name__ == "__main__":
    run_smoke_test()