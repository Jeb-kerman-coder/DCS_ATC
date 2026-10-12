import ollama


class RequestParser:

    def __init__(self, model="gemma3:12b", keep_alive="60m"):

        self.model = model
        self.keep_alive = keep_alive

        print(f"REQUEST PARSER: {self.model} ready")

    def parse(self, transmission):

        prompt = f"""
You are the intent recognition system for a military aviation radio simulation.

Read the pilot's radio transmission and determine what the pilot is requesting.

Pilot transmission:
{transmission}

Available intents:

STARTUP_REQUEST
TAXI_REQUEST
TAKEOFF_REQUEST
INBOUND_REQUEST
LANDING_REQUEST
RADIO_CHECK
PICTURE_REQUEST
ON_STATION_REQUEST
BOGEY_DOPE_REQUEST
CHECK_IN_REQUEST
UNKNOWN

Examples:

"Tower, Colt 1-1, request startup."
STARTUP_REQUEST

"Tower, Colt 1-1, request start."
STARTUP_REQUEST

"Tower, Colt 1-1, requesting startup."
STARTUP_REQUEST

"Tower, Colt 1-1, can we start?"
STARTUP_REQUEST

"Tower, Colt 1-1, ready to taxi."
TAXI_REQUEST

"Tower, Colt 1-1, request taxi."
TAXI_REQUEST

"Tower, Colt 1-1, ready for takeoff."
TAKEOFF_REQUEST

"Tower, Colt 1-1, request takeoff."
TAKEOFF_REQUEST

"Tower, Colt 1-1, inbound."
INBOUND_REQUEST

"Tower, Colt 1-1, inbound for landing."
INBOUND_REQUEST

"Tower, Colt 1-1, request landing."
LANDING_REQUEST

"Tower, Colt 1-1, request landing clearance."
LANDING_REQUEST

"Tower, Colt 1-1, radio check."
RADIO_CHECK

"AWACS, Colt 1-1, radio check."
RADIO_CHECK

"AWACS, Colt 1-1, request picture."
PICTURE_REQUEST

"AWACS, Colt 1-1, picture."
PICTURE_REQUEST

"AWACS, Colt 1-1, what's the picture?"
PICTURE_REQUEST

"AWACS, Colt 1-1, on station, ready for tasking."
ON_STATION_REQUEST

"AWACS, Colt 1-1, reporting on station."
ON_STATION_REQUEST

"AWACS, Colt 1-1, reporting on station, ready for tasking."
ON_STATION_REQUEST

"AWACS, Colt 1-1, on station."
ON_STATION_REQUEST

"AWACS, Colt 1-1, ready for tasking."
ON_STATION_REQUEST

"AWACS, Colt 1-1, I have 4 AMRAAM and 2 Sidewinder, ready for tasking."
ON_STATION_REQUEST

"AWACS, Colt 1-1, request bogey dope."
BOGEY_DOPE_REQUEST

"AWACS, Colt 1-1, bogey dope."
BOGEY_DOPE_REQUEST

" GCI, Colt 1-1, on station, ready for tasking."
ON_STATION_REQUEST

"GCI, Colt 1-1, reporting on station."
ON_STATION_REQUEST

"GCI, Colt 1-1, reporting on station, ready for tasking."
ON_STATION_REQUEST

"GCI, Colt 1-1, on station."
ON_STATION_REQUEST

"GCI, Colt 1-1, ready for tasking."
ON_STATION_REQUEST

"GCI, Colt 1-1, I have 4 AMRAAM and 2 Sidewinder, ready for tasking."
ON_STATION_REQUEST

"AWACS, Colt 1-1, checking in."
CHECK_IN_REQUEST

"GCI, Colt 1-1, checking in."
CHECK_IN_REQUEST

Rules:

- Return exactly ONE intent from the available list.
- Do not explain.
- Do not add punctuation.
- Do not output anything else.
- Ignore the aircraft callsign when determining the intent.
- Weapon and ammunition information does not change an ON_STATION_REQUEST into another intent.

Intent:
"""

        print(
            "REQUEST PARSER: "
            "Sending transmission to Gemma..."
        )

        response = ollama.generate(
            model=self.model,
            prompt=prompt,
            options={
                "temperature": 0.0,
                "num_predict": 10,
            },
            think=False,
            keep_alive=self.keep_alive
        )

        result = response.get(
            "response",
            ""
        ).strip().upper()

        print(
            f"REQUEST PARSER RESULT: "
            f"{result}"
        )

        valid_intents = {
            "STARTUP_REQUEST",
            "TAXI_REQUEST",
            "TAKEOFF_REQUEST",
            "INBOUND_REQUEST",
            "LANDING_REQUEST",
            "RADIO_CHECK",
            "PICTURE_REQUEST",
            "ON_STATION_REQUEST",
            "BOGEY_DOPE_REQUEST",
            "CHECK_IN_REQUEST",
            "UNKNOWN"
        }

        if result not in valid_intents:

            print(
                "REQUEST PARSER: "
                "Invalid AI response."
            )

            return None

        if result == "UNKNOWN":

            return None

        return result