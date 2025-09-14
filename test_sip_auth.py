import logging
import time
import json
import sys

from Sippy.SIP import SIPClient

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('SIPAuthTest')

def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)

def test_sip_authentication():
    logger.info("Starting SIP authentication test")
    
    # Load configuration
    config = load_config()
    
    # Create SIP client
    sip_client = SIPClient(config)
    
    # Connect to SIP server
    logger.info("Connecting to SIP server")
    sip_client.connect()
    
    # Register with SIP server
    logger.info("Registering with SIP server")
    result = sip_client.register()
    
    if result:
        logger.info("SIP authentication test passed - Registration successful")
    else:
        logger.error("SIP authentication test failed - Registration unsuccessful")
    
    # Deregister from SIP server
    logger.info("Deregistering from SIP server")
    sip_client.deregister()
    
    # Close connection
    if hasattr(sip_client, 'sock') and sip_client.sock:
        sip_client.sock.close()
    
    logger.info("SIP authentication test completed")
    return result

if __name__ == "__main__":
    test_sip_authentication()