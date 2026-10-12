"""
Piper voice worker - runs in its OWN process.

The app keeps this process alive so the voice model is loaded only once,
but keeps Piper's native code (ONNX runtime, espeak) out of the main
process, where it clashes with pygame/Whisper and can crash Python.

Protocol (binary-safe, one request at a time):
    app   -> worker : one JSON line  {"id": 1, "text": "..."}
    worker -> app   : {"ready": true}\n                          (once, at start)
                      {"id": 1, "sample_rate": 22050, "bytes": N}\n  + N bytes of
                      int16 mono PCM,   or   {"id": 1, "error": "..."}\n
"""

import json
import sys


def main():

    out = sys.stdout.buffer

    # anything a library prints must not end up inside the audio stream
    sys.stdout = sys.stderr

    from piper import PiperVoice

    voice = PiperVoice.load(sys.argv[1])

    out.write(b'{"ready": true}\n')
    out.flush()

    for line in sys.stdin.buffer:

        line = line.strip()

        if not line:
            continue

        request = json.loads(line)

        try:

            pcm = bytearray()
            sample_rate = None

            for chunk in voice.synthesize(request["text"]):
                pcm += chunk.audio_int16_bytes
                sample_rate = chunk.sample_rate

            if sample_rate is None:
                raise RuntimeError("no audio produced")

            header = {
                "id": request["id"],
                "sample_rate": sample_rate,
                "bytes": len(pcm),
            }

            out.write(json.dumps(header).encode() + b"\n")
            out.write(bytes(pcm))

        except Exception as exc:

            out.write(
                json.dumps({"id": request.get("id"), "error": str(exc)})
                .encode() + b"\n"
            )

        out.flush()


if __name__ == "__main__":
    main()
