"""LuxOS - stare vyvojove kopie programu LuxOS v ~/.local nezakryji systemove (files/session/luxos-shadow-guard).

Skutecny pripad: v ~/.local/bin zustaly kopie luxos-clock-app, luxos-widgets, luxos-tour, luxos-app-studio
a luxos-icon-studio z drivejsich pokusu (a jejich .desktop v ~/.local/share/applications). ~/.local/bin je
v PATH pred /usr/bin, takze relace spoustela stary luxos-widgets misto verze z balicku.

Test pracuje jen v docasnem HOME s falesnym systemem (LUXOS_SYSROOT) a databazi balicku (LUXOS_PKG_DB);
skutecny ~/.local se nikdy nepouzije.

Spusteni:  env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY \\
               python3 -m unittest packages/luxos-desktop/tests/test_luxos_shadow_guard.py -v
"""
# LuxOS: testy nikdy ve skutecne relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import datetime
import glob
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
GUARD = os.path.join(FILES, "session", "luxos-shadow-guard")
I18N = os.path.join(ROOT, "packages", "luxos-i18n", "files")
REAL_HOME = os.path.expanduser("~")
OLD = time.time() - 30 * 86400      # kopie z drivejsich pokusu
PKG = time.time() - 2 * 86400       # soubory z balicku (cas sestaveni)
NEW = time.time() - 3600            # vyvojar na kopii prave pracuje


