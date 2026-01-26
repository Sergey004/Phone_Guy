#!/usr/bin/env python3
"""
example_device_audio.py - Physical Audio Device Example

Demonstrates using microphone and speaker with pjsip_python.

Requirements:
    pip install sounddevice

Usage:
    python3 example_device_audio.py --list-devices
    python3 example_device_audio.py --demo-tone
    python3 example_device_audio.py --demo-capture
    python3 example_device_audio.py --demo-loopback
"""

import sys
import argparse
import time
import asyncio
import numpy as np

sys.path.insert(0, '/home/user/Test_Phone_new')

from pjsip_python.audio import (
    numpy_to_audio, create_tone, create_silence,
    AudioData, AudioFormat
)

try:
    from pjsip_python.audio.device import (
        list_devices, get_default_devices, check_audio_devices,
        AudioCapture, AudioPlayback, FullDuplexStream
    )
    DEVICE_AVAILABLE = True
except ImportError:
    DEVICE_AVAILABLE = False
    print("ERROR: sounddevice not installed. Run: pip install sounddevice")
    sys.exit(1)


def cmd_list_devices():
    """List all available audio devices."""
    print("\n=== Audio Devices ===\n")

    status = check_audio_devices()
    if not status.get('available'):
        print(f"Error: {status.get('error', 'Unknown error')}")
        return 1

    devices = list_devices()
    defaults = get_default_devices()

    print(f"Input devices:  {status['input_devices']}")
    print(f"Output devices: {status['output_devices']}\n")

    print("Default Input: ", defaults['input'].name if defaults['input'] else "None")
    print("Default Output:", defaults['output'].name if defaults['output'] else "None")
    print()

    print("All Devices:")
    print("-" * 70)
    for dev in devices:
        dev_type = {
            AudioDeviceType.INPUT: "INPUT",
            AudioDeviceType.OUTPUT: "OUTPUT",
            AudioDeviceType.FULL_DUPLEX: "DUPLEX"
        }.get(dev.device_type, "UNKNOWN")

        print(f"  [{dev.index:2d}] {dev.name[:40]:<40}")
        print(f"       Type: {dev_type}, In: {dev.max_input_channels}, Out: {dev.max_output_channels}")
        print(f"       Default SR: {dev.default_sample_rate:.0f} Hz")
        print()

    return 0


def cmd_demo_tone():
    """Play a test tone to the default speaker."""
    print("\n=== Demo: Play Test Tone ===\n")

    defaults = get_default_devices()
    if not defaults['output']:
        print("Error: No default output device found")
        return 1

    print(f"Using output device: {defaults['output'].name}")
    print("Playing 440Hz tone for 2 seconds...")

    tone = create_tone(frequency=440, duration=2.0, amplitude=0.3)
    print(f"  Sample rate: {tone.sample_rate} Hz")
    print(f"  Duration: {tone.duration:.2f} seconds")
    print(f"  Samples: {tone.num_samples}")

    with AudioPlayback() as playback:
        playback.write(tone)
        print("\nPlaying...")
        time.sleep(0.5)
        playback.drain()
        print("Done!\n")

    return 0


def cmd_demo_capture():
    """Capture audio from microphone."""
    print("\n=== Demo: Capture Audio ===\n")

    defaults = get_default_devices()
    if not defaults['input']:
        print("Error: No default input device found")
        return 1

    print(f"Using input device: {defaults['input'].name}")
    print("Recording for 3 seconds...")

    with AudioCapture() as capture:
        audio_chunks = []
        end_time = time.time() + 3.0

        while time.time() < end_time:
            chunk = capture.read()
            audio_chunks.append(chunk.to_numpy())
            print(f"  Captured {len(chunk)} samples", end='\r')
            time.sleep(0.02)

        print("\nRecording complete!")

    all_audio = np.concatenate(audio_chunks)
    audio = numpy_to_audio(all_audio, sample_rate=8000, channels=1)

    print(f"  Total samples: {audio.num_samples}")
    print(f"  Duration: {audio.duration:.2f} seconds")

    from pjsip_python.audio import write_wav
    output_file = '/tmp/captured_audio.wav'
    write_wav(output_file, audio)
    print(f"  Saved to: {output_file}\n")

    return 0


def cmd_demo_loopback():
    """Echo captured audio back to output (loopback test)."""
    print("\n=== Demo: Loopback Test ===\n")
    print("Capturing from microphone and playing to speaker.")
    print("Speak into your microphone - you should hear yourself!")
    print("Press Ctrl+C to stop.\n")

    defaults = get_default_devices()

    if defaults['input'] and defaults['output']:
        print(f"Input:  {defaults['input'].name}")
        print(f"Output: {defaults['output'].name}\n")
    else:
        print("Error: Need both input and output devices for loopback")
        return 1

    with AudioCapture() as capture, AudioPlayback() as playback:
        print("Listening... (Ctrl+C to stop)")
        try:
            while True:
                chunk = capture.read()
                playback.write(chunk)
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("\n\nStopped by user.")

    print("\nLoopback test complete.\n")
    return 0


