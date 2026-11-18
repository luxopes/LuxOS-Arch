"""Prava souboru v balicich [luxos-drivers]: setuid/setgid a zapis pro vsechny (drivers/luxdrv.py perms,
drivers/makepkg-tidy-luxos-perms.sh, zaplata Canon cnrdrvcups-lb).

Spusteni: python3 -m unittest discover -s drivers/tests -v
Docasne soubory jsou v out/ repozitare (ne v /tmp).
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVERS = os.path.dirname(HERE)
ROOT = os.path.dirname(DRIVERS)
sys.path.insert(0, DRIVERS)
import luxdrv  # noqa: E402

TIDY = os.path.join(DRIVERS, "makepkg-tidy-luxos-perms.sh")
CNR_PATCH = os.path.join(DRIVERS, "patches", "cnrdrvcups-lb", "luxos-cngplp2-perms.patch")

# .install drivejsi verze zaplaty Canon (1:6.40.1.05-2.1): sticky 1777 = porad zapis pro vsechny
OLD_CNR_INSTALL = """post_install() {
    if [ -d /etc/cngplp2/account ]; then
        chmod 1777 /etc/cngplp2/account
    fi
}
"""


def tmpdir():
    base = os.path.join(ROOT, "out", "test-drivers-perms")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(dir=base)


def make_pkg(path, name, members, install=None):
    """Maly balik .pkg.tar.zst: members = [(cesta, mod, 'f'|'d'|'l')]."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        def add(n, data=b"", mode=0o644, kind="f"):
            ti = tarfile.TarInfo(n)
            ti.mode = mode
            if kind == "d":
                ti.type = tarfile.DIRTYPE
            elif kind == "l":
                ti.type, ti.linkname = tarfile.SYMTYPE, "target"
            else:
                ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data) if kind == "f" else None)
        add(".PKGINFO", f"pkgname = {name}\npkgver = 1-1\n".encode())
        if install is not None:
            add(".INSTALL", install.encode())
        for n, mode, kind in members:
            add(n, b"x" if kind == "f" else b"", mode, kind)
    p = subprocess.run(["zstd", "-q", "-c"], input=buf.getvalue(), capture_output=True, check=True)
    with open(path, "wb") as f:
        f.write(p.stdout)
    return path


class Issues(unittest.TestCase):
    def test_detects_setuid_setgid_and_world_writable(self):
        got = luxdrv.perm_issues([
            ("usr/bin/cnpkmoduleufr2r", 0o4755, "f"),
            ("usr/bin/sg", 0o2755, "f"),
            ("etc/cngplp2/account", 0o1777, "d"),
            ("etc/cngplp2/options", 0o777, "d"),
            ("usr/share/brother/inf/brXrc", 0o666, "f"),
            ("usr/bin/ok", 0o755, "f"),
            ("usr/share/ok", 0o2775, "d"),          # setgid adresar bez zapisu pro vsechny = v poradku
            ("usr/lib/link", 0o777, "l"),           # odkazy maji vzdy 777
        ])
        self.assertEqual([(p, w) for p, _m, w in got], [
            ("usr/bin/cnpkmoduleufr2r", "setuid"),
            ("usr/bin/sg", "setgid"),
            ("etc/cngplp2/account", "world-writable directory"),
            ("etc/cngplp2/options", "world-writable directory"),
            ("usr/share/brother/inf/brXrc", "world-writable file"),
        ])


