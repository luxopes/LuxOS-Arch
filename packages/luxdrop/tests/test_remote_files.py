#!/usr/bin/env python3
"""LuxDrop - soubory jineho pocitace: dve instance v oddelenych HOME na 127.0.0.1 (bez mDNS).

Bob-PC sdili slozky (luxdrop share serve, odpovedi v terminalu), Alice-PC se pripojuje
(luxdrop connect --no-open, sshfs pres FUSE). Potrebuje bwrap, sshfs, sftp-server a /dev/fuse;
jinak se testy preskoci.

Spusteni (z adresare packages/luxdrop): python3 tests/test_remote_files.py -v
"""
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.environ.get("LUXDROP_LIB", os.path.abspath(os.path.join(HERE, "..", "files", "lib")))
LAUNCHER = os.environ.get("LUXDROP_BIN", os.path.abspath(os.path.join(HERE, "..", "files", "luxdrop")))
sys.path.insert(0, LIB)

from luxdrop import remote  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read(path):
    with open(path) as f:
        return f.read()


def can_run():
    if not all(shutil.which(p) for p in ("bwrap", "sshfs", "fusermount3")) or remote.sftp_server_path() is None:
        return "bwrap, sshfs or sftp-server missing"
    if not os.path.exists("/dev/fuse"):
        return "no /dev/fuse"
    r = subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
                        "--symlink", "usr/lib", "/lib64", "/usr/bin/true"], capture_output=True)
    if r.returncode != 0:
        return "bwrap does not work here: %s" % r.stderr.decode(errors="replace").strip()
    return None


SKIP = can_run()


