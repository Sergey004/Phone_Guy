# Устаревшие компоненты бота

## Обзор

В результате реструктуризации проекта для решения критических проблем с PJSIP, следующие компоненты считаются **устаревшими** и не должны использоваться в новом коде. Они оставлены для обратной совместимости, но будут удалены в будущих версиях.

## Устаревшие файлы

### 📁 `bot/Libs/rtp_streamer.py`

**Статус:** ⚠️ **Полностью устарел**

**Причина:** Замен новым модулем `bot/Libs/audio/`

**Устаревшие классы:**
- `ByteStreamMediaPort` - Используйте `AudioPlaybackPort` из `bot/Libs/audio/audio_playback.py`
- `RtpStreamerMediaPort` - Используйте комбинацию `AudioCapturePort` и `AudioPlaybackPort`

**Дата устаревания:** 3 января 2026

**Планируемое удаление:** Версия 2.0

---

## Устаревшие классы и методы

### 📦 `ByteStreamMediaPort`

**Местоположение:** `bot/Libs/rtp_streamer.py`

**Заменен на:** `AudioPlaybackPort` из `bot/Libs/audio/audio_playback.py`

**Причина устаревания:**
- Отсутствие валидации аудио данных
- Нет обработки исключений в C++ обратных вызовах
- Нет форматной конвертации
- Отсутствие статистики

**Миграция:**
```python
# ❌ Старый код
from Libs.rtp_streamer import ByteStreamMediaPort
media_port = ByteStreamMediaPort(pcm_bytes=b'', sample_rate=8000)
media_port.register_with_conf(ep)
media_port.update_playback_data(new_pcm)

# ✅ Новый код
from Libs.audio import AudioPlaybackPort
playback = AudioPlaybackPort(pcm_bytes=b'', sample_rate=8000, logger=logger)
if not playback.register_with_conf(ep):
    logging.error("Failed to register playback port")
playback.update_playback_data(new_pcm, validate=True)
```

---

### 📦 `SttFeederMediaPort`

**Местоположение:** `bot/main.py`

**Заменен на:** `AudioCapturePort` из `bot/Libs/audio_capture_port.py`

**Причина устаревания:**
- Отсутствие форматной конвертации
- Нет обработки исключений
- Нет валидации кадров
- Нет статистики

**Миграция:**
```python
# ❌ Старый код (удален)
class SttFeederMediaPort(pj.AudioMediaPort):
    def putFrame(self, frame: pj.MediaFrame) -> int:
        try:
            samples = list(frame.buf) if hasattr(frame, "buf") else []
            if not samples:
                return pj.PJ_SUCCESS
            pcm = struct.pack("<" + "h" * len(samples), *samples)
            self.stt_adapter.enqueue_frame(pcm)
            return pj.PJ_SUCCESS
        except Exception as e:
            logging.error(f"Error in putFrame: {e}")
            return pj.PJ_EUNKNOWN

# ✅ Новый код
from Libs.audio import AudioCapturePort

capture = AudioCapturePort(sample_rate=8000, logger=logger)
capture.register_with_conf(ep)
audio_media.startTransmit(capture)

# В цикле обработки
frame = capture.get_frame(timeout=0.1)
if frame:
    stt_adapter.enqueue_frame(frame)
```

---

### 📦 `AudioMediaRecorder`

**Местоположение:** Использовался в `bot/main.py`

**Заменен на:** `AudioCapturePort` из `bot/Libs/audio_capture_port.py`

**Причина устаревания:**
- Неэффективная запись в файл
- Требует чтения из файла (file I/O)
- Условия гонки при одновременной записи/чтении
- Нет форматной конвертации

**Миграция:**
```python
# ❌ Старый код (удален)
recorder = pj.AudioMediaRecorder()
recorder.createRecorder(filename)
audio_media.startTransmit(recorder)

# Чтение из файла
with open(filename, "rb") as f:
    f.seek(pos)
    data = f.read(frame_len)
    stt_adapter.enqueue_frame(data)

# ✅ Новый код
from Libs.audio import AudioCapturePort

capture = AudioCapturePort(sample_rate=8000, logger=logger)
capture.register_with_conf(ep)
audio_media.startTransmit(capture)

# Получение кадров напрямую
frame = capture.get_frame(timeout=0.1)
if frame:
    stt_adapter.enqueue_frame(frame)
```

---

## Устаревшие методы в `bot/main.py`

### 🔧 `check_playback_done()`

**Класс:** `MyCall`

**Статус:** ❌ **Удален**

**Причина:** Больше не нужен - `AudioPlaybackPort` имеет встроенный метод `is_playback_done()`

