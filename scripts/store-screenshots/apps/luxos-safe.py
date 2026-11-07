"""Trezor: odemceny Trezor s nastavenim zamykani, zamceny Trezor s heslem a vytvoreni Trezoru (sila hesla).

Falesny stav v docasne slozce (_c_safe.py): zadne /safe, luxos-safe-helper, pkexec ani gocryptfs.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_LINE = "22 1 0:21 / / rw,relatime - btrfs /dev/vda2 rw\n"
LOCKED = ROOT_LINE + "100 22 0:50 / /safe/anna ro,relatime - tmpfs luxos-safe-locked ro\n"
UNLOCKED = LOCKED + "101 22 0:51 / /safe/anna rw,nosuid,nodev,noexec - fuse.gocryptfs /safe/.vaults/anna rw\n"


def shots(s):
    demo = os.path.join(s.tmp, "safe")
    os.makedirs(os.path.join(demo, "vault"))
    mi = os.path.join(demo, "mountinfo")
    conf = os.path.join(demo, "vault", "gocryptfs.conf")

    def put(path, text):
        with open(path, "w") as f:
            f.write(text)
    put(mi, ROOT_LINE)                    # zadny Trezor -> vytvoreni
    s.python_env()
    s.launch([sys.executable, os.path.join(HERE, "_c_safe.py"), s.src("luxos-safe/files/luxos-safe")],
             env={"DEMO_SAFE": demo})
    win = s.window(name="^Safe$", size=None)
    s.type("Blue-Harbor-Lantern-42", win)
    s.key("Tab", win)
    s.type("Blue-Harbor-Lantern-42", win)
    s.capture("3", win)
    put(conf, "{}")                       # Trezor existuje, zamceny
    put(mi, LOCKED)
    s.sleep(3)
    s.center(win)
    s.type("Blue-Harbor", win)
    s.capture("2", win)
    put(mi, UNLOCKED)                     # odemceny
    s.sleep(3)
    s.center(win)
    s.capture("1", win)
