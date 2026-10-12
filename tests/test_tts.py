import os, sys, tempfile, time, types, textwrap
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np

# hardware stand-ins (real libs only needed on the user's PC)
played = []
class _S:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def write(self, x): played.append(len(x))
sys.modules["sounddevice"] = types.SimpleNamespace(OutputStream=_S, InputStream=_S)
sys.modules["soundfile"] = types.SimpleNamespace(read=lambda *a, **k: (np.zeros(2205, "float32"), 22050))

# a fake `piper` package on disk, so the worker PROCESS imports it like the real one
work = tempfile.mkdtemp()
os.makedirs(os.path.join(work, "fakelib", "piper"))
open(os.path.join(work, "fakelib", "piper", "__init__.py"), "w").write(textwrap.dedent('''
    import os, time
    import numpy as np
    class Chunk:
        sample_rate = 22050
        def __init__(self, n): self.audio_int16_bytes = (np.ones(n, "int16") * 3277).tobytes()   # 0.1 full scale
    class Voice:
        def synthesize(self, text):
            print("stray library output that must not corrupt the audio stream")
            if text.startswith("crash"): os._exit(1)
            if text == "boom": raise ValueError("bad text")
            for _ in text.split("."): yield Chunk(2205)
    class PiperVoice:
        @staticmethod
        def load(path, *a, **k): return Voice()
'''))
os.environ["PYTHONPATH"] = os.path.join(work, "fakelib")
os.chdir(work); open("fake-voice.onnx", "w").close()

import tts_manager
class Settings:
    def get(self, s, k): return {"atc_model": "fake-voice", "wingman_model": "fake-voice"}.get(k) if s == "tts" else None
cli_calls = []
import subprocess
subprocess.run = lambda cmd, **k: (cli_calls.append(cmd), types.SimpleNamespace(returncode=0, stderr=""))[1]

t = tts_manager.TTSManager(Settings()); eng = t._engines["fake-voice"]

# 1) both voices share ONE worker; it is started once and reused
t.synthesize("Colt 1-1, Tower, taxi to runway two six.", "atc"); pid = eng._proc.pid
t.synthesize("Two copies.", "wingman"); t.synthesize("Fox three.", "wingman")
print("worker pid stable:", eng._proc.pid == pid, "| played:", len(played), "| CLI fallbacks:", len(cli_calls))
assert eng._proc.pid == pid and len(played) == 3 and not cli_calls

# 2) audio is intact (stray prints did not corrupt the stream) and correctly scaled
audio, sr = eng.synthesize("Hello"); print("sample rate", sr, "| samples", len(audio), "| level", round(float(audio.max()), 3))
assert sr == 22050 and len(audio) == 2205 and abs(float(audio.max()) - 0.1) < 0.001

# 3) repeated line = cache (no worker round trip)
t0 = time.time(); t.synthesize("Fox three.", "wingman"); dt = time.time() - t0
print(f"cached repeat: {dt*1000:.0f} ms"); assert t.last_synth_seconds < 0.01

# 4) multi-sentence reply -> one joined transmission
t.synthesize("Two. Copy that. Turning now.", "wingman"); assert played[-1] >= 3 * 2205

# 5) a reported error for one line -> that line falls back, worker survives
n_cli = len(cli_calls); pid_before = eng._proc.pid
assert t.synthesize("boom", "atc") is True and len(cli_calls) == n_cli + 1 and eng._proc.pid == pid_before
print("error line used CLI fallback; worker kept running")

# 6) worker CRASHES mid-line (like the real native crash) -> app survives, next line restarts it
assert t.synthesize("crash", "atc") is True; print("crash line survived via fallback")
assert eng._proc is None
n_cli = len(cli_calls); assert t.synthesize("Back in business.", "atc") is True
print("restarted:", eng._proc is not None and eng._proc.pid != pid_before, "| used CLI:", len(cli_calls) > n_cli)
assert eng._proc is not None and eng._proc.pid != pid_before and len(cli_calls) == n_cli

# 7) too many failures -> stop retrying the worker, keep working via CLI
for i in range(tts_manager.PiperEngine.MAX_RESTARTS + 1):
    t.synthesize(f"crash {i}", "atc"); print("   after crash", i, "failures =", eng._failures, "proc alive:", eng._proc is not None)
assert eng._failures >= tts_manager.PiperEngine.MAX_RESTARTS
n_cli = len(cli_calls); assert t.synthesize("Still talking.", "atc") is True and len(cli_calls) == n_cli + 1 and eng._proc is None
print("gave up on worker, CLI fallback active")

# 8) warm-up loads the worker; close() kills it
t2 = tts_manager.TTSManager(Settings()); t2.warm_up(); e2 = t2._engines["fake-voice"]; p2 = e2._proc
assert p2 is not None and p2.poll() is None
t2.close(); time.sleep(0.3); assert p2.poll() is not None; print("warm-up started worker; close() stopped it")

# 9) missing voice file -> clean fallback, no crash
t4 = tts_manager.TTSManager(types.SimpleNamespace(get=lambda s, k: "no-such-voice" if s == "tts" else None))
assert t4.synthesize("Hello.", "atc") is True
print("ALL TTS TESTS PASSED")
