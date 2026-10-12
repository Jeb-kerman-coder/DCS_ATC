import threading
import time

WEAPON_CALLS = {
    "FOX_1": "Fox one.",
    "FOX_2": "Fox two.",
    "FOX_3": "Fox three.",
    "MAGNUM": "Magnum.",
    "RIFLE": "Rifle.",
    "PICKLE": "Pickle.",
    "ROCKETS": "Rockets away.",
    "GUNS": "Guns, guns."
}

NUMBER_WORDS = [
    "zero", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten"
]

# The same call twice inside this window is one call (ripple fire).
DUPLICATE_WINDOW_S = 1.5

# Contacts the wingman reported itself are dropped after this long.
CONTACT_LIFETIME_S = 300


def _number_word(value):

    if 0 <= value < len(NUMBER_WORDS):
        return NUMBER_WORDS[value]

    return str(value)


def _round(value):
    return int(float(value) + 0.5)


class CalloutManager:
    """
    Turns events from DCS into things the wingman says unprompted:
    "Fox three.", "Wheels up.", "Contact, 12 o'clock, 20 miles, angels 25."

    Only events for the selected wingman aircraft are used. Each callout
    is printed, optionally spoken (speak = a function taking the text,
    e.g. your text-to-speech), and noted in the wingman's state so the
    conversation can refer to it afterwards.
    """

    def __init__(self, state, telemetry, speak=None, on_announce=None):

        self.state = state
        self.telemetry = telemetry
        self.speak = speak

        # on_announce(text): show the callout somewhere (the GUI log).
        # Without it the callout is printed to the console.
        self.on_announce = on_announce

        self._lock = threading.Lock()
        self._last_call = {}

    # =========================================================
    # ENTRY POINT
    # =========================================================

    def handle_event(self, event):

        unit = self.telemetry.get_selected_unit()

        if not unit or event.get("unit") != unit.get("name"):
            return

        handler = getattr(
            self,
            f"_on_{str(event.get('type')).lower()}",
            None
        )

        if handler:
            handler(event)

    # =========================================================
    # OUTPUT
    # =========================================================

    def announce(self, text):

        if self.on_announce:

            try:
                self.on_announce(text)
            except Exception as exc:
                print(f"[CALLOUT] display failed: {exc}")

        else:

            with self._lock:

                print(f"\n2: {text}")
                print("YOU: ", end="", flush=True)

        self.state.log_event(text)

        if self.speak:

            try:
                self.speak(text)
            except Exception as exc:
                print(f"[CALLOUT] speech failed: {exc}")

    def _is_duplicate(self, key, window=DUPLICATE_WINDOW_S):

        now = time.time()

        last = self._last_call.get(key)

        self._last_call[key] = now

        return last is not None and now - last < window

    # =========================================================
    # EVENTS
    # =========================================================

    def _on_weapon(self, event):

        text = WEAPON_CALLS.get(event.get("callout"))

        if not text:
            return

        if self._is_duplicate(("weapon", event.get("callout"))):
            return

        self.state.mode = "COMBAT"

        self.announce(text)

    def _on_takeoff(self, event):

        self.state.flight["on_ground"] = False
        self.state.flight["gear"] = "UP"

        self.announce("Wheels up.")

    def _on_land(self, event):

        self.state.flight["on_ground"] = True
        self.state.flight["gear"] = "DOWN"

        self.announce("Wheels down.")

    def _on_kill(self, event):

        if not event.get("air"):

            self.announce("Target destroyed.")

            return

        self.state.kills += 1

        self.announce(
            f"Splash {_number_word(self.state.kills)}."
        )

    def _on_contact(self, event):

        visual = event.get("kind") == "visual"

        clock = _round(event.get("rel_deg", 0) / 30.0) % 12 or 12

        parts = [
            "Tally" if visual else "Contact",
            f"{clock} o'clock"
        ]

        range_nm = event.get("range_nm")

        if range_nm is not None:

            miles = _round(range_nm)

            parts.append(
                "1 mile" if miles <= 1 else f"{miles} miles"
            )

        altitude = event.get("alt_ft")

        if altitude is not None:

            angels = _round(altitude / 1000.0)

            parts.append(
                f"angels {angels}" if angels >= 1 else "on the deck"
            )

        count = event.get("count") or 1

        if count > 1:
            parts.append(f"group of {count}")

        if event.get("target_type"):
            parts.append(str(event["target_type"]))

        # Remember it, so "intercept" works on what the wingman found.
        self._remember_contact(event)

        self.announce(", ".join(parts) + ".")

    # =========================================================
    # CONTACT MEMORY
    # =========================================================

    def _remember_contact(self, event):

        contacts = self.state.tactical["contacts"]

        cutoff = time.time() - CONTACT_LIFETIME_S

        # only the wingman's own old reports are dropped, never yours
        contacts[:] = [
            contact
            for contact in contacts
            if not (
                contact.get("source", "").startswith("WINGMAN")
                and contact.get("reported_at", 0) < cutoff
            )
        ]

        contact = self.state.add_contact(
            contact_type=(
                str(event["target_type"]).upper()
                if event.get("target_type")
                else "UNKNOWN"
            ),
            bearing=event.get("brg"),
            bearing_ref="abs",
            range_nm=event.get("range_nm"),
            altitude=event.get("alt_ft")
        )

        contact["source"] = (
            "WINGMAN_VISUAL"
            if event.get("kind") == "visual"
            else "WINGMAN_RADAR"
        )