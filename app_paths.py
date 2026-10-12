"""
Where things live, both when run from source and when installed as an exe.

    resource_path()  read-only files that ship with the app
                     (data/procedures.json, voice + Whisper models)
    user_path()      files the app writes (settings.json, recordings, log)

Installed under Program Files the app folder is read-only, so everything
that gets written goes to %APPDATA%\\DCS ATC. Run from source nothing
changes: both point at the project folder.
"""

import os
import sys
from pathlib import Path

APP_NAME = "DCS ATC"

FROZEN = bool(getattr(sys, "frozen", False))


def resource_dir():

    if FROZEN:
        # PyInstaller one-dir build: bundled files are under _internal
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

    return Path(__file__).resolve().parent


def app_dir():
    """Folder holding the exe (frozen) or the source files."""

    if FROZEN:
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def user_dir():

    if FROZEN:

        base = os.environ.get("APPDATA") or str(Path.home())

        path = Path(base) / APP_NAME
        path.mkdir(parents=True, exist_ok=True)

        return path

    return Path(__file__).resolve().parent


def resource_path(*parts):

    return resource_dir().joinpath(*parts)


def user_path(*parts):

    return user_dir().joinpath(*parts)


def piper_worker_command(model_path):
    """Command line that starts the Piper voice worker process."""

    if FROZEN:
        return [str(app_dir() / "piper-worker.exe"), str(model_path)]

    return [
        sys.executable,
        str(Path(__file__).resolve().parent / "piper_worker.py"),
        str(model_path)
    ]
