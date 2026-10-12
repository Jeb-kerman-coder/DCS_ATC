"""
Hot mic for the wingman.

The ATC / AWACS radio is a COLD mic: nothing is heard until you hold PTT.
The wingman is a HOT mic: it listens all the time and you just talk to it,
like an intercom. This class does that listening.

    microphone -> 30 ms frames -> voice-activity detection
               -> one utterance (with a little lead-in) -> on_utterance(audio)

It deliberately stays deaf in three situations, otherwise it would answer
itself or steal your ATC calls:

    * PTT is held          (you are talking to ATC/AWACS)
    * something is being spoken through the speakers (is_blocked())
    * the mic is muted from the GUI

Audio is 16 kHz mono float32 - exactly what Whisper wants.
"""

import collections
import threading
import time

import numpy as np

SAMPLE_RATE = 16000
FRAME_SECONDS = 0.03
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_SECONDS)

PRE_ROLL_FRAMES = 10          # 0.3 s kept from before speech was detected
START_FRAMES = 3              # speech frames in a row that start an utterance
END_SILENCE_SECONDS = 0.6     # silence that ends one
MIN_SPEECH_SECONDS = 0.25     # less actual speech than this is a click or a cough
MAX_UTTERANCE_SECONDS = 15.0

# speech must also beat the room's noise floor by this factor
NOISE_MARGIN = 3.0

# how much louder the GUI meter draws the level (speech is quiet in float32)
METER_GAIN = 20.0

# an utterance starts when START_FRAMES of the last START_WINDOW frames are
# loud - NOT "in a row", which quiet or breathy speech rarely manages
START_WINDOW = 6


class HotMic:

    def __init__(
        self,
        on_utterance,
        is_blocked=None,
        device=None,
        threshold=0.006
    ):
        self.on_utterance = on_utterance
        self.is_blocked = is_blocked or (lambda: False)
        self.device = device
        self.threshold = float(threshold)

        self.enabled = True       # the GUI's mute switch
        self._ptt_held = False

        self.level = 0.0          # 0..1, for the GUI meter
        self.listening = False    # currently inside an utterance

        self._noise_floor = None
        self._recent = collections.deque(maxlen=START_WINDOW)

        self._preroll = collections.deque(maxlen=PRE_ROLL_FRAMES)
        self._frames = []
        self._silence_run = 0
        self._loud_frames = 0
        self._in_speech = False

        self._pending = np.zeros(0, dtype=np.float32)

        self._stream = None
        self._lock = threading.Lock()

    # =========================================================
    # GATING
    # =========================================================

    def set_enabled(self, enabled):

        self.enabled = bool(enabled)

        if not self.enabled:
            self._reset()

    def ptt_down(self):

        self._ptt_held = True
        self._reset()

    def ptt_up(self):

        self._ptt_held = False
        self._reset()

    def state(self):
        """'off' | 'ptt' | 'busy' | 'speech' | 'hot' - for the GUI."""

        if self._stream is None or not self.enabled:
            return "off"

        if self._ptt_held:
            return "ptt"

        if self.is_blocked():
            return "busy"

        return "speech" if self._in_speech else "hot"

    def _reset(self):

        with self._lock:

            self._preroll.clear()
            self._frames = []
            self._recent.clear()
            self._silence_run = 0
            self._loud_frames = 0
            self._in_speech = False
            self.listening = False
            self._pending = np.zeros(0, dtype=np.float32)

    # =========================================================
    # STREAM
    # =========================================================

    def start(self):

        if self._stream is not None:
            return True

        import sounddevice as sd

        try:

            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME_SAMPLES,
                device=self.device,
                callback=self._callback
            )

            self._stream.start()

        except Exception as exc:

            print(f"HOT MIC: could not open microphone: {exc}")

            self._stream = None

            return False

        print("HOT MIC: listening")

        return True

    def stop(self):

        stream, self._stream = self._stream, None

        if stream is not None:

            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        self._reset()

    def _callback(self, indata, frames, time_info, status):

        try:
            self.feed(indata[:, 0])
        except Exception as exc:
            print(f"HOT MIC: {exc}")

    # =========================================================
    # VOICE ACTIVITY DETECTION
    # =========================================================

    def feed(self, samples):
        """Feed any amount of audio; it is cut into 30 ms frames."""

        samples = np.asarray(samples, dtype=np.float32)

        buffered = np.concatenate([self._pending, samples])

        whole = len(buffered) // FRAME_SAMPLES * FRAME_SAMPLES

        self._pending = buffered[whole:]

        for start in range(0, whole, FRAME_SAMPLES):
            self._frame(buffered[start:start + FRAME_SAMPLES])

    def _frame(self, frame):

        rms = float(np.sqrt(np.mean(frame * frame)))

        self.level = min(1.0, rms * METER_GAIN)

        if not self.enabled or self._ptt_held or self.is_blocked():

            if self._in_speech or self._preroll or self._frames:
                self._reset()

            return

        if self._noise_floor is None:
            self._noise_floor = rms

        loud = rms > max(
            self.threshold,
            self._noise_floor * NOISE_MARGIN
        )

        if not self._in_speech:

            # track the room noise only while nobody is talking
            if not loud:
                self._noise_floor = (
                    0.98 * self._noise_floor + 0.02 * rms
                )

            self._preroll.append(frame)

            self._recent.append(loud)

            if loud and sum(self._recent) >= START_FRAMES:

                self._in_speech = True
                self.listening = True
                self._frames = list(self._preroll)
                self._silence_run = 0
                self._loud_frames = sum(self._recent)

            return

        self._frames.append(frame)

        self._silence_run = 0 if loud else self._silence_run + 1

        if loud:
            self._loud_frames += 1

        length = len(self._frames) * FRAME_SECONDS

        if (
            self._silence_run * FRAME_SECONDS >= END_SILENCE_SECONDS
            or length >= MAX_UTTERANCE_SECONDS
        ):
            self._finish()

    def _finish(self):

        frames = self._frames

        # drop most of the trailing silence, keep a little for Whisper
        trim = max(0, self._silence_run - 5)

        if trim:
            frames = frames[:-trim]

        loud_seconds = self._loud_frames * FRAME_SECONDS

        self._frames = []
        self._preroll.clear()
        self._recent.clear()
        self._silence_run = 0
        self._loud_frames = 0
        self._in_speech = False
        self.listening = False

        if loud_seconds < MIN_SPEECH_SECONDS:
            return

        audio = np.concatenate(frames) if frames else np.zeros(0, np.float32)

        # never block the audio thread
        threading.Thread(
            target=self._deliver,
            args=(audio,),
            daemon=True
        ).start()

    def _deliver(self, audio):

        try:
            self.on_utterance(audio)
        except Exception as exc:
            print(f"HOT MIC: utterance handler failed: {exc}")


# =============================================================
# TRANSCRIPT FILTER
# =============================================================

# Whisper invents these from silence and noise
_HALLUCINATIONS = {
    "you", "thank you", "thanks", "thank you.", "thanks for watching",
    "thank you for watching", "bye", "bye.", "okay", "ok", "uh", "um",
    "hmm", "mm", "the", "so", "oh", "ah", "huh",
}


def is_meaningful(text):
    """Reject empty / one-word-of-noise transcripts from the hot mic."""

    if not text:
        return False

    cleaned = text.strip().strip(".,!?-… ").lower()

    if len(cleaned) < 2:
        return False

    if cleaned in _HALLUCINATIONS:
        return False

    return any(ch.isalpha() for ch in cleaned)
