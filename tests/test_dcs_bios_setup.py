"""DCS-BIOS setup: python tests/test_dcs_bios_setup.py  (offline)"""

import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dcs_bios_setup as bios


def fake_release(path, with_bios=True, evil=False):

    with zipfile.ZipFile(path, "w") as z:
        if with_bios:
            z.writestr("DCS-BIOS/BIOS.lua", "-- bios")
            z.writestr("DCS-BIOS/BIOSConfig.lua", "-- default config")
            z.writestr("DCS-BIOS/lib/Log.lua", "-- log")
        if evil:
            z.writestr("DCS-BIOS/../../evil.lua", "x")
        z.writestr("Export.lua", bios.EXPORT_LINE + "\n")


def main():

    with tempfile.TemporaryDirectory() as tmp:

        tmp = Path(tmp)
        release = tmp / "rel.zip"
        fake_release(release)

        # --- fresh folder: missing -> installed -> ok ---
        sg = tmp / "DCS"
        sg.mkdir()
        assert bios.status(sg) == "missing"

        bios.install_zip(sg, release)
        assert (sg / "Scripts" / "DCS-BIOS" / "BIOS.lua").is_file()
        assert (sg / "Scripts" / "DCS-BIOS" / "lib" / "Log.lua").is_file()
        assert (sg / "Scripts" / "Export.lua").read_text().count("BIOS.lua") == 1
        assert bios.status(sg) == "ok"

        # --- running it again changes nothing, no duplicate line ---
        before = (sg / "Scripts" / "Export.lua").read_bytes()
        bios.install_zip(sg, release)
        assert (sg / "Scripts" / "Export.lua").read_bytes() == before

        # --- an existing Export.lua is appended to, not replaced (CRLF kept) ---
        other = tmp / "DCS.openbeta"
        (other / "Scripts").mkdir(parents=True)
        export = other / "Scripts" / "Export.lua"
        export.write_bytes(b"-- my stuff\r\nlocal x = 1")      # no final newline
        bios.install_zip(other, release)
        data = export.read_bytes()
        assert data.startswith(b"-- my stuff\r\nlocal x = 1\r\n")
        assert data.endswith(bios.EXPORT_LINE.encode() + b"\r\n")

        # --- user's BIOSConfig.lua is kept ---
        cfg = other / "Scripts" / "DCS-BIOS" / "BIOSConfig.lua"
        cfg.write_text("-- my config")
        bios.install_zip(other, release)
        assert cfg.read_text() == "-- my config"

        # --- commented-out line doesn't count; folder present -> no_export_line ---
        third = tmp / "third"
        (third / "Scripts" / "DCS-BIOS").mkdir(parents=True)
        (third / "Scripts" / "DCS-BIOS" / "BIOS.lua").write_text("x")
        (third / "Scripts" / "Export.lua").write_text("--" + bios.EXPORT_LINE + "\n")
        assert bios.status(third) == "no_export_line"
        assert bios.ensure_export_line(third) is True
        assert bios.status(third) == "ok"
        assert bios.ensure_export_line(third) is False

        # --- BIOS loaded from somewhere else (e.g. a hub install) counts as ok ---
        hub = tmp / "hub"
        (hub / "Scripts").mkdir(parents=True)
        (hub / "Scripts" / "Export.lua").write_text(
            'dofile([[C:\\Hub\\DCS-BIOS\\BIOS.lua]])\n')
        assert bios.status(hub) == "ok"

        # --- bad zips are refused, nothing escapes the Scripts folder ---
        bad = tmp / "bad.zip"
        fake_release(bad, with_bios=False)
        try:
            bios.install_zip(tmp / "x1", bad)
            raise AssertionError("should have failed")
        except RuntimeError:
            pass

        evil = tmp / "evil.zip"
        fake_release(evil, evil=True)
        try:
            bios.install_zip(tmp / "x2", evil)
            raise AssertionError("should have failed")
        except RuntimeError:
            pass
        assert not (tmp / "evil.lua").exists()

        # --- download_and_install never raises (network failure) ---
        real = bios.download_latest

        def boom(target):
            raise OSError("offline")

        bios.download_latest = boom
        try:
            ok, message = bios.download_and_install(tmp / "x3")
        finally:
            bios.download_latest = real
        assert not ok and "offline" in message

    print("dcs-bios setup tests passed")


if __name__ == "__main__":
    main()
