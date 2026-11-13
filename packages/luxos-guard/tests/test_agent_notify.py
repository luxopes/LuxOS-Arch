"""Lux Guard v sezeni - pomocnik luxos-guard-agent-helper (Python, spousti ho luxos-guard-agent v LSL):
upozorneni "nebezpecny soubor" zmizi samo a nejde do historie, okno dotazu vraci volbu kodem, volby
"Spustit v sandboxu" / "Presunout do kose". Jen jednou pro stejny obsah hlida agent (test_agent_lsl.py).

Spusteni: python3 -m unittest packages/luxos-guard/tests/test_agent_notify.py (nebo pytest)
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.abspath(os.path.join(HERE, "..", "files"))
HELPER = os.path.join(FILES, "luxos-guard-agent-helper")
I18N = os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))


def load_helper():
    """Modul pomocnika ze zdroju (bez spusteni main) - pro testy volby v jinem souboru."""
    import importlib.machinery
    import importlib.util
    sys.path.insert(0, FILES)
    import luxos_guard_core  # noqa: F401  (ze zdroju drive, nez pomocnik prida systemovou cestu)
    import luxos_guard_session  # noqa: F401
    loader = importlib.machinery.SourceFileLoader("luxos_guard_agent_helper", HELPER)
    spec = importlib.util.spec_from_loader("luxos_guard_agent_helper", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Helper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "calls")
        for name in ("notify-send", "gio", "luxos-sandbox"):
            self.fake(name, 'printf "%s %s\\n" "' + name + '" "$*" >>"' + self.log + '"\n')

    def fake(self, name, body):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def run_helper(self, args, msg, **extra):
        env = {"PATH": self.tmp + os.pathsep + "/usr/bin:/bin", "HOME": self.tmp, "LANG": "C.UTF-8",
               "LUXOS_I18N_DIR": I18N, "LUXOS_GUARD_MSG": json.dumps(msg), "PYTHONDONTWRITEBYTECODE": "1"}
        env.update(extra)
        return subprocess.run([sys.executable, HELPER] + args, env=env, capture_output=True, text=True, timeout=30)

    def read_json(self, path):
        with open(path) as f:
            return json.load(f)

    def calls(self, prefix):
        for _ in range(50):
            if os.path.exists(self.log):
                break
            time.sleep(0.05)
        time.sleep(0.2)
        try:
            with open(self.log) as f:
                return [line for line in f.read().splitlines() if line.startswith(prefix)]
        except OSError:
            return []

    def test_found_notice_transient(self):
        r = self.run_helper(["found"], {"op": "found", "path": "/home/u/helper.sh",
                                        "reasons": ["changes sudo, polkit or login (PAM) security"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls("notify-send ")
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("-e", calls[0].split())             # do historie oznameni nepatri
        self.assertIn("-t 10000", calls[0])                # zmizi samo
        self.assertNotIn("critical", calls[0])             # kriticke by v Xfce nezmizelo
        self.assertIn("helper.sh", calls[0])

    def test_ask_returns_choice_code(self):
        for out, code in (("run", 10), ("sandbox", 11), ("trash", 13), ("deny", 12), ("close", 12), ("", 12),
                          ("nonsense", 12)):
            with self.subTest(out=out):
                gui = self.fake("gui-" + (out or "empty"), 'cat >"$0.in"\n' + ('echo ' + out + '\n' if out else ''))
                r = self.run_helper(["ask"], {"op": "ask", "id": 1, "path": "/tmp/x.sh"}, LUXOS_GUARD_GUI=gui)
                self.assertEqual(r.returncode, code, r.stderr)
                sent = self.read_json(gui + ".in")
                self.assertEqual(sent["mode"], "ask")              # okno dostane zpravu sluzby + rezim
                self.assertEqual(sent["path"], "/tmp/x.sh")
        self.assertEqual(self.calls("gio "), [])                   # dotaz sam nic neprovadi (to je "act")

    def test_ask_without_gui_denies(self):
        r = self.run_helper(["ask"], {"op": "ask", "id": 1, "path": "/tmp/x"},
                            LUXOS_GUARD_GUI=os.path.join(self.tmp, "missing"))
        self.assertEqual(r.returncode, 12)

    def test_act_trash(self):
        victim = os.path.join(self.tmp, "bad.sh")
        open(victim, "w").close()
        r = self.run_helper(["act", "trash"], {"path": victim})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("gio "), ["gio trash -- " + victim])
        self.assertEqual(len(self.calls("notify-send ")), 1)

    def test_blocked_acts_itself(self):
        gui = self.fake("gui-trash", 'cat >"$0.in"\necho trash\n')
        victim = os.path.join(self.tmp, "wipe.sh")
        open(victim, "w").close()
        r = self.run_helper(["blocked"], {"op": "blocked", "path": victim, "level": "critical"}, LUXOS_GUARD_GUI=gui)
        self.assertEqual(r.returncode, 13, r.stderr)
        self.assertEqual(self.read_json(gui + ".in")["mode"], "blocked")
        self.assertEqual(self.calls("gio "), ["gio trash -- " + victim])

    def test_bad_message_and_usage(self):
        r = self.run_helper(["found"], {}, LUXOS_GUARD_MSG="not json")
        self.assertEqual(r.returncode, 0)
        r = self.run_helper([], {})
        self.assertEqual(r.returncode, 2)

    def test_launcher_runs_agent_from_sh_and_python(self):
        """/usr/bin/luxos-guard-agent: sh i Python (drivejsi pomocnik se po aktualizaci spusti pres python3)."""
        fake = self.fake("agent-bin", 'echo "agent $*"\n')
        launcher = os.path.join(FILES, "luxos-guard-agent")
        env = dict(os.environ, LUXOS_GUARD_AGENT_BIN=fake)
        for argv in (["/bin/sh", launcher, "x"], [sys.executable, launcher, "x"], [launcher, "x"]):
            r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual((r.returncode, r.stdout), (0, "agent x\n"), (argv, r.stderr))


if __name__ == "__main__":
    unittest.main()
