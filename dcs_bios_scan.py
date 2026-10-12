import socket
import struct


HOST = "127.0.0.1"
PORT = 7778

SYNC = b"\x55\x55\x55\x55"


# ============================================================
# DCS-BIOS CommonData addresses
# From the installed CommonData.json
# ============================================================

ALT_MSL_FT_ADDRESS = 0x0434

HDG_ADDRESS = 0x0436

LAT_ADDRESS = 0x041E
LAT_SEC_ADDRESS = 0x0420
LAT_FRAC_ADDRESS = 0x0422

LON_ADDRESS = 0x0420
LON_SEC_ADDRESS = 0x0430
LON_FRAC_ADDRESS = 0x0432

LAT_DIR_ADDRESS = 0x041E
LON_DIR_ADDRESS = 0x0430


# ============================================================
# Raw DCS-BIOS memory
# ============================================================

memory = bytearray(0x0500)


def write_memory(address, data):
    """Store a DCS-BIOS payload at its address."""

    end = address + len(data)

    if end > len(memory):
        return

    memory[address:end] = data


def read_u16(address):
    """Read a little-endian unsigned 16-bit value."""

    return struct.unpack_from("<H", memory, address)[0]


# ============================================================
# Decode CommonData
# ============================================================

def get_altitude():

    raw = read_u16(ALT_MSL_FT_ADDRESS)

    # mask = 0xFFFF
    # shift = 0
    altitude = raw

    return altitude


def get_heading():

    raw = read_u16(HDG_ADDRESS)

    # HDG_DEG
    degrees = raw & 0x01FF

    # HDG_DEG_FRAC
    fraction_raw = (raw & 0xFE00) >> 9

    # Fractional degrees / 127
    fraction = fraction_raw / 127.0

    heading = degrees + fraction

    # Keep it inside 0-360
    if heading >= 360:
        heading -= 360

    return heading


def get_latitude():

    raw_deg_word = read_u16(LAT_ADDRESS)
    raw_sec = read_u16(LAT_SEC_ADDRESS)
    raw_frac = read_u16(LAT_FRAC_ADDRESS)

    # LAT_DEG
    degrees = (raw_deg_word & 0x7F00) >> 8

    # LAT_SEC
    seconds = raw_sec & 0x003F

    # LAT_SEC_FRAC
    fraction = raw_frac / 65535.0

    total_seconds = seconds + fraction

    latitude = degrees + (total_seconds / 3600.0)

    # Direction is stored at the same address as LAT_DEG.
    # DCS-BIOS exposes it as a one-character string.
    direction_byte = memory[LAT_DIR_ADDRESS]

    try:
        direction = chr(direction_byte)
    except ValueError:
        direction = "?"

    if direction == "S":
        latitude = -latitude

    return latitude, direction


def get_longitude():

    raw_deg_word = read_u16(LON_ADDRESS)
    raw_sec_word = read_u16(LON_SEC_ADDRESS)
    raw_frac = read_u16(LON_FRAC_ADDRESS)

    # LON_DEG
    degrees = (raw_deg_word & 0x3FC0) >> 6

    # LON_SEC
    seconds = (raw_sec_word & 0x3F00) >> 8

    # LON_SEC_FRAC
    fraction = raw_frac / 65535.0

    total_seconds = seconds + fraction

    longitude = degrees + (total_seconds / 3600.0)

    direction_byte = memory[LON_DIR_ADDRESS]

    try:
        direction = chr(direction_byte)
    except ValueError:
        direction = "?"

    if direction == "W":
        longitude = -longitude

    return longitude, direction


# ============================================================
# Print decoded state
# ============================================================

last_state = {
    "altitude": None,
    "heading": None,
    "latitude": None,
    "longitude": None,
}


def print_state():

    altitude = get_altitude()
    heading = get_heading()
    latitude, lat_dir = get_latitude()
    longitude, lon_dir = get_longitude()

    changed = (
        last_state["altitude"] != altitude
        or last_state["heading"] != heading
        or last_state["latitude"] != latitude
        or last_state["longitude"] != longitude
    )

    if not changed:
        return

    print()
    print("========== COMMONDATA ==========")

    print(f"Altitude : {altitude} ft")
    print(f"Heading  : {heading:.3f}°")

    print(
        f"Latitude : {abs(latitude):.6f}° {lat_dir}"
        f"    ({latitude:.6f})"
    )

    print(
        f"Longitude: {abs(longitude):.6f}° {lon_dir}"
        f"    ({longitude:.6f})"
    )

    print("=================================")

    last_state["altitude"] = altitude
    last_state["heading"] = heading
    last_state["latitude"] = latitude
    last_state["longitude"] = longitude


# ============================================================
# DCS-BIOS connection
# ============================================================

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

print("Connecting to DCS-BIOS...")
sock.connect((HOST, PORT))

print("Connected to DCS-BIOS")
print()
print("Move the aircraft / change:")
print("  - altitude")
print("  - heading")
print("  - position")
print()
print("Press CTRL+C to stop.")
print()


buffer = bytearray()


# ============================================================
# Main receive loop
# ============================================================

while True:

    data = sock.recv(4096)

    if not data:
        print("DCS-BIOS disconnected.")
        break

    buffer.extend(data)

    while True:

        # Find the beginning of a DCS-BIOS frame.
        start = buffer.find(SYNC)

        if start == -1:

            # Keep the last 3 bytes in case they are
            # the beginning of the next sync sequence.
            if len(buffer) > 3:
                del buffer[:-3]

            break

        # Remove anything before the sync.
        if start > 0:
            del buffer[:start]

        # Find the next sync.
        next_sync = buffer.find(SYNC, 4)

        if next_sync == -1:
            break

        # Everything between the sync sequences is the frame.
        frame = bytes(buffer[4:next_sync])

        # Remove this frame from the buffer.
        del buffer[:next_sync]

        position = 0

        while position + 4 <= len(frame):

            address, length = struct.unpack_from(
                "<HH",
                frame,
                position
            )

            position += 4

            if position + length > len(frame):
                break

            payload = frame[
                position:
                position + length
            ]

            position += length

            # Store the raw bytes.
            write_memory(address, payload)

        # Try decoding the current CommonData state.
        print_state()