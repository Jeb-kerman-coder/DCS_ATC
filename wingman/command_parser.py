import re


# =============================================================
# SPOKEN NUMBERS  ("two two five" -> 225, "fifteen thousand" -> 15000)
# =============================================================

_DIGITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "niner": 9
}

_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19
}

_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90
}

_NUMBER_WORD = "|".join(
    sorted(
        list(_DIGITS) + list(_TEENS) + list(_TENS)
        + ["hundred", "thousand"],
        key=len,
        reverse=True
    )
)

_NUMBER_RUN = re.compile(
    rf"\b(?:{_NUMBER_WORD})"
    rf"(?:[\s-]+(?:and[\s-]+)?(?:{_NUMBER_WORD}))*\b"
)


def _evaluate_number_run(run):

    tokens = [
        token
        for token in re.split(r"[\s-]+", run)
        if token != "and"
    ]

    total = 0
    current = 0
    digit_buffer = ""

    def flush_digits():
        nonlocal current, digit_buffer
        if digit_buffer:
            current += int(digit_buffer)
            digit_buffer = ""

    for token in tokens:

        if token in _DIGITS:
            digit_buffer += str(_DIGITS[token])

        elif token in _TEENS:
            flush_digits()
            current += _TEENS[token]

        elif token in _TENS:
            flush_digits()
            current += _TENS[token]

        elif token == "hundred":
            if digit_buffer:
                current += int(digit_buffer)
                digit_buffer = ""
            current = (current or 1) * 100

        elif token == "thousand":
            if digit_buffer:
                current += int(digit_buffer)
                digit_buffer = ""
            total += (current or 1) * 1000
            current = 0

    flush_digits()

    return str(total + current)


def words_to_numbers(text):

    def replace(match):

        run = match.group(0)

        # "15 thousand": the digits are already a number, so the
        # bare word must stay for the altitude patterns to read.
        if run in ("thousand", "hundred"):

            before = text[:match.start()].rstrip()

            if before and before[-1].isdigit():
                return run

        return _evaluate_number_run(run)

    return _NUMBER_RUN.sub(replace, text)


# =============================================================
# FLIGHT ORDER PATTERNS
# =============================================================

_NOT_A_ALTITUDE = (
    r"(?!\s*(?:knots?|kts?|kt\b|degrees?|deg\b|nm\b|miles?|o'?clock))"
)

_HEADING_KEYWORD = re.compile(
    r"\b(?:heading|hdg)\s*(?:to\s*)?(\d{1,3})\b"
)

_HEADING_TURN = re.compile(
    r"\b(?:turn|come|steer)\s+(?:(?:left|right)\s+)?to\s+(\d{3})\b"
)

_ALTITUDE_VERB = re.compile(
    r"\b(?P<verb>climb|descend|ascend|altitude|angels|flight\s*level|fl)\b"
    r"(?:\s+and\s+maintain)?"
    r"(?:\s+(?:to|at))?"
    r"(?:\s+(?P<unit>angels|flight\s*level|fl|altitude))?"
    r"\s*(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<suffix>thousand|k\b|feet|ft\b))?"
    + _NOT_A_ALTITUDE
)

_ALTITUDE_UNIT_ONLY = re.compile(
    r"\b(?P<num>\d[\d,]*)\s*(?P<suffix>feet|ft\b|thousand)"
)

_SPEED_VERB = re.compile(
    r"\b(?:speed(?:\s*up)?|airspeed|accelerate|decelerate|slow(?:\s*down)?)\b"
    r"(?:\s+(?:to|at))?\s*(\d{2,3})\b"
    r"(?!\s*(?:thousand|k\b|feet|ft\b|degrees?|nm\b|miles?))"
)

_SPEED_UNIT = re.compile(
    r"\b(\d{2,3})\s*(?:knots?|kts?|kt\b)"
)

_RELATIVE_TURN = re.compile(
    r"\b(?:turn|come|steer|veer|bank|hook)\s+(?P<dir>left|right)\s+"
    r"(?:by\s+)?(?P<deg>\d{1,3})\b(?!\s*o'?clock)"
)

_RELATIVE_TURN_DEGREES = re.compile(
    r"\b(?P<dir>left|right)\s+(?:by\s+)?(?P<deg>\d{1,3})\s*(?:degrees?|deg)\b"
)

_TURN_AROUND = re.compile(
    r"\b(?:turn around|reverse course|one eighty|180 turn)\b"
)


