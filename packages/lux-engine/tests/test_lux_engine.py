"""Testy baliku lux-engine (jadro lux: libalpm a nastroje pacmanu z Arch Linuxu, bez prikazu pacman).

    python3 -m unittest discover -s packages/lux-engine/tests -v

Bez rootu, bez site a bez sestaveni pacmanu: package() bezi nad napodobeninou vystupu
"meson install" (stejne cesty jako skutecny balik pacman v Archu).
"""
import configparser
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(PKG, "..", ".."))
ENGINE_BIN = "/usr/lib/lux/alpm/bin"
TOOLS = ("pacman", "pacman-key", "pacman-conf", "pacman-db-upgrade")
OTHER_BIN = ("makepkg", "makepkg-template", "repo-add", "repo-elephant", "repo-remove", "testpkg", "vercmp")
MAN8 = ("makepkg", "pacman", "pacman-conf", "pacman-db-upgrade", "pacman-key", "repo-add", "repo-remove",
        "testpkg", "vercmp")
MAN5 = ("BUILDINFO", "PKGBUILD", "alpm-hooks", "makepkg.conf", "pacman-hooks", "pacman.conf")

# Konec bash doplnovani pacmanu z Archu (completions/pacman; makepkg a pacman-key jsou odkazy na nej)
BASH_COMPLETION = """_pacman() { :; }
_makepkg() { :; }
_pacman_key() { :; }
complete -F _pacman pacman
complete -F _makepkg makepkg
complete -F _pacman_key -o default pacman-key

# ex:et ts=2 sw=2 ft=sh
"""
ZSH_COMPLETION = """#compdef pacman pacman.static=pacman pacman-conf pacman-key makepkg

# copy this file to /usr/share/zsh/site-functions/_pacman
_makepkg() { : }
_pacman_comp "$@"
"""


def pkgbuild(expr):
    r = subprocess.run(["bash", "-c", f'set -e; cd "{PKG}"; source PKGBUILD; {expr}'],
                       capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr)
    return r.stdout


class Pkgbuild(unittest.TestCase):
    def test_syntax(self):
        for f in ("PKGBUILD", "makepkg-lux-engine.conf", "lux-engine-keyrings"):
            r = subprocess.run(["bash", "-n", os.path.join(PKG, f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, (f, r.stderr))

    def test_metadata(self):
        out = pkgbuild('echo "$pkgname|$pkgver|$pkgrel|${provides[*]}|${conflicts[*]}|${replaces[*]}|'
                       '${#source[@]}|${#sha256sums[@]}|${options[*]}|${backup[*]}|$pkgdesc"').strip().split("|")
        name, ver, rel, provides, conflicts, replaces, nsrc, nsum, options, backup, desc = out
        self.assertEqual(name, "lux-engine")
        self.assertEqual(provides.split(), [f"pacman={ver}", "libalpm.so", f"luxos-pacman={ver}"])
        self.assertEqual(conflicts.split(), ["pacman", "luxos-pacman"])
        self.assertEqual(replaces.split(), ["pacman", "luxos-pacman"])
        self.assertEqual(nsrc, nsum)
        self.assertIn("!debug", options)
        self.assertEqual(backup.split(), ["etc/pacman.conf", "etc/makepkg.conf", "etc/makepkg.conf.d/fortran.conf",
                                          "etc/makepkg.conf.d/rust.conf"])
        self.assertNotIn("pacman for", desc)
        # verze odpovida tagu Archu v hlavicce a patch level commitu
        self.assertRegex(ver, r"^\d+\.\d+\.\d+(\.r\d+\.g[0-9a-f]{7})?$")
        self.assertRegex(rel, r"^\d+(\.\d+)?$")
        commit = pkgbuild('echo "$_git_patch_level_commit"').strip()
        if ".g" in ver:
            self.assertTrue(commit.startswith(ver.rsplit(".g", 1)[1]))
        with open(os.path.join(PKG, "PKGBUILD")) as f:
            self.assertIn(f"tag {ver}-{rel.split('.')[0]}", f.read())

    def test_local_sources_match_checksums(self):
        """Soubory prevzate z Archu jsou beze zmeny (stejne soucty jako v PKGBUILDu Archu)."""
        pairs = pkgbuild('for i in "${!source[@]}"; do echo "${source[i]}|${sha256sums[i]}"; done')
        n = 0
        for line in pairs.splitlines():
            src, s = line.split("|")
            if "://" in src:
                continue
            with open(os.path.join(PKG, src), "rb") as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), s, src)
            n += 1
        self.assertEqual(n, 6)

    def test_pgp_keys_match_validpgpkeys(self):
        fprs = pkgbuild('printf "%s\\n" "${validpgpkeys[@]}"').split()
        self.assertEqual(sorted(f + ".asc" for f in fprs), sorted(os.listdir(os.path.join(PKG, "keys", "pgp"))))

    def test_pacman_conf_is_luxos_installer_conf(self):
        """Stejny obsah jako konfigurace instalatoru: nahrazeni baliku nevytvori .pacnew."""
        with open(os.path.join(PKG, "pacman.conf"), "rb") as a, \
                open(os.path.join(ROOT, "packages", "luxos-installer", "files", "pacman.conf"), "rb") as b:
            self.assertEqual(a.read(), b.read())


