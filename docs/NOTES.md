# DCS ATC + Wingman - developer notes

One window, two radios:

| | ATC / AWACS / GCI | Wingman |
|---|---|---|
| Mic | **Cold** - hold your PTT button | **Hot** - just talk, no button |
| Voice | Heavy radio effects | Cleaner "intercom" effects |
| Brain | Procedures + LLM wording | Gemma persona + order parser |

Run with `python main.py`.

## How the two mics coexist
* While PTT is held, the hot mic is deaf - your ATC call never reaches the wingman.
* While *anything* is being spoken (ATC reply or wingman), the hot mic is deaf
  so the wingman can't hear itself through your speakers. Headset still recommended.
* One speaker queue plays everything, so voices never talk over each other.
  Urgent wingman calls (Fox / splash / SAM) jump the queue.
* Mute button, "only when addressed" filter and a sensitivity threshold
  (the amber tick on the meter) are in the Wingman panel; all saved in settings.json.

## Picking a wingman
The roster lists every AI aircraft the DCS bridge reports (your own flight first).
Select one and press ASSIGN (or double-click). The assigned aircraft's callsign is used
everywhere: the wingman's persona prompt, callouts, and what he answers to.
Your own callsign/aircraft also now come from DCS and are used by ATC replies
(previously hard-coded "Colt 1-1 / F/A-18C").

## Files
* `wingman/` - the old wingman project as a package (controller.py is the old console main.py)
* `atc_pipeline.py` - ATC logic pulled out of the GUI (testable, AWACS+GCI share one path)
* `speech.py`, `tts_manager.py` - single speaker queue, two voices
* `interface.py` - the new GUI
* `tests/` - `python tests/test_pipeline.py`, `python tests/test_hotmic.py`

## DCS side
`dcs_lua/wingman_bridge.lua` is the ONE script for everything. The app installs a loader hook
(`wingman_hook.lua`, see `dcs_hook.py`) into `Saved Games\DCS*\Scripts\Hooks` on every start, so DCS runs
the bridge in every mission by itself - no Do Script File needed (a manual one still works, it only runs once). It now also feeds the AWACS/GCI (it was missing before,
which is why AWACS had no data).
Ports: 5015 AWACS picture, 5016 telemetry, 5017 orders, 5018 events.

AWACS options are at the top of the Lua (`AWACS_SOURCE`):
* `"auto"` (default): uses a friendly AI AWACS aircraft's radar if one is flying
  (E-3A, E-2C/D, A-50, KJ-2000, or any unit/group with "AWACS" in its name); otherwise
  every hostile aircraft within 200 nm.
* `"awacs"`: only what the AWACS aircraft really detects.  `"all"`: always everything.
Multiplayer: set `AWACS_PLAYER_NAME` to your DCS pilot name.

## Settings (settings.json, new keys are added automatically)
* `tts.atc_model` / `tts.wingman_model` - Piper model names. Drop a second `.onnx` voice
  next to main.py and set `wingman_model` to give him a different voice.
* `channels.tower` / `channels.awacs` - ATC and AWACS frequencies in MHz. Set them in the
  CHANNELS box on the ATC side of the window (Enter to apply); saved automatically.
  (`data/frequencies.json` is no longer used.)
* `audio.input_device` / `audio.output_device` - sounddevice index or name (null = default).
* `wingman.mic_enabled`, `wingman.require_callsign`, `wingman.mic_threshold`.

## Speed
Response = hear you -> Whisper -> LLM -> Piper -> play. The radio log shows a dim `TIMING` line
for each stage so you can see which one is slow.
* Voices stay loaded in a separate worker process (`piper_worker.py`) - no model reload per line,
  and a crash in Piper's native code cannot take the app down. Repeated lines are cached.
* Voices, Whisper and the Ollama models are loaded in the background at start-up. Wait for
  "Ready - warm-up took ..." in the log before the first transmission.
* The LLM is usually the biggest cost. Use a smaller model for the wingman and/or ATC in
  `settings.json` -> `llm.wingman_model` / `llm.atc_model` (e.g. `gemma3:4b`), and check
  `ollama ps` shows 100% GPU while DCS is running.

## DCS-BIOS
`dcs_bios_setup.py`: if no Saved Games\DCS* folder has DCS-BIOS set up, the app offers to download the
latest official release, unpack `DCS-BIOS` into `Scripts\` and append the `dofile(...BIOS.lua)` line to
`Export.lua` (an existing Export.lua is appended to, never overwritten; an existing BIOSConfig.lua is kept).
Declining turns it off (`dcs.auto_install_bios`).

## DCS MissionScripting.lua
`mission_scripting.py` comments out the three `_G['require'|'loadlib'|'package'] = nil` lines in
`DCS World\Scripts\MissionScripting.lua` (each marked `-- [DCS ATC]`) so the bridge can load lua-socket.
Setup does it, the app re-checks on every start (DCS updates restore the file; if admin rights are
needed it asks first), and uninstalling puts the lines back. Off switch: `dcs.auto_fix_mission_scripting`.

## Building the installer (Windows)
Run `build_installer.bat`. It sets up a build environment, downloads the Whisper and Piper
voice models (`fetch_models.py`), builds `dist\DCS ATC\DCS ATC.exe` with PyInstaller
(`DCS_ATC.spec`) and, if Inno Setup 6 is installed, wraps it into
`installer_output\DCS_ATC_Setup.exe` (`installer\DCS_ATC.iss`).

* Installed, the app runs as `DCS ATC.exe`. Settings, recordings and `log.txt` live in
  `%APPDATA%\DCS ATC` (the install folder is read-only); from source they stay in the project folder.
* `piper-worker.exe` sits beside it - that is the voice process, started automatically.
* Ollama (and `ollama pull gemma3:12b`) is still a separate install; see the notes shown at the end of setup.
