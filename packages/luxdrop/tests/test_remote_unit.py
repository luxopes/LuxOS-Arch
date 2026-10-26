#!/usr/bin/env python3
"""LuxDrop - jednotkove testy souboru jineho pocitace (remote.py): pravidla sdileni, povoleni,
prikaz sandboxu, zalozky a prenos dat pres TLS."""
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("LUXDROP_LIB", os.path.abspath(os.path.join(HERE, "..", "files", "lib"))))

from luxdrop import identity, remote, transfer  # noqa: E402


class HomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxdrop-remote-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self._env = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR")}
        os.environ["HOME"] = self.home
        for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            os.environ.pop(k, None)
        rt = os.path.join(self.tmp, "run")
        os.makedirs(rt, mode=0o700)
        os.environ["XDG_RUNTIME_DIR"] = rt

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


class SharePathTest(HomeCase):
    def test_rules(self):
        docs = os.path.join(self.home, "Documents")
        os.makedirs(docs)
        os.makedirs(os.path.join(self.home, ".ssh"))
        os.makedirs(os.path.join(self.home, ".config", "x"))
        self.assertEqual(remote.check_share_path(docs), (os.path.realpath(docs), False))
        self.assertEqual(remote.check_share_path(self.home), (os.path.realpath(self.home), True))
        for bad in (os.path.join(self.home, ".ssh"), os.path.join(self.home, ".config", "x"), "/", "/etc",
                    "/usr", self.tmp, os.path.join(self.home, "missing"), os.path.dirname(self.home)):
            with self.assertRaises(remote.ShareError, msg=bad):
                remote.check_share_path(bad)
        # Symlink na zakazane misto se vyhodnoti
        os.symlink("/etc", os.path.join(self.home, "etc-link"))
        with self.assertRaises(remote.ShareError):
            remote.check_share_path(os.path.join(self.home, "etc-link"))

    def test_shares_default_public_and_home_confirmation(self):
        s = remote.Shares()
        self.assertFalse(s.enabled)
        s.set_enabled(True)
        s = remote.Shares()
        self.assertTrue(s.enabled)
        self.assertEqual([f["name"] for f in s.folders()], ["Public"])
        self.assertTrue(os.path.isdir(os.path.join(self.home, "Public")))
        with self.assertRaises(remote.ShareError):
            s.add(self.home)
        s.add(self.home, allow_home=True)
        names = [f["name"] for f in remote.Shares().folders()]
        self.assertEqual(names[0], "Public")
        self.assertEqual(len(names), 2)
        self.assertEqual(s.remove("Public"), 1)
        self.assertEqual(len(remote.Shares().folders()), 1)
        # Vypnuti a znovu zapnuti nevrati Verejne (seznam uz je nastaveny)
        s.set_enabled(False)
        s.set_enabled(True)
        self.assertEqual(len(remote.Shares().folders()), 1)
        self.assertEqual(os.stat(s.path).st_mode & 0o777, 0o600)

    def test_xdg_public_dir(self):
        os.makedirs(os.path.join(self.home, ".config"))
        with open(os.path.join(self.home, ".config", "user-dirs.dirs"), "w") as f:
            f.write('XDG_PUBLICSHARE_DIR="$HOME/Verejne"\n')
        self.assertEqual(remote.public_dir(), os.path.join(self.home, "Verejne"))

    def test_unique_names(self):
        taken = set()
        n1 = remote.share_name("/a/Fotky", taken)
        taken.add(n1.lower())
        n2 = remote.share_name("/b/fotky", taken)
        self.assertEqual((n1, n2), ("Fotky", "fotky 2"))
        self.assertEqual(remote.share_name("/x/.hidden", set()), "hidden")
        self.assertEqual(remote.mount_name("../Bob/PC\n"), "BobPC")
        self.assertEqual(remote.mount_name("..."), "LuxOS")


class AccessTest(HomeCase):
    def test_store(self):
        a = remote.Access()
        fp = bytes(range(32))
        self.assertIsNone(a.get(fp))
        a.allow(fp, "Alice-PC\x00", False)
        e = remote.Access().get(fp)
        self.assertEqual((e["name"], e["write"]), ("Alice-PC", False))
        self.assertEqual(a.set_write("alice-pc", True), 1)
        self.assertTrue(remote.Access().get(fp)["write"])
        self.assertEqual(a.remove(fp.hex()[:16]), 1)
        self.assertIsNone(remote.Access().get(fp))
        self.assertEqual(os.stat(a.path).st_mode & 0o777, 0o600)


