# Simple SIP Bot (Python)

This repository contains a minimal SIP bot built with **aiosip**.  
The bot registers with a SIP server (e.g., FreePBX) and replies to incoming SIP **MESSAGE** requests with a simple, rule‑based response.

## Prerequisites

- Python 3.8+  
- Access to a SIP server (FreePBX, Asterisk, etc.) with a valid username/password  
- Network connectivity to the SIP server (UDP port 5060 by default)

## Setup

1. **Clone the repository** (or copy the files to a folder).

2. **Create a virtual environment (optional but recommended)**  

   ```bash
   python -m venv venv
   venv\Scripts\activate   # Windows
   # source venv/bin/activate   # macOS/Linux
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the bot**

   Edit **`config.json`** and replace the placeholder values with your SIP credentials and server details:

   ```json
   {
     "username": "your_sip_username",
     "password": "your_sip_password",
     "domain": "your_freepbx_domain_or_ip",
     "local_port": 5060,
     "remote_port": 5060,
     "transport": "udp"
   }
   ```

   - `username` / `password`: SIP account credentials.  
   - `domain` / `domain`: IP address or domain of your FreePBX/Asterisk server.  
   - `local_port`: Port on which the bot will listen (default 5060).  
   - `remote_port`: Port of the SIP server (default 5060).  
   - `transport`: Usually `"udp"` (can be `"tcp"` if your server requires it).

## Running the Bot

```bash
python bot.py
```

The bot will:

1. Register with the SIP server using the credentials from `config.json`.  
2. Listen for incoming **MESSAGE** requests.  
3. Respond with a simple text reply based on the incoming message content:
   - `"hello"` or `"hi"` → `"Hi! How can I help you?"`  
   - `"bye"` → `"Goodbye! Have a great day."`  
   - Any other text → `"You said: <original message>"`

Press **Ctrl+C** to stop the bot.

## Extending the Bot

- Replace `generate_response` with a more sophisticated NLP model or integrate with an external chatbot API.  
- Add handlers for other SIP methods (e.g., `INVITE` for voice calls).  
- Implement logging, metrics, or a of message persistence.

## Troubleshooting

- **Registration failures**: Verify credentials, network reachability, and that the SIP server allows registration from your IP.  
- **Port conflicts**: Ensure `local_port` is not used by another application.  
- **Firewall**: Allow UDP traffic on the chosen ports.

---

**License**: This example is provided for educational purposes and is not covered by any specific license. Feel free to adapt it to your needs.
