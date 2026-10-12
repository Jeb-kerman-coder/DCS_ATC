import sys, time, threading
import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from wingman.hot_mic import HotMic, SAMPLE_RATE, is_meaningful

rng = np.random.default_rng(1)
def noise(sec, amp=0.002): return (rng.standard_normal(int(sec*SAMPLE_RATE))*amp).astype(np.float32)
def speech(sec, amp=0.08):
    t = np.arange(int(sec*SAMPLE_RATE))/SAMPLE_RATE
    return (amp*np.sin(2*np.pi*180*t)*(0.6+0.4*np.sin(2*np.pi*4*t)) + rng.standard_normal(len(t))*0.01).astype(np.float32)

got = []
ev = threading.Event()
blocked = {"v": False}
def on_utt(a): got.append(len(a)/SAMPLE_RATE); ev.set()
m = HotMic(on_utt, is_blocked=lambda: blocked["v"])
m._stream = object()   # pretend the stream is open (state() checks it)

def run(*chunks):
    got.clear(); ev.clear()
    for c in chunks:
        # feed in odd-sized pieces like a real driver would
        for i in range(0, len(c), 700): m.feed(c[i:i+700])
    ev.wait(0.5)

# 1) one utterance
run(noise(1.0), speech(1.5), noise(1.2))
print("utterance:", [round(x,2) for x in got]); assert len(got) == 1 and 1.4 < got[0] < 2.4

# 2) a click / cough is ignored
run(noise(1.0), speech(0.15), noise(1.2)); print("click:", got); assert got == []

# 3) pure quiet noise never triggers, and the noise floor adapts
run(noise(3.0, 0.004)); print("noise only:", got); assert got == []

# 4) PTT held -> nothing heard, and speech before PTT-down is discarded
m.feed(speech(0.5)); m.ptt_down(); print("state while PTT:", m.state())
run(speech(1.5), noise(1.2)); assert got == [] and m.state() == "ptt"
m.ptt_up(); print("state after PTT:", m.state()); assert m.state() == "hot"
run(noise(0.5), speech(1.0), noise(1.2)); assert len(got) == 1

# 5) speaker busy -> deaf (the wingman must not hear itself)
blocked["v"] = True; print("state while speaking:", m.state())
run(speech(1.5), noise(1.2)); assert got == []
blocked["v"] = False

# 6) mute switch
m.set_enabled(False); print("muted:", m.state()); run(speech(1.5), noise(1.2)); assert got == []
m.set_enabled(True)

# 7) two utterances back to back
got.clear(); ev.clear()
for c in (noise(0.5), speech(1.0), noise(1.2), speech(1.0), noise(1.2)):
    for i in range(0, len(c), 480): m.feed(c[i:i+480])
time.sleep(0.3); print("two utterances:", len(got)); assert len(got) == 2

# transcript filter
cases = {"": False, "you": False, "Thank you.": False, "uh": False, "...": False,
         "two, break right": True, "Colt 1-2 what's your fuel": True, "12": False}
for t, want in cases.items():
    assert is_meaningful(t) == want, (t, want)

# 8) a QUIET headset mic (speech RMS ~0.012, below the old 0.015 default) must work,
#    including the way real speech flickers around the threshold
def quiet_speech(sec):
    t = np.arange(int(sec*SAMPLE_RATE))/SAMPLE_RATE
    env = np.abs(np.sin(2*np.pi*3*t))**0.5 * (rng.random(len(t)) > 0.0)
    return (0.02*np.sin(2*np.pi*170*t)*env + rng.standard_normal(len(t))*0.002).astype(np.float32)
q = quiet_speech(1.5); print("quiet speech rms:", round(float(np.sqrt(np.mean(q*q))), 4))
m2 = HotMic(on_utt, is_blocked=lambda: False); m2._stream = object()
got.clear(); ev.clear()
for c in (noise(1.0, 0.001), q, noise(1.2, 0.001)):
    for i in range(0, len(c), 480): m2.feed(c[i:i+480])
ev.wait(0.5); print("quiet mic utterances:", len(got)); assert len(got) == 1

print("filter ok\nALL HOT MIC TESTS PASSED")
