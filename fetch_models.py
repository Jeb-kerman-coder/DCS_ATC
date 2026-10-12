"""
Download the speech models the installer bundles. Run by build_installer.bat;
safe to run again (already-downloaded files are skipped).

    models/faster-whisper-small.en/   Whisper speech-to-text
    en_US-ryan-high.onnx(+.json)      Piper voice
"""

import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

PIPER_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/ryan/high/"
)

VOICE = "en_US-ryan-high"


def download(url, target):

    if target.exists() and target.stat().st_size > 0:
        print(f"have {target.name}")
        return

    print(f"downloading {target.name} ...")

    tmp = target.with_suffix(target.suffix + ".part")

    urllib.request.urlretrieve(url, tmp)

    tmp.replace(target)


def main():

    # --- Piper voice ---
    for suffix in (".onnx", ".onnx.json"):
        download(PIPER_BASE + VOICE + suffix, HERE / (VOICE + suffix))

    # --- Whisper ---
    target = HERE / "models" / "faster-whisper-small.en"

    if (target / "model.bin").exists():
        print("have Whisper small.en")
    else:
        from huggingface_hub import snapshot_download

        print("downloading Whisper small.en ...")

        snapshot_download(
            "Systran/faster-whisper-small.en",
            local_dir=str(target)
        )

    print("models ready")


if __name__ == "__main__":
    sys.exit(main())
