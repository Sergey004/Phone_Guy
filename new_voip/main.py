import asyncio
import numpy as np
from sip_rtp_client import SIPClient
from audio_engine import TTSSource, FilePlayerSource

# === НАСТРОЙКИ ===
SIP_USER = "555533"          # Твой номер
SIP_PASS = "Test1234"     # Пароль
SIP_SERVER = "192.168.1.176" # IP Астериска
LOCAL_IP = "192.168.1.181"   # Твой локальный IP (важно!)
TARGET_NUMBER = "1001"     # Кому звоним

async def ai_generator_mock(tts_source):
    """
    Эмуляция работы AI. Генерирует синусоиду (гудок) чанками
    и отправляет в TTS Source.
    """
    print("[AI] Warming up neural network...")
    await asyncio.sleep(2) 
    
    # Генерация 5 секунд звука (440Hz tone)
    sample_rate = 24000
    duration = 5
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # Синусоида float32
    audio = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    
    # Режем на куски, как будто AI выдает потоком
    chunk_size = 24000 # по 1 секунде
    for i in range(0, len(audio), chunk_size):
        chunk = audio[i:i+chunk_size]
        print(f"[AI] Generated chunk {len(chunk)} samples")
        tts_source.push_audio(chunk, src_rate=sample_rate)
        await asyncio.sleep(1.0) # Имитация задержки генерации

async def main():
    # 1. Создаем источник звука (TTS)
    tts = TTSSource()
    
    # (Опционально) Можно подключить плеер файлов:
    # player = FilePlayerSource("background.wav")
    
    # 2. Создаем SIP клиента
    client = SIPClient(SIP_USER, SIP_PASS, SIP_SERVER, LOCAL_IP)
    client.set_audio_source(tts) # Подключаем TTS как источник звука для RTP

    # Запускаем SIP транспорт
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: client,
        local_addr=('0.0.0.0', 5060)
    )

    try:
        # 3. Регистрация
        await client.register()
        await asyncio.sleep(1) # Ждем ответа сервера

        if client.registered:
            # 4. Звонок
            await client.invite(TARGET_NUMBER)
            
            # 5. Параллельно запускаем генерацию "голоса"
            await ai_generator_mock(tts)
            
            await asyncio.sleep(5) # Держим звонок еще 5 сек
            await client.bye()
        else:
            print("[Main] Failed to register")
            
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())