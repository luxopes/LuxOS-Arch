"""Lux Guard v sezeni: upozorneni "nebezpecny soubor" zmizi samo, nejde do historie a neopakuje se.

Spusteni: python3 -m unittest packages/luxos-guard/tests/test_agent_notify.py (nebo pytest)
"""
import importlib.machinery
import importlib.util
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.abspath(os.path.join(HERE, "..", "files"))
sys.dont_write_bytecode = True
sys.path.insert(0, FILES)
os.environ.setdefault("LUXOS_I18N_DIR", os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))


def load_agent():
    # moduly ze zdroju, ne z /usr/lib/luxos/python (agent si tu cestu pridava na zacatek)
    import luxos_guard_core  # noqa: F401
    import luxos_guard_session  # noqa: F401
    loader = importlib.machinery.SourceFileLoader("luxos_guard_agent", os.path.join(FILES, "luxos-guard-agent"))
    spec = importlib.util.spec_from_loader("luxos_guard_agent", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FoundNotice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls")
        fake = os.path.join(self.tmp, "notify-send")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$*" >>"' + self.log + '"\n')
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = self.tmp + os.pathsep + self.old_path
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self.old_path))
        self.file = os.path.join(self.tmp, "helper.sh")
        with open(self.file, "w") as f:
            f.write("echo hi\n")

    def calls(self):
        import time
        for _ in range(50):
            if os.path.exists(self.log):
                break
            time.sleep(0.05)
        time.sleep(0.2)
        try:
            with open(self.log) as f:
                return [line for line in f.read().splitlines() if line.startswith("-a ")]
        except OSError:
            return []

    def test_transient_once_per_file_version(self):
        mod = load_agent()
        agent = mod.Agent(sock_path="/nonexistent")
        msg = {"op": "found", "path": self.file, "reasons": ["changes sudo, polkit or login (PAM) security"]}
        agent.handle(msg)
        agent.handle(msg)          # stejny soubor znovu: bez dalsiho upozorneni
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("-e", calls[0].split())             # do historie oznameni nepatri
        self.assertIn("-t 10000", calls[0])                # zmizi samo
        self.assertNotIn("critical", calls[0])             # kriticke by v Xfce nezmizelo
        with open(self.file, "a") as f:                    # zmeneny soubor: znovu upozornit
            f.write("echo changed\n")
        os.utime(self.file, ns=(1, 1))
        agent.handle(msg)
        self.assertEqual(len(self.calls()), 2)


    def test_same_content_in_two_places_once(self):
        """Kopie stejneho souboru (pracovni slozky gitu, zalohy) jen jedno upozorneni."""
        mod = load_agent()
        agent = mod.Agent(sock_path="/nonexistent")
        copy = os.path.join(self.tmp, "copy", "helper.sh")
        os.makedirs(os.path.dirname(copy))
        with open(self.file) as src, open(copy, "w") as dst:
            dst.write(src.read())
        for path in (self.file, copy):
            agent.handle({"op": "found", "path": path, "reasons": ["changes sudo, polkit or login (PAM) security"]})
        self.assertEqual(len(self.calls()), 1)

    def test_restarts_after_update(self):
        """Nahrazeny soubor pomocnika (aktualizace) = zmena razitek -> spusteni nove verze."""
        mod = load_agent()
        a = mod.file_stamps()
        fake = os.path.join(self.tmp, "agent-copy")
        with open(fake, "w") as f:
            f.write("x")
        mod.UPDATE_FILES[0] = fake
        b = mod.file_stamps()
        os.replace(self.file, fake)          # novy inode jako pri instalaci baliku
        self.assertNotEqual(b, mod.file_stamps())
        self.assertNotEqual(a, b)

if __name__ == "__main__":
    unittest.main()