class Package(unittest.TestCase):
    """package() nad napodobeninou vystupu meson install."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lux-engine-test-")
        src, pkgdir = os.path.join(cls.tmp, "src"), os.path.join(cls.tmp, "pkg")
        os.makedirs(os.path.join(src, "pacman"))
        for f in ("makepkg.conf", "alpm.sysusers", "fortran.conf", "rust.conf"):
            shutil.copy(os.path.join(PKG, f), src)
        fx = os.path.join(cls.tmp, "fixture")
        os.makedirs(fx)
        with open(os.path.join(fx, "bash"), "w") as f:
            f.write(BASH_COMPLETION)
        with open(os.path.join(fx, "zsh"), "w") as f:
            f.write(ZSH_COMPLETION)
        meson = f"""
meson() {{
    [[ $1 == install ]] || return 1
    local d=$DESTDIR f
    mkdir -p "$d/usr/bin" "$d/etc/makepkg.conf.d" "$d/usr/share/man/man5" "$d/usr/share/man/man8" \\
        "$d/usr/share/bash-completion/completions" "$d/usr/share/zsh/site-functions" "$d/usr/lib"
    for f in {' '.join(TOOLS + OTHER_BIN)}; do printf '#!/bin/sh\\n' >"$d/usr/bin/$f"; chmod 755 "$d/usr/bin/$f"; done
    for f in {' '.join(MAN8)}; do : >"$d/usr/share/man/man8/$f.8"; done
    for f in {' '.join(MAN5)}; do : >"$d/usr/share/man/man5/$f.5"; done
    cp "{fx}/bash" "$d/usr/share/bash-completion/completions/pacman"
    ln -s pacman "$d/usr/share/bash-completion/completions/makepkg"
    ln -s pacman "$d/usr/share/bash-completion/completions/pacman-key"
    cp "{fx}/zsh" "$d/usr/share/zsh/site-functions/_pacman"
    : >"$d/usr/lib/libalpm.so.16"
}}
error() {{ echo "ERROR: $*" >&2; }}
"""
        script = (f'set -e; source "{PKG}/PKGBUILD"; {meson}\n'
                  f'srcdir="{src}" pkgdir="{pkgdir}" startdir="{PKG}"; cd "$srcdir"; package')
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        cls.result = r
        cls.pkgdir = pkgdir

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.pkgdir, *parts)

    def test_package_succeeds(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_no_pacman_command_in_path_dirs(self):
        for d in ("usr/bin", "usr/sbin", "usr/local/bin"):
            if os.path.isdir(self.p(d)):
                self.assertEqual([f for f in os.listdir(self.p(d)) if "pacman" in f], [], d)
        for f in OTHER_BIN:
            self.assertTrue(os.access(self.p("usr/bin", f), os.X_OK), f)

    def test_engine_tools_moved(self):
        for t in TOOLS:
            self.assertTrue(os.access(self.p(ENGINE_BIN.lstrip("/"), t), os.X_OK), t)
        # odkaz pro volajici z LuxOS 0.9
        link = self.p("usr/lib/lux/alpm/pacman")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), "bin/pacman")
        self.assertTrue(os.path.exists(link))

    def test_no_pacman_manuals(self):
        for m in ("man8/pacman.8", "man8/pacman-key.8", "man8/pacman-conf.8", "man8/pacman-db-upgrade.8",
                  "man5/pacman-hooks.5"):
            self.assertFalse(os.path.lexists(self.p("usr/share/man", m)), m)
        for m in ("man8/makepkg.8", "man8/vercmp.8", "man5/PKGBUILD.5", "man5/alpm-hooks.5", "man5/pacman.conf.5"):
            self.assertTrue(os.path.exists(self.p("usr/share/man", m)), m)

    def test_completions_only_for_makepkg(self):
        bc = self.p("usr/share/bash-completion/completions")
        self.assertEqual(sorted(os.listdir(bc)), ["makepkg"])
        self.assertFalse(os.path.islink(os.path.join(bc, "makepkg")))
        with open(os.path.join(bc, "makepkg")) as f:
            text = f.read()
        completes = [ln for ln in text.splitlines() if ln.startswith("complete ")]
        self.assertEqual(completes, ["complete -F _makepkg makepkg"])
        # bash doplnovani pro makepkg funguje (soubor jde nacist, registruje jen makepkg)
        r = subprocess.run(["bash", "-c", f'source "{bc}/makepkg"; complete -p'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), "complete -F _makepkg makepkg".split())
        zc = self.p("usr/share/zsh/site-functions")
        self.assertEqual(sorted(os.listdir(zc)), ["_makepkg"])
        with open(os.path.join(zc, "_makepkg")) as f:
            self.assertEqual(f.readline().strip(), "#compdef makepkg")

    def test_makepkg_dropin_installed(self):
        self.assertTrue(os.path.isfile(self.p("etc/makepkg.conf.d/lux-engine.conf")))
        self.assertFalse(os.path.exists(self.p("etc/makepkg.conf.d/luxos-pacman.conf")))

    def test_systemd_dropins(self):
        for unit in ("archlinux-keyring-wkd-sync", "paccache", "pacman-filesdb-refresh"):
            path = self.p("usr/lib/systemd/system", f"{unit}.service.d", "lux-engine.conf")
            cp = configparser.ConfigParser(strict=False, interpolation=None)
            cp.optionxform = str
            with open(path) as f:
                text = f.read()
            self.assertIn("Environment=PATH=/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin\n", text)
            self.assertIn("[Service]", text)
            if unit == "pacman-filesdb-refresh":
                # ExecStart z pacman-contrib je /usr/bin/pacman: nejdrive vynulovat, pak nova cesta
                lines = [ln for ln in text.splitlines() if ln.startswith("ExecStart=")]
                self.assertEqual(lines, ["ExecStart=", "ExecStart=/usr/lib/lux/alpm/bin/pacman -Fy --noprogressbar"])
        # zadna globalni zmena PATH (system.conf.d by se dostala i do relaci uzivatelu pres lightdm)
        self.assertFalse(os.path.exists(self.p("usr/lib/systemd/system.conf.d")))

    def test_keyring_hook_installed(self):
        hook = self.p("usr/share/libalpm/hooks/lux-engine-keyrings.hook")
        with open(hook) as f:
            text = f.read()
        for line in ("Type = Path", "Target = usr/share/pacman/keyrings/*.gpg", "When = PostTransaction",
                     "Exec = /usr/share/libalpm/scripts/lux-engine-keyrings", "NeedsTargets",
                     "Operation = Install", "Operation = Upgrade"):
            self.assertIn(line + "\n", text)
        self.assertTrue(os.access(self.p("usr/share/libalpm/scripts/lux-engine-keyrings"), os.X_OK))


class MakepkgDropin(unittest.TestCase):
    CONF = os.path.join(PKG, "makepkg-lux-engine.conf")

    def source(self, pre, show):
        r = subprocess.run(["bash", "-c", f'{pre}; source "{self.CONF}"; source "{self.CONF}"; {show}'],
                           capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_pacman_and_path(self):
        self.assertEqual(self.source("unset PACMAN", 'echo "$PACMAN"'), ENGINE_BIN + "/pacman")
        self.assertEqual(self.source("PACMAN=powerpill", 'echo "$PACMAN"'), "powerpill")
        # pacman-conf (zamek databaze v makepkg) jmenem; PATH bez duplicit i pri dvojim nacteni
        self.assertEqual(self.source(":", 'echo "$PATH"'), ENGINE_BIN + ":/usr/bin:/bin")
        self.assertEqual(self.source(":", "bash -c 'echo $PATH'"), ENGINE_BIN + ":/usr/bin:/bin")  # exportovane

    def test_pacman_auth_passes_engine_path_through_sudo(self):
        if not shutil.which("sudo"):
            self.skipTest("sudo neni k dispozici")
        out = self.source("unset PACMAN_AUTH", 'printf "%s\\n" "${PACMAN_AUTH[@]}"').splitlines()
        self.assertEqual(out, ["sudo", "-k", "/usr/bin/env",
                               "PATH=/usr/lib/lux/alpm/bin:/usr/local/sbin:/usr/local/bin:/usr/bin"])
        out = self.source("PACMAN_AUTH=(doas)", 'printf "%s\\n" "${PACMAN_AUTH[@]}"')
        self.assertEqual(out, "doas")

    def test_nounset_safe(self):
        self.source("set -u; unset PACMAN PACMAN_AUTH", "echo ok")


class KeyringScript(unittest.TestCase):
    """lux-engine-keyrings: pacman-key --populate pro klicenky z cilu hooku."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lux-engine-keys-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.log = os.path.join(self.tmp, "log")
        self.gpg = os.path.join(self.tmp, "gnupg")
        os.makedirs(self.gpg)
        with open(os.path.join(self.bin, "pacman-key"), "w") as f:
            f.write('#!/bin/bash\necho "pacman-key $*" >>"$KEYS_LOG"\n'
                    '[[ $1 == -l ]] && exit "${KEYS_LIST_RC:-0}"\nexit 0\n')
        with open(os.path.join(self.bin, "pacman-conf"), "w") as f:
            f.write(f'#!/bin/bash\necho "{self.gpg}/"\n')
        for n in ("pacman-key", "pacman-conf"):
            os.chmod(os.path.join(self.bin, n), 0o755)
        with open(os.path.join(PKG, "lux-engine-keyrings")) as f:
            src = f.read()
        self.assertIn("export PATH=/usr/lib/lux/alpm/bin:", src)
        self.script = os.path.join(self.tmp, "lux-engine-keyrings")
        with open(self.script, "w") as f:
            f.write(src.replace("export PATH=/usr/lib/lux/alpm/bin:", f"export PATH={self.bin}:"))
        os.chmod(self.script, 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, stdin, env=None):
        e = {"PATH": "/usr/bin:/bin", "KEYS_LOG": self.log}
        e.update(env or {})
        r = subprocess.run([self.script], input=stdin, capture_output=True, text=True, env=e)
        try:
            with open(self.log) as f:
                calls = f.read().splitlines()
        except OSError:
            calls = []
        return r.returncode, calls

    def test_populates_triggered_keyrings(self):
        rc, calls = self.run_script("usr/share/pacman/keyrings/archlinux.gpg\nusr/share/pacman/keyrings/luxos.gpg\n")
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["pacman-key -l", "pacman-key --populate archlinux luxos"])

    def test_uninitialized_keyring_is_left_alone(self):
        rc, calls = self.run_script("usr/share/pacman/keyrings/archlinux.gpg\n", env={"KEYS_LIST_RC": "1"})
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["pacman-key -l"])

    def test_no_targets(self):
        rc, calls = self.run_script("")
        self.assertEqual((rc, calls), (0, []))
        rc, calls = self.run_script("usr/share/pacman/keyrings/.gpg\nusr/share/pacman/keyrings/x-trusted\n")
        self.assertEqual((rc, calls), (0, []))

    def test_removes_lock_never(self):
        conf = os.path.join(self.gpg, "gpg.conf")
        with open(conf, "w") as f:
            f.write("no-greeting\nlock-never\nkeyserver-options timeout=10\n")
        rc, _calls = self.run_script("usr/share/pacman/keyrings/archlinux.gpg\n")
        self.assertEqual(rc, 0)
        with open(conf) as f:
            self.assertEqual(f.read(), "no-greeting\nkeyserver-options timeout=10\n")


if __name__ == "__main__":
    unittest.main()
