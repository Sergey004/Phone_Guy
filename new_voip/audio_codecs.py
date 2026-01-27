import numpy as np

class AudioCodec:
    """
    Утилиты для конвертации NumPy Audio (Float32) -> G.711 A-Law (Bytes).
    """
    
    @staticmethod
    def float_to_pcm16(audio_data: np.ndarray) -> np.ndarray:
        """Конвертирует float32 [-1.0, 1.0] в int16."""
        # Клиппинг, чтобы не было треска при перегрузке
        audio_data = np.clip(audio_data, -1.0, 1.0)
        # Преобразование в 16-бит
        return (audio_data * 32767).astype(np.int16)

    @staticmethod
    def pcm16_to_alaw(pcm_data: np.ndarray) -> bytes:
        """
        Конвертация int16 -> A-Law байты. 
        Используем встроенный модуль audioop для точного преобразования.
        """
        import audioop
        # audioop требует bytes, а не ndarray
        raw_bytes = pcm_data.tobytes()
        # A-law (G.711) - width=1 для 8-bit A-law
        return audioop.lin2alaw(raw_bytes, 1)

    @staticmethod
    def create_silence(duration_ms=20, sample_rate=8000) -> bytes:
        """Генерирует тишину в формате A-Law (0xD5)"""
        samples = int(sample_rate * (duration_ms / 1000))
        return b'\xd5' * samples

    @staticmethod
    def mix_sources(source_a: np.ndarray, source_b: np.ndarray, vol_a=1.0, vol_b=1.0) -> np.ndarray:
        """Смешивает два сигнала с учетом громкости."""
        # Приводим к одной длине (обрезаем по короткому или паддим - здесь обрежем)
        min_len = min(len(source_a), len(source_b))
        mixed = (source_a[:min_len] * vol_a) + (source_b[:min_len] * vol_b)
        return np.clip(mixed, -1.0, 1.0)