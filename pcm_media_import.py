"""Convenient import for PcmMedia - automatically handles library paths

Usage:
    from pcm_media_import import PcmMedia
    pcm = PcmMedia()
"""

from native import PcmMedia, ShortVector

__all__ = ['PcmMedia', 'ShortVector']

if __name__ == '__main__':
    # Simple test
    pcm = PcmMedia()
    print(f"✓ PcmMedia loaded: {pcm}")
