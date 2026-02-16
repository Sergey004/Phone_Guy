#!/usr/bin/env python3
"""
Конвертация аудио файла в формат SIP/RTP (8000 Hz, Mono, 16-bit PCM)
"""

import wave
import numpy as np
import sys
import os

def convert_audio(input_file, output_file=None, target_sample_rate=8000):
    """
    Конвертирует аудио файл в формат SIP/RTP
    
    Args:
        input_file: путь к входному файлу
        output_file: путь к выходному файлу (если None, то input_file + '_converted.wav')
        target_sample_rate: целевая частота дискретизации (по умолчанию 8000 Hz)
    """
    if output_file is None:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_converted{ext}"
    
    print(f"[Convert] Чтение файла: {input_file}")
    
    # Читаем исходный файл
    with wave.open(input_file, 'rb') as wf_in:
        n_channels = wf_in.getnchannels()
        sample_width = wf_in.getsampwidth()
        sample_rate = wf_in.getframerate()
        n_frames = wf_in.getnframes()
        
        print(f"[Convert] Исходный формат: {n_channels} каналов, {sample_rate} Hz, {sample_width*8}-bit")
        print(f"[Convert] Длительность: {n_frames / sample_rate:.2f} сек")
        
        # Читаем PCM данные
        frames = wf_in.readframes(n_frames)
        
    # Конвертируем в numpy array
    dtype = np.int16 if sample_width == 2 else np.int8
    audio_data = np.frombuffer(frames, dtype=dtype)
    
    # Если стерео, конвертируем в моно (усреднение каналов)
    if n_channels == 2:
        print("[Convert] Конвертация стерео в моно...")
        audio_data = audio_data.reshape(-1, 2)
        audio_data = audio_data.mean(axis=1).astype(dtype)
    
    # Ресемплинг до целевой частоты
    if sample_rate != target_sample_rate:
        print(f"[Convert] Ресемплинг с {sample_rate} Hz до {target_sample_rate} Hz...")
        # Используем простой линейный интерполяционный ресемплинг
        indices = np.linspace(0, len(audio_data) - 1, int(len(audio_data) * target_sample_rate / sample_rate))
        audio_data = np.interp(indices, np.arange(len(audio_data)), audio_data).astype(dtype)
    
    # Записываем в новый файл
    with wave.open(output_file, 'wb') as wf_out:
        wf_out.setnchannels(1)  # Моно
        wf_out.setsampwidth(2)  # 16-bit
        wf_out.setframerate(target_sample_rate)  # 8000 Hz
        wf_out.writeframes(audio_data.tobytes())
    
    print(f"[Convert] Файл сохранен: {output_file}")
    print(f"[Convert] Итоговый формат: 1 канал, {target_sample_rate} Hz, 16-bit")
    
    return output_file

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python convert_audio.py <input_file> [output_file]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    convert_audio(input_file, output_file)