# =============================================================
# ORDER PATTERNS (checked before contact / hostile logic)
# =============================================================

_RE_RESUME = re.compile(
    r"\b(?:resume(?:\s+(?:mission|route|patrol|navigation))?"
    r"|continue\s+(?:the\s+)?(?:mission|route|patrol)"
    r"|(?:back|return)\s+to\s+(?:the\s+)?(?:mission|route))\b"
)

_RE_CANCEL = re.compile(
    r"\b(?:stand\s*by|cancel\s+(?:that|orders?|order)|disregard"
    r"|belay\s+(?:that|my\s+last)|as\s+you\s+were|scratch\s+that)\b"
)

_RE_ATTACK = re.compile(
    r"\b(?:engage|attack)\b(?P<target>[^,.;!?]*)"
)

_RE_NOT_ATTACK = re.compile(
    r"\b(?:under|an|being|getting|got)\s+attack\b"
)

_GENERIC_TARGETS = {
    "", "it", "them", "him", "that", "this", "target", "targets",
    "bandit", "bandits", "bogey", "bogeys", "contact", "contacts",
    "hostile", "hostiles", "now", "please"
}

_RE_ORBIT = re.compile(
    r"\b(?:orbit|loiter|hold\s+(?:here|position)|circle\s+(?:here|overhead)|racetrack)\b"
)

_RE_FOLLOW = re.compile(
    r"\b(?:follow\s+me|form\s+up|formate|join\s+up|rejoin|on\s+my\s+wing"
    r"|fall\s+in|tuck\s+in|get\s+in\s+formation|close\s+it\s+up)\b"
)

_RE_EMCON_OFF = re.compile(
    r"\b(?:emcon\s*(?:off|cancel|cancelled|normal|release|released)"
    r"|emissions?\s*(?:on|free|normal)|cancel\s+emcon|break\s+emcon)\b"
)

_RE_EMCON_ON = re.compile(
    r"\b(?:emcon|go\s+dark|go\s+silent|silent\s+running"
    r"|emissions?\s*(?:off|control)|radio\s+silence)\b"
)

_RE_RADAR = re.compile(
    r"\bradars?\s+(?P<state>on|active|up|off|standby|silent|dark|down)\b"
)

_RE_CM_OFF = re.compile(
    r"\b(?:no|stop|cease|cancel|disable|hold)\s+(?:the\s+)?"
    r"(?:flares?|chaff|countermeasures)\b"
    r"|\b(?:flares?|chaff|countermeasures)\s+(?:off|cease|stop|cancel)\b"
)

_RE_CM = re.compile(
    r"\b(?P<kind>flares?|chaff|countermeasures)\b"
)

_RE_WEAPONS_HOT = re.compile(
    r"\b(?:weapons\s+hot|cleared\s+weapons\s+hot|weapons\s+free)\b"
)

_RE_WEAPONS_COLD = re.compile(
    r"\b(?:weapons\s+cold|cold\s+weapons|weapons\s+hold|hold\s+fire|cease\s+fire)\b"
)

_RE_BEARING_DEGREES = re.compile(
    r"(?:\bbearing\s*(\d{1,3})\b|(\d{1,3})\s*(?:degrees?|deg)\b)"
)

_RE_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:nm|miles?)\b"
)

_RE_CLOCK = re.compile(
    r"(\d{1,2})\s*o'?clock"
)


def _clean_target(raw):

    """
    "the bandit 1 and climb" -> "bandit 1"
    Returns None when nothing specific was named ("engage", "engage them").
    """

    target = raw.strip()

    target = re.split(
        r"\s+(?:then|and|climb|descend|turn|speed|accelerate)\b",
        target,
        maxsplit=1
    )[0]

    previous = None

    while previous != target:

        previous = target

        target = re.sub(
            r"^(?:the|that|those|these|my|our|group|flight)\s+",
            "",
            target
        ).strip()

    if target in _GENERIC_TARGETS:
        return None

    return target


