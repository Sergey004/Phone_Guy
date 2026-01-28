import asyncio
import numpy as np
from new_voip.sip_rtp_client import SIPClient
from new_voip.audio_engine import TTSSource

# === НАСТРОЙКИ ===
SIP_USER = "555533"          
SIP_PASS = "Test1234"     
SIP_SERVER = "192.168.1.176" 
LOCAL_IP = "192.168.1.181"   
TARGET_NUMBER = "1001"     

async def ai_stream_simulation(tts_source):
    """
    Симулирует поток от AI:
    Генерирует звук кусками по 0.5 секунды и скармливает их в TTS source.
    """
    print("[AI] Neural Network initialized.")
    # Ждем, пока установится соединение, чтобы не говорить в пустоту
    await asyncio.sleep(3) 
    
    sample_rate = 24000  # Типичная частота для TTS моделей
    
    # Генерируем "речь" (меняющиеся тона)
    frequencies = [440, 550, 660, 880, 440] # Ноты: Ля, До, Ми...
    
    print("[AI] Start speaking...")
    
    for freq in frequencies:
        # Генерируем 0.5 секунды звука одной частоты
        duration = 0.5 
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        
        # Синусоида float32 (-1.0 ... 1.0)
        # Добавляем затухание в конце, чтобы не щелкало
        envelope = np.ones_like(t)
        envelope[-1000:] = np.linspace(1, 0, 1000) # Fade out
        
        chunk = (0.5 * np.sin(2 * np.pi * freq * t) * envelope).astype(np.float32)
        
        print(f"[AI] Pushing chunk: {freq} Hz ({len(chunk)} samples)")
        
        # Отправляем в движок
        # Движок сам сделает ресемплинг 24000 -> 8000
        tts_source.push_audio(chunk, src_rate=sample_rate)
        
        # Имитируем, что AI генерирует следующий кусок некоторое время
        # Если пауза будет слишком большой, TTS source начнет слать тишину (это нормально)
        await asyncio.sleep(0.48) 

    print("[AI] Done speaking.")

async def main():
    # 1. Используем TTSSource (Стриминг)
    tts = TTSSource() 
    
    client = SIPClient(SIP_USER, SIP_PASS, SIP_SERVER, LOCAL_IP)
    client.set_audio_source(tts) 

    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: client,
        local_addr=('0.0.0.0', 5060)
    )

    try:
        await client.register()
        await asyncio.sleep(1)

        if client.registered:
            await client.invite(TARGET_NUMBER)
            
            # Запускаем симуляцию AI параллельно с RTP потоком
            # Важно использовать create_task, чтобы не блокировать loop
            ai_task = asyncio.create_task(ai_stream_simulation(tts))
            
            # Ждем пока AI закончит говорить + еще немного времени
            await asyncio.sleep(8) 
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