"""
Keeps DCS's  Scripts\\MissionScripting.lua  open to the bridge.

DCS blocks `require`, `loadlib` and `package` for mission scripts, which the
bridge needs to load lua-socket. The fix is to comment out those three
lines. DCS updates/repairs put them back, so the app checks on every start.

Each line we change gets the marker below, so we can recognise our own edit
and undo exactly it (the uninstaller does that). A line the user already
commented out by hand is left alone.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from app_paths import FROZEN, app_dir, user_path

MARKER = "-- [DCS ATC] "

# an ACTIVE line like   _G['package'] = nil
BLOCK_RE = re.compile(
    r"""^(?P<indent>[ \t]*)_G\s*\[\s*['"](?:require|loadlib|package)['"]\s*\]\s*=\s*nil\b""",
)

SCRIPT = Path("Scripts") / "MissionScripting.lua"

VARIANT_DIRS = ("DCS World", "DCS World OpenBeta", "DCS World OpenAlpha",
                "DCS World Steam")

REG_KEYS = (
    r"Software\Eagle Dynamics\DCS World",
    r"Software\Eagle Dynamics\DCS World OpenBeta",
    r"Software\Eagle Dynamics\DCS World OpenAlpha",
    r"Software\WOW6432Node\Eagle Dynamics\DCS World",
    r"Software\WOW6432Node\Eagle Dynamics\DCS World OpenBeta",
)


# ---------------------------------------------------------
# finding DCS
# ---------------------------------------------------------

def _from_registry():

    found = []

    if sys.platform != "win32":
        return found

    try:
        import winreg
    except ImportError:
        return found

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key in REG_KEYS:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    value, _ = winreg.QueryValueEx(handle, "Path")
                    found.append(Path(value))
            except OSError:
                continue

    return found


def _from_default_locations():

    found = []

    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]

    for root in filter(None, roots):

        for name in VARIANT_DIRS:
            found.append(Path(root) / "Eagle Dynamics" / name)

        found.append(
            Path(root) / "Steam" / "steamapps" / "common" / "DCS World Steam"
        )

    return found


def _from_hook_records():
    """The loader hook writes the real install folder (as DCS sees it) the
    first time DCS starts - this finds installs in any location."""

    import dcs_hook

    found = []

    base = dcs_hook.saved_games_dir()

    for name in dcs_hook.VARIANTS:

        record = base / name / "Scripts" / "WingmanBridge" / "dcs_install_dir.txt"

        try:
            text = record.read_text(encoding="utf-8").strip()
        except OSError:
            continue

        if text:
            found.append(Path(text))

    return found


def find_installs(extra=()):
    """-> list of DCS install folders that contain MissionScripting.lua."""

    candidates = [Path(p) for p in extra if p]
    candidates += _from_hook_records()
    candidates += _from_registry()
    candidates += _from_default_locations()

    installs = []
    seen = set()

    for candidate in candidates:

        # the hook may report the bin folder rather than the root
        for folder in (candidate, candidate.parent):

            try:
                if not (folder / SCRIPT).is_file():
                    continue

                key = str(folder.resolve()).lower()
            except OSError:
                continue

            if key not in seen:
                seen.add(key)
                installs.append(folder)

            break

    return installs


# ---------------------------------------------------------
# reading / patching
# ---------------------------------------------------------

def _read(install):

    raw = (Path(install) / SCRIPT).read_bytes()

    return raw.decode("utf-8", errors="surrogateescape")


def status(install):
    """
    'needs_patch'  DCS is blocking the lines (open to the bridge: no)
    'patched'      we commented them out
    'ok'           nothing blocking (already edited by hand, or old format)
    """

    lines = _read(install).splitlines()

    if any(BLOCK_RE.match(line) for line in lines):
        return "needs_patch"

    if any(line.lstrip().startswith(MARKER.strip()) for line in lines):
        return "patched"

    return "ok"


