"""PTT wav loading: python tests/test_stt_loader.py  (needs numpy, soundfile, scipy)"""

import os
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import stt_manager


def main():

    with tempfile.TemporaryDirectory() as tmp:

        tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype("float32")

        sf.write(f"{tmp}/mono.wav", tone, 16000)
        audio = stt_manager.load_wav_16k(f"{tmp}/mono.wav")
        assert audio.dtype == np.float32 and audio.shape == (16000,)

        stereo = np.stack([tone.repeat(3), tone.repeat(3)], axis=1)
        sf.write(f"{tmp}/stereo.wav", stereo, 48000)
        audio = stt_manager.load_wav_16k(f"{tmp}/stereo.wav")
        assert audio.dtype == np.float32 and abs(audio.shape[0] - 16000) < 5

    print("stt loader tests passed")


if __name__ == "__main__":
    main()
