import re


class LoadoutParser:

    def __init__(self):

        print(
            "LOADOUT PARSER: Ready"
        )

    def parse(self, transmission):

        text = transmission.lower()

        loadout = {
            "amraam": 0,
            "sidewinder": 0,
            "gun_rounds": 0
        }

        # =====================================================
        # AMRAAM
        # =====================================================

        amraam_match = re.search(
            r"(\d+)\s*(?:x\s*)?"
            r"(?:amraam|aim[- ]?120)",
            text
        )

        if amraam_match:

            loadout["amraam"] = int(
                amraam_match.group(1)
            )

        # =====================================================
        # SIDEWINDER
        # =====================================================

        sidewinder_match = re.search(
            r"(\d+)\s*(?:x\s*)?"
            r"(?:sidewinder|aim[- ]?9)",
            text
        )

        if sidewinder_match:

            loadout["sidewinder"] = int(
                sidewinder_match.group(1)
            )

        # =====================================================
        # GUN
        # =====================================================

        gun_match = re.search(
            r"(\d+)\s*(?:rounds?\s*)?"
            r"(?:of\s*)?(?:gun|gun rounds?|rounds?)",
            text
        )

        if gun_match:

            loadout["gun_rounds"] = int(
                gun_match.group(1)
            )

        print(
            "LOADOUT PARSER:"
            f" AMRAAM={loadout['amraam']}"
            f" Sidewinder={loadout['sidewinder']}"
            f" Gun={loadout['gun_rounds']}"
        )

        return loadout