def write(path, text="", mtime=None, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class ShadowGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-shadow-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.root = os.path.join(self.tmp, "root")
        self.db = os.path.join(self.root, "var", "lib", "lux", "local")
        self.assertFalse(os.path.realpath(self.home).startswith(os.path.realpath(REAL_HOME) + "/"))
        self.bin = os.path.join(self.home, ".local", "bin")
        self.apps = os.path.join(self.home, ".local", "share", "applications")
        self.log = os.path.join(self.tmp, "notify.log")
        fake = os.path.join(self.tmp, "fakebin")
        write(os.path.join(fake, "notify-send"),
              '#!/bin/bash\nprintf "%%s\\n" "$@" >>%s\nprintf -- "--\\n" >>%s\n' % (self.log, self.log), mode=0o755)
        self.path = fake + ":/usr/bin:/bin"
        # system: balik luxos-desktop (luxos-widgets, luxos-tour, luxos-clock-app), luxos-app-studio, godot
        self.package("luxos-desktop-1.1.0-79", ["usr/bin/luxos-widgets", "usr/bin/luxos-tour", "usr/bin/luxos-clock-app",
                                                "usr/share/applications/luxos-tour.desktop",
                                                "usr/share/applications/luxos-clock-app.desktop"])
        self.package("luxos-app-studio-1.0.0-3", ["usr/bin/luxos-app-studio",
                                                  "usr/share/applications/luxos-app-studio.desktop"])
        self.package("godot-4.5-1", ["usr/bin/godot"])
        write(os.path.join(self.root, "usr/bin/luxos-unowned"), "#!/bin/sh\n", PKG, 0o755)   # neni v databazi

    def package(self, name, paths):
        write(os.path.join(self.db, name, "files"), "%FILES%\n" + "".join(
            sorted({os.path.dirname(p) + "/\n" for p in paths}) + [p + "\n" for p in paths]) + "\n")
        write(os.path.join(self.db, name, "desc"), "%NAME%\n" + name.rsplit("-", 2)[0] + "\n")
        for p in paths:
            write(os.path.join(self.root, p), "system " + p + "\n", PKG, 0o755 if "/bin/" in p else 0o644)

    def run_guard(self, **extra):
        env = {"PATH": self.path, "HOME": self.home, "LUXOS_SYSROOT": self.root, "LANG": "C"}
        env.update(extra)
        r = subprocess.run(["bash", GUARD], env={k: v for k, v in env.items() if v is not None},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return r.stdout.splitlines()

    def notifications(self, wait=True):
        for _ in range(40 if wait else 1):
            if os.path.exists(self.log):
                break
            time.sleep(0.05)
        if not os.path.exists(self.log):
            return []
        time.sleep(0.1)
        with open(self.log) as f:
            return [n.strip("\n").split("\n") for n in f.read().split("--\n") if n.strip()]

    def dest(self):
        return os.path.join(self.home, ".local/share/luxos/shadowed", datetime.date.today().isoformat())

    def test_real_incident_old_copies_moved(self):
        for n in ("luxos-widgets", "luxos-tour", "luxos-clock-app", "luxos-app-studio"):
            write(os.path.join(self.bin, n), "#!/bin/sh\necho OLD " + n + "\n", OLD, 0o755)
        write(os.path.join(self.apps, "luxos-tour.desktop"), "[Desktop Entry]\nName=Tour\nExec=luxos-tour\n", OLD)
        moved = self.run_guard()
        self.assertEqual(len(moved), 5, moved)
        self.assertEqual(os.listdir(self.bin), [])
        self.assertEqual(os.listdir(self.apps), [])
        d = self.dest()
        self.assertEqual(sorted(os.listdir(os.path.join(d, "bin"))),
                         ["luxos-app-studio", "luxos-clock-app", "luxos-tour", "luxos-widgets"])
        with open(os.path.join(d, "bin", "luxos-widgets")) as f:
            self.assertEqual(f.read(), "#!/bin/sh\necho OLD luxos-widgets\n")      # nic se nesmazalo ani nezmenilo
        self.assertTrue(os.access(os.path.join(d, "bin", "luxos-widgets"), os.X_OK))
        self.assertEqual(os.listdir(os.path.join(d, "applications")), ["luxos-tour.desktop"])
        notes = self.notifications()
        self.assertEqual(len(notes), 1, notes)                                     # jedno upozorneni
        title = next(a for a in notes[0] if a.startswith("Old copies of"))
        for n in ("luxos-widgets", "luxos-tour", "luxos-clock-app", "luxos-app-studio"):
            self.assertIn(n, title)
        self.assertEqual(title.count("luxos-tour"), 1)                            # bin + .desktop = jednou
        self.assertIn("~/.local/share/luxos/shadowed/" + datetime.date.today().isoformat(), notes[0][-1])
        self.assertIn("-u", notes[0])                                              # klidne (low)
        # dalsi prihlaseni: uz neni co presouvat, zadne dalsi upozorneni
        os.unlink(self.log)
        self.assertEqual(self.run_guard(), [])
        self.assertEqual(self.notifications(wait=False), [])

    def test_kept_files(self):
        keep = {
            "luxos-widgets": NEW,       # novejsi nez balik: vyvojar na ni pracuje
            "luxos-tour": PKG,          # stejne stara (napr. cp -p ze systemu)
            "luxos-unowned": OLD,       # systemovy soubor nepatri zadnemu baliku
            "luxos-glass-dock": OLD,    # v systemu neni
            "godot": OLD,               # neni program LuxOS
        }
        for n, t in keep.items():
            write(os.path.join(self.bin, n), "x\n", t, 0o755)
        write(os.path.join(self.apps, "luxos-clock-app.desktop"), "[Desktop Entry]\nNoDisplay=true\n", OLD)  # skryta
        write(os.path.join(self.apps, "luxos-sandbox-app-foo--bar.desktop"), "[Desktop Entry]\n", OLD)
        os.symlink(os.path.join(self.root, "usr/bin/luxos-clock-app"), os.path.join(self.bin, "luxos-clock-app"))
        os.symlink(os.path.join(self.tmp, "missing"), os.path.join(self.bin, "luxos-app-studio"))   # rozbity odkaz
        before = sorted(os.listdir(self.bin)), sorted(os.listdir(self.apps))
        self.assertEqual(self.run_guard(), [])
        self.assertEqual((sorted(os.listdir(self.bin)), sorted(os.listdir(self.apps))), before)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local/share/luxos")))
        self.assertEqual(self.notifications(wait=False), [])

    def test_symlink_to_old_dev_copy_moved_target_untouched(self):
        target = os.path.join(self.tmp, "src", "luxos-widgets")
        write(target, "dev\n", OLD, 0o755)
        os.makedirs(self.bin)
        os.symlink(target, os.path.join(self.bin, "luxos-widgets"))
        self.assertEqual(self.run_guard(), [os.path.join(self.bin, "luxos-widgets")])
        self.assertTrue(os.path.islink(os.path.join(self.dest(), "bin", "luxos-widgets")))
        self.assertTrue(os.path.isfile(target))

    def test_opt_out(self):
        write(os.path.join(self.bin, "luxos-widgets"), "x\n", OLD, 0o755)
        write(os.path.join(self.home, ".config/luxos/keep-local-overrides"))
        self.assertEqual(self.run_guard(), [])
        os.unlink(os.path.join(self.home, ".config/luxos/keep-local-overrides"))
        write(os.path.join(self.home, ".config/luxos/appearance.conf"), "BAR_OPACITY=60\nKEEP_LOCAL_OVERRIDES=1\n")
        self.assertEqual(self.run_guard(), [])
        self.assertTrue(os.path.exists(os.path.join(self.bin, "luxos-widgets")))
        write(os.path.join(self.home, ".config/luxos/appearance.conf"), "KEEP_LOCAL_OVERRIDES=0\n")
        self.assertEqual(len(self.run_guard()), 1)

    def test_same_day_twice_never_overwrites(self):
        for content in ("first\n", "second\n"):
            write(os.path.join(self.bin, "luxos-widgets"), content, OLD, 0o755)
            self.assertEqual(len(self.run_guard()), 1)
        d = os.path.join(self.dest(), "bin")
        self.assertEqual(sorted(os.listdir(d)), ["luxos-widgets", "luxos-widgets.1"])
        with open(os.path.join(d, "luxos-widgets")) as f:
            self.assertEqual(f.read(), "first\n")

    def test_old_pacman_database_and_no_database(self):
        os.rename(os.path.join(self.root, "var/lib/lux"), os.path.join(self.root, "var/lib/pacman"))
        write(os.path.join(self.bin, "luxos-widgets"), "x\n", OLD, 0o755)
        self.assertEqual(len(self.run_guard()), 1)
        write(os.path.join(self.bin, "luxos-widgets"), "x\n", OLD, 0o755)
        shutil.rmtree(os.path.join(self.root, "var/lib/pacman"))
        self.assertEqual(self.run_guard(), [])          # bez databaze se nic nepresouva
        self.assertTrue(os.path.exists(os.path.join(self.bin, "luxos-widgets")))

    @unittest.skipUnless(os.path.exists("/usr/lib/luxos/i18n.sh"), "bez /usr/lib/luxos/i18n.sh (luxos-i18n)")
    def test_notification_translated(self):
        write(os.path.join(self.bin, "luxos-widgets"), "x\n", OLD, 0o755)
        self.run_guard(LANG="cs_CZ.UTF-8", LUXOS_I18N_DIR=I18N)
        note = self.notifications()[0]
        self.assertIn("Staré kopie luxos-widgets nahradila verze ze systému", note)
        self.assertTrue(any(a.startswith("Staré kopie jsou přesunuté do ~/.local/share/luxos/shadowed/") for a in note))

    def test_texts_in_all_languages(self):
        with open(GUARD) as f:
            texts = re.findall(r'\$\(T "([^"]+)"', f.read())
        self.assertEqual(len(texts), 2)
        for tsv in glob.glob(os.path.join(I18N, "*.tsv")):
            with open(tsv, encoding="utf-8") as f:
                keys = {line.split("\t", 1)[0] for line in f if "\t" in line}
            for t in texts:
                self.assertIn(t, keys, os.path.basename(tsv))
        self.assertEqual(len(glob.glob(os.path.join(I18N, "*.tsv"))), 12)


class SessionPaths(unittest.TestCase):
    """Soucasti relace a autostart LuxOS s celou cestou: kopie v ~/.local/bin (PATH) je nezakryje."""

    def test_session_runs_guard_first_and_components_by_full_path(self):
        with open(os.path.join(FILES, "bin", "luxos-session"), encoding="utf-8") as f:
            src = f.read()
        guard = src.index("/usr/lib/luxos/luxos-shadow-guard")
        for cmd in ("luxos-widgets &", "luxos-clock-app --background", "luxos-hub; do", "luxos-menubar &",
                    "luxos-appname watch", "luxos-unfreeze --watch", "luxos-datasaver reapply",
                    "luxos-tour --first-run", "luxos-search --add-to-panel", "luxos-appearance reapply"):
            i = src.index(cmd)
            self.assertEqual(src[i - 9:i], "/usr/bin/", cmd)
            self.assertLess(guard, i, cmd)
        # zadne spusteni soucasti relace jen jmenem (krome testu "command -v" a pgrep -x)
        for line in src.splitlines():
            code = line.split("#", 1)[0]
            for m in re.finditer(r"(?<![\w/.-])(luxos-(?:widgets|clock-app|hub|menubar|tour|welcome|whats-new|"
                                 r"unfreeze|datasaver|appname|session-cover|displays|powersaver))\b", code):
                self.assertRegex(code[:m.start()], r"(pgrep .*-x |command -v )$", line)

    def test_autostart_entries_absolute(self):
        found = []
        for p in glob.glob(os.path.join(ROOT, "packages", "**", "*.desktop"), recursive=True):
            with open(p, encoding="utf-8") as f:
                text = f.read()
            if "/autostart/" not in p and not re.search(r'etc/xdg/autostart/%s"' % re.escape(os.path.basename(p)),
                                                        self.pkgbuilds()):
                continue
            exe = re.search(r"(?m)^Exec=(?:env (?:\S+=\S+ )+)?(\S+)", text).group(1)
            if os.path.basename(exe).startswith("lux"):
                found.append(p)
                self.assertTrue(exe.startswith("/usr/"), "%s: Exec=%s" % (p, exe))
        self.assertGreaterEqual(len(found), 5, found)

    def pkgbuilds(self):
        if not hasattr(self, "_pk"):
            out = []
            for p in glob.glob(os.path.join(ROOT, "packages", "**", "PKGBUILD"), recursive=True):
                with open(p, encoding="utf-8") as f:
                    out.append(f.read())
            self._pk = "\n".join(out)
        return self._pk

    def test_installed(self):
        with open(os.path.join(HERE, "..", "PKGBUILD"), encoding="utf-8") as f:
            pkg = f.read()
        self.assertIn('"$f/session/luxos-shadow-guard"', pkg)
        self.assertTrue(os.access(GUARD, os.X_OK))


if __name__ == "__main__":
    unittest.main()