**Миграция:**
```python
# ❌ Старый код (удален)
if self.media_port.is_playback_done():
    logging.info("Playback completed")

# ✅ Новый код
if self.playback_port.is_playback_done():
    logging.info("Playback completed")
```

---

### 🔧 `tail_recorder_file()`

**Класс:** `MyCall`

**Статус:** ❌ **Удален**

**Причина:** Заменен на `process_audio_capture()` с прямым захватом кадров

**Миграция:**
```python
# ❌ Старый код (удален)
async def tail_recorder_file(self, filename: str, sample_rate: int = 8000):
    pos = 44  # skip WAV header
    while not self._stop_tailer and self.isActive():
        with open(filename, "rb") as f:
            f.seek(pos)
            data = f.read(frame_len)
            self.stt_adapter.enqueue_frame(data)
        await asyncio.sleep(0.02)

# ✅ Новый код
async def process_audio_capture(self):
    while not self._stop_capture and self.isActive():
        if self.capture_port:
            frame = self.capture_port.get_frame(timeout=0.1)
            if frame:
                self.stt_adapter.enqueue_frame(frame)
        await asyncio.sleep(0.02)
```

---

## Устаревшие атрибуты в `MyCall`

### 📊 `self.media_port`

**Заменен на:** `self.playback_port`

**Причина:** Более понятное название, отражающее назначение

**Миграция:**
```python
# ❌ Старый код
self.media_port = ByteStreamMediaPort(pcm_bytes=b'', sample_rate=8000)
await self.tts_adapter.speak(llm_response, self.media_port)

# ✅ Новый код
self.playback_port = AudioPlaybackPort(pcm_bytes=b'', sample_rate=8000, logger=logger)
await self.tts_adapter.speak(llm_response, self.playback_port)
```

---

### 📊 `self.recorder`

**Заменен на:** `self.capture_port`

**Причина:** Более точное отражение функциональности

**Миграция:**
```python
# ❌ Старый код
self.recorder = pj.AudioMediaRecorder()
self.recorder.createRecorder(filename)
audio_media.startTransmit(self.recorder)

# ✅ Новый код
self.capture_port = AudioCapturePort(sample_rate=8000, logger=logger)
self.capture_port.register_with_conf(ep)
audio_media.startTransmit(self.capture_port)
```

---

### 📊 `self.recorder_filename`

**Заменен на:** Не требуется (прямой захват без файла)

**Причина:** Новая архитектура не использует файлы для записи

**Миграция:**
```python
# ❌ Старый код (удален)
self.recorder_filename = f"captured_audio_{int(time.time())}.wav"

# ✅ Новый код (удален)
# Прямой захват без файла - данные поступают через очередь
```

---

### 📊 `self._tail_task`

**Заменен на:** `self._capture_task`

**Причина:** Более точное название задачи

**Миграция:**
```python
# ❌ Старый код (удален)
self._tail_task = self.loop.create_task(self.tail_recorder_file(...))

# ✅ Новый код
self._capture_task = self.loop.create_task(self.process_audio_capture())
```

---

### 📊 `self._stop_tailer`

**Заменен на:** `self._stop_capture`

**Причина:** Более точное название флага

**Миграция:**
```python
# ❌ Старый код (удален)
self._stop_tailer = True
if self._tail_task:
    self._tail_task.cancel()
    self._tail_task = None

# ✅ Новый код
self._stop_capture = True
if self._capture_task:
    self._capture_task.cancel()
    self._capture_task = None
```

---

## Устаревшие импорты

### ❌ `from Libs.rtp_streamer import ByteStreamMediaPort`

**Заменен на:** `from Libs.audio import AudioPlaybackPort`

**Миграция:**
```python
# ❌ Старый код
from Libs.rtp_streamer import ByteStreamMediaPort
media_port = ByteStreamMediaPort(pcm_bytes=b'', sample_rate=8000)
media_port.register_with_conf(ep)
media_port.update_playback_data(new_pcm)

# ✅ Новый код
from Libs.audio import AudioPlaybackPort
playback = AudioPlaybackPort(pcm_bytes=b'', sample_rate=8000, logger=logger)
if not playback.register_with_conf(ep):
    logging.error("Failed to register playback port")
playback.update_playback_data(new_pcm, validate=True)
```

---

### ❌ `from Libs.rtp_streamer import RtpStreamerMediaPort`

**Заменен на:** `from Libs.audio import AudioCapturePort, AudioPlaybackPort`

