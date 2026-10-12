import multiprocessing
import sys
import traceback

from app_paths import FROZEN, user_path


def _redirect_output():
    """The installed exe has no console, so keep what would be printed in a
    log file (%APPDATA%\\DCS ATC\\log.txt) - handy when something breaks."""

    log = user_path("log.txt")
    previous = user_path("log_previous.txt")

    try:
        if log.exists():
            previous.unlink(missing_ok=True)
            log.replace(previous)
    except OSError:
        pass

    stream = open(log, "w", encoding="utf-8", errors="replace", buffering=1)

    sys.stdout = stream
    sys.stderr = stream


def _show_crash(text):

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()

        messagebox.showerror(
            "DCS ATC",
            "DCS ATC hit an error and has to close.\n\n"
            f"{text.strip().splitlines()[-1]}\n\n"
            f"Details are in:\n{user_path('log.txt')}"
        )

    except Exception:
        pass


if __name__ == "__main__":

    multiprocessing.freeze_support()

    # helper modes (run elevated by the app / installer / uninstaller)
    if len(sys.argv) > 1 and sys.argv[1] in (
        "--patch-missionscripting", "--restore-missionscripting"
    ):
        import mission_scripting

        sys.exit(mission_scripting.cli(sys.argv[1:]))

    if FROZEN:
        _redirect_output()

    try:

        from interface import run

        run()

    except Exception:

        details = traceback.format_exc()

        print(details)

        if FROZEN:
            _show_crash(details)

        raise
