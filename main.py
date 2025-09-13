import threading
import time
import json
import logging
import math
import os
import struct
from typing import Optional
import argparse
import asyncio

from Sippy.sipclient import SIPClient
import httpx
import io
import wave
import ffmpeg

from agents.stt_adapter import STTAdapter
from agents.llm_adapter import LLMAdapter
from agents.tts_adapter import TTSAdapter


async def run_call_with_agents(config_path: str = 'config.json', call_type: str = 'incoming', target_uri: str = None):
    # Logging
    logging.basicConfig(level=logging.DEBUG if _is_debug() else logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler('output.log'), logging.StreamHandler()])
    logger = logging.getLogger('Main')
    logging.getLogger('TTSAdapter').setLevel(logging.DEBUG)

    # Load config
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Remove wav_outgoing from config to ensure TTS is the primary audio source
    if 'audio' in config and 'wav_outgoing' in config['audio']:
        del config['audio']['wav_outgoing']

    # Initialize TTS and check health before SIP client
    tts = TTSAdapter(config, logger)
    if not await tts.check_health():
        logger.error("TTS server is not healthy. Aborting application startup.")
        return

    client = SIPClient(config)
    client.connect()
    listener_thread = threading.Thread(target=client.listen, daemon=True)
    listener_thread.start()
    client.register()

    if call_type == 'incoming':
        # Wait for an incoming call
        logger.info("Waiting for incoming call...")
        client.call_established.wait()
        logger.info("Call established. Starting agents...")
    elif call_type == 'outgoing':
        if not target_uri:
            logger.error("Target URI is required for outgoing calls.")
            return
        logger.info(f"Making outgoing call to {target_uri}...")
        client.make_call(target_uri)
        client.call_established.wait()
        logger.info("Call established. Starting agents...")
    else:
        logger.error(f"Invalid call type: {call_type}. Use 'incoming' or 'outgoing'.")
        return

    # Custom text for Phone Guy
    phone_guy_text = "Welcome to Freddy Fazbear's Pizza. A magical place for kids and grown-ups alike, where fantasy and fun come to life."

    # Initial greeting
    try:
        tts.speak(phone_guy_text, client)
    except Exception as e:
        logger.warning(f"TTS greeting failed: {e}")

    logger.info("Ending call...")
    time.sleep(5.0) # Add a delay to allow audio to play out
    client.send_bye()

def _is_debug() -> bool:
    v = os.getenv('DEBUG')
    if v is None:
        return True
    return v.lower() in ('true', '1', 't')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run SIP client with agent.")
    parser.add_argument('--config', type=str, default='config.json',
                        help='Path to the configuration file.')
    parser.add_argument('--call-type', type=str, default='incoming',
                        choices=['incoming', 'outgoing'],
                        help='Type of call to handle: "incoming" or "outgoing".')
    parser.add_argument('--target', type=str,
                        help='Target SIP URI for outgoing calls (e.g., "sip:user@domain").')
    args = parser.parse_args()

    # Set logging level for rtp_protocol to INFO
    logging.getLogger('Sippy.rtp_protocol').setLevel(logging.INFO)

    asyncio.run(run_call_with_agents(config_path=args.config, call_type=args.call_type, target_uri=args.target))
