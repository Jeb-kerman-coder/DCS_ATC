# PyInstaller spec - build with:  pyinstaller DCS_ATC.spec --noconfirm
#
# Two programs share one folder (and one copy of every library):
#   DCS ATC.exe       the app (windowed, no console)
#   piper-worker.exe  the voice process the app starts (console, hidden by
#                     the app with CREATE_NO_WINDOW, talks over stdin/stdout)

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

here = Path(SPECPATH)

datas = [
    (str(here / "data" / "procedures.json"), "data"),
    (str(here / "models" / "faster-whisper-small.en"),
     "models/faster-whisper-small.en"),
]
binaries = []
hiddenimports = []

# packages with data files / native libraries PyInstaller can't see
for package in (
    "faster_whisper", "ctranslate2", "onnxruntime", "tokenizers",
    "av", "piper", "sounddevice", "soundfile", "pygame", "scipy",
    "ollama",
):
    try:
        d, b, h = collect_all(package)
    except Exception as exc:
        print(f"spec: could not collect {package}: {exc}")
        continue

    datas += d
    binaries += b
    hiddenimports += h

excludes = ["matplotlib", "pandas", "IPython", "pytest", "torch"]

app = Analysis(
    [str(here / "main.py")],
    pathex=[str(here)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

worker = Analysis(
    [str(here / "piper_worker.py")],
    pathex=[str(here)],
    binaries=binaries,
    datas=[],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

MERGE((app, "main", "DCS ATC"), (worker, "piper_worker", "piper-worker"))

app_pyz = PYZ(app.pure)
worker_pyz = PYZ(worker.pure)

app_exe = EXE(
    app_pyz,
    app.scripts,
    [],
    exclude_binaries=True,
    name="DCS ATC",
    icon=str(here / "assets" / "icon.ico"),
    console=False,
    upx=False,
)

worker_exe = EXE(
    worker_pyz,
    worker.scripts,
    [],
    exclude_binaries=True,
    name="piper-worker",
    icon=str(here / "assets" / "icon.ico"),
    console=True,
    upx=False,
)

COLLECT(
    app_exe, app.binaries, app.datas,
    worker_exe, worker.binaries, worker.datas,
    name="DCS ATC",
    upx=False,
)
