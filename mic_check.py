"""Standalone PyAudio smoke test: list devices, record 3s from the default
mic, play it back through the default speakers. No Pipecat, no LLM."""

import pyaudio

RATE = 16000
CHANNELS = 1
CHUNK = 1024
RECORD_SECONDS = 3


def main():
    pa = pyaudio.PyAudio()

    print("Audio devices:")
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        print(f"  [{i}] {info['name']!r} "
              f"(in={info['maxInputChannels']}, out={info['maxOutputChannels']})")

    default_in = pa.get_default_input_device_info()
    default_out = pa.get_default_output_device_info()
    print(f"\nDefault input:  {default_in['name']!r}")
    print(f"Default output: {default_out['name']!r}")

    input_stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )

    print(f"\nRecording {RECORD_SECONDS}s... speak now.")
    frames = []
    for _ in range(int(RATE / CHUNK * RECORD_SECONDS)):
        frames.append(input_stream.read(CHUNK))
    input_stream.stop_stream()
    input_stream.close()
    print("Done recording.")

    output_stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RATE,
        output=True,
    )

    print("Playing it back...")
    for frame in frames:
        output_stream.write(frame)
    output_stream.stop_stream()
    output_stream.close()
    print("Done.")

    pa.terminate()


if __name__ == "__main__":
    main()
