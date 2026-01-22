# SimpleSIP - Pure Python SIP/RTP Client

Нативная (Pure Python) библиотека для SIP/RTP звонков без внешних зависимостей. Использует только стандартную библиотеку Python 3.9+.

## Особенности

- ✅ **Pure Python** - никаких сложных зависимостей вроде PJSIP
- ✅ **AsyncIO** - полностью асинхронная реализация
- ✅ **SIP протокол** - REGISTER, INVITE, BYE, ACK
- ✅ **MD5 Digest авторизация** - поддержка 401 Unauthorized
- ✅ **RTP транспорт** - правильный тайминг (20мс чанки)
- ✅ **PCMA кодек** - только G.711 A-law (Payload Type 8)
- ✅ **Интеграция с TTS** - поддержка Tensor TTS с RVC

## Структура

### `simple_sip.py` - основная библиотека

**Классы:**
- `SipClient` - основной клиент для SIP звонков
- `Call` - управление активным звонком
- `RtpTransport` - RTP транспорт для аудио
- `RtpPacket` - упаковка RTP заголовков через `struct`
- `SipProtocol` - asyncio.DatagramProtocol для SIP

**Функции:**
- `generate_md5_digest()` - генерация Authorization заголовка
- `parse_sip_message()` - разбор SIP сообщений
- `parse_sdp()` - извлечение IP/порта из SDP

### `test_tensor_sip.py` - тестовый скрипт

Интеграция с Tensor TTS и RVC для тестирования звонков.

## Установка

Нет внешних зависимостей! Только Python 3.9+.

```bash
# Клонируйте репозиторий
cd /home/user/Test_Phone_new

# Скопируйте конфигурацию
cp .env.simple_sip .env

# Отредактируйте .env с вашими настройками
nano .env
```

## Конфигурация (.env)

```bash
# SIP сервер
SIP_USER=1001
SIP_PASSWORD=password
SIP_SERVER=192.168.1.5
TARGET_NUMBER=1002

# Локальный IP
LOCAL_IP=192.168.1.20

# TTS (опционально)
TTS_ENGINE=turbo
TTS_DEVICE=cuda

# RVC (опционально)
RVC_ENABLED=false
RVC_MODEL_PATH=/path/to/model.pth
RVC_INDEX_PATH=/path/to/index.index
```

## Использование

### Базовый пример

```python
import asyncio
from simple_sip import SipClient

async def main():
    # Создаём клиент
    client = SipClient(
        user="1001",
        pwd="password",
        server="192.168.1.5",
        local_ip="192.168.1.20"
    )
    
    # Запускаем
    await client.start()
    
    # Регистрируемся
    if await client.register():
        print("Registered!")
    
    # Звоним
    call = await client.invite("1002")
    
    if call.success:
        print("Call established!")
        
        # Отправляем аудио (PCMA)
        dummy_audio = b'\xd5' * 8000 * 5  # 5 секунд тишины
        await call.send_audio(dummy_audio)
        
        await call.bye()
    
    await client.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### С TTS и RVC

```python
import asyncio
import audioop
from simple_sip import SipClient
from AI.tts_adapter import TTSAdapter

async def main():
    # SIP клиент
    client = SipClient(user="1001", pwd="password", 
                      server="192.168.1.5", local_ip="192.168.1.20")
    await client.start()
    await client.register()
    
    # TTS с RVC
    tts = TTSAdapter(config={
        'tts': {
            'engine': 'turbo',
            'device': 'cuda',
            'rvc_enabled': True,
            'rvc_model_path': '/path/to/model.pth',
            'rvc_index_path': '/path/to/index.index'
        }
    }, logger=logger)
    
    # Звонок
    call = await client.invite("1002")
    
    if call.success:
        # Генерируем речь (английский текст)
        text = "Hello, this is a test call from AI."
        pcm_data = tts.synthesize_sync(text)
        
        # Конвертируем PCM → PCMA
        pcma_data = audioop.lin2alaw(pcm_data, 2)
        
        # Отправляем через RTP
        await call.send_audio(pcma_data)
        
        await call.bye()
    
    await client.stop()

asyncio.run(main())
```

## Запуск теста

```bash
# С конфигурацией из .env
python test_tensor_sip.py

# Или напрямую с параметрами
SIP_USER=1001 SIP_PASSWORD=password SIP_SERVER=192.168.1.5 python test_tensor_sip.py
```

## Протоколы

### SIP (Signaling)

**Поддерживаемые методы:**
- `REGISTER` - регистрация на сервере
- `INVITE` - инициирование звонка
- `BYE` - завершение звонка
- `ACK` - подтверждение 200 OK

**Авторизация:**
- MD5 Digest (RFC 2617)
- Автоматическая обработка 401 Unauthorized

**Заголовки:**
- `Call-ID` - уникальный ID звонка
- `CSeq` - порядковый номер
- `Via` - с генерацией branch
- `From/To` - с тегами

### SDP (Media Negotiation)

**Формат:**
```
v=0
o=- <timestamp> <timestamp> IN IP4 <local_ip>
s=SimpleSIP
c=IN IP4 <local_ip>
t=0 0
m=audio <rtp_port> RTP/AVP 8
a=rtpmap:8 PCMA/8000
a=sendrecv
```

**Только PCMA (G.711 A-law):**
- Payload Type: 8
- Частота: 8000 Hz
- Битрейт: 64 kbps

### RTP (Media Transport)

**Заголовок (12 байт):**
```
Version: 2
Payload Type: 8 (PCMA)
Sequence: 0-65535 (инкремент +1)
Timestamp: 0-4294967295 (инкремент +160 для 20мс)
SSRC: случайный ID
```

**Тайминг:**
- Размер чанка: 160 байт (20мс при 8000 Hz)
- Задержка: 0.02 секунды между пакетами
- Автоматическое разбитие аудио на чанки

## Архитектура

```
┌─────────────────┐
│   SipClient     │
│  (SIP Signaling)│
└────────┬────────┘
         │
         ├─ REGISTER → 401 → REGISTER (auth) → 200 OK
         │
         └─ INVITE → 200 OK → ACK
                 │
                 ▼
            ┌─────────┐
            │  Call   │
            └────┬────┘
                 │
                 ├─ SDP negotiation
                 │
                 ▼
         ┌───────────────┐
         │ RtpTransport  │
         │ (UDP Socket)  │
         └───────┬───────┘
                 │
                 ├─ Audio chunks (160 bytes)
                 ├─ Timing (20ms delay)
                 └─ RTP headers (struct)
```

## Требования

- Python 3.9+
- Asterisk или другой SIP сервер
- (Опционально) CUDA для TTS
- (Опционально) RVC модели для voice conversion

## Ограничения

- Только исходящие звонки (входящие только логируются)
- Только PCMA кодек (G.711 A-law)
- Нет поддержки видео
- Нет поддержки DTMF
- Нет поддержки переадресации

## Troubleshooting

**Ошибка "Registration failed":**
- Проверьте SIP_USER и SIP_PASSWORD
- Проверьте SIP_SERVER (IP:порт)
- Проверьте LOCAL_IP

**Ошибка "Call failed to establish":**
- Проверьте TARGET_NUMBER
- Проверьте что сервер поддерживает PCMA
- Проверьте firewall (UDP 5060 для SIP, 10000-20000 для RTP)

**Нет звука:**
- Проверьте что аудио в формате PCMA
- Проверьте конвертацию PCM → PCMA: `audioop.lin2alaw(data, 2)`
- Проверьте размер чанков (160 байт)

## Лицензия

MIT License

## Автор

Created for Phone_Guy project - Pure Python SIP/RTP implementation
