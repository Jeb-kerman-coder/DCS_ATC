"""
ATC / AWACS / GCI request pipeline.

    pilot transmission (text)
        -> intent            (RequestParser, LLM)
        -> procedure         (data/procedures.json, deterministic)
        -> response data     (BRAA / picture / tasking, deterministic)
        -> radio wording     (LLMManager, LLM - wording only)

This used to be one 1,400 line method inside the GUI. It is now plain
Python with no tkinter in it, so it can be tested without a window, and the
AWACS and GCI controllers share one implementation instead of two copies.
"""


class ATCPipeline:

    def __init__(
        self,
        request_parser,
        loadout_parser,
        procedure_manager,
        llm_manager,
        contact_manager,
        braa_calculator,
        get_heading,
        get_fallback_ownship=None,
        get_lead=None,
        log=None
    ):
        self.request_parser = request_parser
        self.loadout_parser = loadout_parser
        self.procedure_manager = procedure_manager
        self.llm_manager = llm_manager
        self.contact_manager = contact_manager
        self.braa_calculator = braa_calculator

        # () -> heading in degrees or None
        self.get_heading = get_heading

        # () -> {"x","y","z"} or None; used when the AWACS feed has no
        # ownship position (the telemetry bridge knows where the player is)
        self.get_fallback_ownship = get_fallback_ownship

        # () -> (callsign, aircraft) of the human pilot
        self.get_lead = get_lead

        self._log = log or (lambda source, message: None)

    # =========================================================
    # ENTRY POINT
    # =========================================================

    def respond(self, controller, frequency, text):
        """
        Returns the words the controller should transmit, or None when the
        request could not be handled (reason is logged).
        """

        request_type = self.request_parser.parse(text)

        loadout = self.loadout_parser.parse(text)

        if not request_type:
            print("ATC: Could not identify pilot request.")
            self._log("ATC", "Request not understood.")
            return None

        print(f"ATC: Request identified as {request_type}")

        procedure = self.procedure_manager.get_procedure(
            controller,
            request_type
        )

        if not procedure:
            print(f"ATC: No procedure for {controller} / {request_type}")
            self._log(
                "ATC",
                f"{controller} has no procedure for {request_type}."
            )
            return None

        response_data = dict(procedure.get("response_data", {}))

        if controller in ("AWACS", "GCI"):

            if not self._add_air_picture(
                controller,
                request_type,
                response_data,
                loadout
            ):
                return None

        callsign, aircraft = self._lead()

        return self.llm_manager.generate_controller_response(
            controller=controller,
            frequency=frequency,
            aircraft=aircraft,
            callsign=callsign,
            pilot_transmission=text,
            controller_action=procedure.get("controller_action"),
            response_data=response_data
        )

    def _lead(self):

        if self.get_lead:

            try:

                callsign, aircraft = self.get_lead()

                if callsign and aircraft:
                    return callsign, aircraft

            except Exception as exc:
                print(f"ATC: lead lookup failed: {exc}")

        return "Colt 1-1", "F/A-18C"

    # =========================================================
    # AWACS / GCI DATA
    # =========================================================

    def _ownship(self):

        ownship = self.contact_manager.get_ownship()

        if ownship.get("x") is None and self.get_fallback_ownship:

            fallback = self.get_fallback_ownship()

            if fallback:
                ownship = dict(fallback)

        return ownship

    @staticmethod
    def _horizontal_distance_sq(ownship, contact):

        position = contact.get("position", {})

        x = position.get("x")
        z = position.get("z")

        if x is None or z is None:
            return None

        return (x - ownship["x"]) ** 2 + (z - ownship["z"]) ** 2

    def _braa(self, ownship, contact, heading):

        braa = self.braa_calculator.calculate(
            ownship=ownship,
            contact=contact,
            heading_deg=heading
        )

        if braa is None:
            return None

        return {
            "bearing_deg": round(braa["bearing_deg"]),
            "relative_bearing_deg": round(braa["relative_bearing_deg"]),
            "range_nm": round(braa["range_nm"], 1),
            "altitude_ft": round(braa["altitude_ft"]),
        }

    def _add_air_picture(
        self,
        controller,
        request_type,
        response_data,
        loadout
    ):
        """Adds the deterministic data the LLM will phrase. Returns False
        when there is nothing usable (the original code stayed silent too)."""

        if request_type not in (
            "BOGEY_DOPE_REQUEST",
            "PICTURE_REQUEST",
            "ON_STATION_REQUEST"
        ):
            return True

        ownship = self._ownship()
        contacts = self.contact_manager.get_contacts()

        print(f"{controller}: {request_type} - {len(contacts)} contacts")

        # ---- on station: the pilot's loadout is part of the reply ----

        if request_type == "ON_STATION_REQUEST":

            response_data["amraam"] = loadout["amraam"]
            response_data["sidewinder"] = loadout["sidewinder"]
            response_data["gun_rounds"] = loadout["gun_rounds"]

        if ownship.get("x") is None or ownship.get("z") is None:

            print(f"{controller}: OWNSHIP POSITION UNAVAILABLE")
            self._log(controller, "Ownship position unavailable.")

            if request_type == "ON_STATION_REQUEST":
                response_data["tasking_available"] = False
                response_data["task_target"] = None
                return True

            return False

        heading = self.get_heading()

        if heading is None:

            print(f"{controller}: HEADING UNAVAILABLE")
            self._log(controller, "Own heading unavailable.")

            if request_type == "ON_STATION_REQUEST":
                response_data["tasking_available"] = False
                response_data["task_target"] = None
                return True

            return False

        # ---- bogey dope: nearest contact ----

        if request_type == "BOGEY_DOPE_REQUEST":

            contact = self.contact_manager.get_nearest_contact()

            # nearest-by-ownship needs the AWACS ownship; recompute with
            # the (possibly fallback) ownship so both paths agree
            best, best_d = None, None

            for candidate in contacts.values():

                d = self._horizontal_distance_sq(ownship, candidate)

                if d is not None and (best_d is None or d < best_d):
                    best, best_d = candidate, d

            contact = best or contact

            if contact is None:
                print(f"{controller}: NO USABLE CONTACT")
                self._log(controller, "No contacts.")
                return False

            braa = self._braa(ownship, contact, heading)

            if braa is None:
                print(f"{controller}: BRAA CALCULATION FAILED")
                self._log(controller, "BRAA calculation failed.")
                return False

            response_data["contact_type"] = contact.get("type")
            response_data.update(braa)

            self._log(
                controller,
                f"BRAA {braa['bearing_deg']}° {braa['range_nm']} NM "
                f"{braa['altitude_ft']} ft"
            )

            return True

        # ---- picture: every contact, nearest first ----

        if request_type == "PICTURE_REQUEST":

            picture = []

            for contact_id, contact in contacts.items():

                braa = self._braa(ownship, contact, heading)

                if braa is None:
                    print(
                        f"{controller}: could not calculate "
                        f"contact {contact_id}"
                    )
                    continue

                entry = {
                    "id": contact_id,
                    "type": contact.get("type"),
                    "relationship": contact.get("relationship", "UNKNOWN"),
                }

                entry.update(braa)

                picture.append(entry)

            picture.sort(key=lambda entry: entry["range_nm"])

            response_data["contact_count"] = len(picture)
            response_data["contacts"] = picture

            if picture:
                response_data["use_military_brevity"] = True

            self._log(controller, f"PICTURE {len(picture)} CONTACTS")

            return True

        # ---- on station: task the closest hostile ----

        hostile = [
            contact for contact in contacts.values()
            if contact.get("relationship") == "HOSTILE"
        ]

        print(f"{controller}: HOSTILE CONTACTS: {len(hostile)}")

        response_data["tasking_available"] = False
        response_data["task_target"] = None

        closest, closest_d = None, None

        for contact in hostile:

            d = self._horizontal_distance_sq(ownship, contact)

            if d is not None and (closest_d is None or d < closest_d):
                closest, closest_d = contact, d

        if closest is None:
            self._log(controller, "NO HOSTILE TARGET AVAILABLE")
            return True

        braa = self._braa(ownship, closest, heading)

        if braa is None:
            self._log(controller, "Tasking BRAA calculation failed.")
            return True

        target = {
            "id": closest.get("id"),
            "type": closest.get("type"),
            "relationship": closest.get("relationship", "UNKNOWN"),
        }

        target.update(braa)

        response_data["tasking_available"] = True
        response_data["task_target"] = target

        self._log(
            controller,
            f"TASKING {target['type']} BRAA {braa['bearing_deg']}° "
            f"{braa['range_nm']} NM {braa['altitude_ft']} ft"
        )

        return True
