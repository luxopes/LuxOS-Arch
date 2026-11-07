"""Skener: naskenovany recept (nahled + pruh stranek), pak druha stranka a ulozeni do PDF.

Falesny scanimage v PATH (_d.py) - jeden sitovy skener, "naskenovane" stranky jsou ukazkove obrazky
vykreslene v postupu; zadny skutecny skener ani SANE."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN_BTN = (791, 505)             # tlacitko Skenovat vpravo (okno 940x680)


def helper():
    spec = importlib.util.spec_from_file_location("shots_group_d", os.path.join(HERE, "_d.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shots(s):
    env = helper().fake_bin(s)
    p = s.launch_python("luxos-printing/files/luxos-scan", env=env, paths=("luxos-printing/files",))
    win = s.window(pid=p.pid, size=(940, 680))
    s.sleep(2)
    s.click(*SCAN_BTN, win)
    s.sleep(4)
    s.capture("1", win)
    s.click(*SCAN_BTN, win)          # Skenovat dalsi stranku
    s.sleep(4)
    s.click(895, 627, win)            # Ulozit (PDF do ~/Documents docasneho HOME)
    s.sleep(3)
    s.capture("2", win)