class InstallScript(unittest.TestCase):
    def bad(self, text):
        return luxdrv.install_perm_problems(text)

    def test_old_canon_install_is_rejected(self):
        self.assertTrue(self.bad(OLD_CNR_INSTALL))

    def test_forbidden_modes(self):
        for line in ("chmod 4755 /usr/bin/x", "chmod u+s /usr/bin/x", "chmod -R o+w /opt/x", "chmod a+rw /x",
                     "chmod 0777 /opt/x", "chmod g+s,o+w /x", "install -m 4755 a /usr/bin/a", "install -Dm666 a /b",
                     "install --mode=2755 a /b", "mkdir -m 1777 /var/x", "mkdir -p -m 777 /x",
                     "test -d /x && chmod 777 /x"):
            self.assertTrue(self.bad(f"post_install() {{\n  {line}\n}}\n"), line)

    def test_disguised_modes(self):
        """5mistny oktal, find -exec / xargs / env, mod z promenne nebo stdin (nejde overit)."""
        for line in ("chmod 04755 /usr/bin/x", "chmod 0004755 /x", "install -m04755 a /b", "install -Dm 04755 a /b",
                     "find /opt/x -name y -exec chmod 4755 {} \\;", "find /opt -exec chmod u=rwxs {} +",
                     "echo /x | xargs chmod 4755", "echo /x | xargs chmod", "env chmod 4755 /x", 'chmod "$m" /x',
                     "chmod --reference=/usr/bin/sudo /x", "x=$(chmod 4755 /x)"):
            self.assertTrue(self.bad(f"post_install() {{\n  {line}\n}}\n"), line)

    def test_allowed_modes(self):
        for line in ("chmod 0755 /usr/bin/x", "chmod 755 /x", "chmod 0750 /etc/cngplp2/account", "chmod -R go-w /x",
                     "chmod u+x /x", "install -Dm755 a /usr/bin/a", "install -m 0644 a b", "mkdir -p /x",
                     "chmod +t /x", "echo 'chmod 777 is bad'", "# chmod 777 /x"):
            self.assertEqual(self.bad(f"post_install() {{\n  {line}\n}}\n"), [], line)


