#!/usr/bin/env python3
"""
Example: SIP Registration with Event Handling

Demonstrates:
- Creating and configuring a User Agent
- Registering with a SIP server
- Handling registration state changes
- Periodic re-registration
- Graceful shutdown
"""

import asyncio
import signal
import sys
sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python import (
    Ua, UaConfig,
    Account, AccountConfig, RegState
)


class SipRegistration:
    """
    SIP Registration manager with event handling.
    """
    
    def __init__(self):
        self.ua: Ua = None
        self.account: Account = None
        self.running = False
        self.registration_timer = None
    
    async def create(self, local_ip: str, local_port: int):
        """Create the User Agent."""
        config = UaConfig(
            local_ip=local_ip,
            local_port=local_port,
            user_agent="RegistrationClient/1.0"
        )
        self.ua = await Ua.create(config)
        print(f"UA created on {local_ip}:{local_port}")
    
    def on_registration_state(self, state: RegState):
        """Handle registration state changes."""
        state_names = {
            RegState.UNREGISTERED: "Unregistered",
            RegState.REGISTERING: "Registering...",
            RegState.REGISTERED: "Registered",
            RegState.UNREGISTERING: "Unregistering...",
            RegState.FAILED: "Registration failed"
        }
        print(f"Registration state: {state_names.get(state, f'Unknown({state})')}")
    
    async def register(self, id_uri: str, reg_server: str, 
                       username: str = None, password: str = None):
        """Register with SIP server."""
        acc_config = AccountConfig(
            id=id_uri,
            reg_uri=reg_server,
            username=username,
            password=password,
            realm='*' if username else '*'
        )
        
        self.account = await self.ua.create_account(acc_config)
        
        # Set registration callback
        # self.account.on_register_state = self.on_registration_state
        
        # Perform registration
        if self.account.register():
            print(f"Registration initiated for {id_uri}")
            self.running = True
            return True
        else:
            print(f"Registration failed for {id_uri}")
            return False
    
    async def unregister(self):
        """Unregister from SIP server."""
        if self.account:
            print("Unregistering...")
            self.account.unregister()
            self.running = False
    
    async def periodic_refresh(self, interval: int = 60):
        """
        Periodically refresh registration.
        
        SIP registrations expire, so we need to refresh before expiry.
        """
        while self.running:
            await asyncio.sleep(interval)
            if self.running and self.account:
                print("Refreshing registration...")
                self.account.register()
    
    async def run_forever(self):
        """Run the registration client until interrupted."""
        print("\nRegistration client running...")
        print("Press Ctrl+C to exit\n")
        
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            print("\nShutting down...")
    
    async def shutdown(self):
        """Graceful shutdown."""
        self.running = False
        await self.unregister()
        if self.ua:
            await self.ua.destroy()
        print("Shutdown complete")


async def main():
    """Run the registration example."""
    print("=" * 60)
    print("SIP Registration Example")
    print("=" * 60)
    
    client = SipRegistration()
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        print("\nReceived shutdown signal...")
        asyncio.create_task(client.shutdown())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Create UA
        await client.create("192.168.1.181", 5064)
        
        # Register (configure for your SIP server)
        # For Asterisk/FreeSWITCH on localhost:
        await client.register(
            id_uri="sip:registration_demo@192.168.1.181",
            reg_server="sip:192.168.1.5:5060",
            username="demo",
            password="demo123"
        )
        
        # Run until interrupted
        await client.run_forever()
        
    except Exception as e:
        print(f"Error: {e}")
        await client.shutdown()


if __name__ == "__main__":
    asyncio.run(main())


# ============================================================
# Configuration for common SIP servers
# ============================================================

ASTERISK_CONFIG = {
    "id_uri": "sip:1001@192.168.1.5",
    "reg_server": "sip:192.168.1.5:5060",
    "username": "1001",
    "password": "password"
}

FREESWITCH_CONFIG = {
    "id_uri": "sip:1001@192.168.1.5",
    "reg_server": "sip:192.168.1.5:5060",
    "username": "1001",
    "password": "password"
}

KAMAILIO_CONFIG = {
    "id_uri": "sip:user@domain.com",
    "reg_server": "sip:kamailio.domain.com:5060",
    "username": "user",
    "password": "secret"
}
