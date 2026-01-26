"""
pjsip_python - Pure Python SIP/RTP Stack

A complete implementation of SIP signaling and media transport
for voice calls, inspired by PJSIP but written entirely in Python.

Author: Sergey004
Version: 1.0.0

Example Usage:
    import asyncio
    from pjsip_python import Ua, Account

    async def main():
        # Create UA
        ua = await Ua.create()
        await ua.start()

        # Create account and register
        acc = await ua.create_account({
            'id': 'sip:1001@192.168.1.5',
            'reg_uri': 'sip:192.168.1.5:5060',
            'username': '1001',
            'password': 'password'
        })
        await acc.register()

        # Make call
        call = await ua.call('sip:1002@192.168.1.5')
        await call.wait_for_state(CallState.CONFIRMED)

        # Send audio (numpy format from TTS)
        await call.send_audio_pcm(tts_audio)

        await call.hangup()
        await ua.destroy()

    asyncio.run(main())
"""

__version__ = '1.0.0'
__author__ = 'Sergey004'

from .pjlib import *
from .pjsip import *
from .pjmedia import *
from .pjnath import *
from .pjsua import *
from .utils import *

__all__ = [
    'Ua', 'Call', 'Account', 'Buddy',
    'SipMessage', 'SipTransaction', 'SipDialog',
    'G711Codec', 'RtpSession', 'MediaStream',
    'IceSession', 'StunClient', 'TurnClient',
    'resample_audio', 'numpy_to_pcm16',
]
