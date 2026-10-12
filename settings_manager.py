import copy
import json
from pathlib import Path

from app_paths import user_path


class SettingsManager:

    DEFAULT_SETTINGS = {
        "ptt": {
            "device": None,
            "button": None
        },
        "audio": {
            "input_device": None,
            "output_device": None
        },
        "radio": {
            "default_com": 1
        },
        "dcs": {
            # keep the DCS mission loader (Hooks) installed and current
            "auto_install_hook": True,
            # offer to download + set up DCS-BIOS when it is missing
            "auto_install_bios": True,
            # keep DCS's MissionScripting.lua open to the bridge
            "auto_fix_mission_scripting": True
        },
        # MHz. Changed from the ATC panel in the interface.
        "channels": {
            "tower": 127.800,
            "awacs": 225.870
        },
        "llm": {
            # Ollama model names. A smaller model (e.g. "gemma3:4b") is much
            # faster, especially when DCS is using most of your VRAM.
            "atc_model": "gemma3:12b",
            "wingman_model": "gemma3:12b",
            # keep the model loaded between calls (no reload delay)
            "keep_alive": "60m"
        },
        "tts": {
            # Piper voice models (the .onnx file must sit next to main.py).
            # Give the wingman a different model to get a different voice.
            "atc_model": "en_US-ryan-high",
            "wingman_model": "en_US-ryan-high"
        },
        "wingman": {
            # Hot mic: the wingman listens continuously, no PTT needed.
            "mic_enabled": True,
            # Only react to speech that contains the wingman's callsign
            # (or "two"/"wingman"). Useful if you talk to yourself a lot.
            "require_callsign": False,
            # Voice-activity threshold (microphone RMS, 0..1). Raise it if
            # background noise keeps triggering the wingman.
            "mic_threshold": 0.006
        }
    }

    def __init__(self, filename=None):

        # installed: %APPDATA%\DCS ATC\settings.json
        self.filename = Path(filename) if filename else user_path("settings.json")

        self.settings = self.load()

    @staticmethod
    def _merge(defaults, loaded):
        """Defaults first, then whatever the file overrides.
        New settings therefore show up for old settings.json files."""

        merged = copy.deepcopy(defaults)

        for key, value in loaded.items():

            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = SettingsManager._merge(merged[key], value)
            else:
                merged[key] = value

        return merged

    def load(self):

        if not self.filename.exists():

            self.save_defaults()

            return copy.deepcopy(self.DEFAULT_SETTINGS)

        try:

            with open(self.filename, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            if not isinstance(loaded, dict):
                raise ValueError("settings.json is not an object")

            merged = self._merge(self.DEFAULT_SETTINGS, loaded)

            # 0.015 was the first release's default, written into
            # settings.json by any later save, and it is too deaf for a
            # quiet headset mic. Nobody picks it by hand on purpose.
            wingman = merged.get("wingman", {})

            if wingman.get("mic_threshold") == 0.015:
                wingman["mic_threshold"] = self.DEFAULT_SETTINGS[
                    "wingman"
                ]["mic_threshold"]

            return merged

        except (json.JSONDecodeError, OSError, ValueError):

            print("Warning: settings.json could not be loaded.")

            return copy.deepcopy(self.DEFAULT_SETTINGS)

    def save_defaults(self):

        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.DEFAULT_SETTINGS, f, indent=4)

    def save(self):

        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4)

    def get(self, section, key):

        return self.settings.get(section, {}).get(key)

    def set(self, section, key, value):

        if section not in self.settings:
            self.settings[section] = {}

        self.settings[section][key] = value

        self.save()

    def get_ptt(self):

        return self.settings.get("ptt", {})

    def set_ptt(self, device, button):

        self.settings["ptt"] = {
            "device": device,
            "button": button
        }

        self.save()