**Миграция:**
```python
# ❌ Старый код (удален)
from Libs.rtp_streamer import RtpStreamerMediaPort
rtp_port = RtpStreamerMediaPort(compatible_file, clock_rate=8000)
rtp_port.createPlayer()
rtp_port.createRecorder("captured_audio.wav")
rtp_port.startTransmit(audio_media)
rtp_port.receiveFrom(audio_media)

# ✅ Новый код
from Libs.audio import AudioCapturePort, AudioPlaybackPort

# Для захвата
capture = AudioCapturePort(sample_rate=8000, logger=logger)
capture.register_with_conf(ep)
audio_media.startTransmit(capture)

# Для воспроизведения
playback = AudioPlaybackPort(pcm_bytes=b'', sample_rate=8000, logger=logger)
playback.register_with_conf(ep)
playback.startTransmit(audio_media)
```

---

## Рекомендации по миграции

### Шаг 1: Обновить импорты

Замените все импорты из `rtp_streamer` на импорты из `audio`:

```python
# Удалить
from Libs.rtp_streamer import ByteStreamMediaPort

# Добавить
from Libs.audio import AudioPlaybackPort
```

### Шаг 2: Заменить классы

Замените использование устаревших классов на новые:

```python
# ByteStreamMediaPort → AudioPlaybackPort
# SttFeederMediaPort → AudioCapturePort
# AudioMediaRecorder → AudioCapturePort
```

### Шаг 3: Обновить методы

Замените устаревшие методы на новые реализации:

```python
# check_playback_done() → playback_port.is_playback_done()
# tail_recorder_file() → process_audio_capture()
```

### Шаг 4: Обновить атрибуты

Замените устаревшие атрибуты на новые:

```python
# media_port → playback_port
# recorder → capture_port
# recorder_filename → (удален)
# _tail_task → _capture_task
# _stop_tailer → _stop_capture
```

---

## Сравнение функциональности

| Функция | Устаревший компонент | Новый компонент | Преимущества |
|---------|---------------------|----------------|-------------|
| Воспроизведение аудио | `ByteStreamMediaPort` | `AudioPlaybackPort` | Валидация, статистика, обработка ошибок |
| Захват аудио | `SttFeederMediaPort` | `AudioCapturePort` | Конвертация форматов, статистика |
| Запись аудио | `AudioMediaRecorder` | `AudioCapturePort` | Прямой захват, без файлов |

---

## План удаления

### Версия 1.1 (Текущая)
- ✅ Созданы новые компоненты в `bot/Libs/audio/`
- ✅ Обновлен `bot/main.py` для использования новых компонентов
- ✅ Обновлен `bot/Libs/tts_adapter.py` для использования `AudioPlaybackPort`
- ✅ Обновлены тестовые файлы
- ✅ Создана документация
- ℹ️ Устаревшие компоненты оставлены для совместимости

### Версия 2.0 (Планируется)
- ⏳ Удалить `bot/Libs/rtp_streamer.py`
- ⏳ Удалить `SttFeederMediaPort` из всех файлов
- ⏳ Удалить методы `check_playback_done()` и `tail_recorder_file()`
- ⏳ Удалить атрибуты `media_port`, `recorder`, `recorder_filename`, `_tail_task`, `_stop_tailer`
- ⏳ Обновить всю документацию

---

## Поддержка

Если вы все еще используете устаревшие компоненты:

1. **Внимательно изучите документацию:** `bot/Libs/audio/README.md`
2. **Используйте примеры миграции** из этого документа
3. **Протестируйте новые компоненты** перед удалением старых
4. **Обратитесь к `RESTRUCTURING_SUMMARY.md` для деталей архитектуры**
5. **Обратитесь к `DEPRECATED.md` для полного списка изменений**

---

## Часто задаваемые вопросы

### Q: Нужно ли мне немедленно заменять устаревшие компоненты?

**A:** Рекомендуется, но не обязательно. Устаревшие компоненты продолжат работать в версии 1.x, но не получат обновлений и будут удалены в версии 2.0. Если вы планируете использовать новые компоненты, сделайте это постепенно.

### Q: Могу ли я использовать и старые, и новые компоненты вместе?

**A:** Не рекомендуется. Смешивание старых и новых компонентов может привести к проблемам с производительностью и надежностью. Если вы все еще используете старые компоненты, смешивание может вызвать конфликты и нестабильность.

### Q: Что если у меня есть кастомный код, основанный на устаревших компонентах?

**A:** Вам нужно будет переписать его для использования новых компонентов. Обратитесь к разделу "Рекомендации по миграции" в `DEPRECATED.md` для пошагового руководства.

### Q: Будут ли новые компоненты работать с моим существующим кодом?

**A:** Новые компоненты имеют совместимый API для основных функций, но предоставляют дополнительные возможности. Вам может потребоваться минимальная адаптация кода для использования новых возможностей (валидация, статистика, форматная конвертация).

---

**Дата создания:** 3 января 2026  
**Версия:** 1.0  
**Статус:** Активно