class Proc:
    """Proces s citanim vystupu po radcich (stdout i stderr)."""

    def __init__(self, env, *args):
        self.p = subprocess.Popen([sys.executable, LAUNCHER] + list(args), env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.q = queue.Queue()
        self.lines = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = ""
        while True:
            ch = self.p.stdout.read(1)
            if not ch:
                if buf:
                    self.q.put(buf)
                self.q.put(None)
                return
            buf += ch
            # Vyzvy bez konce radku ("... [y/N]: ") se predaji hned
            if ch == "\n" or (buf.endswith(": ") and "[" in buf):
                self.q.put(buf.rstrip("\n"))
                buf = ""

    def expect(self, pattern, timeout=20):
        deadline = time.monotonic() + timeout
        rx = re.compile(pattern)
        while time.monotonic() < deadline:
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                raise AssertionError("process ended while waiting for %r; output:\n%s"
                                     % (pattern, "\n".join(self.lines)))
            self.lines.append(line)
            m = rx.search(line)
            if m:
                return m
        raise AssertionError("timeout waiting for %r; output:\n%s" % (pattern, "\n".join(self.lines)))

    def send(self, text):
        self.p.stdin.write(text + "\n")
        self.p.stdin.flush()

    def wait(self, timeout=20):
        return self.p.wait(timeout)

    def stop(self):
        for f in (self.p.stdin,):
            try:
                f.close()
            except OSError:
                pass
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()
        self.p.stdout.close()


@unittest.skipIf(SKIP, SKIP)
class RemoteFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxdrop-files-")
        self.port = free_port()
        self.procs = []
        self.bob = self.make_env("bob", "Bob-PC")
        self.alice = self.make_env("alice", "Alice-PC")
        self.carol = self.make_env("carol", "Carol-PC")
        self.bob_home = self.bob["HOME"]
        pub = os.path.join(self.bob_home, "Public")
        os.makedirs(os.path.join(pub, "photos"))
        with open(os.path.join(pub, "hello.txt"), "w") as f:
            f.write("hello from bob\n")
        with open(os.path.join(self.bob_home, "secret.txt"), "w") as f:
            f.write("secret\n")
        os.symlink(os.path.join(self.bob_home, "secret.txt"), os.path.join(pub, "escape"))
        os.makedirs(os.path.join(self.bob_home, ".ssh"))
        with open(os.path.join(self.bob_home, ".ssh", "id_ed25519"), "w") as f:
            f.write("PRIVATE KEY\n")
        r = self.run_cli(self.bob, "share", "on")
        self.assertEqual(r.returncode, 0, r.stdout)

    def tearDown(self):
        for p in self.procs:
            p.stop()
        for env in (self.alice, self.carol):
            for e in self.connections(env):
                subprocess.run(["fusermount3", "-u", "-z", e["path"]], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_env(self, who, name):
        home = os.path.join(self.tmp, who)
        rt = os.path.join(self.tmp, who + "-run")
        os.makedirs(home)
        os.makedirs(rt, mode=0o700)
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CONFIG_HOME",
                                                                "XDG_DATA_HOME", "DBUS_SESSION_BUS_ADDRESS")}
        env.update({"HOME": home, "XDG_RUNTIME_DIR": rt, "LUXDROP_LIB": LIB, "LUXDROP_NO_MDNS": "1",
                    "LUXDROP_NO_SYSTEMD": "1", "LANG": "C.UTF-8", "LANGUAGE": "en", "PYTHONUNBUFFERED": "1"})
        os.makedirs(os.path.join(home, ".config", "luxdrop"))
        with open(os.path.join(home, ".config", "luxdrop", "settings.json"), "w") as f:
            f.write('{"name": "%s"}' % name)
        return env

    def run_cli(self, env, *args, input_text=None):
        return subprocess.run([sys.executable, LAUNCHER] + list(args), env=env, capture_output=True, text=True,
                              input=input_text, timeout=60)

    def start(self, env, *args):
        p = Proc(env, *args)
        self.procs.append(p)
        return p

    def serve(self):
        bob = self.start(self.bob, "share", "serve", "--no-mdns", "--bind", "127.0.0.1", "--port", str(self.port))
        bob.expect(r"Sharing as \"Bob-PC\"")
        return bob

    def connections(self, env):
        r = self.run_cli(env, "connections")
        out = []
        for line in r.stdout.splitlines():
            m = re.search(r"(\S+/luxdrop-files/.+)$", line)
            if m:
                out.append({"path": m.group(1)})
        return out

    def connect(self, env, *extra):
        return self.start(env, "connect", "127.0.0.1:%d" % self.port, "--no-open", *extra)

    def wait_unmounted(self, path, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not os.path.ismount(path):
                return True
            time.sleep(0.2)
        return False

    # --- Testy ------------------------------------------------------------------

    def test_read_only_once(self):
        bob = self.serve()
        alice = self.connect(self.alice)
        code_bob = bob.expect(r"Verification code: (\d{3} \d{3})").group(1)
        code_alice = alice.expect(r"Verification code: (\d{3} \d{3})").group(1)
        self.assertEqual(code_bob, code_alice)
        alice.expect(r"same code\?")
        alice.send("y")
        bob.expect(r"Allow\?")
        bob.send("o")
        path = alice.expect(r"Connected to Bob-PC \(read-only\): (.+)$").group(1)
        self.assertTrue(os.path.ismount(path))
        self.assertEqual(sorted(os.listdir(path)), ["Public"])
        with open(os.path.join(path, "Public", "hello.txt")) as f:
            self.assertEqual(f.read(), "hello from bob\n")
        # Odkaz mimo sdilenou slozku je v sandboxu rozbity
        with self.assertRaises(OSError):
            read(os.path.join(path, "Public", "escape"))
        # Jen pro cteni
        with self.assertRaises(OSError):
            open(os.path.join(path, "Public", "new.txt"), "w").write("x")
        with self.assertRaises(OSError):
            os.mkdir(os.path.join(path, "x"))
        self.assertFalse(os.path.exists(os.path.join(self.bob_home, "Public", "new.txt")))
        # Zalozka v postrannim panelu
        bm = read(os.path.join(self.alice["HOME"], ".config", "gtk-3.0", "bookmarks"))
        self.assertIn("luxdrop-files/Bob-PC", bm)
        self.assertEqual(len(self.connections(self.alice)), 1)
        # "Jednou" se neulozi: Bob nema zadne trvale povoleni
        st = self.run_cli(self.bob, "share", "status").stdout
        self.assertIn("None (every connection is asked first)", st)
        r = self.run_cli(self.alice, "disconnect", "--all")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(alice.wait(15), 0)
        self.assertTrue(self.wait_unmounted(path))
        self.assertFalse(os.path.exists(path))
        bm = read(os.path.join(self.alice["HOME"], ".config", "gtk-3.0", "bookmarks"))
        self.assertNotIn("luxdrop-files/Bob-PC", bm)

    def test_always_with_write_then_revoke(self):
        bob = self.serve()
        alice = self.connect(self.alice, "--write")
        alice.expect(r"same code\?")
        alice.send("y")
        bob.expect(r"Allow\?")
        bob.send("a")
        bob.expect(r"Also allow changes")
        bob.send("y")
        path = alice.expect(r"Connected to Bob-PC \(can change files\): (.+)$").group(1)
        with open(os.path.join(path, "Public", "from-alice.txt"), "w") as f:
            f.write("hi bob\n")
        os.mkdir(os.path.join(path, "Public", "newdir"))
        os.rename(os.path.join(path, "Public", "photos"), os.path.join(path, "Public", "pictures"))
        with open(os.path.join(self.bob_home, "Public", "from-alice.txt")) as f:
            self.assertEqual(f.read(), "hi bob\n")
        self.assertTrue(os.path.isdir(os.path.join(self.bob_home, "Public", "newdir")))
        self.assertTrue(os.path.isdir(os.path.join(self.bob_home, "Public", "pictures")))
        # Koren (mimo sdilene slozky) je jen pro cteni, symlinky zakazane
        with self.assertRaises(OSError):
            open(os.path.join(path, "outside.txt"), "w").write("x")
        with self.assertRaises(OSError):
            os.symlink("/etc/passwd", os.path.join(path, "Public", "link"))
        self.assertIn("can change files", self.run_cli(self.bob, "share", "status").stdout)
        self.run_cli(self.alice, "disconnect", "--all")
        alice.wait(15)

        # Podruhe bez dotazu (Vzdy) a bez kodu (Alice si Boba zapamatovala)
        alice = self.connect(self.alice, "--write")
        path = alice.expect(r"Connected to Bob-PC \(can change files\): (.+)$").group(1)
        self.assertNotIn("same code", "\n".join(alice.lines))
        with self.assertRaises(AssertionError):
            bob.expect(r"Allow\?", timeout=1)
        # Odebrani pristupu ukonci spojeni
        r = self.run_cli(self.bob, "share", "forget", "Alice-PC")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(alice.wait(20), 0)
        self.assertTrue(self.wait_unmounted(path))

    def test_deny_and_cooldown(self):
        bob = self.serve()
        carol = self.connect(self.carol)
        carol.expect(r"same code\?")
        carol.send("y")
        bob.expect(r"Allow\?")
        bob.send("n")
        self.assertEqual(carol.wait(20), 3)
        # Hned znovu: odmitnuto bez dotazu
        r = self.run_cli(self.carol, "connect", "127.0.0.1:%d" % self.port, "--no-open", input_text="y\n")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("declined", r.stderr)

    def test_code_not_confirmed(self):
        bob = self.serve()
        alice = self.connect(self.alice)
        alice.expect(r"same code\?")
        bob.expect(r"Allow\?")
        alice.send("n")
        self.assertEqual(alice.wait(20), 3)
        bob.expect(r"cancelled the request|cancelled", timeout=10)

    def test_other_computer_gone(self):
        bob = self.serve()
        alice = self.connect(self.alice)
        alice.expect(r"same code\?")
        alice.send("y")
        bob.expect(r"Allow\?")
        bob.send("o")
        path = alice.expect(r"Connected to Bob-PC \(read-only\): (.+)$").group(1)
        self.assertEqual(self.connections(self.alice), [{"path": path}])
        self.assertTrue(os.path.ismount(path))
        bob.p.kill()  # druhy pocitac zmizi (spojeni se zavre)
        self.assertEqual(alice.wait(20), 0)
        self.assertTrue(self.wait_unmounted(path))
        self.assertEqual(self.connections(self.alice), [])

    def test_sharing_off(self):
        self.run_cli(self.bob, "share", "off")
        r = self.run_cli(self.bob, "share", "serve", "--no-mdns", "--port", str(self.port))
        self.assertEqual(r.returncode, 1)

    def test_home_share_hides_dotfiles(self):
        r = self.run_cli(self.bob, "share", "add", self.bob_home, input_text="n\n")
        self.assertEqual(r.returncode, 3)
        r = self.run_cli(self.bob, "share", "add", self.bob_home, "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli(self.bob, "share", "add", os.path.join(self.bob_home, ".ssh"))
        self.assertNotEqual(r.returncode, 0)
        bob = self.serve()
        alice = self.connect(self.alice)
        alice.expect(r"same code\?")
        alice.send("o")
        bob.expect(r"Allow\?")
        bob.send("o")
        path = alice.expect(r"Connected to Bob-PC \(read-only\): (.+)$").group(1)
        self.assertEqual(sorted(os.listdir(path)), ["Public", "bob"])
        home = os.path.join(path, "bob")
        self.assertIn("secret.txt", os.listdir(home))
        self.assertEqual(os.listdir(os.path.join(home, ".ssh")), [])
        self.assertFalse(os.path.exists(os.path.join(home, ".config", "luxdrop", "settings.json")))
        # Alice si Boba nezapamatovala ([o]nly this time)
        self.assertNotIn("Bob-PC", self.run_cli(self.alice, "trust").stdout)
        self.run_cli(self.alice, "disconnect", "Bob-PC")
        alice.wait(15)

    def test_home_share_write_only_in_subfolders(self):
        os.makedirs(os.path.join(self.bob_home, "Documents"))
        self.run_cli(self.bob, "share", "remove", "Public")
        r = self.run_cli(self.bob, "share", "add", self.bob_home, "--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        bob = self.serve()
        alice = self.connect(self.alice, "--write")
        alice.expect(r"same code\?")
        alice.send("y")
        bob.expect(r"Allow\?")
        bob.send("o")
        bob.expect(r"Also allow changes")
        bob.send("y")
        path = alice.expect(r"Connected to Bob-PC \(can change files\): (.+)$").group(1)
        home = os.path.join(path, "bob")
        self.assertEqual(os.listdir(path), ["bob"])
        with open(os.path.join(home, "Documents", "note.txt"), "w") as f:
            f.write("ok")
        self.assertEqual(read(os.path.join(self.bob_home, "Documents", "note.txt")), "ok")
        for bad in (".bashrc", "top.txt", os.path.join(".ssh", "authorized_keys")):
            with self.assertRaises(OSError, msg=bad):
                open(os.path.join(home, bad), "w").write("x")
            self.assertFalse(os.path.exists(os.path.join(self.bob_home, bad)), bad)
        with self.assertRaises(OSError):
            os.remove(os.path.join(home, "secret.txt"))
        self.assertTrue(os.path.exists(os.path.join(self.bob_home, "secret.txt")))
        self.run_cli(self.alice, "disconnect", "--all")
        alice.wait(15)

    def test_key_mismatch(self):
        bob = self.serve()
        alice = self.connect(self.alice)
        alice.expect(r"same code\?")
        alice.send("y")
        bob.expect(r"Allow\?")
        bob.send("o")
        alice.expect(r"Connected to Bob-PC")
        self.run_cli(self.alice, "disconnect", "--all")
        alice.wait(15)
        bob.stop()
        # Jiny pocitac (Carol) se vydava za Boba na stejne adrese
        os.makedirs(os.path.join(self.carol["HOME"], "Public"), exist_ok=True)
        self.run_cli(self.carol, "share", "on")
        mallory = self.start(self.carol, "share", "serve", "--no-mdns", "--bind", "127.0.0.1",
                             "--port", str(self.port))
        mallory.expect(r"Sharing as")
        r = self.run_cli(self.alice, "connect", "Bob-PC@127.0.0.1:%d" % self.port, "--no-open")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("key_mismatch", r.stderr)


if __name__ == "__main__":
    unittest.main()
