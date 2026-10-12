"""
WingmanController - everything the old wingman console app's main.py did,
minus the console.

    list_candidates()        AI aircraft you can assign as wingman
    select(name)             assign one (callsign, state, ROE, callouts)
    release()                stop managing it
    hear(text)               something the pilot said to the wingman
                             -> parses orders, sends them to DCS, and
                                returns the wingman's spoken reply
    developer_command("/x")  /sam /clear /reset /status

Output goes through two callbacks supplied by the GUI:
    log(source, message)     radio log lines
    speak(text, urgent)      text to speech
"""

import threading
import time

from .callouts import CalloutManager
from .callsigns import format_callsign
from .command_parser import CommandParser
from .dcs_commander import DCSCommander
from .dcs_events import DCSEventListener
from .dcs_orders import dispatch_to_dcs, is_dcs_order, sync_initial_state
from .dcs_telemetry import DCSTelemetry
from .llm import Wingman
from .state import WingmanState


class WingmanController:

    def __init__(self, log=None, speak=None, llm=None,
                 model="gemma3:12b", keep_alive="60m"):

        self._log = log or (lambda source, message: None)
        self._speak = speak

        self.state = WingmanState()
        self.telemetry = DCSTelemetry(self.state)
        self.commander = DCSCommander()
        self.command_parser = CommandParser()
        self.llm = (
            llm if llm is not None
            else Wingman(self.state, model=model, keep_alive=keep_alive)
        )

        self.callouts = CalloutManager(
            self.state,
            self.telemetry,
            speak=self._speak_callout,
            on_announce=lambda text: self._log("WINGMAN", text)
        )

        self.listener = DCSEventListener(
            self.callouts.handle_event,
            keepalive=self._keepalive
        )

        self.selected_name = None
        self.callsign = None

        self._lock = threading.Lock()

    # =========================================================
    # LIFECYCLE
    # =========================================================

    def start(self):

        self.telemetry.start()
        self.listener.start()

    def stop(self):

        for step in (
            self.release,
            self.listener.stop,
            self.telemetry.stop,
            self.commander.close
        ):
            try:
                step()
            except Exception as exc:
                print(f"WINGMAN: shutdown step failed: {exc}")

    # =========================================================
    # DCS LINK STATUS
    # =========================================================

    def bridge_online(self):

        return self.telemetry.is_connected()

    def lead(self):
        """The human pilot's aircraft as reported by DCS, or None."""

        return self.telemetry.get_player_unit()

    def lead_callsign(self):

        unit = self.lead()

        if unit:
            return format_callsign(
                unit.get("callsign") or unit.get("name"),
                "Lead"
            )

        return "Lead"

    # =========================================================
    # SELECTION
    # =========================================================

    def list_candidates(self):

        return self.telemetry.get_candidates()

    def selected_unit(self):

        if not self.selected_name:
            return None

        return self.telemetry.get_selected_unit()

    def select(self, unit_name):
        """Assign an aircraft as your wingman. Returns the unit or None."""

        candidates = {
            unit["name"]: unit for unit in self.list_candidates()
        }

        unit = candidates.get(unit_name)

        if unit is None:
            self._log("WINGMAN", f"{unit_name} is not available.")
            return None

        with self._lock:

            if self.selected_name and self.selected_name != unit_name:
                self._release_locked()

            self.selected_name = unit_name

            self.callsign = format_callsign(
                unit.get("callsign"),
                unit.get("name")
            )

            # a different aircraft is a different pilot: fresh state
            self.state.reset()
            self.state.set_callsign(self.callsign)
            self.llm.reset_history()

            self.telemetry.select_unit(unit_name)
            self.state.update_dcs_telemetry(unit)

        # DCS side: weapons hold to match the wingman's COLD state, and
        # ask the Lua bridge to report this aircraft's shots/contacts
        sync_initial_state(
            self.state,
            self.telemetry,
            self.commander,
            log=lambda message: self._log("DCS", message.replace("[DCS] ", "", 1))
        )

        self.commander.watch(unit_name)

        self._log(
            "WINGMAN",
            f"{self.callsign} assigned "
            f"({unit.get('type') or 'unknown type'})."
        )

        return unit

    def release(self):

        with self._lock:
            self._release_locked()

    def _release_locked(self):

        name = self.selected_name

        if not name:
            return

        try:
            self.commander.clear(name)
        except Exception as exc:
            print(f"WINGMAN: release failed: {exc}")

        self._log("WINGMAN", f"{self.callsign} released.")

        self.selected_name = None
        self.callsign = None

        self.telemetry.select_unit(None)

    def _keepalive(self):
        """Re-send the 'watch this aircraft' request so callouts survive
        a mission restart in DCS."""

        name = self.selected_name

        if name:
            self.commander.watch(name)

    # =========================================================
    # OUTPUT
    # =========================================================

    def _speak_callout(self, text):

        if self._speak:
            self._speak(text, True)

    def _say(self, text):

        if self._speak:
            self._speak(text, False)

    # =========================================================
    # PILOT -> WINGMAN
    # =========================================================

    def addressed(self, text):
        """Does this sound like it was meant for the wingman? Used when
        'require callsign' is on for the hot mic."""

        if not self.callsign:
            return False

        spoken = text.lower()

        words = {
            "wingman",
            "two",
            "2",
            "dash two",
        }

        parts = self.callsign.lower().split()

        # "colt" / "colt 1-2" / "colt one two"
        if parts and parts[0] in spoken:
            return True

        return any(
            f" {word} " in f" {spoken.replace(',', ' ').replace('.', ' ')} "
            for word in words
        )

    def hear(self, text, speak=True, stt_seconds=None):
        """
        The pilot said something to the wingman. Parses it, executes any
        order, and returns the wingman's reply (also spoken when speak).
        Returns None when no wingman is assigned.
        """

        text = (text or "").strip()

        if not text:
            return None

        if not self.selected_name:
            self._log("WINGMAN", "No wingman assigned.")
            return None

        if text.startswith("/"):
            self.developer_command(text)
            return None

        self._log("YOU", text)

        try:
            self._process_command(text)
        except Exception as exc:
            print(f"WINGMAN: command failed: {exc}")

        started = time.time()

        reply = self.llm.respond(
            text,
            wingman_callsign=self.callsign or "Two",
            lead_callsign=self.lead_callsign()
        )

        llm_seconds = time.time() - started

        timing = f"LLM {llm_seconds:.1f}s"

        if stt_seconds is not None:
            timing = f"STT {stt_seconds:.1f}s · " + timing

        self._log("TIMING", timing)

        if not reply:
            self._log("WINGMAN", "[no response]")
            return None

        self._log("WINGMAN", reply)

        if speak:
            self._say(reply)

        return reply

    # ---------------------------------------------------------
    # command execution (was process_player_command in main.py)
    # ---------------------------------------------------------

    def _contact_text(self, contact):

        bearing = contact.get("bearing")
        range_nm = contact.get("range_nm")

        bearing_text = (
            "bearing unknown" if bearing is None else f"{bearing:03.0f}°"
        )

        range_text = (
            "range unknown" if range_nm is None else f"{range_nm} NM"
        )

        return (
            f"#{contact['id']} {bearing_text} {range_text} "
            f"{contact['status']}"
        )

    def _process_command(self, text):

        command = self.command_parser.parse(text)

        if not command:
            return

        action = command.get("action")
        parameters = command.get("parameters", {})
        state = self.state

        if action == "CONTACT_REPORT":

            contact = state.add_contact(
                bearing=parameters.get("bearing"),
                range_nm=parameters.get("range_nm"),
                altitude=parameters.get("altitude"),
                fast_mover=parameters.get("fast_mover", False),
                hostile=parameters.get("hostile", False),
                bearing_ref=parameters.get("bearing_ref")
            )

            self._log("CONTACT", self._contact_text(contact))

            return

        if action in ("UPDATE_CONTACT", "IDENTIFY_CONTACT", "DECLARE_HOSTILE"):

            contact = state.get_latest_contact()

            if contact is None:
                self._log("CONTACT", "No contact available.")
                return

            if action == "UPDATE_CONTACT":

                updates = {
                    key: parameters[key]
                    for key in (
                        "bearing", "bearing_ref", "range_nm", "altitude",
                        "fast_mover", "type", "hostile"
                    )
                    if parameters.get(key) is not None
                }

                updated = state.update_contact(contact["id"], **updates)

                if updated:
                    self._log("CONTACT", f"Contact {updated['id']} updated")

            elif action == "IDENTIFY_CONTACT":

                updated = state.update_contact(
                    contact["id"],
                    type=parameters.get("type")
                )

                if updated:
                    self._log(
                        "CONTACT",
                        f"Contact {updated['id']} identified as "
                        f"{updated['type']}"
                    )

            else:

                updated = state.set_contact_hostile(contact["id"])

                if updated:
                    self._log(
                        "CONTACT",
                        f"Contact {updated['id']} declared HOSTILE"
                    )

            return

        if is_dcs_order(command):

            dispatch_to_dcs(
                command,
                state,
                self.telemetry,
                self.commander,
                log=lambda message: self._log("DCS", message.replace("[DCS] ", "", 1))
            )

            return

        if state.execute_command(command):
            self._log("CMD", str(command))

    # =========================================================
    # DEVELOPER COMMANDS
    # =========================================================

    def developer_command(self, command):

        parts = command.strip().split()

        if not parts:
            return

        name = parts[0].lower()

        if name == "/sam" and len(parts) >= 3 and parts[1].lower() == "launch":

            direction = " ".join(parts[2:])
            self.state.set_threat("SAM", direction)
            self._log("EVENT", f"SAM launch detected {direction}")

        elif name == "/clear":

            self.state.clear_threat()
            self._log("EVENT", "Threat cleared")

        elif name == "/reset":

            self.state.reset()
            self.llm.reset_history()
            self._log("EVENT", "Wingman state reset")

        elif name == "/status":

            state = self.state
            aircraft = state.aircraft

            self._log(
                "STATUS",
                f"mode {state.mode} | threat {state.threat} | "
                f"hdg {aircraft['heading']} alt {aircraft['altitude']} "
                f"spd {aircraft['speed']} | "
                f"weapons {state.tactical['weapons_status']} | "
                f"{len(state.get_contacts())} contacts"
            )

            for contact in state.get_contacts():
                self._log("STATUS", self._contact_text(contact))

        else:

            self._log(
                "WINGMAN",
                "Commands: /sam launch left, /clear, /reset, /status"
            )
