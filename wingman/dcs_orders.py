import time

# Actions that are sent to DCS. Everything else (contact reports,
# fox calls, ...) only updates the wingman's own state.
DCS_ACTIONS = {
    "FLIGHT_COMMAND",
    "RTB",
    "BUGOUT",
    "BREAK",
    "INTERCEPT",
    "INVESTIGATE_CONTACT",
    "MERGE",
    "DEFENDING",
    "ATTACK",
    "ORBIT",
    "FOLLOW",
    "RESUME",
    "CANCEL_ORDERS",
    "RADAR",
    "EMCON",
    "FLARE",
    "CHAFF",
    "COUNTERMEASURES",
    "WEAPONS_HOT",
    "WEAPONS_COLD",
    "INBOUND"
}

# A reported contact older than this is ignored (the lead has moved on);
# the wingman then picks the nearest hostile aircraft instead.
CONTACT_MAX_AGE_S = 180


def is_dcs_order(command):

    action = command.get("action")

    if action not in DCS_ACTIONS:
        return False

    # "missile inbound" is a threat call, not a request to go anywhere
    if action == "INBOUND":
        return command.get("parameters", {}).get("vector", True)

    return True


def _pick_contact(state):

    """Most recent fresh contact, preferring hostile ones."""

    now = time.time()

    fresh = [
        contact
        for contact in state.get_contacts()
        if now - contact.get("reported_at", 0) <= CONTACT_MAX_AGE_S
    ]

    hostile = [c for c in fresh if c.get("hostile")]

    pool = hostile or fresh

    return pool[-1] if pool else None


def _contact_fields(state):

    contact = _pick_contact(state)

    if not contact or contact.get("bearing") is None:

        return {}

    return {
        "bearing": contact["bearing"],
        "bearing_ref": contact.get("bearing_ref") or "abs",
        "range_nm": contact.get("range_nm"),
        "altitude_ft": contact.get("altitude")
    }


def sync_initial_state(state, telemetry, commander, log=print):

    """
    The wingman's state starts at weapons COLD, so make DCS agree:
    otherwise the AI could be shooting while the wingman says cold.
    """

    unit = telemetry.get_selected_unit() if telemetry else None

    if unit is None or commander is None:
        return

    status = state.tactical.get("weapons_status", "COLD")

    commander.roe(
        unit["name"],
        "free" if status == "HOT" else "hold"
    )

    log(
        f"[DCS] Wingman weapons set to "
        f"{'FREE' if status == 'HOT' else 'HOLD'}"
    )


def dispatch_to_dcs(command, state, telemetry, commander, log=print):

    """
    Send one parsed command to the selected wingman aircraft and,
    if it went out, record it in the wingman's state.
    """

    action = command["action"]
    parameters = command.get("parameters", {})

    unit = telemetry.get_selected_unit() if telemetry else None

    if unit is None or commander is None:

        log(
            "[DCS] Order not sent: "
            "wingman aircraft not available"
        )

        return False

    name = unit["name"]

    sent = True
    recorded = command
    label = action

    # ---------------------------------------------------------
    # FLIGHT (heading / altitude / speed / relative turn)
    # ---------------------------------------------------------

    if action == "FLIGHT_COMMAND":

        result = commander.send_flight(
            name,
            heading=parameters.get("heading"),
            altitude_ft=parameters.get("altitude"),
            speed_kts=parameters.get("speed"),
            turn_deg=parameters.get("turn")
        )

        if not result:

            log("[DCS] Order not sent")

            return False

        recorded = {"action": action, "parameters": result}

        text = []

        if "heading" in result:
            text.append(f"heading {result['heading']:03d}")

        if "turn" in result:
            side = "right" if result["turn"] > 0 else "left"
            text.append(f"turn {side} {abs(result['turn'])}")

        if "altitude" in result:
            text.append(f"altitude {result['altitude']} ft")

        if "speed" in result:
            text.append(f"speed {result['speed']} kt")

        label = ", ".join(text)

    # ---------------------------------------------------------
    # RETURN TO BASE / DISENGAGE / MANEUVER
    # ---------------------------------------------------------

    elif action == "RTB":

        sent = commander.rtb(name)
        label = "return to base"

    elif action == "BUGOUT":

        sent = commander.bugout(name)
        label = "bugout"

    elif action == "BREAK":

        direction = parameters.get("direction")

        sent = commander.break_turn(name, direction)
        label = f"break {direction}"

    # ---------------------------------------------------------
    # CHASING A CONTACT
    # ---------------------------------------------------------

    elif action in ("INTERCEPT", "MERGE", "DEFENDING"):

        mode = {
            "INTERCEPT": "intercept",
            "MERGE": "merge",
            "DEFENDING": "defend"
        }[action]

        fields = {} if action == "DEFENDING" else _contact_fields(state)

        sent = commander.engage(name, mode, **fields)
        label = mode

    elif action == "INVESTIGATE_CONTACT":

        clock = parameters.get("clock")

        if clock is not None:

            contact = _pick_contact(state)

            fields = {
                "bearing": (clock % 12) * 30,
                "bearing_ref": "rel",
                "range_nm": contact.get("range_nm") if contact else None
            }

        else:

            fields = _contact_fields(state)

        sent = commander.engage(name, "investigate", **fields)
        label = "investigate"

    elif action == "ATTACK":

        target = parameters.get("target")

        if target:

            sent = commander.engage(name, "attack", target=target)
            label = f"attack {target}"

        else:

            sent = commander.engage(
                name,
                "intercept",
                **_contact_fields(state)
            )
            label = "engage latest contact"

    # ---------------------------------------------------------
    # POSITION / FORMATION
    # ---------------------------------------------------------

    elif action == "ORBIT":

        sent = commander.orbit(
            name,
            altitude_ft=parameters.get("altitude"),
            speed_kts=parameters.get("speed")
        )
        label = "orbit"

    elif action == "FOLLOW":

        formation = parameters.get("formation", "right")

        sent = commander.follow(name, formation)
        label = f"form up ({formation})"

    elif action == "INBOUND":

        sent = commander.inbound(
            name,
            bearing=parameters.get("bearing"),
            bearing_ref=parameters.get("bearing_ref"),
            range_nm=parameters.get("range_nm")
        )
        label = "inbound"

    elif action == "RESUME":

        sent = commander.resume(name)
        label = "resume mission route"

    elif action == "CANCEL_ORDERS":

        sent = commander.clear(name)
        label = "cancel orders"

    # ---------------------------------------------------------
    # SENSORS / WEAPONS
    # ---------------------------------------------------------

    elif action == "RADAR":

        enable = parameters.get("enable", True)

        sent = commander.radar(name, enable)
        label = f"radar {'on' if enable else 'off'}"

    elif action == "EMCON":

        enable = parameters.get("enable", True)

        sent = commander.emcon(name, enable)
        label = f"EMCON {'on' if enable else 'off'}"

    elif action in ("FLARE", "CHAFF", "COUNTERMEASURES"):

        enable = parameters.get("enable", True)

        sent = commander.countermeasures(name, enable)
        label = f"countermeasures {'on' if enable else 'off'}"

    elif action == "WEAPONS_HOT":

        sent = commander.roe(name, "free")
        label = "weapons free"

    elif action == "WEAPONS_COLD":

        sent = commander.roe(name, "hold")
        label = "weapons hold"

    if not sent:

        log(f"[DCS] Order not sent: {action}")

        return False

    state.execute_command(recorded)

    log(f"[DCS] {name}: {label}")

    return True