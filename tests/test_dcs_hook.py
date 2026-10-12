"""DCS loader install: python tests/test_dcs_hook.py"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dcs_hook


def main():

    lua = Path(__file__).resolve().parent.parent / "dcs_lua"

    with tempfile.TemporaryDirectory() as tmp:

        saved = Path(tmp) / "Saved Games"
        os.environ["DCS_ATC_SAVED_GAMES"] = str(saved)

        # no DCS folder yet -> a warning, nothing created
        out = dcs_hook.install(lua)
        assert out and out[0][0] == "warn", out
        assert not (saved / "DCS").exists()

        # two DCS variants present
        (saved / "DCS").mkdir(parents=True)
        (saved / "DCS.openbeta").mkdir()

        out = dcs_hook.install(lua)
        assert len(out) == 2 and all(l == "info" for l, _ in out), out

        for name in ("DCS", "DCS.openbeta"):
            hook = saved / name / "Scripts" / "Hooks" / "wingman_loader.lua"
            bridge = saved / name / "Scripts" / "WingmanBridge" / "wingman_bridge.lua"
            assert hook.read_bytes() == (lua / "wingman_hook.lua").read_bytes()
            assert bridge.read_bytes() == (lua / "wingman_bridge.lua").read_bytes()

        # second start: nothing changed -> silent
        assert dcs_hook.install(lua) == []

        # a newer bridge script is picked up
        bridge = saved / "DCS" / "Scripts" / "WingmanBridge" / "wingman_bridge.lua"
        bridge.write_text("-- old version")
        out = dcs_hook.install(lua)
        assert len(out) == 1 and "DCS" in out[0][1]
        assert bridge.read_bytes() == (lua / "wingman_bridge.lua").read_bytes()

        # missing source files never raise
        out = dcs_hook.install(Path(tmp) / "nope")
        assert out and out[0][0] == "warn"

    print("dcs hook tests passed")


if __name__ == "__main__":
    main()
