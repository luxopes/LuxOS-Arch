#!/usr/bin/env python3
"""LuxOS - posta pro exo-open (luxos-mail-reader, MailReader v helpers.rc).

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_mail_reader.py -v

Bez okna: gio, xdg-mime, notify-send a luxos-store jsou napodoby v PATH, ktere zapisuji volani;
aplikace jsou falesne .desktop v docasnem XDG_DATA_DIRS.
"""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "files")
SCRIPT = os.path.join(FILES, "bin", "luxos-mail-reader")


class MailReader(unittest.TestCase):
    def run_reader(self, apps, mailto_default="", arg=None):
        with tempfile.TemporaryDirectory() as tmp:
            data, bindir, log = os.path.join(tmp, "data"), os.path.join(tmp, "bin"), os.path.join(tmp, "log")
            os.makedirs(os.path.join(data, "applications"))
            os.makedirs(bindir)
            for app in apps:
                with open(os.path.join(data, "applications", app + ".desktop"), "w") as f:
                    f.write(f"[Desktop Entry]\nType=Application\nName={app}\nExec={app}\n")
            stubs = {"gio": 'echo "gio $*" >> "$LOG"', "notify-send": 'echo "notify $*" >> "$LOG"',
                     "luxos-store": 'echo "store $*" >> "$LOG"',
                     "xdg-mime": f'echo "{mailto_default}"'}
            for name, body in stubs.items():
                p = os.path.join(bindir, name)
                with open(p, "w") as f:
                    f.write("#!/bin/bash\n" + body + "\n")
                os.chmod(p, 0o755)
            env = {"PATH": bindir + ":/usr/bin:/bin", "HOME": tmp, "XDG_DATA_HOME": os.path.join(tmp, "home"),
                   "XDG_DATA_DIRS": data, "LOG": log, "LANG": "C.UTF-8"}
            r = subprocess.run(["bash", SCRIPT] + ([arg] if arg else []), env=env, capture_output=True,
                               text=True, timeout=20)
            try:
                with open(log) as f:
                    calls = f.read()
            except OSError:
                calls = ""
            return r.returncode, calls.replace(data, "DATA")

    def test_mailto_default_app(self):
        rc, calls = self.run_reader(["luxos-mail", "thunderbird"], "thunderbird.desktop", "a@b.cz?subject=Hi")
        self.assertEqual(rc, 0)
        self.assertEqual(calls, "gio launch DATA/applications/thunderbird.desktop mailto:a@b.cz?subject=Hi\n")

    def test_known_app_without_default(self):
        rc, calls = self.run_reader(["org.mozilla.Thunderbird"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, "gio launch DATA/applications/org.mozilla.Thunderbird.desktop\n")

    def test_default_pointing_to_removed_app_falls_back(self):
        rc, calls = self.run_reader(["luxos-mail"], "thunderbird.desktop", "mailto:x@y.cz")
        self.assertEqual(calls, "gio launch DATA/applications/luxos-mail.desktop mailto:x@y.cz\n")

    def test_no_mail_app_opens_store(self):
        rc, calls = self.run_reader([], "", "x@y.cz")
        self.assertIn("notify", calls)
        self.assertIn("No mail app is installed", calls)
        self.assertIn("store mail", calls)
        self.assertNotIn("gio launch", calls)

    def test_helpers_rc_uses_luxos_reader(self):
        with open(os.path.join(FILES, "xdg", "xfce4", "helpers.rc")) as f:
            rc = f.read()
        self.assertIn("\nMailReader=luxos-mail-reader\n", rc)
        self.assertNotIn("MailReader=thunderbird", rc)
        with open(os.path.join(FILES, "helpers", "luxos-mail-reader.desktop")) as f:
            helper = f.read()
        self.assertIn("X-XFCE-Category=MailReader", helper)
        self.assertIn("X-XFCE-Binaries=luxos-mail-reader;", helper)


if __name__ == "__main__":
    unittest.main()
