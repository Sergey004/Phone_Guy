# PcmMedia C++ Extension Module

## Описание

`PcmMedia` - это C++ расширение для Python, которое обеспечивает интеграцию с PJSUA2 библиотекой для работы с аудио в VoIP приложениях.

## Установка

Модуль уже скомпилирован и готов к использованию. Проверьте наличие следующих файлов:

- `native/pcm_media.cpython-311-x86_64-linux-gnu.so` - скомпилированное расширение
- `native/pcm_media_wrapper.py` - Python обёртка
- `native/__init__.py` - инициализатор пакета

## Использование

### Способ 1: Прямой импорт из пакета (рекомендуется)

```python
from native import PcmMedia

# Создание экземпляра
pcm = PcmMedia(clockRate=16000, channelCount=1, samplesPerFrame=160)

# Управление аудио
pcm.start()
pcm.stop()

# Отправка PCM семплов
pcm.push(audio_samples)
```

### Способ 2: Через удобный импорт

```python
from pcm_media_import import PcmMedia

pcm = PcmMedia()
```

## Параметры конструктора

- `clockRate` (int, default=16000): Частота дискретизации в Гц
- `channelCount` (int, default=1): Количество каналов (1 для моно)
- `samplesPerFrame` (int, default=160): Семплов на кадр

## Методы

### `__init__(clockRate=16000, channelCount=1, samplesPerFrame=160)`
Инициализирует объект PcmMedia

### `initialize()`
Инициализирует аудиопорт (требует инициализированного Endpoint)

### `start()`
Начинает обработку аудио

### `stop()`
Останавливает обработку аудио

### `push(samples: bytes | bytearray | array.array)`
Отправляет PCM аудиосемплы

## Обработка зависимостей

Модуль автоматически загружает необходимые PJSUA2 библиотеки из директории `pjproject/*/lib/`.

При импорте модуля происходит предварительная загрузка следующих библиотек:
- libpj.so.2
- libpjlib-util.so.2
- libpjnath.so.2
- libpjmedia.so.2
- libpjmedia-codec.so.2
- libpjmedia-audiodev.so.2

## Пример использования

```python
from native import PcmMedia
import array

# Создание экземпляра с параметрами
pcm = PcmMedia(clockRate=16000, channelCount=1, samplesPerFrame=160)

# Генерация тестового сигнала (1000 Hz тон, 1 сек)
sample_rate = 16000
frequency = 1000
duration = 1
samples = []

import math
for i in range(sample_rate * duration):
    sample = int(32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
    samples.append(sample)

# Создание массива int16
audio = array.array('h', samples)

# Отправка аудио
pcm.push(audio)
```

## Компиляция (для разработчиков)

Если нужна пересборка:

```bash
cd native
python setup.py build_ext --inplace
```

## Системные требования

- Python 3.11+
- PJSUA2 2.16 (уже включена в pjproject/)
- GCC/G++ с поддержкой C++17

## Решение проблем

### ImportError: libpjnath.so.2: cannot open shared object file

Это решается автоматически через функцию `_preload_libraries()` в `pcm_media_wrapper.py`.

Если всё ещё происходит ошибка, установите `LD_LIBRARY_PATH`:

```bash
export LD_LIBRARY_PATH=/home/user/Test_Phone/pjproject/pjlib/lib:/home/user/Test_Phone/pjproject/pjmedia/lib:/home/user/Test_Phone/pjproject/pjsip/lib:/home/user/Test_Phone/pjproject/pjnath/lib:/home/user/Test_Phone/pjproject/pjlib-util/lib
```

### AttributeError: module 'pcm_media' has no attribute 'new_PcmMedia'

Убедитесь, что импортируете из пакета `native`, а не из файла `pcm_media.py`:

```python
# ✓ Правильно
from native import PcmMedia

# ✗ Неправильно
import pcm_media
```

## Файлы проекта

```
Test_Phone/
├── native/
│   ├── __init__.py                              # Инициализатор пакета
│   ├── pcm_media.cpython-311-x86_64-linux-gnu.so  # Скомпилированное расширение
│   ├── pcm_media_wrapper.py                    # Python обёртка с управлением библиотеками
│   ├── pcm_media.hpp                           # C++ заголовок
│   ├── pcm_media.cpp                           # C++ реализация
│   ├── bindings.i                              # SWIG интерфейс
│   ├── setup.py                                # Скрипт сборки
│   └── bindings_wrap.cpp                       # SWIG сгенерированный код
├── pcm_media_import.py                         # Удобный точка входа для импорта
├── pjproject/                                  # PJSUA2 библиотеки
└── README_PCMMEDIA.md                          # Этот файл
```

## Лицензия

Проект использует PJSUA2 (GPL/Commercial) и SWIG для binding.
