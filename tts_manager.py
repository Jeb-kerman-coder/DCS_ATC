import atexit
import json
import os
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from app_paths import (
    FROZEN, app_dir, piper_worker_command, resource_dir, user_path
)
from radio_effects import RadioEffects

CACHE_SIZE = 64


class PiperEngine:
    """
    One Piper voice kept loaded in a long-lived WORKER PROCESS.

    Starting `python -m piper` for every line reloads the whole voice model
    (seconds for a "high" voice) before it says a word, so the voice is
    loaded once and reused. It lives in a separate process (piper_worker.py)
    because Piper's native ONNX/espeak code crashes the whole app when it
    runs inside this process next to pygame and Whisper.
    """

    START_TIMEOUT = 90      # seconds to load the voice
    REQUEST_TIMEOUT = 30    # seconds for one line
    MAX_RESTARTS = 3

    def __init__(self, model_name):

        self.model_name = model_name

        self._proc = None
        self._failures = 0
        self._request_id = 0
        self._lock = threading.Lock()

    def _find_model(self):

        path = Path(self.model_name)

        if path.exists():
            return path

        for base in (
            app_dir() / "voices", user_path("voices"),
            resource_dir(), user_path(), Path.cwd(),
            Path(__file__).resolve().parent
        ):

            candidate = base / f"{self.model_name}.onnx"

            if candidate.exists():
                return candidate

        raise FileNotFoundError(
            f"voice model '{self.model_name}.onnx' not found"
        )

    @staticmethod
    def _kill(proc):

        try:
            proc.kill()
        except Exception:
            pass

    def _start(self):
        """Launch the worker and wait until the voice is loaded."""

        started = time.time()

        model = self._find_model()

        flags = (
            subprocess.CREATE_NO_WINDOW
            if sys.platform == "win32" else 0
        )

        proc = subprocess.Popen(
            piper_worker_command(model),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            creationflags=flags
        )

        # a hung load must not hang the app: kill it after the timeout
        watchdog = threading.Timer(
            self.START_TIMEOUT, self._kill, args=(proc,)
        )
        watchdog.start()

        try:
            ready = proc.stdout.readline()
        finally:
            watchdog.cancel()

        if b"ready" not in ready:
            self._kill(proc)
            raise RuntimeError("voice worker did not start")

        self._proc = proc

        print(
            f"TTS: voice '{self.model_name}' loaded in its own process "
            f"({time.time() - started:.1f}s)"
        )

    def _ensure(self):

        if self._proc is not None and self._proc.poll() is None:
            return True

        if self._failures >= self.MAX_RESTARTS:
            return False

        try:

            self._start()

            return True

        except Exception as exc:

            self._failures += 1
            self._proc = None

            print(
                f"TTS: voice worker failed ({exc}) "
                f"[{self._failures}/{self.MAX_RESTARTS}]"
            )

            if self._failures >= self.MAX_RESTARTS:
                print(
                    "TTS: giving up on the resident voice; using one "
                    "Piper process per line instead"
                )

            return False

    def load(self):
        """True when the voice is loaded and ready."""

        with self._lock:
            return self._ensure()

    def synthesize(self, text):
        """-> (float32 mono audio, sample_rate), or None on any problem."""

        with self._lock:

            if not self._ensure():
                return None

            proc = self._proc

            self._request_id += 1

            watchdog = threading.Timer(
                self.REQUEST_TIMEOUT, self._kill, args=(proc,)
            )
            watchdog.start()

            try:

                request = json.dumps(
                    {"id": self._request_id, "text": text}
                )

                proc.stdin.write(request.encode() + b"\n")
                proc.stdin.flush()

                header = json.loads(proc.stdout.readline())

                if "error" in header:
                    print(f"TTS: voice error: {header['error']}")
                    return None

                data = proc.stdout.read(header["bytes"])

                if len(data) != header["bytes"]:
                    raise RuntimeError("voice worker stopped mid-line")

                audio = (
                    np.frombuffer(data, dtype=np.int16)
                    .astype(np.float32) / 32768.0
                )

                # only back-to-back failures count towards giving up
                self._failures = 0

                return audio, header["sample_rate"]

            except Exception as exc:

                # worker died / hung: drop it, the next line restarts it
                print(f"TTS: voice worker problem ({exc}); restarting it")

                self._failures += 1
                self._kill(proc)
                self._proc = None

                return None

            finally:
                watchdog.cancel()

    def close(self):

        with self._lock:

            proc, self._proc = self._proc, None

            if proc is not None:
                self._kill(proc)


