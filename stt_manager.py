import threading

import numpy as np
import soundfile as sf

from app_paths import resource_path

WHISPER_RATE = 16000


def load_wav_16k(path):
    """
    Read a wav file as the float32 mono 16 kHz array Whisper wants.

    Handing Whisper a file path makes it decode the file with PyAV (FFmpeg),
    which is fragile inside a packaged exe. Reading the wav ourselves means
    the PTT path feeds Whisper exactly like the hot mic does.
    """

    data, rate = sf.read(str(path), dtype="float32", always_2d=True)

    audio = data.mean(axis=1)

    if rate != WHISPER_RATE:

        from scipy.signal import resample_poly

        audio = resample_poly(audio, WHISPER_RATE, rate).astype(np.float32)

    return np.ascontiguousarray(audio, dtype=np.float32)


class STTManager:
    """
    Speech to text. Used by both the PTT path (ATC, from a wav file) and
    the hot mic (wingman, from an in-memory array), so transcriptions are
    serialised with a lock - one Whisper model, one job at a time.
    """

    def __init__(self):

        print("STT: Loading Whisper model...")

        from faster_whisper import WhisperModel

        # the installer ships the model; from source it is downloaded
        # (and cached) on first run
        bundled = resource_path("models", "faster-whisper-small.en")

        self.model = WhisperModel(
            str(bundled) if bundled.exists() else "small.en",
            device="cpu",
            compute_type="int8"
        )

        self._lock = threading.Lock()

        print("STT: Whisper ready")

    def transcribe(self, source, quiet=False, fast=False):
        """source: a wav path, or a float32 mono 16 kHz numpy array."""

        if not quiet:
            print(f"STT: Transcribing {source if isinstance(source, str) else type(source).__name__}")

        # a file (str / Path) -> read it ourselves; arrays go straight through
        if isinstance(source, (str, bytes)) or hasattr(source, "__fspath__"):
            source = load_wav_16k(source)

        with self._lock:

            segments, info = self.model.transcribe(
                source,
                language="en",
                beam_size=1 if fast else 5,
                vad_filter=False,
                condition_on_previous_text=False
            )

            text_parts = []

            for segment in segments:

                if not quiet:
                    print(
                        f"STT SEGMENT: "
                        f"[{segment.start:.2f} - {segment.end:.2f}] "
                        f"{segment.text}"
                    )

                text_parts.append(segment.text.strip())

        text = " ".join(text_parts).strip()

        if not quiet:
            print(f"STT: {text}")

        return text
