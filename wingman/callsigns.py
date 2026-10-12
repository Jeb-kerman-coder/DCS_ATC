"""
Callsign helpers.

DCS reports a unit's callsign as one run-together string such as "Colt11" or
"Enfield21". Spoken (and in prompts) it is "Colt 1-1" / "Enfield 2-1".
"""

import re

_CALLSIGN = re.compile(
    r"^\s*([A-Za-z]+)\s*(\d)\s*[-\s]?\s*(\d)\s*$"
)


def format_callsign(raw, fallback=None):
    """'Colt11' / 'Colt 1-1' / 'colt1-1' -> 'Colt 1-1'. Anything that
    doesn't look like a flight callsign is returned cleaned-up as-is."""

    if not raw:
        return fallback

    text = str(raw).strip()

    match = _CALLSIGN.match(text)

    if match:
        name, flight, element = match.groups()
        return f"{name.capitalize()} {flight}-{element}"

    return text or fallback


# DCS type names -> how a controller would say them
_TYPES = {
    "FA-18C_hornet": "F/A-18C",
    "F-16C_50": "F-16C",
    "F-16C bl.50": "F-16C",
    "F-16C bl.52d": "F-16C",
    "F-15C": "F-15C",
    "F-15ESE": "F-15E",
    "F-14B": "F-14B",
    "F-14A-135-GR": "F-14A",
    "A-10C": "A-10C",
    "A-10C_2": "A-10C",
    "AV8BNA": "AV-8B",
    "JF-17": "JF-17",
    "M-2000C": "Mirage 2000",
    "F-5E-3": "F-5E",
    "MiG-21Bis": "MiG-21",
    "MiG-29S": "MiG-29",
    "Su-27": "Su-27",
    "Su-33": "Su-33",
    "AH-64D_BLK_II": "Apache",
    "UH-1H": "Huey",
    "Ka-50": "Ka-50",
    "Mi-24P": "Mi-24",
}


def friendly_type(dcs_type, fallback="aircraft"):
    """'FA-18C_hornet' -> 'F/A-18C'. Unknown types are returned as DCS
    reports them."""

    if not dcs_type:
        return fallback

    return _TYPES.get(str(dcs_type), str(dcs_type))
