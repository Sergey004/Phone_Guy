"""Convenient import for PcmMedia - automatically handles library paths"""

from native.pcm_media_wrapper import PcmMedia, ShortVector

__all__ = ['PcmMedia', 'ShortVector']

if __name__ == '__main__':
    # Simple test
    pcm = PcmMedia()
    print(f"✓ PcmMedia loaded: {pcm}")
