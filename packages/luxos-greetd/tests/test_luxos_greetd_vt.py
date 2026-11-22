"""libluxos-greetd-vt.so: snimek greeteru (/run/luxos-greeter/login-frame) cte root v greetd, zapisuje ho neprivilegovany
greeter. Predani obrazovky jen s obycejnym souborem uzivatele greeter, cerstvym a presne tak velkym, jak rika hlavicka;
odkaz, FIFO, adresar, cizi vlastnik nebo spatna velikost = zadne predani (KD_TEXT jako bez snimku, nic do framebufferu).

Preklad s -DGREETD_VT_TEST: cesta snimku v docasne slozce, uzivatel greeter = uzivatel testu (cizi vlastnik: root).
"""
import ctypes
import getpass
import os
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "luxos-greetd-vt.c")
W, H = 4, 3


class FrameCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="greetd-vt-")
        cls.frame = os.path.join(cls.tmp, "login-frame")
        cls.lib = cls.build(getpass.getuser())

    @classmethod
    def build(cls, user):
        so = os.path.join(cls.tmp, f"vt-{user}.so")
        subprocess.run(["gcc", "-Wall", "-Werror", "-shared", "-fPIC", "-DGREETD_VT_TEST", f'-DFRAME="{cls.frame}"',
                        f'-DGREETER_USER="{user}"', "-o", so, SRC], check=True)
        lib = ctypes.CDLL(so)
        lib.luxos_greetd_vt_init()
        return lib

    def setUp(self):
        for name in os.listdir(self.tmp):
            path = os.path.join(self.tmp, name)
            if not name.endswith(".so"):
                os.rmdir(path) if os.path.isdir(path) and not os.path.islink(path) else os.unlink(path)

    def write(self, path, w=W, h=H, extra=0):
        with open(path, "wb") as f:
            f.write(b"LUXFRAME1 %d %d\n" % (w, h) + b"\x40" * (w * h * 4 + extra))

    def ok(self):
        return self.lib.luxos_greetd_vt_frame_ok() == 1

    def test_regular_file_of_the_greeter(self):
        self.write(self.frame)
        self.assertTrue(self.ok())

    def test_symlink_is_refused(self):
        real = os.path.join(self.tmp, "real-frame")
        self.write(real)
        os.symlink(real, self.frame)
        self.assertFalse(self.ok(), "a symlink must not be followed (O_NOFOLLOW)")

    def test_size_must_match_header(self):
        self.write(self.frame, extra=1)
        self.assertFalse(self.ok())
        self.write(self.frame, extra=-4)
        self.assertFalse(self.ok())
        self.write(self.frame, w=0)
        self.assertFalse(self.ok())

    def test_not_a_regular_file(self):
        os.mkfifo(self.frame)
        self.assertFalse(self.ok(), "FIFO (and the open must not block)")
        os.unlink(self.frame)
        os.mkdir(self.frame)
        self.assertFalse(self.ok())

    def test_old_frame(self):
        self.write(self.frame)
        old = time.time() - 60
        os.utime(self.frame, (old, old))
        self.assertFalse(self.ok())

    def test_other_owner_or_no_greeter_user(self):
        self.write(self.frame)
        # soubor patri uzivateli testu, "greeter" tu je root
        self.assertFalse(self.build("root").luxos_greetd_vt_frame_ok() == 1)
        self.assertFalse(self.build("luxos-no-such-user").luxos_greetd_vt_frame_ok() == 1)


if __name__ == "__main__":
    unittest.main()
