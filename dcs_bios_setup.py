"""
Installs DCS-BIOS (the export the app reads radio frequencies from) for the
user, the way its own instructions say:

  1. the  DCS-BIOS  folder from the official release goes into
         Saved Games\\DCS*\\Scripts\\DCS-BIOS
  2. Export.lua  (same Scripts folder) gets the line
         dofile(lfs.writedir() .. [[Scripts\\DCS-BIOS\\BIOS.lua]])
     added - appended to an existing file, never overwriting it.

DCS-BIOS is downloaded from its official GitHub releases when the user
agrees, rather than shipped inside our installer (it has its own licence).
"""

import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://github.com/DCS-Skunkworks/dcs-bios"
LATEST = BASE + "/releases/latest"

EXPORT_LINE = "dofile(lfs.writedir() .. [[Scripts\\DCS-BIOS\\BIOS.lua]])"

FOLDER_IN_ZIP = "DCS-BIOS/"


# ---------------------------------------------------------
# state of one Saved Games\DCS* folder
# ---------------------------------------------------------

def has_export_line(export_lua):
    """An ACTIVE (not commented out) line that loads a BIOS.lua."""

    try:
        text = Path(export_lua).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    for line in text.splitlines():

        stripped = line.strip()

        if (
            stripped
            and not stripped.startswith("--")
            and "bios.lua" in stripped.lower()
        ):
            return True

    return False


def status(variant_folder):
    """
    'ok'              Export.lua already loads DCS-BIOS
    'no_export_line'  the DCS-BIOS folder is there but Export.lua isn't set up
    'missing'         DCS-BIOS is not installed
    """

    scripts = Path(variant_folder) / "Scripts"

    if has_export_line(scripts / "Export.lua"):
        return "ok"

    if (scripts / "DCS-BIOS" / "BIOS.lua").is_file():
        return "no_export_line"

    return "missing"


def ensure_export_line(variant_folder):
    """Add the dofile line to Export.lua (creating it if needed).
    -> True if the file was changed."""

    export = Path(variant_folder) / "Scripts" / "Export.lua"

    if has_export_line(export):
        return False

    export.parent.mkdir(parents=True, exist_ok=True)

    raw = export.read_bytes() if export.exists() else b""

    newline = b"\r\n" if b"\r\n" in raw else b"\n"

    if raw and not raw.endswith(b"\n"):
        raw += newline

    export.write_bytes(raw + EXPORT_LINE.encode("utf-8") + newline)

    return True


# ---------------------------------------------------------
# download + install
# ---------------------------------------------------------

def _open(url):

    request = urllib.request.Request(url, headers={"User-Agent": "DCS-ATC"})

    return urllib.request.urlopen(request, timeout=60)


def latest_zip_url():
    """URL of the newest DCS-BIOS_<version>.zip release asset."""

    with _open(LATEST) as response:
        tag = response.geturl().rstrip("/").split("/")[-1]

    try:
        with _open(f"{BASE}/releases/expanded_assets/{tag}") as response:
            page = response.read().decode("utf-8", errors="replace")

        match = re.search(
            r'href="(/[^"]*/releases/download/[^"]+/DCS-BIOS_[^"/]+\.zip)"',
            page
        )

        if match:
            return "https://github.com" + match.group(1)

    except OSError:
        pass

    return f"{BASE}/releases/download/{tag}/DCS-BIOS_{tag}.zip"


def download_latest(target):

    with _open(latest_zip_url()) as response, open(target, "wb") as out:
        shutil.copyfileobj(response, out)


def install_zip(variant_folder, zip_path):
    """Unpack the DCS-BIOS folder from a release zip and set up Export.lua.
    An existing BIOSConfig.lua is kept."""

    scripts = Path(variant_folder) / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)

    root = scripts.resolve()

    with zipfile.ZipFile(zip_path) as archive:

        members = [
            m for m in archive.namelist()
            if m.startswith(FOLDER_IN_ZIP) and not m.endswith("/")
        ]

        if not any(m == FOLDER_IN_ZIP + "BIOS.lua" for m in members):
            raise RuntimeError("this zip does not contain DCS-BIOS/BIOS.lua")

        for member in members:

            target = (scripts / member).resolve()

            if root not in target.parents:
                raise RuntimeError(f"unsafe path in zip: {member}")

            if target.name == "BIOSConfig.lua" and target.exists():
                continue

            target.parent.mkdir(parents=True, exist_ok=True)

            with archive.open(member) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)

    ensure_export_line(variant_folder)


def download_and_install(variant_folder):
    """-> (ok, message). Never raises."""

    try:

        with tempfile.TemporaryDirectory() as tmp:

            zip_path = Path(tmp) / "dcs-bios.zip"

            download_latest(zip_path)
            install_zip(variant_folder, zip_path)

        return True, f"DCS-BIOS installed in {Path(variant_folder).name}."

    except Exception as exc:

        return False, (
            f"Could not install DCS-BIOS in {Path(variant_folder).name}: "
            f"{exc}"
        )
