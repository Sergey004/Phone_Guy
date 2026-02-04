#!/usr/bin/env python3
"""Тестовый скрипт для проверки индексации документов"""

import os
import sys
from dotenv import load_dotenv

# Добавляем new_voip в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'new_voip'))

load_dotenv()

print("=" * 60)
print("ТЕСТ ИНДЕКСАЦИИ ДОКУМЕНТОВ RAG")
print("=" * 60)

# Проверяем наличие API ключа
if not os.getenv("NVIDIA_API_KEY"):
    print("❌ ОШИБКА: NVIDIA_API_KEY не найден в .env файле")
    sys.exit(1)

print("✅ NVIDIA_API_KEY найден")
print()

# Импортируем и инициализируем DocumentProcessor
try:
    from document_processor import DocumentProcessor
    
    print("📚 Инициализация DocumentProcessor...")
    processor = DocumentProcessor()
    
    if processor.vector_store is None:
        print("❌ ОШИБКА: Vector store не инициализирован")
        sys.exit(1)
    
    print("✅ Vector store инициализирован")
    print()
    
    # Проверяем папку с документами
    print(f"📁 Папка с документами: {processor.doc_path}")
    if os.path.exists(processor.doc_path):
        files = os.listdir(processor.doc_path)
        print(f"📄 Найдено файлов: {len(files)}")
        for f in files:
            print(f"   - {f}")
    else:
        print("❌ Папка не существует")
        sys.exit(1)
    
    print()
    print("=" * 60)
    print("ЗАПУСК ИНДЕКСАЦИИ")
    print("=" * 60)
    print()
    
    # Запускаем индексацию
    processor.index_documents()
    
    print()
    print("=" * 60)
    print("ТЕСТ ПОИСКА")
    print("=" * 60)
    print()
    
    # Тестируем поиск
    test_queries = [
        "Фредди Фазбер",
        "хронология событий",
        "аниматроники"
    ]
    
    for query in test_queries:
        print(f"🔍 Запрос: '{query}'")
        result = processor.retrieve_documents(query, k=2)
        if result:
            print(f"✅ Найдено результатов (первые 200 символов):")
            print(f"   {result[:200]}...")
        else:
            print("❌ Ничего не найдено")
        print()
    
    print("=" * 60)
    print("✅ ТЕСТ ЗАВЕРШЁН")
    print("=" * 60)
    
except Exception as e:
    print(f"❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)