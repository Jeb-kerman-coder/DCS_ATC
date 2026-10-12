"""
One speaker for everybody.

ATC replies and wingman callouts both want the speakers. Playing them from
separate threads would talk over each other, so every transmission goes
through this queue and is spoken one at a time. Urgent calls (Fox three,
splash, ...) jump ahead of anything that has not started yet.

The hot mic uses is_busy() to stay deaf while we are talking, otherwise the
wingman would hear itself (and the controller) through your speakers.
"""

import itertools
import queue
import threading
import time

URGENT = 0
NORMAL = 1

# keep the hot mic closed this long after speech ends (room echo / tail)
TAIL_SECONDS = 0.6


class Speaker:

    def __init__(self, tts_manager, on_timing=None):

        self.tts = tts_manager

        # on_timing(voice, synth_seconds): how long Piper took
        self.on_timing = on_timing

        self._queue = queue.PriorityQueue()
        self._counter = itertools.count()

        self._speaking = False
        self._last_end = 0.0
        self._lock = threading.Lock()

        self._thread = threading.Thread(
            target=self._run,
            name="speaker",
            daemon=True
        )

        self._thread.start()

    def say(self, text, voice="atc", priority=NORMAL, on_done=None):

        if not text:
            return

        self._queue.put(
            (priority, next(self._counter), text, voice, on_done)
        )

    def is_busy(self):

        with self._lock:

            speaking = self._speaking
            last_end = self._last_end

        return (
            speaking
            or not self._queue.empty()
            or (time.time() - last_end) < TAIL_SECONDS
        )

    def _run(self):

        while True:

            priority, _, text, voice, on_done = self._queue.get()

            with self._lock:
                self._speaking = True

            try:
                self.tts.synthesize(text, voice=voice, play=True)

                if self.on_timing:
                    self.on_timing(voice, self.tts.last_synth_seconds)
            except Exception as exc:
                print(f"SPEAKER: {exc}")
            finally:
                with self._lock:
                    self._speaking = False
                    self._last_end = time.time()

            if on_done:
                try:
                    on_done()
                except Exception as exc:
                    print(f"SPEAKER: on_done failed: {exc}")
