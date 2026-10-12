import sounddevice as sd
import soundfile as sf
from pathlib import Path
import threading
import time

from app_paths import user_path


class AudioManager:

    def __init__(self):

        self.sample_rate = 16000
        self.channels = 1

        self.recording = False
        self.audio_data = []

        # sounddevice device (index or name); None = system default
        self.device = None

        self.stream = None
        self.lock = threading.Lock()

        self.output_directory = user_path("recordings")
        self.output_directory.mkdir(
            parents=True, exist_ok=True
        )

    # ---------------------------------------------------------
    # START RECORDING
    # ---------------------------------------------------------

    def start_recording(self):

        with self.lock:

            if self.recording:
                return

            self.audio_data = []
            self.recording = True

        print("AUDIO: Recording started")

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
            callback=self._audio_callback
        )

        self.stream.start()

    # ---------------------------------------------------------
    # AUDIO CALLBACK
    # ---------------------------------------------------------

    def _audio_callback(
        self,
        indata,
        frames,
        time_info,
        status
    ):

        if status:
            print(
                f"AUDIO: {status}"
            )

        with self.lock:

            if self.recording:

                self.audio_data.append(
                    indata.copy()
                )

    # ---------------------------------------------------------
    # STOP RECORDING
    # ---------------------------------------------------------

    def stop_recording(self):

        with self.lock:

            if not self.recording:
                return None

            self.recording = False

        print("AUDIO: Recording stopped")

        if self.stream:

            self.stream.stop()
            self.stream.close()

            self.stream = None

        with self.lock:

            if not self.audio_data:
                return None

            audio = self.audio_data

            self.audio_data = []

        filename = (
            self.output_directory
            / f"transmission_{int(time.time())}.wav"
        )

        import numpy as np

        audio = np.concatenate(
            audio,
            axis=0
        )

        sf.write(
            filename,
            audio,
            self.sample_rate
        )

        print(
            f"AUDIO: Saved {filename}"
        )

        return filename

    # ---------------------------------------------------------
    # STOP
    # ---------------------------------------------------------

    def close(self):

        if self.recording:

            self.stop_recording()

                # ---------------------------------------------------------
    # DELETE TEMPORARY RECORDINGS
    # ---------------------------------------------------------

    def delete_recordings(self):

        if not self.output_directory.exists():
            return

        for file in self.output_directory.glob("*.wav"):

            try:
                file.unlink()

                print(
                    f"AUDIO: Deleted {file.name}"
                )

            except OSError as e:

                print(
                    f"AUDIO: Could not delete "
                    f"{file.name}: {e}"
                )