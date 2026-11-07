"""Lux Guard: okno (hlidane soubory, posledni rozhodnuti, obnova ze snimku), dotaz u neznameho programu
a zprava o zablokovanem nebezpecnem programu.

Ukazkovy stav (_c_guard.py): zadny skutecny socket /run/luxos-guard, sluzba, sandbox ani obnova.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def shots(s):
    s.python_env("luxos-guard/files")
    gui = s.src("luxos-guard/files/luxos-guard-gui")
    helper = os.path.join(HERE, "_c_guard.py")
    p = s.launch([sys.executable, helper, gui, "window"])
    win = s.window(pid=p.pid, size=(660, 796))
    s.sleep(1.0)
    s.capture("1", win)
    p2 = s.launch([sys.executable, helper, gui, "ask"])
    dlg = s.window(pid=p2.pid, size=None)
    s.capture("2", dlg)
    p3 = s.launch([sys.executable, helper, gui, "blocked"])
    dlg = s.window(pid=p3.pid, size=None)
    s.capture("3", dlg)