class Allowlist(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def load(self, data):
        p = os.path.join(self.d, "allow.json")
        with open(p, "w") as f:
            json.dump(data, f)
        return luxdrv.load_perms_allow(p)

    def test_repo_allowlist_is_valid(self):
        allow, problems = luxdrv.load_perms_allow()
        self.assertEqual(problems, [])

    def test_entry_needs_justification(self):
        _a, p = self.load({"allow": {"x": [{"path": "usr/bin/x", "mode": "4755"}]}})
        self.assertTrue(p and "justification" in p[0])
        _a, p = self.load({"allow": {"x": [{"path": "usr/bin/x", "mode": "4755", "why": "short"}]}})
        self.assertTrue(p)

    def test_bad_path_and_mode(self):
        _a, p = self.load({"allow": {"x": [{"path": "/usr/bin/x", "mode": "4755", "why": "w" * 30}]}})
        self.assertTrue(p and "bad path" in p[0])
        _a, p = self.load({"allow": {"x": [{"path": "usr/../etc/x", "mode": "4755", "why": "w" * 30}]}})
        self.assertTrue(p)
        _a, p = self.load({"allow": {"x": [{"path": "usr/bin/x", "mode": "u+s", "why": "w" * 30}]}})
        self.assertTrue(p and "bad mode" in p[0])

    def test_missing_file_is_an_error(self):
        _a, p = luxdrv.load_perms_allow(os.path.join(self.d, "nothing.json"))
        self.assertTrue(p)

    def test_valid_entry(self):
        a, p = self.load({"allow": {"x": [{"path": "usr/bin/x", "mode": "4755", "why": "needs raw USB access for y"}]}})
        self.assertEqual((a, p), ({"x": {"usr/bin/x": 0o4755}}, []))


class Package(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_vulnerable_canon_package_fails(self):
        # jako zverejneny cnrdrvcups-lb 1:6.40.1.05-2.1
        pkg = make_pkg(os.path.join(self.d, "cnr.pkg.tar.zst"), "cnrdrvcups-lb", [
            ("usr/bin/cnpkmoduleufr2r", 0o4755, "f"), ("etc/cngplp2/account", 0o1777, "d"),
            ("etc/cngplp2/options", 0o1777, "d"), ("usr/lib/cups/filter/rastertoufr2", 0o755, "f")],
            install=OLD_CNR_INSTALL)
        name, problems = luxdrv.check_package_perms(pkg, {})
        self.assertEqual(name, "cnrdrvcups-lb")
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("cnpkmoduleufr2r 4755: setuid" in p for p in problems))
        self.assertTrue(any(p.startswith(".INSTALL") for p in problems))

    def test_fixed_package_passes(self):
        pkg = make_pkg(os.path.join(self.d, "cnr.pkg.tar.zst"), "cnrdrvcups-lb", [
            ("usr/bin/cnpkmoduleufr2r", 0o755, "f"), ("etc/cngplp2/account", 0o750, "d"),
            ("etc/cngplp2/options", 0o755, "d"), ("usr/lib/link", 0o777, "l")],
            install=patch_new_file(CNR_PATCH, "luxos-cngplp2.install"))
        self.assertEqual(luxdrv.check_package_perms(pkg, {}), ("cnrdrvcups-lb", []))

    def test_allowlisted_exact_mode_only(self):
        pkg = make_pkg(os.path.join(self.d, "a.pkg.tar.zst"), "vendor-x", [("usr/bin/x", 0o4755, "f")])
        self.assertEqual(luxdrv.check_package_perms(pkg, {"vendor-x": {"usr/bin/x": 0o4755}})[1], [])
        # jiny balik nebo jiny mod vyjimku nema
        self.assertTrue(luxdrv.check_package_perms(pkg, {"vendor-y": {"usr/bin/x": 0o4755}})[1])
        self.assertTrue(luxdrv.check_package_perms(pkg, {"vendor-x": {"usr/bin/x": 0o4711}})[1])

    def test_cli_exit_code(self):
        bad = make_pkg(os.path.join(self.d, "bad.pkg.tar.zst"), "b", [("usr/share/b/rc", 0o666, "f")])
        good = make_pkg(os.path.join(self.d, "good.pkg.tar.zst"), "g", [("usr/share/g/rc", 0o644, "f")])
        run = [sys.executable, os.path.join(DRIVERS, "luxdrv.py"), "perms"]
        self.assertEqual(subprocess.run(run + [good], capture_output=True).returncode, 0)
        r = subprocess.run(run + [good, bad], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("b: /usr/share/b/rc 0666: world-writable file", r.stdout)
        r = subprocess.run(run + ["--report", self.d], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


class BuildKey(unittest.TestCase):
    def test_key_changes_with_patches_and_policy(self):
        m = {"commit": "abc"}
        k = luxdrv.build_key(m)
        self.assertTrue(k.startswith("abc ") and f"perms:{luxdrv.PERMS_POLICY}" in k)
        k1 = luxdrv.build_key(dict(m, patches={"a.patch": "1" * 64}))
        k2 = luxdrv.build_key(dict(m, patches={"a.patch": "2" * 64}))
        self.assertNotEqual(k1, k2)
        self.assertNotEqual(k, k1)


def patch_new_file(patch, name):
    """Obsah noveho souboru (--- /dev/null) ze zaplaty."""
    out, on = [], False
    with open(patch, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith("+++ "):
            on = line.strip().endswith("/" + name)
            continue
        if line.startswith("--- "):
            on = False
            continue
        if on and line.startswith("+"):
            out.append(line[1:])
    return "".join(out)


class CanonPatch(unittest.TestCase):
    """Zaplata LuxOS pro cnrdrvcups-lb: bez setuid, bez adresaru zapisovatelnych pro vsechny, i u starsich instalaci."""

    def setUp(self):
        with open(CNR_PATCH, encoding="utf-8") as f:
            self.text = f.read()
        self.inst = patch_new_file(CNR_PATCH, "luxos-cngplp2.install")

    def test_no_world_writable_or_setuid_left(self):
        added = [ln[1:] for ln in self.text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        code = [ln.split("#", 1)[0] for ln in added]
        self.assertFalse(any("777" in c or "u+s" in c for c in code))
        self.assertIn('chmod 0755 "$pkgdir/usr/bin/cnpkmoduleufr2r"', self.text)
        self.assertIn('chmod 0750 "$pkgdir/etc/cngplp2/account"', self.text)

    def test_install_script_fixes_existing_dirs_and_passes_checks(self):
        self.assertIn("chmod 0750 /etc/cngplp2/account", self.inst)
        self.assertIn("chmod 0755 /etc/cngplp2/options", self.inst)
        self.assertIn("post_upgrade()", self.inst)
        self.assertEqual(luxdrv.check_install_script(self.inst), [])
        self.assertEqual(luxdrv.install_perm_problems(self.inst), [])

    def test_patched_pkgbuild_passes_static_check(self):
        """Zmenene radky PKGBUILD v package() projdou kontrolou overovani (luxdrv FORBIDDEN, zapisy)."""
        body = [(i + 1, ln[1:]) for i, ln in enumerate(self.text.splitlines())
                if ln.startswith("+") and not ln.startswith("+++") and "$pkgdir" in ln]
        self.assertTrue(body)
        self.assertEqual(luxdrv.scan_code(body, "package()"), [])


@unittest.skipUnless(shutil.which("bash") and shutil.which("stat") and shutil.which("find"), "needs bash")
class Tidy(unittest.TestCase):
    """makepkg-tidy-luxos-perms.sh na falesnem $pkgdir (chgrp jen zaznamenan - bez fakeroot ho nejde provest)."""

    def setUp(self):
        self.d = tmpdir()
        self.pkg = os.path.join(self.d, "pkg")
        for p, mode, kind in (("usr/bin/cnpkmoduleufr2r", 0o4755, "f"), ("usr/bin/sg", 0o2755, "f"),
                              ("usr/bin/ok", 0o755, "f"), ("usr/bin/allowed", 0o4755, "f"),
                              ("etc/cngplp2/account", 0o1777, "d"), ("usr/share/brother/inf", 0o777, "d"),
                              ("usr/share/brother/inf/brXrc", 0o666, "f"), ("usr/share/gid", 0o2775, "d")):
            full = os.path.join(self.pkg, p)
            if kind == "d":
                os.makedirs(full, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                open(full, "w").close()
        for p, mode in (("usr/bin/cnpkmoduleufr2r", 0o4755), ("usr/bin/sg", 0o2755), ("usr/bin/ok", 0o755),
                        ("usr/bin/allowed", 0o4755), ("usr/share/brother/inf/brXrc", 0o666),
                        ("etc/cngplp2/account", 0o1777), ("usr/share/brother/inf", 0o777), ("usr/share/gid", 0o2775)):
            os.chmod(os.path.join(self.pkg, p), mode)
        self.allow = os.path.join(self.d, "allow.tsv")
        with open(self.allow, "w") as f:
            f.write("testpkg\tusr/bin/allowed\t4755\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def mode(self, p):
        return os.stat(os.path.join(self.pkg, p)).st_mode & 0o7777

    def test_strips_and_records(self):
        log = os.path.join(self.d, "chgrp.log")
        script = (f'warning() {{ printf "W: $1\\n" "${{@:2}}"; }}\n'
                  f'chgrp() {{ echo "$@" >> "{log}"; }}\n'
                  f'tidy_modify=()\nsource "{TIDY}"\npkgname=testpkg\ncd "{self.pkg}"\n'
                  '[ "${tidy_modify[*]}" = tidy_luxos_perms ] || exit 9\ntidy_luxos_perms\n')
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                           env=dict(os.environ, LUXDRV_PERMS_ALLOW_TSV=self.allow))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.mode("usr/bin/cnpkmoduleufr2r"), 0o755)
        self.assertEqual(self.mode("usr/bin/sg"), 0o755)
        self.assertEqual(self.mode("usr/bin/ok"), 0o755)
        self.assertEqual(self.mode("usr/bin/allowed"), 0o4755)          # vyjimka z perms-allow.json
        self.assertEqual(self.mode("etc/cngplp2/account"), 0o1775)
        self.assertEqual(self.mode("usr/share/brother/inf"), 0o775)
        self.assertEqual(self.mode("usr/share/brother/inf/brXrc"), 0o664)
        self.assertEqual(self.mode("usr/share/gid"), 0o2775)
        with open(log) as f:
            groups = sorted(f.read().split("\n"))
        self.assertEqual([g for g in groups if g], ["209 -- ./etc/cngplp2/account", "209 -- ./usr/share/brother/inf",
                                                     "209 -- ./usr/share/brother/inf/brXrc"])
        self.assertIn("removed setuid/setgid from /usr/bin/cnpkmoduleufr2r (4755)", r.stdout)


if __name__ == "__main__":
    unittest.main()
