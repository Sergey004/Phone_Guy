import asyncio
from new_voip.sip_rtp_client import SIPClient
from new_voip.audio_engine import FilePlayerSource

# === НАСТРОЙКИ ===
SIP_USER = "555533"          # Твой номер
SIP_PASS = "Test1234"     # Пароль
SIP_SERVER = "192.168.1.176" # IP Астериска
LOCAL_IP = "192.168.1.181"   # Твой локальный IP (важно!)
TARGET_NUMBER = "1001"     # Кому звоним

async def main():
    # 1. Создаем источник звука (плеер файлов)
    audio_file = "audio.wav"  # Конвертированный файл 8000Hz Mono
    player = FilePlayerSource(audio_file, loop=False)  # loop=True для зацикливания
    
    # 2. Создаем SIP клиента
    client = SIPClient(SIP_USER, SIP_PASS, SIP_SERVER, LOCAL_IP)
    client.set_audio_source(player)  # Подключаем плеер как источник звука для RTP

    # Запускаем SIP транспорт
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: client,
        local_addr=('0.0.0.0', 5060)
    )

    try:
        # 3. Регистрация
        await client.register()
        await asyncio.sleep(1)  # Ждем ответа сервера

        if client.registered:
            # 4. Звонок
            await client.invite(TARGET_NUMBER)
            
            # 5. Ждем окончания воспроизведения или прерывания
            print("[Main] Воспроизведение аудио... Нажмите Ctrl+C для остановки")
            while player.active:
                await asyncio.sleep(1)
            
            # 6. Завершаем звонок
            await client.bye()
        else:
            print("[Main] Failed to register")
            
    except KeyboardInterrupt:
        print("\n[Main] Stopping...")
        await client.bye()
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())