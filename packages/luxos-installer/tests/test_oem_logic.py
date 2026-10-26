#!/usr/bin/env python3
"""LuxOS installer - logika Pruvodce nastavenim (luxos_oem.py) bez GTK.

    python3 packages/luxos-installer/tests/test_oem_logic.py
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "files"))
import luxos_oem as oem  # noqa: E402


def state(**kw):
    s = {"locale": "cs_CZ.UTF-8", "timezone": "Europe/Prague", "fullname": " Jana Nováková ", "username": "jana",
         "pw1": "tajne heslo", "pw2": "tajne heslo", "hostname": "jana-luxos", "autologin": False,
         "care": "carefree", "luxai": None, "disk_same": True, "disk1": "", "disk2": ""}
    s.update(kw)
    return s


def parse(text):
    return dict(line.split("=", 1) for line in text.splitlines())


class Steps(unittest.TestCase):
    def test_order(self):
        self.assertEqual(oem.steps(False), ["welcome", "keyboard", "network", "timezone", "account", "luxai",
                                            "care", "finish"])

    def test_disk_page_only_when_pending(self):
        st = oem.steps(True)
        self.assertIn("diskpass", st)
        self.assertLess(st.index("luxai"), st.index("diskpass"))
        self.assertLess(st.index("diskpass"), st.index("care"))

    def test_status(self):
        s = oem.parse_status("OEM=1\nARMED=1\nLUKS=pending\nnoise\nEVIL=1\nUSER=jana\n")
        self.assertEqual((s["LUKS"], s["USER"], s["ARMED"]), ("pending", "jana", "1"))
        self.assertNotIn("EVIL", s)
        self.assertEqual(oem.parse_status("")["LUKS"], "none")   # sudo selhal = bez stranky disku


class Progress(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "sub", "progress.json")

    def test_roundtrip_without_secrets(self):
        s = state(xkb=[("cz", "qwerty"), ("us", "")], step="account", luxai={"sessionToken": "x"},
                  disk1="d", photo="/tmp/p.png")
        oem.save_progress(s, self.path)
        with open(self.path, encoding="utf-8") as f:
            raw = f.read()
        for secret in ("tajne heslo", "sessionToken", '"d"'):
            self.assertNotIn(secret, raw)
        back = oem.load_progress(self.path)
        self.assertEqual(back["xkb"], [("cz", "qwerty"), ("us", "")])
        self.assertEqual(back["step"], "account")
        self.assertEqual(back["fullname"], " Jana Nováková ")
        self.assertNotIn("pw1", back)
        self.assertEqual(oct(os.stat(os.path.dirname(self.path)).st_mode & 0o777), "0o700")

    def test_broken_file_starts_over(self):
        os.makedirs(os.path.dirname(self.path))
        for content in ("{nedokonceny", "[1, 2]", '{"xkb": 5, "step": "care"}', ""):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(content)
            got = oem.load_progress(self.path)
            self.assertIsInstance(got, dict)
            self.assertNotIn("xkb", got)
        self.assertEqual(oem.load_progress(os.path.join(self.dir, "missing.json")), {})

    def test_atomic_no_temp_left(self):
        oem.save_progress(state(), self.path)
        oem.save_progress(state(username="petr"), self.path)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["progress.json"])
        self.assertEqual(oem.load_progress(self.path)["username"], "petr")


class Finish(unittest.TestCase):
    XKB = ("cz,us", "qwerty,", "grp:shifts_toggle")

    def test_values(self):
        d = parse(oem.finish_input(state(), self.XKB, False))
        self.assertEqual(list(d), list(oem.FINISH_KEYS))
        self.assertEqual(d["FULLNAME"], "Jana Nováková")
        self.assertEqual(d["XKB_LAYOUT"], "cz,us")
        self.assertEqual(d["PASSWORD"], "tajne heslo")
        self.assertEqual(d["DISK_PASS"], "")        # bez sifrovani se heslo disku neposila
        self.assertEqual(d["LUXAI_ACCOUNT"], "")
        self.assertEqual(d["AUTOLOGIN"], "0")

    def test_disk_same_as_account(self):
        d = parse(oem.finish_input(state(), self.XKB, True))
        self.assertEqual(d["DISK_PASS"], "tajne heslo")

    def test_disk_own(self):
        s = state(disk_same=False, disk1="disk", disk2="disk")
        self.assertEqual(oem.disk_problem(s), "")
        self.assertEqual(parse(oem.finish_input(s, self.XKB, True))["DISK_PASS"], "disk")

    def test_disk_problems(self):
        self.assertEqual(oem.disk_problem(state(disk_same=False)), "empty")
        self.assertEqual(oem.disk_problem(state(disk_same=False, disk1="a", disk2="b")), "mismatch")
        self.assertEqual(oem.disk_problem(state(pw1="")), "account")

    def test_luxai_json_one_line(self):
        acc = {"sessionToken": "t", "user": {"email": "j@x.cz", "name": "Jana\nN"}}
        d = parse(oem.finish_input(state(luxai=acc), self.XKB, False))
        self.assertEqual(json.loads(d["LUXAI_ACCOUNT"]), acc)

    def test_newline_rejected(self):
        for bad in ({"pw1": "a\nUSERNAME=root"}, {"fullname": "x\ry"}, {"username": "a\0"}):
            with self.assertRaises(ValueError):
                oem.finish_input(state(**bad), self.XKB, False)

    def test_reserved(self):
        self.assertFalse(oem.valid_user("lightdm"))
        self.assertFalse(oem.valid_user("Jana"))
        self.assertTrue(oem.valid_user("jana"))


class Output(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(oem.parse_line("@@STEP 2 5 Creating your account"), ("step", "Creating your account", 2, 5))
        self.assertEqual(oem.parse_line("@@ERROR Invalid user name."), ("error", "Invalid user name."))
        self.assertEqual(oem.parse_line("@@DONE"), ("done", ""))
        self.assertEqual(oem.parse_line("hello")[0], "log")


if __name__ == "__main__":
    unittest.main(verbosity=1)
