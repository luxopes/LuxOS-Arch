#!/usr/bin/env python3
"""Aktualizace softwaru: "Posledni aktualizace" i po lux update z Terminalu (regrese audit 1.0.2:
po aktualizaci tlacitkem v uvitacim okne okno ukazovalo "Last update: never").
    python3 packages/luxos-care/tests/test_update_last.py"""
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
import datetime
import os
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "luxos-update")


def load():
    src = open(SRC, encoding="utf-8").read()
    ns = {"os": os, "ROOT": ""}
    exec(src[src.index("def last_upgrade("):src.index("def when(t):")], ns)
    return ns["last_upgrade"]


class LastUpgrade(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_last_upgraded_line(self):
        log = self.write(
            "[2026-11-16T16:43:03+0100] [ALPM] upgraded lux (0.3.0-24 -> 0.3.0-25)\n"
            "[2026-11-16T17:55:01+0100] [ALPM] upgraded xfwm4 (4.20.0-2.2 -> 4.20.0-2.4)\n"
            "[2026-11-16T17:55:02+0100] [ALPM] running 'zz-luxos-protect.hook'...\n"
            "[2026-11-16T18:00:00+0100] [ALPM] installed htop (3.4-1)\n")
        want = datetime.datetime(2026, 11, 16, 17, 55, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
        self.assertEqual(load()(log), int(want.timestamp()))

    def test_no_upgrade_or_no_log(self):
        self.assertEqual(load()(self.write("[2026-11-16T18:00:00+0100] [ALPM] installed htop (3.4-1)\n")), 0)
        self.assertEqual(load()("/nonexistent/lux.log"), 0)
        self.assertEqual(load()(self.write("garbage\n[bad] [ALPM] upgraded x (1 -> 2)\n")), 0)

    def test_reads_only_the_end_of_a_big_log(self):
        big = "[2026-01-01T00:00:00+0000] [ALPM] upgraded old (1 -> 2)\n" + "x" * 300000 + "\n"
        self.assertEqual(load()(self.write(big)), 0)          # stary zaznam mimo konec souboru
        self.assertGreater(load()(self.write(big + "[2026-11-16T10:00:00+0000] [ALPM] upgraded a (1 -> 2)\n")), 0)


if __name__ == "__main__":
    unittest.main()
