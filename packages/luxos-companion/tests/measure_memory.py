#!/usr/bin/env python3
"""Izolovane mereni PSS sluzby a kalendarove cache, bez Bluetooth a skutecnych dat.

    python3 tests/measure_memory.py [--files /cesta/k/puvodnim/files] [--events 4000]

Spoustet zvlast pro obe revize, stejnym Pythonem. Zamerne se nemeri GUI ani bluetoothd.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def pss_kib():
    for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
        if line.startswith("Pss:"):
            return int(line.split()[1])
    raise RuntimeError("PSS is unavailable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=Path, default=Path(__file__).resolve().parents[1] / "files")
    parser.add_argument("--events", type=int, default=4000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(args.files), str(root / "luxos-desktop/files/python"),
                    str(root / "luxos-i18n/files")]
    with tempfile.TemporaryDirectory(prefix="companion-memory-") as tmp:
        for kind in ("CONFIG", "DATA", "STATE", "CACHE"):
            os.environ[f"XDG_{kind}_HOME"] = str(Path(tmp) / kind.lower())
        os.environ.update(LANG="en_GB.UTF-8", LC_ALL="en_GB.UTF-8", GIO_USE_VFS="local",
                          LUXOS_COMPANION_QUIET="1", LUXOS_I18N_DIR=str(root / "luxos-i18n/files"),
                          LUXOS_CALENDAR_DIR=str(Path(tmp) / "calendar"))
        from luxos_companion import service

        svc = service.Service(None)
        result = {"idle_kib": pss_kib(), "events": args.events}

        class Transport:
            def close(self):
                pass

        peer = {"address": "AA:BB:CC:DD:EE:01", "name": "Memory test"}
        connection = svc.new_connection(-1, peer, transport=Transport())
        directory = Path(svc.calendar.dir)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "events.ics").open("w") as f:
            f.write("BEGIN:VCALENDAR\nVERSION:2.0\n")
            for i in range(args.events):
                f.write(f"BEGIN:VEVENT\nUID:memory-{i}\nDTSTART;VALUE=DATE:20261028\n"
                        f"DTEND;VALUE=DATE:20261029\nSUMMARY:Event {i}\nDESCRIPTION:{'x' * 4096}\nEND:VEVENT\n")
            f.write("END:VCALENDAR\n")
        svc.calendar_reader.list_events({"date": "2026-10-28", "timezone": "UTC"})
        result["calendar_loaded_kib"] = pss_kib()
        connection.close("disconnected")
        result["disconnected_kib"] = pss_kib()
        print(json.dumps(result))


if __name__ == "__main__":
    main()
