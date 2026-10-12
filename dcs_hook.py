"""
Puts the DCS auto-loader in place so the bridge script runs in every mission
without touching the Mission Editor:

    Saved Games\\DCS*\\Scripts\\Hooks\\wingman_loader.lua            (DCS runs this itself)
    Saved Games\\DCS*\\Scripts\\WingmanBridge\\wingman_bridge.lua    (the bridge it starts)

Done by the app on every start (only rewrites a file when it changed), for
each DCS variant that has a Saved Games folder: DCS, DCS.openbeta, ...
"""

import os
import sys
from pathlib import Path

from app_paths import app_dir

VARIANTS = ("DCS", "DCS.openbeta", "DCS.openalpha")

HOOK_NAME = "wingman_loader.lua"
BRIDGE_NAME = "wingman_bridge.lua"


def saved_games_dir():
    """The user's Saved Games folder (it can be relocated on Windows)."""

    override = os.environ.get("DCS_ATC_SAVED_GAMES")

    if override:
        return Path(override)

    if sys.platform == "win32":

        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            # FOLDERID_SavedGames
            guid = GUID(
                0x4C5C32FF, 0xBB9D, 0x43B0,
                (ctypes.c_ubyte * 8)(
                    0xB5, 0xB4, 0x2D, 0x72, 0xE5, 0x4E, 0xAA, 0xA4
                )
            )

            buffer = ctypes.c_wchar_p()

            result = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(guid), 0, None, ctypes.byref(buffer)
            )

            if result == 0 and buffer.value:
                path = Path(buffer.value)
                ctypes.windll.ole32.CoTaskMemFree(buffer)
                return path

        except Exception:
            pass

    return Path.home() / "Saved Games"


def variant_folders():
    """Saved Games\\DCS* folders that exist (DCS has been run at least once)."""

    base = saved_games_dir()

    return [base / name for name in VARIANTS if (base / name).is_dir()]


def _copy_if_changed(source, target):
    """-> True if the target was created or updated."""

    data = source.read_bytes()

    if target.exists() and target.read_bytes() == data:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    return True


def install(lua_dir=None):
    """
    Returns a list of (level, message) for the log.
    Never raises - a problem here must not stop the app starting.
    """

    messages = []

    try:

        lua_dir = Path(lua_dir) if lua_dir else app_dir() / "dcs_lua"

        hook_source = lua_dir / "wingman_hook.lua"
        bridge_source = lua_dir / BRIDGE_NAME

        if not hook_source.exists() or not bridge_source.exists():
            return [("warn", f"DCS scripts not found in {lua_dir}")]

        found = variant_folders()

        if not found:
            return [(
                "warn",
                "No DCS Saved Games folder found - start DCS once, then "
                "restart this app to set up the mission loader."
            )]

        for folder in found:

            scripts = folder / "Scripts"

            changed = _copy_if_changed(
                bridge_source, scripts / "WingmanBridge" / BRIDGE_NAME
            )
            changed |= _copy_if_changed(
                hook_source, scripts / "Hooks" / HOOK_NAME
            )

            if changed:
                messages.append((
                    "info",
                    f"DCS mission loader installed/updated in {folder.name}"
                    " - restart DCS if it is running."
                ))

    except Exception as exc:

        messages.append(("warn", f"Could not set up the DCS loader: {exc}"))

    return messages
