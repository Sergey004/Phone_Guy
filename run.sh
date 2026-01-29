#!/bin/bash

# Скрипт для запуска Phone Guy бота с правильным виртуальным окружением

echo "🚀 Starting Phone Guy Bot..."
echo ""

# Активируем виртуальное окружение
source /home/user/Test_Phone_new/.venv/bin/activate

# Проверяем, что окружение активировано
if [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ ERROR: Failed to activate virtual environment"
    exit 1
fi

echo "✓ Virtual environment activated: $VIRTUAL_ENV"
echo "✓ Python: $(which python)"
echo ""

# Запускаем приложение
python new_voip/main_integration.py