class TTSManager:
    """
    Text to speech through Piper.

    Two voices are defined:
        "atc"      ATC / AWACS / GCI - heavy radio effects
        "wingman"  your AI wingman   - light intercom effects

    Playback uses a short-lived OutputStream per sound rather than
    sd.play(): sd.play() is global, so a second sound (a PTT click, a
    wingman callout) would cut off the one already playing.
    """

    def __init__(self, settings=None):

        self.settings = settings

        self.last_synth_seconds = 0.0

        self.output_directory = user_path("tts")
        self.output_directory.mkdir(parents=True, exist_ok=True)

        self.voices = {
            "atc": {
                "model": self._setting("atc_model", "en_US-ryan-high"),
                "effects": RadioEffects("radio"),
            },
            "wingman": {
                "model": self._setting("wingman_model", "en_US-ryan-high"),
                "effects": RadioEffects("intercom"),
            },
        }

        # two voices using the same model share one loaded copy
        self._engines = {}

        for voice in self.voices.values():

            model = voice["model"]

            if model not in self._engines:
                self._engines[model] = PiperEngine(model)

        # recent lines: ("model", "text") -> (audio, sample_rate)
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()

        # kept so older code that used tts_manager.radio_effects still works
        self.radio_effects = self.voices["atc"]["effects"]

        atexit.register(self.close)

    def close(self):
        """Stop the voice worker processes."""

        for engine in self._engines.values():
            engine.close()

    # ---------------------------------------------------------
    # helpers
    # ---------------------------------------------------------

    def _setting(self, key, default):

        if self.settings is None:
            return default

        return self.settings.get("tts", key) or default

    def _output_device(self):

        if self.settings is None:
            return None

        return self.settings.get("audio", "output_device")

    def _voice(self, voice):

        return self.voices.get(voice) or self.voices["atc"]

    def warm_up(self):
        """Load every voice now (and run one throwaway line through it,
        which also warms the ONNX runtime) so the first call is fast."""

        for model, engine in self._engines.items():

            started = time.time()

            if engine.load():
                engine.synthesize("Radio check.")

            print(
                f"TTS: warmed up '{model}' in {time.time() - started:.1f}s"
            )

    # ---------------------------------------------------------
    # SYNTHESIS
    # ---------------------------------------------------------

    def _cache_get(self, key):

        with self._cache_lock:

            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        return None

    def _cache_put(self, key, value):

        with self._cache_lock:

            self._cache[key] = value
            self._cache.move_to_end(key)

            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)

    def _speech(self, text, voice):
        """-> (audio, sample_rate) or None. Cache, then the loaded voice,
        then (last resort) one Piper process for this line."""

        model = self._voice(voice)["model"]

        key = (model, text)

        cached = self._cache_get(key)

        if cached is not None:
            print(f"TTS[{voice}]: cached")
            return cached

        result = self._engines[model].synthesize(text)

        if result is None:
            result = self._synthesize_subprocess(text, model)

        if result is not None:
            self._cache_put(key, result)

        return result

    def _synthesize_subprocess(self, text, model):

        # the installed exe has no Python to run "-m piper" with
        if FROZEN:
            return None

        output_file = (
            self.output_directory /
            f"transmission_{time.time_ns()}.wav"
        )

        command = [
            sys.executable, "-m", "piper",
            "-m", model,
            "-f", str(output_file),
            "--", text
        ]

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                print("TTS ERROR:")
                print(result.stderr)
                return None

            audio, sample_rate = sf.read(output_file, dtype="float32")

            return np.asarray(audio, dtype=np.float32), sample_rate

        except Exception as e:
            print(f"TTS ERROR: {e}")
            return None

        finally:
            self._remove(output_file)

    def synthesize(self, text, voice="atc", play=True):
        """Generate (and by default play) speech. True on success."""

        if not text:
            return None

        started = time.time()

        result = self._speech(text, voice)

        self.last_synth_seconds = time.time() - started

        if result is None:
            return None

        print(
            f"TTS[{voice}]: ready in {self.last_synth_seconds:.2f}s"
        )

        if play:
            self._play_audio(result[0], result[1], voice)

        return True

    @staticmethod
    def _remove(path):

        try:
            os.remove(path)
        except OSError:
            pass

    # ---------------------------------------------------------
    # PLAYBACK
    # ---------------------------------------------------------

    def play_array(self, audio, sample_rate):
        """Blocking playback of a float32 mono array."""

        with sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=self._output_device()
        ) as stream:

            stream.write(audio.reshape(-1, 1))

    def _play_audio(self, audio, sample_rate, voice):

        try:

            audio = self._voice(voice)["effects"].create_transmission(
                audio,
                sample_rate
            )

            self.play_array(audio, sample_rate)

            print("TTS: Playback finished")

        except Exception as e:
            print(f"TTS PLAYBACK ERROR: {e}")

    def play(self, audio_file, voice="atc"):
        """Play an existing wav file through a voice's radio effects."""

        try:

            audio, sample_rate = sf.read(audio_file, dtype="float32")

        except Exception as e:
            print(f"TTS PLAYBACK ERROR: {e}")
            return

        self._play_audio(audio, sample_rate, voice)

    def play_ptt_burst(self, voice="atc"):

        try:

            sample_rate = 22050

            burst = self._voice(voice)["effects"].generate_static_burst(
                sample_rate,
                duration=0.08
            )

            self.play_array(burst, sample_rate)

        except Exception as e:
            print(f"PTT BURST ERROR: {e}")
