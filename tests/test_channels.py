"""Channel settings: python tests/test_channels.py"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from frequency_manager import FrequencyManager
from settings_manager import SettingsManager


def make(path):
    settings = SettingsManager(path)
    return settings, FrequencyManager(settings)


def main():

    with tempfile.TemporaryDirectory() as tmp:

        path = os.path.join(tmp, "settings.json")

        # defaults match the old hard-coded values
        settings, freqs = make(path)
        assert freqs.lookup(127.8)["controller"] == "TOWER"
        assert freqs.lookup(225.87)["controller"] == "AWACS"

        # change both, accept loose formats
        ok, msg, f = freqs.set_channel("tower", "251,1")
        assert ok and f == 251.1, msg
        ok, msg, f = freqs.set_channel("awacs", "305.5 MHz")
        assert ok and f == 305.5, msg

        # old frequencies no longer map to anything
        assert freqs.lookup(127.8) is None
        assert freqs.lookup(225.87) is None
        assert freqs.lookup(251.1)["controller"] == "TOWER"
        assert freqs.lookup(305.5)["controller"] == "AWACS"

        # bad input is rejected and changes nothing
        for bad in ("abc", "", "5", "999", "305.5"):
            ok, msg, _ = freqs.set_channel("tower", bad)
            assert not ok, bad
        assert freqs.get_channel("tower") == 251.1

        # "restart": brand new objects reading the same file
        settings, freqs = make(path)
        assert freqs.get_channel("tower") == 251.1
        assert freqs.get_channel("awacs") == 305.5
        assert freqs.lookup(305.5)["controller"] == "AWACS"

        # an old settings.json with no "channels" key still works
        old = os.path.join(tmp, "old.json")
        with open(old, "w") as fh:
            fh.write('{"radio": {"default_com": 2}}')
        settings, freqs = make(old)
        assert freqs.get_channel("tower") == 127.8
        assert settings.get("radio", "default_com") == 2

        # garbage saved by hand falls back to the default
        settings.settings["channels"]["tower"] = "nonsense"
        freqs.reload()
        assert freqs.get_channel("tower") == 127.8

    print("channel tests passed")


if __name__ == "__main__":
    main()
