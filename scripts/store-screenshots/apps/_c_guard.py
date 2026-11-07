#!/usr/bin/env python3
"""Lux Guard pro snimky Obchodu: okno ze zdroju s ukazkovym stavem (zadny skutecny socket ani sluzba).

Spousti postup luxos-guard.py. Dotazy na sluzbu (request), seznam snimku /home a spusteni v sandboxu jsou
nahrazene ukazkovymi daty - na /run/luxos-guard se nesaha, nic se nespousti ani neobnovuje.

    _c_guard.py PATH_TO_luxos-guard-gui window|ask|blocked
"""
import datetime
import importlib.machinery
import importlib.util
import os
import sys
import time

# Moduly ze zdroju drive, nez luxos_guard_session prida /usr/lib/luxos/python na zacatek sys.path
import luxos_guard_core  # noqa: E402,F401
import luxos_guard_rules  # noqa: E402,F401
import luxos_guard_snap  # noqa: E402,F401
import luxos_guard_session  # noqa: E402,F401

DL = "/home/anna/Downloads"
NOW = time.time()

STATUS = {"op": "status", "version": "1.0.0"}
LIST = {"op": "list", "entries": [
    {"path": DL + "/codec-installer.sh", "kind": "script", "interp": "bash", "level": "critical",
     "status": "flagged", "t": NOW - 1800, "reasons": ["deletes your files, your home folder or the whole system"]},
    {"path": DL + "/SuperTuxKart-1.5-x86_64.AppImage", "kind": "appimage", "level": "risky", "status": "allowed",
     "t": NOW - 3 * 3600, "reasons": []},
    {"path": DL + "/setup-printer.sh", "kind": "script", "interp": "bash", "level": "risky", "status": "flagged",
     "t": NOW - 26 * 3600, "reasons": []},
], "log": [
    {"t": NOW - 26 * 3600, "action": "found", "path": DL + "/setup-printer.sh"},
    {"t": NOW - 3 * 3600 - 60, "action": "found", "path": DL + "/SuperTuxKart-1.5-x86_64.AppImage"},
    {"t": NOW - 3 * 3600, "action": "allowed", "path": DL + "/SuperTuxKart-1.5-x86_64.AppImage"},
    {"t": NOW - 1800, "action": "blocked", "path": DL + "/codec-installer.sh"},
    {"t": NOW - 1700, "action": "sandbox", "path": DL + "/codec-installer.sh"},
]}

ASK = {"mode": "ask", "path": DL + "/minecraft-launcher.sh", "level": "risky", "kind": "script",
       "interp": "bash", "reasons": [], "notes": ["downloads more code from the internet and runs it"],
       "origin": "download"}
BLOCKED = {"mode": "blocked", "path": DL + "/codec-installer.sh", "level": "critical", "kind": "script",
           "interp": "bash", "reasons": ["deletes your files, your home folder or the whole system",
                                         "tries to switch off Lux Guard or delete its backups"],
           "origin": "download"}


def snapshots():
    now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [now - datetime.timedelta(hours=h) for h in range(0, 2)]
    days = [(now - datetime.timedelta(days=1)).replace(hour=21)]
    return [(t, "/nonexistent/snapshot") for t in sorted(days + hours)]


def main():
    loader = importlib.machinery.SourceFileLoader("luxos_guard_gui", sys.argv[1])
    spec = importlib.util.spec_from_loader("luxos_guard_gui", loader)
    gui = importlib.util.module_from_spec(spec)
    loader.exec_module(gui)
    gui.request = lambda msg, timeout=5: STATUS if msg.get("op") == "status" else LIST
    gui.snap.list_snapshots = lambda home=None: snapshots()
    gui.snap.fs_type = lambda path: "btrfs"
    gui.snap.restore = lambda *a, **k: (0, 0)
    gui.run_in_sandbox = lambda *a, **k: None
    gui.subprocess = None                      # zadne xdg-open
    gui.setup_css()
    gui.GLib.set_prgname("luxos-guard")
    mode = sys.argv[2]
    if mode == "window":
        gui.GuardWindow()
    else:
        d = gui.GuardDialog(ASK if mode == "ask" else BLOCKED)
        d.connect("destroy", lambda _w: gui.Gtk.main_quit())
    gui.Gtk.main()


if __name__ == "__main__":
    main()
