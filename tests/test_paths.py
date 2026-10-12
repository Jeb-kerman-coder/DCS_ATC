"""Frozen-path logic: python tests/test_paths.py"""

import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():

    import app_paths

    # from source: everything stays in the project folder
    assert not app_paths.FROZEN
    assert app_paths.user_dir() == app_paths.resource_dir()
    assert app_paths.piper_worker_command("m.onnx")[1].endswith("piper_worker.py")

    # pretend to be the installed exe
    with tempfile.TemporaryDirectory() as tmp:

        install = Path(tmp) / "Program Files" / "DCS ATC"
        (install / "_internal").mkdir(parents=True)

        sys.frozen = True
        sys._MEIPASS = str(install / "_internal")
        real_exe = sys.executable
        sys.executable = str(install / "DCS ATC.exe")
        os.environ["APPDATA"] = str(Path(tmp) / "AppData")

        try:
            importlib.reload(app_paths)

            assert app_paths.FROZEN
            assert app_paths.resource_dir() == install / "_internal"
            assert app_paths.user_dir() == Path(tmp) / "AppData" / "DCS ATC"
            assert app_paths.user_dir().is_dir()

            command = app_paths.piper_worker_command("v.onnx")
            assert command[0] == str(install / "piper-worker.exe"), command

            # settings land in AppData, not in the install folder
            import settings_manager
            importlib.reload(settings_manager)
            settings = settings_manager.SettingsManager()
            settings.set("radio", "default_com", 2)
            assert (Path(tmp) / "AppData" / "DCS ATC" / "settings.json").exists()
            assert not (install / "settings.json").exists()

        finally:
            del sys.frozen
            del sys._MEIPASS
            sys.executable = real_exe
            importlib.reload(app_paths)

    print("path tests passed")


if __name__ == "__main__":
    main()
