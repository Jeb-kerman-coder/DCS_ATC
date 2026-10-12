"""MissionScripting.lua patching: python tests/test_mission_scripting.py"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mission_scripting as ms

ORIGINAL = """--Initialization script for the Mission lua Environment (SSE)

dofile('Scripts/ScriptingSystem.lua')

local function sanitizeModule(name)
\t_G[name] = nil
\tpackage.loaded[name] = nil
end

do
\tsanitizeModule('os')
\tsanitizeModule('io')
\tsanitizeModule('lfs')
\t_G['require'] = nil
\t_G['loadlib'] = nil
\t_G['package'] = nil
end
"""


def make_install(root, text=ORIGINAL, newline="\n"):

    install = Path(root) / "DCS World"
    (install / "Scripts").mkdir(parents=True)

    (install / "Scripts" / "MissionScripting.lua").write_bytes(
        text.replace("\n", newline).encode()
    )

    return install


def read(install):
    return (install / "Scripts" / "MissionScripting.lua").read_bytes().decode()


def main():

    with tempfile.TemporaryDirectory() as tmp:

        # --- patch / status / idempotent ---
        install = make_install(tmp)
        assert ms.status(install) == "needs_patch"

        assert ms.patch(install) == 3
        text = read(install)
        assert text.count("-- [DCS ATC] _G[") == 3
        assert "sanitizeModule('os')" in text          # untouched
        assert "\n\tsanitizeModule('io')\n" in text
        assert ms.status(install) == "patched"
        assert ms.patch(install) == 0                   # nothing left

        # --- restore gives back the exact original ---
        assert ms.restore(install) == 3
        assert read(install) == ORIGINAL
        assert ms.status(install) == "needs_patch"

        # --- CRLF files keep their line endings ---
        crlf = make_install(Path(tmp) / "crlf", newline="\r\n")
        ms.patch(crlf)
        raw = read(crlf)
        assert "\r\n" in raw and "\n" not in raw.replace("\r\n", "")
        ms.restore(crlf)
        assert read(crlf) == ORIGINAL.replace("\n", "\r\n")

        # --- lines the user commented out by hand are left alone ---
        manual = make_install(
            Path(tmp) / "manual",
            ORIGINAL.replace("\t_G['package'] = nil", "\t-- _G['package'] = nil"),
        )
        assert ms.patch(manual) == 2
        ms.restore(manual)
        assert "\t-- _G['package'] = nil" in read(manual)

        everything_off = make_install(
            Path(tmp) / "off",
            ORIGINAL.replace("\t_G['require'] = nil", "--_G['require'] = nil")
                    .replace("\t_G['loadlib'] = nil", "--_G['loadlib'] = nil")
                    .replace("\t_G['package'] = nil", "--_G['package'] = nil"),
        )
        assert ms.status(everything_off) == "ok"

        # --- check(): fixes it, then reports nothing to do ---
        fresh = make_install(Path(tmp) / "fresh")
        out = ms.check([fresh])
        assert out[0]["state"] == "fixed", out
        out = ms.check([fresh])
        assert out[0]["state"] == "patched", out

        # --- DCS update restores the lines -> fixed again ---
        (fresh / "Scripts" / "MissionScripting.lua").write_text(ORIGINAL)
        assert ms.check([fresh])[0]["state"] == "fixed"

        # --- no permission -> asks for admin, file untouched ---
        locked = make_install(Path(tmp) / "locked")
        real_write = ms._write

        def denied(*a, **k):
            raise PermissionError("denied")

        ms._write = denied
        try:
            out = ms.check([locked])
        finally:
            ms._write = real_write

        assert out[0]["state"] == "needs_admin" and out[0]["needs_admin"], out
        assert read(locked) == ORIGINAL

        # --- find_installs: hook record may point at the bin folder ---
        saved = Path(tmp) / "Saved Games"
        os.environ["DCS_ATC_SAVED_GAMES"] = str(saved)
        record = saved / "DCS" / "Scripts" / "WingmanBridge"
        record.mkdir(parents=True)
        (record / "dcs_install_dir.txt").write_text(str(fresh / "bin"))
        (fresh / "bin").mkdir()
        assert fresh in ms.find_installs()

        # --- command line helper ---
        cli_install = make_install(Path(tmp) / "cli")
        assert ms.cli(["--patch-missionscripting", str(cli_install)]) == 0
        assert ms.status(cli_install) == "patched"
        assert ms.cli(["--restore-missionscripting", str(cli_install)]) == 0
        assert ms.status(cli_install) == "needs_patch"

    print("mission scripting tests passed")


if __name__ == "__main__":
    main()
