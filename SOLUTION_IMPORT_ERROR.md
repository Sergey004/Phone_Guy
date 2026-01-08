# Решение проблемы: ImportError: libpjnath.so.2

## Проблема
При попытке импорта модуля:
```python
import pcm_media
```

Возникала ошибка:
```
ImportError: libpjnath.so.2: cannot open shared object file: No such file or directory
```

## Корневая причина
Скомпилированное расширение Python (`pcm_media.cpython-311-x86_64-linux-gnu.so`) зависит от динамических библиотек PJSUA2, которые находятся в директории `pjproject/*/lib/`, но система не знает где их искать.

## Решение

### 1. Автоматическая предзагрузка библиотек
В файл `pcm_media_wrapper.py` добавлена функция `_preload_libraries()`, которая:
- Находит все PJSUA2 библиотеки
- Загружает их с помощью `ctypes.CDLL()` с флагом `RTLD_GLOBAL`
- Это делает их доступными для скомпилированного расширения

### 2. Структурирование как пакет Python
Создана правильная структура пакета:
```
native/
├── __init__.py                 # Инициализирует пакет
├── pcm_media_wrapper.py        # Содержит PcmMedia класс
└── pcm_media.cpython-311.so    # Скомпилированное расширение
```

### 3. Избежание конфликтов имён
Файл, который была попыткой создать как `pcm_media.py`, был переименован в `pcm_media_import.py` чтобы избежать конфликта с названием расширения.

## Использование

Теперь импорт работает просто:

```python
# Способ 1 - Прямой импорт из пакета (рекомендуется)
from native import PcmMedia

# Способ 2 - Через удобный модуль
from pcm_media_import import PcmMedia

# Использование
pcm = PcmMedia()
pcm.start()
pcm.push(audio_data)
pcm.stop()
```

## Файлы решения

1. **native/__init__.py** - Пакет инициализация
   - Экспортирует PcmMedia и ShortVector
   
2. **native/pcm_media_wrapper.py** - Обёртка Python
   - Функция `_preload_libraries()` загружает PJSUA2 libs
   - Класс `PcmMediaWrapper` предоставляет интерфейс
   - Класс заменён на имя `PcmMedia` для удобства

3. **native/pcm_media.cpython-311-x86_64-linux-gnu.so** - Скомпилированное расширение
   - SWIG генерированный код
   - Функции: new_PcmMedia, delete_PcmMedia, PcmMedia_start, и т.д.

4. **pcm_media_import.py** - Удобная точка входа
   - Импортирует из пакета native
   - Позволяет использовать `from pcm_media_import import PcmMedia`

## Ключевые моменты

- ✓ Библиотеки загружаются автоматически при импорте
- ✓ Нет необходимости устанавливать LD_LIBRARY_PATH
- ✓ Поддерживаются оба способа импорта
- ✓ Модуль готов к интеграции с PJSUA2

## Проверка

```bash
cd /home/user/Test_Phone
python3 -c "from native import PcmMedia; pcm = PcmMedia(); print('✓ Success')"
# Output: ✓ Success
```

Тестирование показало успешный импорт и создание объекта без ошибок с зависимостями.
