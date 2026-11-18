#!/usr/bin/env python3
"""Sledovani systemu (luxos-monitor): razeni seznamu podle sloupce a zapamatovana volba.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_monitor_sort.py -v

Bez okna: testuje se jen sort_groups / load_sort / save_sort z programu (nastaveni v docasne slozce).
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(HERE, "..", "files", "bin", "luxos-monitor")
# moduly ze zdroju (luxos_charts, luxos_winsize, luxos_i18n), ne jen nainstalovane
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "files", "python")))


def load():
    loader = importlib.machinery.SourceFileLoader("luxos_monitor", PROG)
    spec = importlib.util.spec_from_loader("luxos_monitor", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


try:
    MON = load()
except (ImportError, ValueError) as e:      # bez GTK/Wnck
    MON = None
    WHY = str(e)

GROUPS = {
    "a": {"name": "Firefox", "cpu": 2.0, "mem": 900},
    "b": {"name": "code", "cpu": 9.0, "mem": 300},
    "c": {"name": "Bash", "cpu": 2.0, "mem": 950},
    "d": {"name": "zed", "cpu": 0.0, "mem": 300},
}


@unittest.skipIf(MON is None, "luxos-monitor needs python-gobject with Gtk 3 and Wnck 3")
class Sort(unittest.TestCase):
    def names(self, key, desc):
        return [g["name"] for _k, g in MON.sort_groups(GROUPS, key, desc)]

    def test_cpu(self):
        # shoda procesoru -> rozhodne pamet
        self.assertEqual(self.names("cpu", True), ["code", "Bash", "Firefox", "zed"])
        self.assertEqual(self.names("cpu", False), ["zed", "Firefox", "Bash", "code"])

    def test_memory(self):
        self.assertEqual(self.names("mem", True), ["Bash", "Firefox", "code", "zed"])
        self.assertEqual(self.names("mem", False)[:2], ["zed", "code"])

    def test_name_case_insensitive(self):
        self.assertEqual(self.names("name", False), ["Bash", "code", "Firefox", "zed"])
        self.assertEqual(self.names("name", True), ["zed", "Firefox", "code", "Bash"])

    def test_remembered(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = d
            try:
                self.assertEqual(MON.load_sort(), ("cpu", True), "vychozi")
                MON.save_sort("mem", False)
                self.assertEqual(MON.load_sort(), ("mem", False))
                with open(os.path.join(d, "luxos", "monitor.conf"), "w") as f:
                    f.write("{rozbite")
                self.assertEqual(MON.load_sort(), ("cpu", True), "poskozeny soubor -> vychozi")
                with open(os.path.join(d, "luxos", "monitor.conf"), "w") as f:
                    f.write('{"sort": "pid"}')
                self.assertEqual(MON.load_sort(), ("cpu", True), "neznamy sloupec -> vychozi")
            finally:
                if old is None:
                    os.environ.pop("XDG_CONFIG_HOME")
                else:
                    os.environ["XDG_CONFIG_HOME"] = old


if __name__ == "__main__":
    unittest.main()
