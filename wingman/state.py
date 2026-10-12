import time


class WingmanState:

    def __init__(self):

        self.mode = "ROUTINE"

        self.threat = None
        self.threat_direction = None

        # How the wingman is addressed on the radio ("Colt 1-2"). Set when
        # a wingman is selected; live telemetry never overwrites it.
        self.display_callsign = None

        # =====================================================
        # DCS TELEMETRY
        # =====================================================

        self.dcs = {
    "connected": False,
    "aircraft": None,
    "altitude_ft": None,
    "heading_deg": None,
    "position": None,
    "last_update": None
}

        self.position = {
            "latitude": None,
            "longitude": None
        }

        # =====================================================
        # MISSION STATE
        # =====================================================

        self.mission = {
            "type": "CAP",
            "target_waypoint": "Bulls",
            "target_area": None,
            "target_distance_nm": None,
            "bullseye": None,
            "rules_of_engagement": None
        }

        # =====================================================
        # AIRCRAFT STATE
        # =====================================================

        self.aircraft = {
            "callsign": "Colt 1-2",
            "fuel": 22800,
            "bingo_fuel": 20000,
            "heading": 225,
            "altitude": 20000,
            "speed": 350,
            "master_mode": None,
            "weapon_mode": None,
            "formation": "WING"
        }

        # =====================================================
        # TACTICAL STATE
        # =====================================================

        self.tactical = {
            "contacts": [],
            "target_coordinates": None,

            "jtac": {
                "available": False,
                "coordinates": None,
                "target_description": None
            },

            "weapons_status": "COLD",

            "lead_weapons": {
                "amraam": 0,
                "sidewinder": 0,
                "harm": 0
            },

            "wingman_weapons": {
                "amraam": 0,
                "sidewinder": 0,
                "harm": 0
            }
        }

        # =====================================================
        # FLIGHT STATE
        # =====================================================

        self.flight = {
            "distance_to_base_nm": None,
            "inbound": False,
            "gear": "UP",
            "on_ground": False,
            "commanded": {}
        }

        self.next_contact_id = 1

        # things the wingman announced on its own ("Fox three", ...)
        self.recent_events = []
        self.kills = 0

        # =========================================================
    # DCS TELEMETRY
    # =========================================================

    def update_dcs_telemetry(self, aircraft_data):

        if aircraft_data is None:

            self.dcs["connected"] = False
            self.dcs["aircraft"] = None

            return

        # Store complete telemetry for the selected aircraft
        self.dcs["connected"] = True
        self.dcs["aircraft"] = aircraft_data
        self.dcs["last_update"] = time.time()

        # -----------------------------------------------------
        # Update main aircraft state from DCS
        # -----------------------------------------------------

        name = aircraft_data.get("name")

        if self.display_callsign:
            self.aircraft["callsign"] = self.display_callsign

        elif name:
            self.aircraft["callsign"] = name

        altitude = aircraft_data.get(
            "altitude_ft"
        )

        if altitude is not None:
            self.aircraft["altitude"] = round(
                altitude
            )

            self.dcs["altitude_ft"] = altitude

        heading = aircraft_data.get(
            "heading_deg"
        )

        if heading is not None:
            self.aircraft["heading"] = round(
                heading,
                1
            )

            self.dcs["heading_deg"] = heading

        speed = aircraft_data.get(
            "speed_kts"
        )

        if speed is not None:
            self.aircraft["speed"] = round(
                speed,
                1
            )

        fuel = aircraft_data.get(
            "fuel"
        )

        if fuel is not None:
            self.aircraft["fuel"] = fuel

        # -----------------------------------------------------
        # Position
        # -----------------------------------------------------

        position = aircraft_data.get(
            "position",
            {}
        )

        if isinstance(position, dict):

            self.dcs["position"] = position.copy()

    def set_dcs_connection(self, connected):

        self.dcs["connected"] = connected

        if connected:
            self.dcs["last_update"] = time.time()

    def get_dcs_status(self):

        return self.dcs.copy()

    # =========================================================
    # THREAT
    # =========================================================

    def set_threat(self, threat, direction=None):

        self.threat = threat
        self.threat_direction = direction
        self.mode = "COMBAT"

    def clear_threat(self):

        self.threat = None
        self.threat_direction = None

        if self.mode == "COMBAT":
            self.mode = "ROUTINE"

    # =========================================================
    # MISSION
    # =========================================================

    def set_mission_type(self, mission_type):

        if mission_type:
            self.mission["type"] = mission_type.upper()

    def set_target_waypoint(self, waypoint):

        self.mission["target_waypoint"] = waypoint

    def set_target_area(self, area):

        self.mission["target_area"] = area

    def set_target_distance(self, distance_nm):

        self.mission["target_distance_nm"] = distance_nm

    def set_roe(self, roe):

        self.mission["rules_of_engagement"] = roe

    # =========================================================
    # WEAPONS / SENSORS
    # =========================================================

    def set_lead_weapon_mode(self, mode):

        if mode:
            self.aircraft["weapon_mode"] = mode.upper()

    def set_master_mode(self, mode):

        if mode:
            self.aircraft["master_mode"] = mode.upper()

    def set_weapons_status(self, status):

        if status:
            self.tactical["weapons_status"] = status.upper()

    # =========================================================
    # JTAC
    # =========================================================

    def set_jtac(
        self,
        available=True,
        coordinates=None,
        target_description=None
    ):

        self.tactical["jtac"] = {
            "available": available,
            "coordinates": coordinates,
            "target_description": target_description
        }

        if coordinates is not None:
            self.tactical["target_coordinates"] = coordinates

    # =========================================================
    # CONTACT SYSTEM
    # =========================================================

    def add_contact(
        self,
        contact_type="UNKNOWN",
        bearing=None,
        range_nm=None,
        altitude=None,
        fast_mover=False,
        datalink=False,
        hostile=False,
        weapons=None,
        bearing_ref=None
    ):

        contact = {
            "id": self.next_contact_id,

            "type": (
                contact_type.upper()
                if contact_type
                else "UNKNOWN"
            ),

            "bearing": bearing,

            # "rel" = off the lead's nose (clock call), "abs" = compass
            "bearing_ref": bearing_ref,

            "reported_at": time.time(),

            "range_nm": range_nm,
            "altitude": altitude,
            "fast_mover": fast_mover,
            "datalink": datalink,

            "identified": (
                contact_type not in
                (None, "UNKNOWN")
            ),

            "hostile": hostile,

            "weapons": weapons or [],

            "status": (
                "HOSTILE"
                if hostile
                else "UNKNOWN"
            )
        }

        self.tactical["contacts"].append(contact)
        self.next_contact_id += 1

        if hostile:

            self.mode = "COMBAT"

            self.threat = (
                contact["type"]
                if contact["type"] != "UNKNOWN"
                else "HOSTILE"
            )

            self.threat_direction = bearing

        return contact

    def update_contact(
        self,
        contact_id,
        **updates
    ):

        for contact in self.tactical["contacts"]:

            if contact["id"] != contact_id:
                continue

            for key, value in updates.items():

                if value is not None:
                    contact[key] = value
                    contact["reported_at"] = time.time()

            if contact.get("type") not in (
                None,
                "UNKNOWN"
            ):

                contact["identified"] = True

            if contact.get("hostile"):

                contact["status"] = "HOSTILE"
                self.mode = "COMBAT"

                self.threat = (
                    contact["type"]
                    if contact["type"] != "UNKNOWN"
                    else "HOSTILE"
                )

                self.threat_direction = (
                    contact.get("bearing")
                )

            return contact

        return None

    def get_contact(self, contact_id):

        for contact in self.tactical["contacts"]:

            if contact["id"] == contact_id:
                return contact.copy()

        return None

    def get_contacts(self):

        return [
            contact.copy()
            for contact in self.tactical["contacts"]
        ]

    def get_latest_contact(self):

        if not self.tactical["contacts"]:
            return None

        return self.tactical["contacts"][-1].copy()

    def set_contact_hostile(self, contact_id):

        return self.update_contact(
            contact_id,
            hostile=True
        )

    def remove_contact(self, contact_id):

        self.tactical["contacts"] = [
            contact
            for contact in self.tactical["contacts"]
            if contact["id"] != contact_id
        ]

    def clear_contacts(self):

        self.tactical["contacts"] = []

    # =========================================================
    # FLIGHT
    # =========================================================

    def log_event(self, text):

        self.recent_events.append(
            {"text": text, "time": time.time()}
        )

        del self.recent_events[:-10]

    def get_recent_events(self, max_age_s=600):

        now = time.time()

        return [
            {
                "event": event["text"],
                "seconds_ago": round(now - event["time"])
            }
            for event in list(self.recent_events)
            if now - event["time"] <= max_age_s
        ]

    def set_distance_to_base(self, distance_nm):

        self.flight["distance_to_base_nm"] = distance_nm

    def set_gear(self, gear):

        if gear:
            self.flight["gear"] = gear.upper()

    def set_inbound(self, inbound=True):

        self.flight["inbound"] = inbound

        if inbound:
            self.mode = "INBOUND"

    # =========================================================
    # COMMAND EXECUTION
    # =========================================================

    def execute_command(self, command):

        if not command:
            return False

        action = command.get("action")

        parameters = command.get(
            "parameters",
            {}
        )

        # -------------------------
        # FLIGHT
        # -------------------------

        # Any of these replaces whatever heading/altitude/speed the
        # wingman was told to hold.
        if action in (
            "RTB", "BUGOUT", "BREAK", "INTERCEPT", "INVESTIGATE_CONTACT",
            "MERGE", "DEFENDING", "ATTACK", "ORBIT", "FOLLOW", "RESUME",
            "CANCEL_ORDERS", "INBOUND"
        ):
            self.flight["commanded"] = {}

        if action == "ATTACK":

            self.mode = "COMBAT"

            return True

        if action in ("ORBIT", "CANCEL_ORDERS"):

            return True

        if action in ("FOLLOW", "RESUME"):

            self.mode = "ROUTINE"
            self.flight["inbound"] = False

            return True

        if action in (
            "RADAR", "EMCON", "COUNTERMEASURES"
        ):

            return True

        if action == "FLIGHT_COMMAND":

            # What the wingman has been ordered to fly. (self.aircraft is
            # overwritten by live telemetry, so orders are kept separately.)
            commanded = {
                key: parameters[key]
                for key in ("heading", "altitude", "speed")
                if parameters.get(key) is not None
            }

            if not commanded and parameters.get("turn") is None:
                return False

            if "turn" in parameters:
                self.flight["commanded"].pop("heading", None)

            self.flight["commanded"].update(commanded)

            return True

        if action == "CHANGE_HEADING":

            heading = parameters.get("heading")

            if heading is None:
                return False

            self.aircraft["heading"] = heading

            return True

        if action == "CHANGE_ALTITUDE":

            altitude = parameters.get("altitude")

            if altitude is None:
                return False

            self.aircraft["altitude"] = altitude

            return True

        if action == "CHANGE_SPEED":

            speed = parameters.get("speed")

            if speed is None:
                return False

            self.aircraft["speed"] = speed

            return True

        # -------------------------
        # RTB / BUGOUT
        # -------------------------

        if action == "RTB":

            self.mode = "RTB"
            self.flight["inbound"] = True

            return True

        if action == "BUGOUT":

            self.mode = "BUGOUT"

            return True

        # -------------------------
        # TACTICAL
        # -------------------------

        if action == "INTERCEPT":

            self.mode = "INTERCEPT"

            return True

        if action == "INVESTIGATE_CONTACT":

            self.mode = "INTERCEPT"

            direction = parameters.get(
                "direction"
            )

            if direction:
                self.threat_direction = direction

            return True

        if action == "BREAK":

            direction = parameters.get(
                "direction"
            )

            self.mode = "COMBAT"
            self.threat_direction = direction

            return True

        if action == "MERGE":

            self.mode = "COMBAT"

            return True

        if action == "DEFENDING":

            self.mode = "COMBAT"

            return True

        # -------------------------
        # WEAPONS
        # -------------------------

        if action == "WEAPONS_HOT":

            self.tactical["weapons_status"] = "HOT"
            self.mode = "COMBAT"

            return True

        if action == "WEAPONS_COLD":

            self.tactical["weapons_status"] = "COLD"

            return True

        if action in (
            "FOX_1",
            "FOX_2",
            "FOX_3",
            "MAGNUM",
            "RIFLE",
            "PITBULL"
        ):

            self.mode = "COMBAT"

            return True

        if action == "CHAFF":
            return True

        if action == "FLARE":
            return True

        # -------------------------
        # INBOUND
        # -------------------------

        if action == "INBOUND":

            distance = parameters.get(
                "distance_nm"
            )

            if distance is not None:

                self.flight[
                    "distance_to_base_nm"
                ] = distance

            self.set_inbound(True)

            return True

        return False

    # =========================================================
    # RESET
    # =========================================================

    def set_callsign(self, callsign):

        self.display_callsign = callsign or None

        if callsign:
            self.aircraft["callsign"] = callsign

    def reset(self):

        keep = self.display_callsign

        self.__init__()

        self.set_callsign(keep)

    # =========================================================
    # CONTEXT
    # =========================================================

    def get_context(self):

        return {
            "mode": self.mode,

            "threat": self.threat,

            "threat_direction":
                self.threat_direction,

            "mission":
                self.mission.copy(),

            "aircraft":
                self.aircraft.copy(),

            "position":
                self.position.copy(),

            "dcs":
                self.dcs.copy(),

            "tactical": {
                "contacts":
                    self.get_contacts(),

                "target_coordinates":
                    self.tactical[
                        "target_coordinates"
                    ],

                "jtac":
                    self.tactical[
                        "jtac"
                    ].copy(),

                "weapons_status":
                    self.tactical[
                        "weapons_status"
                    ],

                "lead_weapons":
                    self.tactical[
                        "lead_weapons"
                    ].copy(),

                "wingman_weapons":
                    self.tactical[
                        "wingman_weapons"
                    ].copy()
            },

            "flight":
                self.flight.copy(),

            "recent_events":
                self.get_recent_events()
        }