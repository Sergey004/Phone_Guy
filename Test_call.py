import asyncio
import json
import logging
from Sippy.sipclient import SIPClient

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

async def main():
    with open('Test_config.json', 'r') as f:
        config = json.load(f)
    
    client = SIPClient(config)
    await client.connect()
    
    listener_task = asyncio.create_task(client.listen())
    
    await client.register()
    
    # Устанавливаем, какой WAV-файл проигрывать
    await client.play_audio("output_phone.wav")
    
    # Совершаем звонок. Этот вызов будет ожидать установки сессии.
    await client.make_call(config['sip']['target'])
    
    # Оценим длительность исходящего файла, чтобы не сбросить вызов раньше времени
    try:
        duration = client.audio.get_outgoing_duration_seconds()
    except Exception:
        duration = None
    if duration is None:
        duration = 10.0  # разумный дефолт, если не удалось определить
    margin = 0.5  # небольшой запас на хвост буфера

    logging.info("Call established, playing audio for 2 seconds before unhold...")
    await asyncio.sleep(2)

    logging.info("Sending re-INVITE to unhold")
    await client.reinvite(hold=False)

    remaining = max(0.0, duration - 2.0)
    logging.info(f"Playing audio for ~{remaining:.2f}s to finish file (total ~{duration:.2f}s)...")
    await asyncio.sleep(remaining + margin)
    
    logging.info("Ending call...")
    await client.send_bye()
    
    await asyncio.sleep(2) # Даем время на обработку BYE
    
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        logging.info("Listener task cancelled.")

if __name__ == "__main__":
    asyncio.run(main())