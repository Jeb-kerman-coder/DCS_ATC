import socket
import struct

HOST = "127.0.0.1"
PORT = 7778

SYNC = b"\x55\x55\x55\x55"

COMM1_ADDRESS = 0x7400
COMM2_ADDRESS = 0x7402


# ============================================================
# COMMONDATA ADDRESSES
# ============================================================

ALT_MSL_FT_ADDRESS = 0x0434
HDG_ADDRESS = 0x0436

LAT_ADDRESS = 0x041E
LAT_SEC_ADDRESS = 0x0420
LAT_FRAC_ADDRESS = 0x0422

LON_ADDRESS = 0x0420
LON_SEC_ADDRESS = 0x0430
LON_FRAC_ADDRESS = 0x0432


class DCSBIOS:

    def __init__(self):

        self.sock = None
        self.buffer = bytearray()

        self.state = {
            "com1_frequency": None,
            "com2_frequency": None,

            "altitude_ft": None,
            "heading_deg": None,
            "latitude": None,
            "longitude": None,
        }

        # ----------------------------------------------------
        # CommonData raw memory
        #
        # DCS-BIOS may send a larger block containing several
        # CommonData values. We therefore maintain a memory
        # image and decode values from their addresses.
        # ----------------------------------------------------

        self.memory = bytearray(0x0500)

    # ========================================================
    # CONNECTION
    # ========================================================

    def connect(self):

        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        self.sock.connect(
            (HOST, PORT)
        )

        print(
            "Connected to DCS-BIOS"
        )

    # ========================================================
    # UPDATE
    # ========================================================

    def update(self):

        data = self.sock.recv(4096)

        if not data:

            raise ConnectionError(
                "DCS-BIOS disconnected"
            )

        self.buffer.extend(data)

        self._process_buffer()

    # ========================================================
    # BUFFER PROCESSING
    # ========================================================

    def _process_buffer(self):

        while True:

            start = self.buffer.find(
                SYNC
            )

            if start == -1:

                if len(self.buffer) > 3:

                    del self.buffer[:-3]

                return

            if start > 0:

                del self.buffer[:start]

            next_sync = self.buffer.find(
                SYNC,
                4
            )

            if next_sync == -1:

                return

            frame = bytes(
                self.buffer[4:next_sync]
            )

            del self.buffer[:next_sync]

            self._process_frame(
                frame
            )

    # ========================================================
    # FRAME PROCESSING
    # ========================================================

    def _process_frame(
        self,
        frame
    ):

        position = 0

        while position + 4 <= len(frame):

            address, length = struct.unpack_from(
                "<HH",
                frame,
                position
            )

            position += 4

            if position + length > len(frame):

                return

            data = frame[
                position:
                position + length
            ]

            position += length

            # =================================================
            # EXISTING COMMUNICATION CODE
            # =================================================

            if address == COMM1_ADDRESS:

                if len(data) >= 2:

                    self.state[
                        "com1_frequency"
                    ] = (
                        struct.unpack_from(
                            "<H",
                            data
                        )[0] / 100
                    )

            elif address == COMM2_ADDRESS:

                if len(data) >= 2:

                    self.state[
                        "com2_frequency"
                    ] = (
                        struct.unpack_from(
                            "<H",
                            data
                        )[0] / 100
                    )

            # =================================================
            # STORE COMMONDATA IN MEMORY
            # =================================================

            if (
                address + length
                <= len(self.memory)
            ):

                self.memory[
                    address:
                    address + length
                ] = data

        # =====================================================
        # IMPORTANT
        #
        # Decode CommonData AFTER the entire frame has been
        # copied into memory.
        #
        # This handles DCS-BIOS records which contain multiple
        # CommonData values in one payload.
        # =====================================================

        self._decode_commondata()

    # ========================================================
    # COMMONDATA DECODER
    # ========================================================

    def _decode_commondata(self):

        # ----------------------------------------------------
        # ALTITUDE
        #
        # 0x0434
        # 16-bit integer, feet MSL
        # ----------------------------------------------------

        if (
            ALT_MSL_FT_ADDRESS + 2
            <= len(self.memory)
        ):

            altitude_raw = struct.unpack_from(
                "<H",
                self.memory,
                ALT_MSL_FT_ADDRESS
            )[0]

            self.state[
                "altitude_ft"
            ] = altitude_raw

        # ----------------------------------------------------
        # HEADING
        #
        # 0x0436
        #
        # Bits 0-8:
        #   Whole degrees
        #
        # Bits 9-15:
        #   Fraction
        #
        # Fraction is divided by 127.
        # ----------------------------------------------------

        if (
            HDG_ADDRESS + 2
            <= len(self.memory)
        ):

            heading_raw = struct.unpack_from(
                "<H",
                self.memory,
                HDG_ADDRESS
            )[0]

            degrees = (
                heading_raw
                & 0x01FF
            )

            fraction_raw = (
                heading_raw
                & 0xFE00
            ) >> 9

            fraction = (
                fraction_raw / 127.0
            )

            heading = (
                degrees + fraction
            )

            heading %= 360.0

            self.state[
                "heading_deg"
            ] = heading

        # ----------------------------------------------------
        # LATITUDE
        # ----------------------------------------------------

        self._decode_latitude()

        # ----------------------------------------------------
        # LONGITUDE
        # ----------------------------------------------------

        self._decode_longitude()

    # ========================================================
    # LATITUDE
    # ========================================================

    def _decode_latitude(self):

        # 0x041E
        if (
            LAT_ADDRESS + 2
            > len(self.memory)
        ):

            return

        # Latitude degrees occupy bits 8-14.
        raw = struct.unpack_from(
            "<H",
            self.memory,
            LAT_ADDRESS
        )[0]

        degrees = (
            raw & 0x7F00
        ) >> 8

        # Latitude seconds occupy bits 0-5
        seconds = (
            raw & 0x003F
        )

        # Latitude fractional seconds
        if (
            LAT_FRAC_ADDRESS + 2
            <= len(self.memory)
        ):

            fraction_raw = struct.unpack_from(
                "<H",
                self.memory,
                LAT_FRAC_ADDRESS
            )[0]

            fraction = (
                fraction_raw / 65535.0
            )

        else:

            fraction = 0.0

        latitude = (
            degrees
            + (
                seconds + fraction
            ) / 3600.0
        )

        # Direction.
        #
        # The direction is represented in the CommonData
        # byte overlay at 0x041E.
        direction = chr(
            self.memory[LAT_ADDRESS]
        )

        if direction == "S":

            latitude = -latitude

        self.state[
            "latitude"
        ] = latitude

    # ========================================================
    # LONGITUDE
    # ========================================================

    def _decode_longitude(self):

        # Longitude degrees share 0x0420.
        if (
            LON_ADDRESS + 2
            > len(self.memory)
        ):

            return

        raw = struct.unpack_from(
            "<H",
            self.memory,
            LON_ADDRESS
        )[0]

        degrees = (
            raw & 0x3FC0
        ) >> 6

        # Longitude seconds are at 0x0430.
        if (
            LON_SEC_ADDRESS + 2
            <= len(self.memory)
        ):

            seconds_raw = struct.unpack_from(
                "<H",
                self.memory,
                LON_SEC_ADDRESS
            )[0]

            seconds = (
                seconds_raw & 0x3F00
            ) >> 8

        else:

            seconds = 0

        # Longitude fractional seconds.
        if (
            LON_FRAC_ADDRESS + 2
            <= len(self.memory)
        ):

            fraction_raw = struct.unpack_from(
                "<H",
                self.memory,
                LON_FRAC_ADDRESS
            )[0]

            fraction = (
                fraction_raw / 65535.0
            )

        else:

            fraction = 0.0

        longitude = (
            degrees
            + (
                seconds + fraction
            ) / 3600.0
        )

        # Direction is the character overlay at 0x0430.
        direction = chr(
            self.memory[LON_SEC_ADDRESS]
        )

        if direction == "W":

            longitude = -longitude

        self.state[
            "longitude"
        ] = longitude

    # ========================================================
    # STATE
    # ========================================================

    def get_state(self):

        return self.state.copy()

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self):

        if self.sock:

            self.sock.close()

            self.sock = None