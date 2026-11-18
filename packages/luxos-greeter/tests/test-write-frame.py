#!/usr/bin/env python3
"""LuxOS - zapis snimku pro prechod (write_frame) do slozky, kam muze zapisovat i uzivatel relace.

    env -u DISPLAY python3 packages/luxos-greeter/tests/test-write-frame.py

Overuje: symbolicke odkazy nastrazene na stare jmeno docasneho souboru i na cilove jmeno nic neprepisou
ani nezmeni jejich prava; vysledny soubor je obycejny, 0644, se spravnou hlavickou; zadny docasny soubor
nezustane. Nepotrebuje X (jen cairo).
"""
import os
import stat
import sys
import tempfile
import types
from importlib.machinery import SourceFileLoader

os.environ.pop("DISPLAY", None)
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "..", "files", "luxos-greeter"), encoding="utf-8").read()
# jen funkce write_frame (modul greeteru pri importu nacita Gtk a LightDM)
start = src.index("FRAME_NAME = ")
end = src.index("\ndef box_blur(")
mod = types.ModuleType("frame")
exec("import os\nimport tempfile\n" + src[start:end], mod.__dict__)  # noqa: S102 - vlastni zdrojovy kod

import cairo  # noqa: E402

failed = 0


def check(cond, what):
    global failed
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        failed += 1


tmp = tempfile.mkdtemp(prefix="luxos-frame-")
d = os.path.join(tmp, "lightdm-data")
os.makedirs(d)
victim = os.path.join(tmp, "victim")
with open(victim, "w") as f:
    f.write("secret")
os.chmod(victim, 0o600)
target = os.path.join(d, mod.FRAME_NAME)
os.symlink(victim, target + ".tmp")          # stare pevne jmeno docasneho souboru
surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 7, 3)
mod.write_frame(target, surf)
check(open(victim).read() == "secret", "symlink at the old temp name: victim not overwritten")
check(stat.S_IMODE(os.stat(victim).st_mode) == 0o600, "symlink at the old temp name: victim mode unchanged")
st = os.lstat(target)
check(stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o644, "frame is a regular 0644 file")
with open(target, "rb") as f:
    data = f.read()
check(data.startswith(b"LUXFRAME1 7 3\n") and len(data) == len(b"LUXFRAME1 7 3\n") + 7 * 3 * 4, "frame content")
# cil je symbolicky odkaz: nahradi se samotny odkaz, ne soubor, na ktery ukazuje
os.unlink(target)
os.symlink(victim, target)
mod.write_frame(target, surf)
check(open(victim).read() == "secret" and not os.path.islink(target), "symlink at the target name replaced, victim intact")
left = sorted(n for n in os.listdir(d) if n.endswith(".tmp") and not os.path.islink(os.path.join(d, n)))
check(left == [], "no temp file left behind")
sys.exit(1 if failed else 0)