def _write(install, text):

    path = Path(install) / SCRIPT

    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))


def patch(install):
    """Comment out the blocking lines. -> number of lines changed.
    Raises PermissionError when the folder needs admin rights."""

    text = _read(install)

    out = []
    changed = 0

    for line in text.splitlines(keepends=True):

        match = BLOCK_RE.match(line)

        if match:
            indent = match.group("indent")
            line = indent + MARKER + line[len(indent):]
            changed += 1

        out.append(line)

    if changed:
        _write(install, "".join(out))

    return changed


def restore(install):
    """Undo exactly what patch() did. -> number of lines restored."""

    text = _read(install)

    out = []
    changed = 0

    for line in text.splitlines(keepends=True):

        stripped = line.lstrip()

        if stripped.startswith(MARKER):
            indent = line[:len(line) - len(stripped)]
            line = indent + stripped[len(MARKER):]
            changed += 1

        out.append(line)

    if changed:
        _write(install, "".join(out))

    return changed


# ---------------------------------------------------------
# start-up check used by the app
# ---------------------------------------------------------

def check(installs=None, fix=True):
    """
    Look at every DCS install, patching what we can.
    -> list of dicts: {install, state, message, needs_admin}
    Never raises.
    """

    results = []

    try:
        installs = list(installs) if installs is not None else find_installs()
    except Exception as exc:
        return [{
            "install": None, "state": "error", "needs_admin": False,
            "message": f"Could not look for DCS: {exc}"
        }]

    for install in installs:

        entry = {"install": Path(install), "needs_admin": False}

        try:

            state = status(install)

            if state == "needs_patch" and fix:

                try:
                    patch(install)
                    entry["state"] = "fixed"
                    entry["message"] = (
                        f"DCS ({Path(install).name}): enabled sockets for "
                        "mission scripts (MissionScripting.lua)."
                    )

                except PermissionError:
                    entry["state"] = "needs_admin"
                    entry["needs_admin"] = True
                    entry["message"] = (
                        f"DCS ({Path(install).name}): MissionScripting.lua "
                        "blocks the bridge and needs administrator rights "
                        "to change."
                    )

            else:
                entry["state"] = state
                entry["message"] = f"DCS ({Path(install).name}): {state}"

        except Exception as exc:

            entry["state"] = "error"
            entry["message"] = f"DCS ({Path(install).name}): {exc}"

        results.append(entry)

    return results


# ---------------------------------------------------------
# administrator rights
# ---------------------------------------------------------

def _elevated_command(args):

    if FROZEN:
        return str(Path(sys.executable)), subprocess.list2cmdline(args)

    script = str(Path(__file__).resolve().parent / "main.py")

    return sys.executable, subprocess.list2cmdline([script] + list(args))


def run_elevated(args):
    """Start this program again as administrator (Windows UAC prompt).
    -> True if the prompt was accepted."""

    if sys.platform != "win32":
        return False

    import ctypes

    program, params = _elevated_command(args)

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", program, params, None, 0
    )

    return result > 32


# ---------------------------------------------------------
# command line: DCS ATC.exe --patch-missionscripting [folder ...]
# ---------------------------------------------------------

def cli(argv):
    """argv[0] is --patch-missionscripting or --restore-missionscripting.
    With no folders given, every DCS install found is used."""

    mode = argv[0]
    folders = [Path(a) for a in argv[1:]]

    installs = find_installs(extra=folders) if not folders else folders

    lines = []
    code = 0

    for install in installs:

        try:

            if mode == "--restore-missionscripting":
                count = restore(install)
                lines.append(f"{install}: restored {count} line(s)")
            else:
                count = patch(install)
                lines.append(f"{install}: patched {count} line(s)")

        except Exception as exc:
            code = 1
            lines.append(f"{install}: FAILED {exc}")

    try:
        user_path("log_missionscripting.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    except OSError:
        pass

    return code
