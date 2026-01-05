# VoIP Library

SIP/VoIP клиентская библиотека на базе PJSUA2.

## Обзор

Эта библиотека предоставляет простой и модульный интерфейс для работы с SIP/VoIP функциональностью в Python с использованием PJSUA2.

## Компоненты

### VoIPClient

Основной класс для управления PJSIP клиентом.

**Функции:**
- Инициализация PJSIP endpoint
- Настройка транспорта (UDP)
- Конфигурация кодеков (PCMA/PCMU)
- Создание и регистрация SIP аккаунтов
- Совершение исходящих звонков
- Управление жизненным циклом

**Пример использования:**
```python
from Libs.voip import VoIPClient

config = {
    'sip': {
        'domain': '192.168.1.176',
        'username': '555533',
        'password': 'password',
        'local_addr': '192.168.1.181',
        'local_port': 5060
    }
}

client = VoIPClient(config, logger)
client.initialize()
client.start()
```

### VoIPAccount

Наследуется от `pj.Account`, обрабатывает регистрацию и входящие звонки.

**Функции:**
- Автоматическая регистрация на SIP сервере
- Обработка входящих звонков
- Кастомные обработчики входящих звонков
- Управление текущим звонком

**Пример использования:**
```python
from Libs.voip import VoIPAccount

class MyAccount(VoIPAccount):
    def __init__(self, ep, **kwargs):
        super().__init__(ep, call_class=MyCall, **kwargs)
    
    def onRegState(self, prm):
        info = self.getInfo()
        print(f"Registration: {info.regIsActive}")
```

### VoIPCall

Наследуется от `pj.Call`, обрабатывает состояние звонка и медиа.

**Функции:**
- Отслеживание состояния звонка
- Настройка аудио медиа
- Воспроизведение аудио файлов
- Запись аудио
- Планирование автоматического завершения
- Кастомные обработчики изменений состояния

**Пример использования:**
```python
from Libs.voip import VoIPCall

class MyCall(VoIPCall):
    def __init__(self, acc, call_id, **kwargs):
        super().__init__(acc, call_id, **kwargs)
    
    def _setup_audio_media(self, media_info):
        audio_media = self.getAudioMedia(media_info.index)
        # Настройка аудио
        
    def play_audio_file(self, file_path, audio_media):
        # Воспроизведение файла
```

## Полный пример

### Простой SIP клиент с воспроизведением аудио

```python
#!/usr/bin/env python3
import sys
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall
import logging

logging.basicConfig(level=logging.INFO)

class MyCall(VoIPCall):
    def __init__(self, acc, call_id, wav_file="output.wav", **kwargs):
        super().__init__(acc, call_id, **kwargs)
        self.wav_file = wav_file
    
    def _setup_audio_media(self, media_info):
        audio_media = self.getAudioMedia(media_info.index)
        self.play_audio_file(self.wav_file, audio_media)
        
        # Планируем завершение через 10 секунд
        self.schedule_hangup(10.0)

class MyAccount(VoIPAccount):
    def __init__(self, ep, wav_file="output.wav", **kwargs):
        super().__init__(ep, call_class=MyCall, **kwargs)
        self.wav_file = wav_file

def main():
    config = {
        'sip': {
            'domain': '192.168.1.176',
            'username': '555533',
            'password': 'password',
            'local_addr': '192.168.1.181',
            'local_port': 5060
        }
    }
    
    client = VoIPClient(config, logging.getLogger("VoIPClient"))
    client.initialize()
    client.start()
    
    client.create_account(MyAccount, wav_file="output.wav")
    
    # Главный цикл
    import time
    try:
        while True:
            time.sleep(0.1)
            account = client.get_account()
            if account:
                call = account.get_current_call()
                if call:
                    call.process_hangup_queue()
    except KeyboardInterrupt:
        client.destroy()

if __name__ == "__main__":
    main()
```

## Конфигурация

### SIP настройки

```python
config = {
    'sip': {
        'domain': '192.168.1.176',      # SIP домен
        'username': '555533',            # SIP пользователь
        'password': 'password',          # Пароль
        'local_addr': '192.168.1.181',   # Локальный IP адрес
        'local_port': 5060               # Локальный порт
    }
}
```

### Аудио настройки

По умолчанию:
- Частота дискретизации: 8000 Hz
- Каналы: 1 (моно)
- Размер фрейма: 20 ms
- Кодеки: PCMA (255), PCMU (254)

## Преимущества

### Модульность
- Разделение на независимые компоненты
- Легкое наследование и расширение
- Переиспользование кода

### Безопасность
- Безопасная обработка потоков PJSIP
- Graceful cleanup ресурсов
- Обработка ошибок

### Гибкость
- Кастомные обработчики событий
- Расширяемая архитектура
- Поддержка различных сценариев использования

## Интеграция с существующим кодом

### bot/main.py
```python
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall

# Замена VoIPBot на VoIPClient
bot = VoIPClient(config, logger)
bot.initialize()
bot.start()
bot.create_account(MyAccount, stt_adapter=stt, tts_adapter=tts)
```

### bot/Test_RTP/Test_RTP.py
```python
from Libs.voip import VoIPClient, VoIPAccount, VoIPCall

# Использование библиотеки вместо прямого PJSIP
bot = VoIPClient(config, logger)
bot.initialize()
bot.start()
bot.create_account(TestAccount, wav_file=wav_file)
```

## Миграция со старого кода

### Было (прямой PJSIP):
```python
class VoIPBot:
    def __init__(self, config):
        self.ep = pj.Endpoint()
        self.ep.libCreate()
        self.ep.libInit(ep_cfg)
        self.ep.libStart()
        # ... много кода
```

### Стало (VoIP библиотека):
```python
from Libs.voip import VoIPClient

bot = VoIPClient(config, logger)
bot.initialize()
bot.start()
```

## Примечания

- PJSIP требует регистрации потоков для вызова функций из других потоков
- Библиотека автоматически обрабатывает это через очереди
- Все операции с медиа должны выполняться в главном потоке PJSIP
- Таймеры используют очереди для безопасного завершения звонков

## Требования

- Python 3.7+
- PJSUA2 (pjsua2)
- Логирование (logging)

## Лицензия

Часть проекта Phone_Guy
