class FrequencyManager:
    """
    Maps radio frequencies to controllers.

    The tower and AWACS channels are stored in settings.json (the
    "channels" section) and can be changed from the interface, so they
    survive a restart. data/frequencies.json is no longer used.
    """

    # settings key -> (controller, station)
    CONTROLLERS = {
        "tower": ("TOWER", "AIRBASE"),
        "awacs": ("AWACS", "TACTICAL"),
    }

    MIN_MHZ = 30.0
    MAX_MHZ = 400.0

    def __init__(self, settings):

        self.settings = settings

        self.frequencies = {}

        self.reload()

    # ---------------------------------------------------------
    # parsing
    # ---------------------------------------------------------

    @classmethod
    def parse(cls, text):
        """'127.8' / '127,800' / '127.800 MHz' -> 127.8, or None if invalid."""

        if isinstance(text, (int, float)):
            value = float(text)
        else:
            cleaned = str(text).strip().lower().replace(",", ".")

            if cleaned.endswith("mhz"):
                cleaned = cleaned[:-3].strip()

            try:
                value = float(cleaned)
            except ValueError:
                return None

        if not (cls.MIN_MHZ <= value <= cls.MAX_MHZ):
            return None

        return round(value, 3)

    @staticmethod
    def _key(frequency):

        return f"{frequency:.3f}"

    # ---------------------------------------------------------
    # channels
    # ---------------------------------------------------------

    def get_channel(self, name):
        """Current frequency (MHz) for 'tower' or 'awacs'."""

        value = self.parse(self.settings.get("channels", name))

        if value is None:
            value = self.parse(
                self.settings.DEFAULT_SETTINGS["channels"][name]
            )

        return value

    def set_channel(self, name, text):
        """
        Validate, save and apply a new channel.
        Returns (ok, message, frequency).
        """

        if name not in self.CONTROLLERS:
            return False, f"Unknown channel '{name}'.", None

        frequency = self.parse(text)

        if frequency is None:
            return (
                False,
                f"Enter a frequency between {self.MIN_MHZ:.0f} and "
                f"{self.MAX_MHZ:.0f} MHz, e.g. 127.800",
                None
            )

        for other in self.CONTROLLERS:

            if other != name and self.get_channel(other) == frequency:

                return (
                    False,
                    f"{frequency:.3f} is already used by "
                    f"{self.CONTROLLERS[other][0]}.",
                    None
                )

        self.settings.set("channels", name, frequency)

        self.reload()

        return True, f"{self.CONTROLLERS[name][0]} set to {frequency:.3f} MHz", frequency

    def reload(self):
        """Rebuild the lookup table from settings (swapped in one step so
        the DCS worker thread never sees a half-built table)."""

        table = {}

        for name, (controller, station) in self.CONTROLLERS.items():

            table[self._key(self.get_channel(name))] = {
                "controller": controller,
                "station": station
            }

        self.frequencies = table

    # ---------------------------------------------------------
    # lookup
    # ---------------------------------------------------------

    def lookup(self, frequency):

        if frequency is None:
            return None

        return self.frequencies.get(self._key(frequency))