class CommandParser:

    def __init__(self):

        print("COMMAND PARSER: Ready")

    def parse(self, text):

        text = text.lower().strip()

        # Orders to the wingman come first, so "engage bandit 1" or
        # "break left, bandit six o'clock" are orders, not contact reports.
        order = self._parse_orders(text)

        if order:
            return order

        # =====================================================
        # CONTACT SYSTEM
        # =====================================================

        if re.search(
            r"\b(?:contact|bogey)\b",
            text
        ):

            clock_match = re.search(
                r"(\d{1,2})\s*o'?clock",
                text
            )

            bearing_match = re.search(
                r"(?:bearing\s*)?"
                r"(\d{1,3})\s*"
                r"(?:degrees?|deg)\b",
                text
            )

            range_match = re.search(
                r"(\d+(?:\.\d+)?)\s*"
                r"(?:nm|miles?)",
                text
            )

            angels_match = re.search(
                r"angels\s*"
                r"(\d+(?:\.\d+)?)",
                text
            )

            hostile_match = re.search(
                r"\b(?:"
                r"hostile|"
                r"bandit|"
                r"confirmed hostile|"
                r"confirmed bandit"
                r")\b",
                text
            )

            fast_mover_match = re.search(
                r"\bfast\s*mover\b",
                text
            )

            # -------------------------------------------------
            # BEARING
            # -------------------------------------------------

            bearing = None

            if clock_match:

                clock = int(
                    clock_match.group(1)
                )

                bearing = (
                    (clock % 12) * 30
                )

            elif bearing_match:

                bearing = int(
                    bearing_match.group(1)
                )

                if bearing == 360:
                    bearing = 0

                if bearing > 360:
                    bearing = None

            # -------------------------------------------------
            # RANGE
            # -------------------------------------------------

            range_nm = None

            if range_match:

                range_nm = float(
                    range_match.group(1)
                )

            # -------------------------------------------------
            # ALTITUDE
            # -------------------------------------------------

            altitude = None

            if angels_match:

                altitude = (
                    float(
                        angels_match.group(1)
                    ) * 1000
                )

            # -------------------------------------------------
            # CONTACT DETAILS
            # -------------------------------------------------

            # "3 o'clock" is off the nose, "270 degrees" is a compass bearing
            bearing_ref = None

            if bearing is not None:

                bearing_ref = (
                    "rel"
                    if clock_match
                    else "abs"
                )

            fast_mover = (
                fast_mover_match is not None
            )

            hostile = (
                hostile_match is not None
            )

            is_update = (
                "contact is" in text
                or "bogey is" in text
            )

            # -------------------------------------------------
            # UPDATE EXISTING CONTACT
            # -------------------------------------------------

            if is_update:

                has_update_information = (
                    bearing is not None
                    or range_nm is not None
                    or altitude is not None
                    or fast_mover
                    or hostile
                )

                if has_update_information:

                    return {
                        "action": "UPDATE_CONTACT",
                        "parameters": {
                            "bearing": bearing,
                            "bearing_ref": bearing_ref,
                            "range_nm": range_nm,
                            "altitude": altitude,
                            "fast_mover": (
                                True
                                if fast_mover
                                else None
                            ),
                            "hostile": (
                                True
                                if hostile
                                else None
                            )
                        }
                    }

            # -------------------------------------------------
            # NEW CONTACT
            # -------------------------------------------------

            has_contact_information = (
                bearing is not None
                or range_nm is not None
                or altitude is not None
                or fast_mover
                or hostile
            )

            if has_contact_information:

                return {
                    "action": "CONTACT_REPORT",
                    "parameters": {
                        "bearing": bearing,
                        "bearing_ref": bearing_ref,
                        "range_nm": range_nm,
                        "altitude": altitude,
                        "fast_mover": fast_mover,
                        "hostile": hostile
                    }
                }

        # =====================================================
        # STANDALONE HOSTILE
        # =====================================================

        if re.search(
            r"\b(?:hostile|bandit)\b",
            text
        ):

            return {
                "action": "DECLARE_HOSTILE",
                "parameters": {}
            }

        # =====================================================
        # AIRCRAFT IDENTIFICATION
        # =====================================================

        aircraft_types = [
            "mig-29",
            "mig 29",
            "su-27",
            "su 27",
            "su-30",
            "su 30",
            "su-35",
            "su 35",
            "su-33",
            "su 33",
            "f-16",
            "f16",
            "f-15",
            "f15",
            "f-14",
            "f14",
            "f-18",
            "f18",
            "f-22",
            "f22",
            "f-35",
            "f35"
        ]

        for aircraft_type in aircraft_types:

            if aircraft_type in text:

                return {
                    "action": "IDENTIFY_CONTACT",
                    "parameters": {
                        "type": aircraft_type.upper()
                    }
                }

        # =====================================================
        # FLIGHT CONTROL (heading / altitude / speed)
        # =====================================================
        # One utterance can hold several orders, e.g.
        # "turn heading 225, climb 15000, accelerate 250 knots"

        flight = self._parse_flight(text)

        if flight:

            return {
                "action": "FLIGHT_COMMAND",
                "parameters": flight
            }

        # =====================================================
        # WEAPON CALLS
        # =====================================================

        weapon_calls = {

            "fox 1": "FOX_1",
            "fox one": "FOX_1",

            "fox 2": "FOX_2",
            "fox two": "FOX_2",

            "fox 3": "FOX_3",
            "fox three": "FOX_3",

            "magnum": "MAGNUM",
            "rifle": "RIFLE",
            "pitbull": "PITBULL"
        }

        for phrase, action in weapon_calls.items():

            if phrase in text:

                return {
                    "action": action,
                    "parameters": {}
                }

        # =====================================================
        # INBOUND
        # =====================================================

        if "inbound" in text:

            spoken = words_to_numbers(text)

            # "missile inbound" / "SAM inbound" is a threat call, not a
            # request to go anywhere.
            is_threat_call = bool(
                re.search(
                    r"\b(?:missile|sam|aaa|spike|mud|launch|launched)\b",
                    spoken
                )
            )

            bearing = None
            bearing_ref = None
            range_nm = None

            bearing_match = _RE_BEARING_DEGREES.search(spoken)
            clock_match = _RE_CLOCK.search(spoken)
            range_match = _RE_RANGE.search(spoken)

            if clock_match:
                bearing = (int(clock_match.group(1)) % 12) * 30
                bearing_ref = "rel"
            elif bearing_match:
                value = int(bearing_match.group(1) or bearing_match.group(2))
                if value <= 360:
                    bearing = value % 360
                    bearing_ref = "abs"

            if range_match:
                range_nm = float(range_match.group(1))

            return {
                "action": "INBOUND",
                "parameters": {
                    "vector": not is_threat_call,
                    "bearing": bearing,
                    "bearing_ref": bearing_ref,
                    "range_nm": range_nm
                }
            }

        return None

    # =========================================================
    # FLIGHT ORDER EXTRACTION
    # =========================================================

    def _parse_flight(self, text):
        """
        Pull any heading / altitude / speed orders out of one
        utterance. Returns a dict containing only what was
        ordered (heading deg, altitude ft, speed kt), or None.
        """

        text = words_to_numbers(text)

        flight = {}

        # ----- heading -----

        match = (
            _HEADING_KEYWORD.search(text)
            or _HEADING_TURN.search(text)
        )

        if match:

            heading = int(match.group(1))

            if 0 <= heading <= 360:
                flight["heading"] = heading % 360

        # ----- relative turn ("turn left 90", "come right 20") -----

        if "heading" not in flight:

            turn = self._parse_relative_turn(text)

            if turn is not None:

                if isinstance(turn, tuple):
                    flight["heading"] = turn[0]
                else:
                    flight["turn"] = turn

        # ----- altitude -----

        altitude = self._parse_altitude(text)

        if altitude is not None:
            flight["altitude"] = altitude

        # ----- speed -----

        match = (
            _SPEED_VERB.search(text)
            or _SPEED_UNIT.search(text)
        )

        if match:
            flight["speed"] = int(match.group(1))

        return flight or None

    @staticmethod
    def _parse_altitude(text):

        match = _ALTITUDE_VERB.search(text)

        if match:

            number = float(match.group("num").replace(",", ""))
            suffix = match.group("suffix")

            unit_word = (
                match.group("unit")
                or match.group("verb")
            ).replace(" ", "")

            if unit_word == "angels":
                return round(number * 1000)

            if unit_word in ("flightlevel", "fl"):
                return round(number * 100)

            if suffix in ("thousand", "k"):
                return round(number * 1000)

            # "climb 15" -> 15,000 ft ; "climb 15000" -> 15,000 ft
            if number < 100:
                return round(number * 1000)

            return round(number)

        match = _ALTITUDE_UNIT_ONLY.search(text)

        if match:

            number = float(match.group("num").replace(",", ""))

            if match.group("suffix") == "thousand":
                return round(number * 1000)

            return round(number)

        return None

    @staticmethod
    def _parse_relative_turn(text):
        """
        Signed degrees (left negative) for "turn left 90" / "right 20
        degrees" / "turn around". A leading-zero or >180 number is really a
        heading ("turn left 090"), returned as a 1-tuple (heading,).
        """

        if _TURN_AROUND.search(text):
            return 180

        match = (
            _RELATIVE_TURN.search(text)
            or _RELATIVE_TURN_DEGREES.search(text)
        )

        if not match:
            return None

        digits = match.group("deg")
        degrees = int(digits)

        if (len(digits) == 3 and digits.startswith("0")) or degrees > 180:
            return (degrees % 360,)

        if degrees == 0:
            return None

        return -degrees if match.group("dir") == "left" else degrees

    # =========================================================
    # ORDERS TO THE WINGMAN
    # =========================================================

    def _parse_orders(self, text):

        spoken = words_to_numbers(text)

        # ----- resume / cancel -----

        if _RE_RESUME.search(spoken):
            return {"action": "RESUME", "parameters": {}}

        if _RE_CANCEL.search(spoken):
            return {"action": "CANCEL_ORDERS", "parameters": {}}

        # ----- attack / engage -----

        match = _RE_ATTACK.search(spoken)

        if match and not _RE_NOT_ATTACK.search(spoken):

            return {
                "action": "ATTACK",
                "parameters": {
                    "target": _clean_target(match.group("target"))
                }
            }

        # ----- return to base -----

        if (
            "rtb" in spoken
            or "return to base" in spoken
            or "returning to base" in spoken
        ):
            return {"action": "RTB", "parameters": {}}

        # ----- bugout -----

        if (
            "bugout" in spoken
            or "bug out" in spoken
            or "scram" in spoken
        ):
            return {"action": "BUGOUT", "parameters": {}}

        # ----- break -----

        break_match = re.search(r"\bbreak\s+(left|right)\b", spoken)

        if break_match:
            return {
                "action": "BREAK",
                "parameters": {"direction": break_match.group(1)}
            }

        # ----- intercept / investigate / merge / defending -----

        if "intercept" in spoken:
            return {"action": "INTERCEPT", "parameters": {}}

        if (
            "go check" in spoken
            or "check them out" in spoken
            or "check 'em out" in spoken
            or "investigate" in spoken
        ):

            clock = None
            direction = None

            clock_match = _RE_CLOCK.search(spoken)

            if clock_match:
                clock = int(clock_match.group(1))
                direction = f"{clock} o'clock"

            return {
                "action": "INVESTIGATE_CONTACT",
                "parameters": {"direction": direction, "clock": clock}
            }

        if re.search(r"\bmerg(?:e|ed|ing)\b", spoken):
            return {"action": "MERGE", "parameters": {}}

        if re.search(r"\bdefending\b", spoken):
            return {"action": "DEFENDING", "parameters": {}}

        # ----- orbit -----

        if _RE_ORBIT.search(spoken):

            parameters = {}

            altitude = self._parse_altitude(spoken)

            if altitude is not None:
                parameters["altitude"] = altitude

            speed = (
                _SPEED_VERB.search(spoken)
                or _SPEED_UNIT.search(spoken)
            )

            if speed:
                parameters["speed"] = int(speed.group(1))

            return {"action": "ORBIT", "parameters": parameters}

        # ----- follow / form up -----

        if _RE_FOLLOW.search(spoken):

            formation = "right"

            if re.search(r"\bleft\b", spoken):
                formation = "left"
            elif re.search(r"\btrail\b", spoken):
                formation = "trail"
            elif re.search(r"\b(?:line\s+abreast|abreast)\b", spoken):
                formation = "abreast"

            return {
                "action": "FOLLOW",
                "parameters": {"formation": formation}
            }

        # ----- EMCON / radar -----

        if _RE_EMCON_OFF.search(spoken):
            return {"action": "EMCON", "parameters": {"enable": False}}

        if _RE_EMCON_ON.search(spoken):
            return {"action": "EMCON", "parameters": {"enable": True}}

        match = _RE_RADAR.search(spoken)

        if match:

            return {
                "action": "RADAR",
                "parameters": {
                    "enable": match.group("state") in ("on", "active", "up")
                }
            }

        # ----- flares / chaff -----

        match = _RE_CM.search(spoken)

        if match:

            kind = match.group("kind")

            action = (
                "CHAFF" if kind == "chaff"
                else "COUNTERMEASURES" if kind == "countermeasures"
                else "FLARE"
            )

            return {
                "action": action,
                "parameters": {"enable": not _RE_CM_OFF.search(spoken)}
            }

        # ----- weapons -----

        if _RE_WEAPONS_HOT.search(spoken):
            return {"action": "WEAPONS_HOT", "parameters": {}}

        if _RE_WEAPONS_COLD.search(spoken):
            return {"action": "WEAPONS_COLD", "parameters": {}}

        return None