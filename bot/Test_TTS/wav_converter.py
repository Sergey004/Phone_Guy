#!/usr/bin/env python3
"""
Класс для автоматической конвертации WAV файлов в формат PJSUA2
"""
import wave
import logging
import numpy as np
from scipy.io import wavfile
from scipy import signal

logger = logging.getLogger(__name__)


class WavConverter:
    """
    Конвертер WAV файлов для PJSUA2
    Автоматически конвертирует любой WAV в формат:
    - PCM 16-bit
    - Mono
    - 8kHz или 16kHz
    """
    
    def __init__(self, target_rate=8000):
        """
        Args:
            target_rate: целевая частота (8000 или 16000 Hz)
        """
        if target_rate not in [8000, 16000]:
            logger.warning(f"Unusual sample rate {target_rate}, recommended 8000 or 16000")
        self.target_rate = target_rate
    
    def convert(self, input_file, output_file=None):
        """
        Конвертирует WAV файл в формат PJSUA2
        
        Args:
            input_file: путь к исходному файлу
            output_file: путь к выходному файлу (если None, будет input_pjsua.wav)
        
        Returns:
            str: путь к выходному файлу
        
        Raises:
            Exception: если конвертация не удалась
        """
        if output_file is None:
            output_file = input_file.rsplit('.', 1)[0] + '_pjsua.wav'
        
        logger.info(f"Converting {input_file} -> {output_file}")
        
        try:
            # Читаем файл
            samplerate, data = wavfile.read(input_file)
            logger.debug(f"Original: {samplerate}Hz, {data.dtype}, shape={data.shape}")
            
            # Конвертируем в mono
            if len(data.shape) > 1 and data.shape[1] > 1:
                logger.debug("Converting stereo to mono")
                data = data.mean(axis=1)
            
            # Конвертируем в int16
            if data.dtype == np.float32 or data.dtype == np.float64:
                logger.debug("Converting float to int16")
                data = np.clip(data, -1.0, 1.0)
                data = (data * 32767).astype(np.int16)
            elif data.dtype != np.int16:
                logger.debug(f"Converting {data.dtype} to int16")
                # Для uint8 и других
                if data.dtype == np.uint8:
                    data = ((data.astype(np.int32) - 128) * 256).astype(np.int16)
                else:
                    data = data.astype(np.int16)
            
            # Ресемплинг
            if samplerate != self.target_rate:
                logger.debug(f"Resampling {samplerate}Hz -> {self.target_rate}Hz")
                num_samples = int(len(data) * self.target_rate / samplerate)
                data = signal.resample(data, num_samples).astype(np.int16)
                samplerate = self.target_rate
            
            # Сохраняем
            with wave.open(output_file, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(samplerate)
                wf.writeframes(data.tobytes())
            
            logger.info(f"Converted: {len(data)} samples, {len(data)/samplerate:.2f}s")
            return output_file
            
        except Exception as e:
            logger.error(f"Conversion failed: {e}")
            raise
    
    def is_compatible(self, filename):
        """
        Проверяет, совместим ли файл с PJSUA2
        
        Returns:
            bool: True если файл уже в правильном формате
        """
        try:
            with wave.open(filename, 'rb') as wf:
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                comptype = wf.getcomptype()
                
                return (
                    channels == 1 and
                    sampwidth == 2 and
                    framerate in [8000, 16000] and
                    comptype == 'NONE'
                )
        except:
            return False
    
    def auto_convert(self, filename):
        """
        Автоматически конвертирует файл если нужно
        
        Args:
            filename: путь к файлу
        
        Returns:
            str: путь к совместимому файлу (может быть тот же самый)
        """
        if self.is_compatible(filename):
            logger.info(f"{filename} already compatible")
            return filename
        
        logger.info(f"{filename} needs conversion")
        output = self.convert(filename)
        return output


# Удобная функция для быстрого использования
def ensure_pjsua_compatible(filename, target_rate=8000):
    """
    Убеждается что файл совместим с PJSUA2, конвертирует если нужно
    
    Args:
        filename: путь к WAV файлу
        target_rate: целевая частота (8000 или 16000)
    
    Returns:
        str: путь к совместимому файлу
    """
    converter = WavConverter(target_rate)
    return converter.auto_convert(filename)


# Пример использования
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python wav_converter.py <input.wav> [output.wav] [sample_rate]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    sample_rate = int(sys.argv[3]) if len(sys.argv) > 3 else 8000
    
    converter = WavConverter(sample_rate)
    result = converter.auto_convert(input_file)
    print(f"Result: {result}")