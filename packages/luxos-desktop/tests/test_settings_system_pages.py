#!/usr/bin/env python3
"""LuxOS - Nastaveni: Datum a cas, Jazyk a oblast, Uzivatele, Soukromi a zabezpeceni. Falesne programy (timedatectl,
localectl, locale, busctl, luxos-guard, pkexec) zapisuji volani do FAKE_LOG; overuje se, co stranka ukaze a co
spusti. Hesla: sluzbe jde jen hash yescrypt, nikdy heslo v argumentech.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      python3 -m unittest packages/luxos-desktop/tests/test_settings_system_pages.py -v
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
import json
import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lsl_app_harness as h  # noqa: E402

LOGGER = 'printf "%s\\n" "$(basename "$0") $*" >>"$FAKE_LOG"\n'

FAKES = {
    "timedatectl": '#!/bin/sh\n' + LOGGER + '''case "$1" in
  show) printf 'Timezone=Europe/Prague\\nLocalRTC=no\\nCanNTP=yes\\nNTP=yes\\nNTPSynchronized=yes\\n';;
  list-timezones) printf 'America/New_York\\nEurope/London\\nEurope/Prague\\n';;
esac
exit 0
''',
    "localectl": '#!/bin/sh\n' + LOGGER + 'exit 0\n',
    "locale": '#!/bin/sh\nprintf "C.utf8\\ncs_CZ.utf8\\nen_US.utf8\\n"\n',
    "pkexec": '#!/bin/sh\n' + LOGGER + 'exit 0\n',
    "luxos-guard": '#!/bin/sh\n' + LOGGER + '''case "$1 $2" in
  "status --json") echo '{"active": true, "antivirus": true, "antivirus_conf": true, "quarantine": 1, "database": 1795700000, "snapshots": 5, "newest_snapshot": 1795700000}';;
  "quarantine --json") echo '[{"id": "1795710361323-8d2b8ea5", "path": "/home/anna/Downloads/faktura.pdf", "signature": "Eicar-Test-Signature", "time": 1795710361}]';;
esac
exit 0
''',
    # busctl: dva uzivatele; FAKE_LOG zapisuje i argumenty (heslo by tam bylo videt)
    "busctl": '#!/bin/sh\n' + LOGGER + '''for a in "$@"; do last="$a"; done
case "$*" in
  *ListCachedUsers*) echo '{"type":"ao","data":[["/org/freedesktop/Accounts/User1000","/org/freedesktop/Accounts/User1001"]]}';;
  *FindUserByName*) echo '{"type":"o","data":["/org/freedesktop/Accounts/User1002"]}';;
  *get-property*User1000*) printf '{"type":"s","data":"anna"}\\n{"type":"s","data":"Anna Nováková"}\\n{"type":"i","data":1}\\n{"type":"t","data":1000}\\n{"type":"b","data":false}\\n';;
  *get-property*User1001*) printf '{"type":"s","data":"petr"}\\n{"type":"s","data":"Petr"}\\n{"type":"i","data":0}\\n{"type":"t","data":1001}\\n{"type":"b","data":false}\\n';;
  *CreateUser*) echo '{"type":"o","data":"/org/freedesktop/Accounts/User1002"}';;
esac
exit 0
''',
}


def setUpModule():
    if not h.lslc_ok():
        raise unittest.SkipTest("lslc 0.11 is not installed")
    h.build("luxos-settings")


def make_env(lang="C.UTF-8"):
    tmp = Path(tempfile.mkdtemp(prefix="settings-sys-", dir=h.private_dir()))
    env = h.base_env(tmp, lang)
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for name, body in FAKES.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", USER="anna")
    return tmp, env


def calls(tmp, program):
    log = tmp / "fake.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [ln for ln in lines if ln.startswith(program + " ")]


def find(dump, kind, text):
    for i, line in enumerate(dump):
        if line == f"GtkLabel\t{text}":
            for nxt in dump[i + 1:i + 6]:
                if nxt.startswith(kind + "\t"):
                    return nxt.split("\t")[1:]
    return None


@unittest.skipUnless(h.HAVE_X11, "Xvfb, xdotool or dbus-run-session missing")
class SystemPages(unittest.TestCase):
    def run_app(self, page, script, tmp, env):
        app = h.X11App([str(h.build("luxos-settings")), page], env, script, tmp=tmp)
        self.addCleanup(app.close)
        return app

    # ---- Datum a cas ----

    def test_datetime_shows_and_changes(self):
        tmp, env = make_env()
        app = self.run_app("datetime", ["wait 500", "dump", "switch Set time automatically off", "combo Time zone Europe/London",
                                        "switch 24-hour time off", "wait 800", "dump", "quit"], tmp, env)
        d = app.wait_dump(1)
        self.assertEqual(find(d, "GtkSwitch", "Set time automatically"), ["on"])
        self.assertEqual(find(d, "GtkComboBoxText", "Time zone"), ["Europe/Prague"])
        self.assertEqual(find(d, "GtkSwitch", "24-hour time"), ["on"])      # mimo USA: 24 h
        app.wait_exit()
        log = calls(tmp, "timedatectl")
        self.assertIn("timedatectl set-ntp false", log)
        self.assertIn("timedatectl set-timezone Europe/London", log)
        conf = (tmp / "config/luxos/appearance.conf").read_text()
        self.assertIn("CLOCK_24H=no", conf)

    def test_datetime_manual_time_validated(self):
        tmp, env = make_env()
        self.run_app("datetime", ["wait 400", "click Set", "wait 500", "dump", "quit"], tmp, env).wait_exit()
        # automaticky cas zapnuty: radek je neaktivni, ale i tak se spatny vstup nepredava
        self.assertFalse(any("set-time" in ln and "  " in ln for ln in calls(tmp, "timedatectl")))

    def test_english_us_defaults_to_12_hours(self):
        tmp, env = make_env("en_US.UTF-8")
        d = self.run_app("datetime", ["wait 400", "dump", "quit"], tmp, env).wait_dump()
        self.assertEqual(find(d, "GtkSwitch", "24-hour time"), ["off"])

    # ---- Jazyk a oblast ----

    def test_language_writes_user_locale(self):
        tmp, env = make_env("en_GB.UTF-8")
        (tmp / "config/locale.conf").write_text("LC_COLLATE=C\n")
        app = self.run_app("language", ["wait 400", "dump", "combo Language de_DE", "combo Formats cs_CZ", "wait 300",
                                        "click Use My Language", "wait 600", "dump", "quit"], tmp, env)
        d = app.wait_dump(1)
        self.assertEqual(find(d, "GtkComboBoxText", "Language"), ["en_GB"])
        self.assertEqual(find(d, "GtkComboBoxText", "Formats"), ["same"])
        d2 = app.wait_dump(2)
        app.wait_exit()
        conf = (tmp / "config/locale.conf").read_text().splitlines()
        self.assertIn("LC_COLLATE=C", conf)                              # cizi radky zustanou
        self.assertIn("LANG=de_DE.UTF-8", conf)
        self.assertIn("LC_TIME=cs_CZ.UTF-8", conf)
        self.assertIn("localectl set-locale LANG=de_DE.UTF-8", calls(tmp, "localectl"))
        # de_DE neni vygenerovany: poznamka
        self.assertTrue(any("older programs" in ln for ln in d2), d2)

    # ---- Uzivatele ----

    def test_users_list_add_and_type(self):
        tmp, env = make_env()
        app = self.run_app("users", ["wait 500", "dump",
                                     "entry Full name=Jana Malá", "entry Password=tajne-heslo-123",
                                     "entry Confirm password=tajne-heslo-123", "click Add User", "wait 800",
                                     "dump", "quit"], tmp, env)
        d = app.wait_dump(1)
        self.assertIn("GtkLabel\tAnna Nováková", d)
        self.assertIn("GtkLabel\tPetr", d)
        app.wait_exit()
        log = calls(tmp, "busctl")
        create = [ln for ln in log if "CreateUser" in ln]
        self.assertEqual(len(create), 1, log)
        self.assertIn("ssi jana Jana Malá 0", create[0])
        setpw = [ln for ln in log if "SetPassword" in ln]
        self.assertEqual(len(setpw), 1, log)
        self.assertIn("/org/freedesktop/Accounts/User1002", setpw[0])
        self.assertIn(" ss $y$", setpw[0])
        self.assertFalse(any("tajne-heslo-123" in ln for ln in log), "the password must never be an argument")

    def test_users_rejects_mismatch_and_bad_name(self):
        tmp, env = make_env()
        self.run_app("users", ["wait 400", "entry Full name=X", "entry User name=Bad Name", "entry Password=abcdef",
                               "entry Confirm password=abcdef", "click Add User", "wait 300",
                               "entry User name=ok", "entry Confirm password=other", "click Add User", "wait 300",
                               "quit"], tmp, env).wait_exit()
        self.assertFalse(any("CreateUser" in ln for ln in calls(tmp, "busctl")))

    # ---- Soukromi a zabezpeceni ----

    def test_security_overview_and_quarantine(self):
        tmp, env = make_env()
        app = self.run_app("security", ["wait 500", "dump", "click Restore", "switch Antivirus off", "wait 600", "quit"],
                           tmp, env)
        d = app.wait_dump(1)
        app.wait_exit()
        self.assertEqual(find(d, "GtkSwitch", "Antivirus"), ["on"])
        self.assertIn("GtkLabel\tfaktura.pdf", d)
        log = calls(tmp, "luxos-guard")
        self.assertIn("luxos-guard quarantine restore 1795710361323-8d2b8ea5", log)
        self.assertIn("pkexec luxos-guard set-antivirus no", calls(tmp, "pkexec"))


if __name__ == "__main__":
    unittest.main()
