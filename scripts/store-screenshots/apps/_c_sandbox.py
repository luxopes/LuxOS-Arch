#!/usr/bin/env python3
"""Sandbox pro snimky Obchodu: okno ze zdroju s falesnym prikazem luxos-sandbox (zadny skutecny sandbox).

    _c_sandbox.py cli ARGS...            falesny luxos-sandbox (LUXOS_SANDBOX_CLI): status, install, run
    _c_sandbox.py gui PATH_TO_GUI MODE   okno; MODE "ready" nebo "install" (instalace + Podrobnosti)

Falesny prikaz jen vypisuje ukazkovy text - nic nevytvari, nestahuje, nespousti pkexec ani bubblewrap.
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import time

APPS = {"firefox": "firefox", "gimp": "gimp", "vlc": "vlc"}
INSTALL_LOG = """:: Synchronizing package databases...
 core is up to date
 extra is up to date
resolving dependencies...
looking for conflicting packages...

Packages (6) gc-8.2.8-1  gsl-2.8-1  gtkmm3-3.24.9-1  poppler-glib-24.12.0-1  potrace-1.16-6  inkscape-1.4-3

Total Download Size:    48.21 MiB
Total Installed Size:  212.67 MiB

:: Proceed with installation? [Y/n]
:: Retrieving packages...
 inkscape-1.4-3-x86_64 downloading...
:: Processing package changes...
(6/6) installing inkscape
:: Running post-transaction hooks...
(1/3) Updating icon theme caches...
(2/3) Updating the desktop file MIME type cache...
(3/3) Arming ConditionNeedsUpdate...
"""


def cli(args):
    state = os.environ.get("DEMO_SANDBOX_STATE")
    apps = dict(APPS)
    if state and os.path.exists(state):
        apps.update(json.load(open(state)))
    if args[:1] == ["status"]:
        print(json.dumps({"exists": True, "path": "/var/lib/luxos/sandbox/anna", "size": 1_412_000_000,
                          "shared": "~/Sandbox", "link": "/dev/sandbox/anna", "apps": apps}))
        return 0
    if args[:1] == ["install"]:
        for line in INSTALL_LOG.splitlines():
            print(line, flush=True)
            time.sleep(0.02)
        if state:
            apps = {p: p for p in args[1:]}
            json.dump(apps, open(state, "w"))
        return 0
    return 0


def gui(path, mode):
    loader = importlib.machinery.SourceFileLoader("luxos_sandbox_gui", path)
    spec = importlib.util.spec_from_loader("luxos_sandbox_gui", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.SHARED = "/home/anna/Sandbox"          # jen popisek (skutecny docasny HOME by byl dlouhy)
    if mode == "install":
        def go():
            win = [w for w in mod.Gtk.Window.list_toplevels() if isinstance(w, mod.SandboxWindow)][0]
            win.pkg_entry.set_text("inkscape")
            win.install()
            win.expander.set_expanded(True)

            def bottom():
                adj = win.get_child().get_vadjustment()
                adj.set_value(adj.get_upper() - adj.get_page_size())
                buf = win.log.get_buffer()
                win.log.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
                return True
            mod.GLib.timeout_add(300, bottom)
            return False
        mod.GLib.timeout_add(800, go)
    mod.main()


if __name__ == "__main__":
    if sys.argv[1] == "cli":
        sys.exit(cli(sys.argv[2:]))
    gui(sys.argv[2], sys.argv[3])
