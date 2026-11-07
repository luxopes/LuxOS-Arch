#!/usr/bin/env python3
"""Ovladace pro snimky Obchodu: okno ze zdroju nad falesnym hardwarem (zadny pkexec ani instalace).

    _c_drivers.py gui PATH_TO_luxos-drivers MODE   MODE "list" nebo "install"
    _c_drivers.py helper ...                       falesny pomocnik: jen vypise prubeh (@@ radky)

luxos-hwdetect ze zdroju cte falesny /sys a /proc v $LUXOS_HW_ROOT (pripravi postup luxos-drivers.py),
nainstalovane baliky jsou falesna databaze v tomtez koreni (drv.ROOT). Spusteni "pkexec HELPER" se
nahradi timto skriptem v rezimu helper, restart pocitace nicim.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import time


def helper():
    for line in ("@@STEP install", "@@PROGRESS download 35", "@@PROGRESS download 72"):
        print(line, flush=True)
        time.sleep(0.3)
    time.sleep(120)                     # prubeh zustane videt (skupinu procesu ukonci harness)


class FakeSubprocess:
    """subprocess pro okno: "pkexec ..." -> falesny pomocnik, nic jineho se nespousti."""
    PIPE, STDOUT, DEVNULL = subprocess.PIPE, subprocess.STDOUT, subprocess.DEVNULL

    @staticmethod
    def Popen(cmd, **kw):
        if cmd[:1] != ["pkexec"]:
            raise OSError("not in the demo")
        return subprocess.Popen([sys.executable, os.path.abspath(__file__), "helper"], **kw)


def gui(path, mode):
    import luxos_drivers as drv          # ze zdroju (PYTHONPATH) drive, nez okno prida /usr/lib/luxos/python
    import luxos_i18n  # noqa: F401
    drv.HWDETECT = os.environ["DEMO_HWDETECT"]
    drv.ROOT = os.environ["LUXOS_HW_ROOT"]
    loader = importlib.machinery.SourceFileLoader("luxos_drivers_gui", path)
    spec = importlib.util.spec_from_loader("luxos_drivers_gui", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.subprocess = FakeSubprocess
    mod.DriversWindow.restart = lambda self: None
    if mode == "install":
        def go():
            win = [w for w in mod.Gtk.Window.list_toplevels() if isinstance(w, mod.DriversWindow)][0]
            if not win.states:
                return True
            win.install(None)
            return False
        mod.GLib.timeout_add(500, go)
    mod.main()


if __name__ == "__main__":
    if sys.argv[1] == "helper":
        helper()
    else:
        gui(sys.argv[2], sys.argv[3])
