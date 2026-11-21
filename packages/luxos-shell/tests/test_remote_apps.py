"""Testy funkce ssh z remote-apps.sh ("ssh -X" v relaci na Waylandu pres waypipe nebo XWayland).

    python3 -m unittest discover -s packages/luxos-shell/tests -v

Bez site: ssh, waypipe, xauth a mcookie jsou atrapy (PATH), ktere zapisuji argumenty do logu.
Kazdy pripad bezi v bashi (tedy i lsh) a v zsh, jak je funkce nacitana z aliases.sh.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.normpath(os.path.join(HERE, "..", "files", "remote-apps.sh"))

# kazde volani = jeden radek: program, XAUTHORITY a argumenty oddelene "|"
MOCKS = {
    "ssh": r'''#!/bin/bash
if [[ $1 == -G ]]; then
    printf 'user %s\nhostname %s\nport %s\n' "${MOCK_USER:-me}" "${!#}" "${MOCK_PORT:-22}"
    exit 0
fi
( IFS='|'; echo "ssh|${XAUTHORITY-}|$*" ) >> "$FAKE/log"
if [[ $* == *"command -v waypipe"* ]]; then
    [[ -n ${MOCK_PROBE_RC-} ]] && exit "$MOCK_PROBE_RC"
    printf '%b' "${MOCK_PROBE-}"
fi
exit 0
''',
    "waypipe": r'''#!/bin/bash
( IFS='|'; echo "waypipe|${XAUTHORITY-}|$*" ) >> "$FAKE/log"
exit "${MOCK_WAYPIPE_RC:-0}"
''',
    "xauth": r'''#!/bin/bash
[[ $1 == list ]] && { [[ -n ${MOCK_XAUTH_LIST-} ]] && echo "$MOCK_XAUTH_LIST"; exit 0; }
[[ $1 == -q ]] && shift
[[ $1 == -f ]] && echo "$4 $5 $6" > "$2"
exit 0
''',
    "mcookie": "#!/bin/sh\necho 0123456789abcdef0123456789abcdef\n",
}


class RemoteApps(unittest.TestCase):
    shell = "bash"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.bin)
        os.makedirs(self.run_dir, mode=0o700)
        for name, body in MOCKS.items():
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        self.env = {
            "PATH": self.bin + ":/usr/bin:/bin",
            "HOME": self.tmp,
            "FAKE": self.tmp,
            "XDG_RUNTIME_DIR": self.run_dir,
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
            "MOCK_PROBE": "waypipe\nx11\n",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def ssh(self, *args, **env):
        e = dict(self.env)
        e.update(env)
        e = {k: v for k, v in e.items() if v is not None}
        if os.path.exists(os.path.join(self.tmp, "log")):
            os.remove(os.path.join(self.tmp, "log"))
        r = subprocess.run([self.shell, "-c", '. "$0"; ssh "$@"', SCRIPT, *args],
                           env=e, capture_output=True, text=True, timeout=20)
        try:
            with open(os.path.join(self.tmp, "log")) as f:
                calls = [line.rstrip("\n").split("|") for line in f]
        except FileNotFoundError:
            calls = []
        return r.returncode, calls

    def last(self, calls):
        return calls[-1][0], calls[-1][2:]

    def cache(self, key="me@host:22"):
        return os.path.join(self.run_dir, "luxos-ssh", "remote-" + key)

    def test_waypipe_with_x11(self):
        rc, calls = self.ssh("-X", "host", "gedit", "a b.txt")
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("command -v waypipe", calls[0][-1])
        self.assertEqual(self.last(calls),
                         ("waypipe", ["ssh", "-X", "-o", "ForwardX11Trusted=yes", "host", "gedit", "a b.txt"]))

    def test_waypipe_without_x11_drops_x(self):
        rc, calls = self.ssh("-XC", "-p", "2222", "host", "gedit", MOCK_PROBE="waypipe\n")
        self.assertEqual(self.last(calls), ("waypipe", ["ssh", "-C", "-p", "2222", "host", "gedit"]))
        rc, calls = self.ssh("-Y", "host", MOCK_PROBE="waypipe\n")
        self.assertEqual(self.last(calls), ("waypipe", ["ssh", "host"]))

    def test_fallback_x11_through_xwayland(self):
        rc, calls = self.ssh("-X", "host", "xeyes", MOCK_PROBE="x11\n")
        prog, xa = calls[-1][0], calls[-1][1]
        self.assertEqual(prog, "ssh")
        self.assertEqual(calls[-1][2:], ["-X", "-o", "ForwardX11Trusted=yes", "host", "xeyes"])
        # XWayland bez cookie: nahodne cookie v soukromem souboru, at ssh nehlasi "No xauth data"
        self.assertEqual(xa, os.path.join(self.run_dir, "luxos-ssh", "xauth"))
        with open(xa) as f:
            self.assertEqual(f.read().split(), [":0", "MIT-MAGIC-COOKIE-1", "0123456789abcdef0123456789abcdef"])
        self.assertEqual(oct(os.stat(os.path.dirname(xa)).st_mode & 0o777), "0o700")

    def test_own_xauthority_kept(self):
        rc, calls = self.ssh("-X", "host", "xeyes", MOCK_PROBE="x11\n", MOCK_XAUTH_LIST="host/unix:0 MIT 00",
                             XAUTHORITY="/tmp/mine")
        self.assertEqual(calls[-1][1], "/tmp/mine")
        rc, calls = self.ssh("-X", "host", "xeyes", MOCK_PROBE="x11\n", MOCK_XAUTH_LIST="host/unix:0 MIT 00")
        self.assertEqual(calls[-1][1], os.path.join(self.tmp, ".Xauthority"))

    def test_user_option_wins(self):
        # u ssh plati prvni hodnota: volba uzivatele musi byt pred nasi
        rc, calls = self.ssh("-X", "-o", "ForwardX11Trusted=no", "host", MOCK_PROBE="x11\n")
        args = calls[-1][2:]
        self.assertLess(args.index("ForwardX11Trusted=no"), args.index("ForwardX11Trusted=yes"))

    def test_cache(self):
        self.ssh("-X", "host", "a")
        rc, calls = self.ssh("-X", "host", "b")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "waypipe")
        # jiny uzivatel nebo port = jiny pocitac
        rc, calls = self.ssh("-X", "host", "b", MOCK_PORT="2222")
        self.assertEqual(len(calls), 2)

    def test_negative_cache_expires(self):
        self.ssh("-X", "host", "a", MOCK_PROBE="x11\n")
        rc, calls = self.ssh("-X", "host", "a", MOCK_PROBE="x11\n")
        self.assertEqual(len(calls), 1)
        old = os.path.getmtime(self.cache()) - 11 * 60
        os.utime(self.cache(), (old, old))
        rc, calls = self.ssh("-X", "host", "a")
        self.assertEqual(self.last(calls)[0], "waypipe")

    def test_probe_failure_not_cached(self):
        rc, calls = self.ssh("-X", "host", "a", MOCK_PROBE_RC="255")
        self.assertEqual(self.last(calls)[0], "ssh")
        self.assertFalse(os.path.exists(self.cache()))

    def test_remote_without_waypipe_127_reprobes(self):
        self.ssh("-X", "host", "a")
        rc, calls = self.ssh("-X", "host", "a", MOCK_WAYPIPE_RC="127")
        self.assertEqual(rc, 127)
        self.assertFalse(os.path.exists(self.cache()))

    def test_exit_code_passed(self):
        rc, calls = self.ssh("-X", "host", "a", MOCK_WAYPIPE_RC="3")
        self.assertEqual(rc, 3)

    def test_untouched_cases(self):
        plain = [
            ("host", "ls"),                      # bez -X
            ("-X", "-L", "8080:localhost:80", "host"),   # preposilani portu
            ("-XN", "host"),
            ("-X", "-O", "exit", "host"),
            ("-X",),                             # bez pocitace
            ("-Xx", "host", "ls"),               # -x ruci -X
        ]
        for args in plain:
            rc, calls = self.ssh(*args)
            self.assertEqual(calls, [["ssh", ""] + list(args)], args)
        for env in ({"WAYLAND_DISPLAY": None}, {"LUXOS_SSH_WAYPIPE": "0"}):
            rc, calls = self.ssh("-X", "host", "gedit", **env)
            self.assertEqual(calls, [["ssh", "", "-X", "host", "gedit"]], env)

    def test_option_arguments(self):
        rc, calls = self.ssh("-p2222", "-l", "bob", "-i", "/k/-X", "-X", "host", "-x", MOCK_PROBE="waypipe\n")
        self.assertEqual(self.last(calls), ("waypipe", ["ssh", "-p2222", "-l", "bob", "-i", "/k/-X", "host", "-x"]))
        rc, calls = self.ssh("-X", "--", "host", "cmd")
        self.assertEqual(self.last(calls)[1][-2:], ["host", "cmd"])

    def test_no_display(self):
        rc, calls = self.ssh("-X", "host", "a", DISPLAY=None, MOCK_PROBE="")
        self.assertEqual(calls[-1][2:], ["-X", "host", "a"])


@unittest.skipUnless(shutil.which("zsh"), "zsh neni nainstalovany")
class RemoteAppsZsh(RemoteApps):
    shell = "zsh"


if __name__ == "__main__":
    unittest.main()
