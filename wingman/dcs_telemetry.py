import json
import socket
import threading
import time


UDP_HOST = "127.0.0.1"
UDP_PORT = 5016

BUFFER_SIZE = 65535
STALE_AFTER = 3.0


class DCSTelemetry:

    def __init__(self, state=None):
        self.state = state

        self.running = False
        self.connected = False

        self.sock = None
        self.thread = None

        self.units = []
        self.last_update = 0.0

        self.selected_unit_name = None

        # Multipart packet reassembly
        self.pending = {}
        self.pending_lock = threading.Lock()

        self.units_lock = threading.Lock()

    # =========================================================
    # START / STOP
    # =========================================================

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._receive_loop,
            daemon=True
        )

        self.thread.start()

        print(
            f"[DCS] Telemetry listener started on "
            f"{UDP_HOST}:{UDP_PORT}"
        )

    def stop(self):

        self.running = False

        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

        self.sock = None

    # =========================================================
    # RECEIVE LOOP
    # =========================================================

    def _receive_loop(self):

        try:

            self.sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            self.sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1
            )

            self.sock.bind(
                (UDP_HOST, UDP_PORT)
            )

            self.sock.settimeout(1.0)

            print(
                f"[DCS] Listening for aircraft telemetry "
                f"on UDP {UDP_PORT}"
            )

        except OSError as exc:

            self.connected = False

            print(
                f"[DCS] Failed to open UDP port "
                f"{UDP_PORT}: {exc}"
            )

            self.running = False
            return

        while self.running:

            try:

                data, _ = self.sock.recvfrom(
                    BUFFER_SIZE
                )

                self._process_packet(data)

            except socket.timeout:
                continue

            except OSError:

                if self.running:
                    print(
                        "[DCS] UDP socket closed unexpectedly"
                    )

                break

            except Exception as exc:

                print(
                    f"[DCS] Telemetry receive error: {exc}"
                )

        self.connected = False

    # =========================================================
    # PACKET PROCESSING
    # =========================================================

    def _process_packet(self, data):

        try:

            message = data.decode(
                "utf-8",
                errors="replace"
            )

            packet = json.loads(message)

        except (UnicodeDecodeError, json.JSONDecodeError) as exc:

            print(
                f"[DCS] Invalid telemetry packet: {exc}"
            )

            return

        timestamp = packet.get("timestamp")

        part = packet.get("part", 1)
        parts = packet.get("parts", 1)

        units = packet.get("units", [])

        if not isinstance(units, list):
            units = []

        try:
            part = int(part)
            parts = int(parts)
        except (TypeError, ValueError):
            return

        # Single-part frame
        if parts <= 1:

            self._accept_frame(units)
            return

        # Multipart frame
        with self.pending_lock:

            # Prevent the dictionary growing forever
            if len(self.pending) > 20:
                self.pending.clear()

            frame = self.pending.setdefault(
                timestamp,
                {}
            )

            frame[part] = units

            if len(frame) < parts:
                return

            merged = []

            for index in range(1, parts + 1):

                chunk = frame.get(index)

                if chunk is None:
                    return

                merged.extend(chunk)

            # Remove completed frame
            del self.pending[timestamp]

            # Remove older frames
            old_keys = [
                key
                for key in self.pending
                if isinstance(key, (int, float))
                and isinstance(timestamp, (int, float))
                and key <= timestamp
            ]

            for key in old_keys:
                del self.pending[key]

        self._accept_frame(merged)

    # =========================================================
    # ACCEPT COMPLETE FRAME
    # =========================================================

    def _accept_frame(self, units):

        cleaned_units = []

        for unit in units:

            if not isinstance(unit, dict):
                continue

            cleaned = self._clean_unit(unit)

            if cleaned:
                cleaned_units.append(cleaned)

        with self.units_lock:

            self.units = cleaned_units
            self.last_update = time.time()

        self.connected = True

        self._update_state()

    # =========================================================
    # CLEAN UNIT
    # =========================================================

    def _clean_unit(self, unit):

        try:

            position = unit.get(
                "position",
                {}
            )

            if not isinstance(position, dict):
                position = {}

            callsign = unit.get("callsign")

            name = unit.get("name")

            cleaned = {

                "id": unit.get("id"),

                "name": str(
                    name or ""
                ),

                "callsign": str(
                    callsign or name or ""
                ),

                "type": str(
                    unit.get("type", "")
                ),

                "category": str(
                    unit.get("category", "")
                ),

                "group": str(
                    unit.get("group", "")
                ),

                "group_id": unit.get(
                    "group_id"
                ),

                "coalition": str(
                    unit.get(
                        "coalition",
                        "unknown"
                    )
                ).lower(),

                "player": unit.get(
                    "player"
                ),

                "position": {

                    "x": self._number(
                        position.get("x")
                    ),

                    "y": self._number(
                        position.get("y")
                    ),

                    "z": self._number(
                        position.get("z")
                    ),
                },

                "lat": self._number(
                    unit.get("lat")
                ),

                "lon": self._number(
                    unit.get("lon")
                ),

                "altitude_ft": self._number(
                    unit.get("altitude_ft")
                ),

                "heading_deg": self._number(
                    unit.get("heading_deg")
                ),

                "speed_kts": self._number(
                    unit.get("speed_kts")
                ),

                "vertical_speed_fpm": self._number(
                    unit.get("vertical_speed_fpm")
                ),

                "fuel": self._number(
                    unit.get("fuel")
                ),

                "life": self._number(
                    unit.get("life")
                ),

                "life_max": self._number(
                    unit.get("life_max")
                ),

                "alive": bool(
                    unit.get("alive", True)
                ),
            }

            # Preserve velocity if supplied
            velocity = unit.get(
                "velocity"
            )

            if isinstance(velocity, dict):

                cleaned["velocity"] = {

                    "x": self._number(
                        velocity.get("x")
                    ),

                    "y": self._number(
                        velocity.get("y")
                    ),

                    "z": self._number(
                        velocity.get("z")
                    ),
                }

            else:

                cleaned["velocity"] = {
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.0
                }

            return cleaned

        except Exception as exc:

            print(
                f"[DCS] Failed to process aircraft: {exc}"
            )

            return None

    # =========================================================
    # NUMBER HELPER
    # =========================================================

    @staticmethod
    def _number(value):

        if value is None:
            return 0.0

        try:

            value = float(value)

            if value != value:
                return 0.0

            if value == float("inf"):
                return 0.0

            if value == float("-inf"):
                return 0.0

            return value

        except (TypeError, ValueError):

            return 0.0

    # =========================================================
    # AIRCRAFT ACCESS
    # =========================================================

    def get_units(self):

        with self.units_lock:
            return list(self.units)

    def get_friendly_units(
        self,
        coalition_name="blue"
    ):

        coalition_name = coalition_name.lower()

        return [

            unit

            for unit in self.get_units()

            if unit.get("coalition") == coalition_name
            and unit.get("alive", True)

        ]

    def get_player_unit(self):
        """The human-flown aircraft (the lead), if one is reported."""

        for unit in self.get_units():

            if unit.get("player") and unit.get("alive", True):
                return unit

        return None

    def get_candidates(self):
        """
        Friendly aircraft that can be given orders: AI-flown and alive.
        (The Lua bridge refuses to steer human-flown aircraft.)
        """

        return sorted(
            (
                unit for unit in self.get_units()
                if unit.get("alive", True) and not unit.get("player")
            ),
            key=lambda unit: (
                unit.get("group", ""),
                unit.get("callsign", "")
            )
        )

    # =========================================================
    # AIRCRAFT SELECTION
    # =========================================================

    def select_unit(self, unit_name):

        if not unit_name:
            self.selected_unit_name = None
            self._update_state()
            return None

        self.selected_unit_name = str(
            unit_name
        )

        selected = self.get_selected_unit()

        self._update_state()

        return selected

    def get_selected_unit(self):

        if not self.selected_unit_name:
            return None

        wanted = self.selected_unit_name.lower()

        for unit in self.get_units():

            callsign = str(
                unit.get("callsign", "")
            ).lower()

            name = str(
                unit.get("name", "")
            ).lower()

            if callsign == wanted or name == wanted:

                if unit.get("alive", True):
                    return unit

                return None

        return None

    # =========================================================
    # STATE INTEGRATION
    # =========================================================

    def _update_state(self):

        if self.state is None:
            return

        selected = self.get_selected_unit()

        try:

            if hasattr(
                self.state,
                "update_dcs_telemetry"
            ):

                self.state.update_dcs_telemetry(
                    selected
                )

        except Exception as exc:

            print(
                f"[DCS] State update failed: {exc}"
            )

    # =========================================================
    # CONNECTION STATUS
    # =========================================================

    def set_dcs_connection(
        self,
        connected
    ):

        self.connected = bool(
            connected
        )

        if connected:
            self.last_update = time.time()

    def is_connected(self):

        if not self.connected:
            return False

        if self.last_update <= 0:
            return False

        return (
            time.time() - self.last_update
        ) < STALE_AFTER

    def age(self):

        if self.last_update <= 0:
            return float("inf")

        return (
            time.time() - self.last_update
        )

    # =========================================================
    # STATUS
    # =========================================================

    def get_status(self):

        return {

            "connected": self.is_connected(),

            "port": UDP_PORT,

            "aircraft_count": len(
                self.get_units()
            ),

            "selected": self.selected_unit_name,

            "last_update": self.last_update,

            "age": self.age(),

        }