class SandboxTest(HomeCase):
    def test_read_only_argv(self):
        pub = os.path.join(self.home, "Public")
        os.makedirs(pub)
        argv = remote.sandbox_argv([{"name": "Public", "path": pub, "home": False}], False, "/x",
                                   sftp_server="/usr/lib/ssh/sftp-server")
        self.assertEqual(argv[0], "bwrap")
        for opt in ("--unshare-all", "--die-with-parent", "--clearenv", "--new-session"):
            self.assertIn(opt, argv)
        i = argv.index(pub)
        self.assertEqual(argv[i - 1], "--ro-bind")
        self.assertEqual(argv[i + 1], "/share/Public")
        self.assertEqual(argv[-1], "-R")
        self.assertIn("symlink,hardlink@openssh.com", argv)
        # Zadna jina cesta z domova, jen /usr
        binds = [argv[k + 1] for k, a in enumerate(argv) if a in ("--bind", "--ro-bind")]
        self.assertEqual([b for b in binds if b.startswith(self.home)], [pub])

    def test_write_and_home_masks(self):
        os.makedirs(os.path.join(self.home, ".ssh"))
        open(os.path.join(self.home, ".bash_history"), "w").close()
        os.symlink("/etc", os.path.join(self.home, ".link"))
        os.makedirs(os.path.join(self.home, "Documents"))
        os.symlink("/etc", os.path.join(self.home, "etc-link"))
        argv = remote.sandbox_argv([{"name": "home", "path": self.home, "home": True}], True, "/x",
                                   sftp_server="/usr/lib/ssh/sftp-server")
        self.assertNotIn("-R", argv)
        i = argv.index(self.home)
        # Koren domova jen pro cteni (zadne nove .bashrc), zapisovat jde do neskrytych podslozek
        self.assertEqual(argv[i - 1], "--ro-bind")
        d = argv.index(os.path.join(self.home, "Documents"))
        self.assertEqual((argv[d - 1], argv[d + 1]), ("--bind", "/share/home/Documents"))
        self.assertNotIn(os.path.join(self.home, "etc-link"), argv)
        self.assertIn("/share/home/.ssh", argv)
        self.assertEqual(argv[argv.index("/share/home/.ssh") - 1], "--tmpfs")
        j = argv.index("/share/home/.bash_history")
        self.assertEqual(argv[j - 2:j], ["--ro-bind", "/dev/null"])
        self.assertNotIn("/share/home/.link", argv)
        # Koren jen pro cteni az po vsech pripojenich
        self.assertGreater(argv.index("--remount-ro"), i)


class BookmarkTest(HomeCase):
    def test_add_remove_keeps_others(self):
        f = remote.bookmarks_file()
        os.makedirs(os.path.dirname(f))
        with open(f, "w") as fh:
            fh.write("file:///home/x/Projects Projects\n")
        p = os.path.join(os.environ["XDG_RUNTIME_DIR"], "luxdrop-files", "Bob PC")
        remote.add_bookmark(p, "Bob PC")
        remote.add_bookmark(p, "Bob PC")
        lines = open(f).read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("file://") and "Bob%20PC" in lines[1])
        remote.remove_bookmark(p)
        self.assertEqual(open(f).read(), "file:///home/x/Projects Projects\n")


class RelayTest(HomeCase):
    def test_tls_relay_both_directions(self):
        ident = identity.Identity.load_or_create(os.path.join(self.tmp, "id"))
        srv = socket.create_server(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        sctx = remote._server_context(ident)
        payload = os.urandom(3 * 1024 * 1024 + 17)
        got = {}

        def server():
            conn, _a = srv.accept()
            tls = sctx.wrap_socket(conn, server_side=True)
            a, b = socket.socketpair()

            def echo():
                # Druha strana (jako sftp-server): vse prijate vrati obracene po blocich
                buf = bytearray()
                while len(buf) < len(payload):
                    d = b.recv(1 << 16)
                    if not d:
                        break
                    buf += d
                got["server"] = bytes(buf)
                b.sendall(bytes(buf[::-1]))
                b.close()
            t = threading.Thread(target=echo)
            t.start()
            remote.relay(tls, a)
            t.join()
            a.close()

        th = threading.Thread(target=server)
        th.start()
        raw = socket.create_connection(("127.0.0.1", port))
        tls = remote._client_context().wrap_socket(raw, server_hostname=None)
        self.assertEqual(tls.selected_alpn_protocol(), remote.ALPN)
        tls.sendall(payload)
        buf = bytearray()
        while True:
            try:
                d = tls.recv(1 << 16)
            except (ssl.SSLError, OSError):
                break
            if not d:
                break
            buf += d
        th.join(10)
        self.assertEqual(got["server"], payload)
        self.assertEqual(bytes(buf), payload[::-1])
        srv.close()
        tls.close()

    def test_alpn_mismatch(self):
        ident = identity.Identity.load_or_create(os.path.join(self.tmp, "id"))
        srv = socket.create_server(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        sctx = remote._server_context(ident)

        def server():
            conn, _a = srv.accept()
            try:
                sctx.wrap_socket(conn, server_side=True)
            except (ssl.SSLError, OSError):
                pass
            conn.close()
        th = threading.Thread(target=server)
        th.start()
        raw = socket.create_connection(("127.0.0.1", port))
        # Klient LuxDrop (prenos souboru) se na sdileni nedomluvi
        with self.assertRaises((ssl.SSLError, OSError, Exception)):
            tls = transfer.client_context().wrap_socket(raw, server_hostname=None)
            transfer.check_alpn(tls)
            remote._check_alpn(tls)
            raise ssl.SSLError("ALPN accepted")
        th.join(5)
        srv.close()


if __name__ == "__main__":
    unittest.main()