def cmd_demo_full_duplex():
    """Full-duplex stream with custom processing."""
    print("\n=== Demo: Full-Duplex Stream ===\n")
    print("Full-duplex audio with volume normalization.")
    print("Press Ctrl+C to stop.\n")

    class ProcessedStream(FullDuplexStream):
        def _process(self, input_data: np.ndarray, output_data: np.ndarray) -> None:
            normalized = input_data * 0.5
            output_data[:] = normalized

    try:
        with ProcessedStream() as stream:
            print("Stream active. Speak now! (Ctrl+C to stop)")
            try:
                while True:
                    audio = stream.read()
                    stream.write(create_silence(0.02))
                    time.sleep(0.01)
            except KeyboardInterrupt:
                print("\n\nStopped by user.")
    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure you have a full-duplex audio device.")
        return 1

    print("\nFull-duplex test complete.\n")
    return 0


async def cmd_demo_call_sim():
    """Simulate a VoIP call with device audio."""
    print("\n=== Demo: Simulated VoIP Call ===\n")
    print("Simulating call audio flow:")
    print("  1. Capture from mic")
    print("  2. Convert to G.711")
    print("  3. (Simulated network transmission)")
    print("  4. Convert from G.711")
    print("  5. Play to speaker")
    print()

    print("Recording 5 seconds of call audio...")

    with AudioCapture() as capture:
        audio_chunks = []
        end_time = time.time() + 5.0

        while time.time() < end_time:
            chunk = capture.read()
            audio_chunks.append(chunk.to_numpy())
            print(f"  Progress: {int((5.0 - (end_time - time.time())))}s remaining", end='\r')
            time.sleep(0.02)

    print("\nProcessing audio...")

    all_audio = np.concatenate(audio_chunks)
    audio = numpy_to_audio(all_audio, sample_rate=8000, channels=1)

    g711_data = audio.to_bytes(AudioFormat.G711_ALAW)
    print(f"  Original size: {audio.num_samples * 2} bytes")
    print(f"  G.711 size:    {len(g711_data)} bytes")
    print(f"  Compression:   {100 - (len(g711_data) * 100 / (audio.num_samples * 2)):.1f}%")

    from pjsip_python.audio import AudioData
    received = AudioData(g711_data, sample_rate=8000, channels=1, format=AudioFormat.G711_ALAW)
    pcm_data = received.to_numpy()

    print(f"\nPlayback decoded audio ({len(pcm_data)} samples)...")

    with AudioPlayback() as playback:
        decoded_audio = numpy_to_audio(pcm_data, sample_rate=8000, channels=1)
        playback.write(decoded_audio)
        time.sleep(0.5)
        playback.drain()

    print("\nSimulated call complete!\n")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Physical Audio Device Example',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --list-devices      List all audio devices
    %(prog)s --demo-tone         Play a test tone
    %(prog)s --demo-capture      Record from microphone
    %(prog)s --demo-loopback     Loopback test (mic -> speaker)
    %(prog)s --demo-duplex       Full-duplex with processing
    %(prog)s --demo-call-sim     Simulate VoIP call audio flow
        """
    )

    parser.add_argument('--list-devices', action='store_true',
                        help='List available audio devices')
    parser.add_argument('--demo-tone', action='store_true',
                        help='Play a test tone')
    parser.add_argument('--demo-capture', action='store_true',
                        help='Capture audio from microphone')
    parser.add_argument('--demo-loopback', action='store_true',
                        help='Loopback test (mic -> speaker)')
    parser.add_argument('--demo-duplex', action='store_true',
                        help='Full-duplex stream with processing')
    parser.add_argument('--demo-call-sim', action='store_true',
                        help='Simulate VoIP call audio flow')

    args = parser.parse_args()

    if not any([args.list_devices, args.demo_tone, args.demo_capture,
                args.demo_loopback, args.demo_duplex, args.demo_call_sim]):
        parser.print_help()
        print("\n" + "=" * 50)
        print("No demo selected. Running device check...")
        print("=" * 50 + "\n")

        status = check_audio_devices()
        if status.get('available'):
            print(f"Input devices:  {status['input_devices']}")
            print(f"Output devices: {status['output_devices']}")
            print(f"Default input:  {status.get('default_input', 'None')}")
            print(f"Default output: {status.get('default_output', 'None')}")
            print("\nUse --help to see available demos.")
        else:
            print(f"Audio devices not available: {status.get('error')}")
        return 0

    if args.list_devices:
        return cmd_list_devices()
    elif args.demo_tone:
        return cmd_demo_tone()
    elif args.demo_capture:
        return cmd_demo_capture()
    elif args.demo_loopback:
        return cmd_demo_loopback()
    elif args.demo_duplex:
        return cmd_demo_full_duplex()
    elif args.demo_call_sim:
        return asyncio.run(cmd_demo_call_sim())


if __name__ == '__main__':
    sys.exit(main())
