import socket

CMD_HOST = "127.0.0.1"
CMD_PORT = 5017

# Sanity limits (the Lua side clamps again, and also respects the airframe ceiling)
MIN_ALT_FT = 500
MAX_ALT_FT = 60000
MIN_SPEED_KTS = 100
MAX_SPEED_KTS = 1500


class DCSCommander:
    """
    Sends orders to the Lua bridge running inside DCS (UDP, fire-and-forget).

    Wire format, one datagram per order (see wingman_bridge.lua):
        FLIGHT|unit=<unit name>|hdg=225|alt=15000|spd=250|rel=-90
        ROE|COUNTERMEASURES|RADAR|EMCON|RTB|ORBIT|FOLLOW|BREAK|BUGOUT|
        ENGAGE|INBOUND|RESUME|CLEAR  ...
    """

    def __init__(self, host=CMD_HOST, port=CMD_PORT):

        self.addr = (host, port)

        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        print(
            f"DCS COMMANDER: Sending orders to "
            f"{host}:{port}"
        )

    # =========================================================
    # LOW LEVEL
    # =========================================================

    def _send(self, action, **fields):

        parts = [action]

        for key, value in fields.items():

            if value is None:
                continue

            value = str(value)

            if "|" in value:
                print(
                    f"[DCS] Refusing to send field "
                    f"'{key}' containing '|'"
                )
                return False

            parts.append(f"{key}={value}")

        try:

            self.sock.sendto(
                "|".join(parts).encode("utf-8"),
                self.addr
            )

            return True

        except OSError as exc:

            print(f"[DCS] Failed to send order: {exc}")

            return False

    # =========================================================
    # FLIGHT ORDERS
    # =========================================================

    def send_flight(
        self,
        unit_name,
        heading=None,
        altitude_ft=None,
        speed_kts=None,
        turn_deg=None
    ):
        """
        Returns the dict of values actually sent
        (after validation), or None if nothing was sent.
        turn_deg is a relative turn, positive = right.
        """

        if not unit_name:
            return None

        sent = {}

        if heading is not None:

            heading = float(heading) % 360

            sent["heading"] = round(heading)

        if altitude_ft is not None:

            altitude_ft = float(altitude_ft)

            if not MIN_ALT_FT <= altitude_ft <= MAX_ALT_FT:

                print(
                    f"[DCS] Altitude {altitude_ft:.0f} ft "
                    f"outside {MIN_ALT_FT}-{MAX_ALT_FT}; ignored"
                )

            else:

                sent["altitude"] = round(altitude_ft)

        if speed_kts is not None:

            speed_kts = float(speed_kts)

            if not MIN_SPEED_KTS <= speed_kts <= MAX_SPEED_KTS:

                print(
                    f"[DCS] Speed {speed_kts:.0f} kt "
                    f"outside {MIN_SPEED_KTS}-{MAX_SPEED_KTS}; ignored"
                )

            else:

                sent["speed"] = round(speed_kts)

        if turn_deg is not None and "heading" not in sent:

            turn_deg = float(turn_deg)

            if -180 <= turn_deg <= 180 and turn_deg != 0:

                sent["turn"] = round(turn_deg)

        if not sent:
            return None

        ok = self._send(
            "FLIGHT",
            unit=unit_name,
            hdg=sent.get("heading"),
            rel=sent.get("turn"),
            alt=sent.get("altitude"),
            spd=sent.get("speed")
        )

        return sent if ok else None

    # =========================================================
    # OTHER ORDERS
    # =========================================================

    def _unit_order(self, action, unit_name, **fields):

        if not unit_name:
            return False

        return self._send(action, unit=unit_name, **fields)

    def roe(self, unit_name, mode):
        """mode: free | tight | return | hold"""

        if mode not in ("free", "tight", "return", "hold"):
            return False

        return self._unit_order("ROE", unit_name, mode=mode)

    def countermeasures(self, unit_name, enable=True):
        return self._unit_order(
            "COUNTERMEASURES", unit_name,
            mode="on" if enable else "off"
        )

    def radar(self, unit_name, enable=True):
        return self._unit_order(
            "RADAR", unit_name,
            mode="on" if enable else "off"
        )

    def emcon(self, unit_name, enable=True):
        return self._unit_order(
            "EMCON", unit_name,
            mode="on" if enable else "off"
        )

    def rtb(self, unit_name):
        return self._unit_order("RTB", unit_name)

    def orbit(self, unit_name, altitude_ft=None, speed_kts=None):

        if altitude_ft is not None and not (
            MIN_ALT_FT <= float(altitude_ft) <= MAX_ALT_FT
        ):
            altitude_ft = None

        if speed_kts is not None and not (
            MIN_SPEED_KTS <= float(speed_kts) <= MAX_SPEED_KTS
        ):
            speed_kts = None

        return self._unit_order(
            "ORBIT", unit_name,
            alt=None if altitude_ft is None else round(altitude_ft),
            spd=None if speed_kts is None else round(speed_kts)
        )

    def follow(self, unit_name, formation="right"):

        if formation not in ("right", "left", "trail", "abreast"):
            formation = "right"

        return self._unit_order("FOLLOW", unit_name, formation=formation)

    def break_turn(self, unit_name, direction):

        if direction not in ("left", "right"):
            return False

        return self._unit_order("BREAK", unit_name, dir=direction)

    def bugout(self, unit_name):
        return self._unit_order("BUGOUT", unit_name)

    def engage(
        self,
        unit_name,
        mode,
        target=None,
        bearing=None,
        bearing_ref=None,
        range_nm=None,
        altitude_ft=None
    ):
        """
        mode: intercept | merge | defend | investigate | attack
        attack needs a target (group name). The others can carry a
        reported contact (bearing + reference + range) to search around.
        """

        if mode not in (
            "intercept", "merge", "defend", "investigate", "attack"
        ):
            return False

        if mode == "attack" and not target:
            return False

        return self._unit_order(
            "ENGAGE", unit_name,
            mode=mode,
            target=target,
            brg=None if bearing is None else round(bearing),
            ref=bearing_ref if bearing is not None else None,
            rng=None if range_nm is None else round(range_nm, 1),
            alt=None if altitude_ft is None else round(altitude_ft)
        )

    def inbound(
        self,
        unit_name,
        bearing=None,
        bearing_ref=None,
        range_nm=None
    ):
        return self._unit_order(
            "INBOUND", unit_name,
            brg=None if bearing is None else round(bearing),
            ref=bearing_ref if bearing is not None else None,
            rng=None if range_nm is None else round(range_nm, 1)
        )

    def watch(self, unit_name):
        """
        Ask the Lua bridge to report this aircraft's weapon shots,
        takeoff/landing, kills and radar contacts (UDP 5018).
        """
        return self._unit_order("WATCH", unit_name)

    def resume(self, unit_name):
        """Back to the mission designer's original route."""
        return self._unit_order("RESUME", unit_name)

    def clear(self, unit_name):
        """
        Stop the Lua side holding the last flight order.
        Call this before handing the aircraft any other task (RTB etc.).
        """

        if not unit_name:
            return False

        return self._send("CLEAR", unit=unit_name)

    def close(self):

        try:
            self.sock.close()
        except OSError:
            pass