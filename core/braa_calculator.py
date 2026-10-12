import math


METERS_TO_NM = 1 / 1852
METERS_TO_FEET = 3.28084


class BRAACalculator:

    def calculate(
        self,
        ownship,
        contact,
        heading_deg
    ):

        # =========================================================
        # VALIDATE INPUT
        # =========================================================

        if ownship is None:
            return None

        if contact is None:
            return None

        if heading_deg is None:
            return None

        own_x = ownship.get("x")
        own_y = ownship.get("y")
        own_z = ownship.get("z")

        position = contact.get(
            "position",
            {}
        )

        bogey_x = position.get("x")
        bogey_y = position.get("y")
        bogey_z = position.get("z")

        if None in (
            own_x,
            own_y,
            own_z,
            bogey_x,
            bogey_y,
            bogey_z
        ):
            return None

        # =========================================================
        # RELATIVE POSITION
        # =========================================================

        relative_x = (
            bogey_x - own_x
        )

        relative_y = (
            bogey_y - own_y
        )

        relative_z = (
            bogey_z - own_z
        )

        # =========================================================
        # HORIZONTAL RANGE
        # =========================================================

        horizontal_distance_m = math.sqrt(
            relative_x ** 2 +
            relative_z ** 2
        )

        range_nm = (
            horizontal_distance_m *
            METERS_TO_NM
        )

        # =========================================================
        # ABSOLUTE BEARING
        #
        # DCS:
        #   X = north/south
        #   Z = east/west
        # =========================================================

        bearing_rad = math.atan2(
            relative_z,
            relative_x
        )

        bearing_deg = math.degrees(
            bearing_rad
        )

        bearing_deg %= 360

        # =========================================================
        # RELATIVE BEARING
        # =========================================================

        relative_bearing_deg = (
            bearing_deg -
            heading_deg
        ) % 360

        # =========================================================
        # ALTITUDE DIFFERENCE
        # =========================================================

        altitude_ft = (
    bogey_y * METERS_TO_FEET
)

        # =========================================================
        # RETURN RESULT
        # =========================================================

        return {

            "bearing_deg": bearing_deg,

            "relative_bearing_deg":
                relative_bearing_deg,

            "range_nm":
                range_nm,

            "altitude_ft": 
            altitude_ft,

            "relative_position": {

                "x": relative_x,
                "y": relative_y,
                "z": relative_z

            }

        }