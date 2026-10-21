"""Testy kompatibilni vrstvy /usr/bin/pacman (pacman-shim) a baliku luxos-pacman.

    python3 -m unittest discover -s packages/luxos-pacman/tests -v

Bez rootu a bez site: skutecny pacman je zastupny skript, ktery zapise sve argumenty; terminal
je skutecny pseudoterminal (pty), predci procesu jsou skutecne procesy (makepkg, pacstrap...).
"""
import hashlib
import os
import pty
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(PKG, "..", ".."))
SHIM = os.path.join(PKG, "pacman-shim")
I18N = os.path.join(ROOT, "packages", "luxos-i18n", "files")

REAL_STUB = """#!/bin/bash
printf '%s\\n' "$#" "$@" >>"$SHIM_LOG"
exit "${REAL_RC:-0}"
"""

HAVE_UNSHARE = bool(shutil.which("unshare")) and subprocess.run(
    ["unshare", "-r", "true"], capture_output=True).returncode == 0


class Shim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pacman-shim-test-")
        self.log = os.path.join(self.tmp, "real.log")
        self.real = os.path.join(self.tmp, "alpm", "pacman")
        self.allow = os.path.join(self.tmp, "allow-pacman")
        os.makedirs(os.path.dirname(self.real))
        self.write(self.real, REAL_STUB, 0o755)
        # i18n.sh z repozitare, preklady z packages/luxos-i18n/files
        with open(os.path.join(I18N, "i18n.sh")) as f:
            i18n = f.read().replace("/usr/share/luxos/i18n", I18N)
        self.i18n = os.path.join(self.tmp, "i18n.sh")
        self.write(self.i18n, i18n)
        with open(SHIM) as f:
            src = f.read()
        for a, b in (("REAL=/usr/lib/lux/alpm/pacman", "REAL=" + self.real),
                     ("ALLOW_FILE=/etc/lux/allow-pacman", "ALLOW_FILE=" + self.allow),
                     ("/usr/lib/luxos/i18n.sh", self.i18n)):
            self.assertIn(a, src)
            src = src.replace(a, b)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.shim = os.path.join(self.bin, "pacman")
        self.write(self.shim, src, 0o755)
        self.env = {"PATH": self.bin + ":/usr/bin:/bin", "SHIM_LOG": self.log, "LANG": "C.UTF-8",
                    "HOME": self.tmp}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def write(path, text, mode=0o644):
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def real_calls(self):
        """Seznam volani skutecneho pacmanu, kazde jako seznam argumentu."""
        try:
            with open(self.log) as f:
                lines = f.read().split("\n")
        except OSError:
            return []
        calls, i = [], 0
        while i < len(lines) and lines[i] != "":
            n = int(lines[i])
            calls.append(lines[i + 1:i + 1 + n])
            i += 1 + n
        return calls

    def run_shim(self, args, tty_in=True, tty_out=True, env=None, cmd=None):
        """Spusti vrstvu (nebo cmd) se stdin/stdout na pty nebo rourach. -> (rc, stdout, stderr)"""
        e = dict(self.env, **(env or {}))
        master, slave = pty.openpty()
        try:
            stdin = slave if tty_in else subprocess.DEVNULL
            stdout = slave if tty_out else subprocess.PIPE
            p = subprocess.Popen(cmd or [self.shim] + list(args), stdin=stdin, stdout=stdout,
                                 stderr=subprocess.PIPE, env=e)
            out, err = p.communicate(timeout=30)
        finally:
            os.close(slave)
            os.close(master)
        return p.returncode, (out or b"").decode(), err.decode()

    # ---- bez terminalu: vzdy skutecny pacman -----------------------------------------------
    def test_non_interactive_passes_through_exact_args(self):
        args = ["-S", "--needed", "--noconfirm", "a b", "", "x*", "--", "-weird"]
        for tty_in, tty_out in ((False, False), (True, False), (False, True)):
            os.path.exists(self.log) and os.unlink(self.log)
            rc, _o, err = self.run_shim(args, tty_in, tty_out)
            self.assertEqual(rc, 0, err)
            self.assertEqual(self.real_calls(), [args])
            self.assertNotIn("lux", err)

    def test_exit_code_and_output_of_real_pacman(self):
        rc, _o, _e = self.run_shim(["-Q", "nope"], tty_out=False, env={"REAL_RC": "1"})
        self.assertEqual(rc, 1)
        rc, _o, _e = self.run_shim(["-Q"], tty_in=False, env={"REAL_RC": "42"})
        self.assertEqual(rc, 42)

    def test_pipe_query(self):
        out = subprocess.run(["bash", "-c", f'{self.shim} -Qq | cat'], env=self.env, capture_output=True,
                             text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(self.real_calls(), [["-Qq"]])

    # ---- clovek v terminalu: prikaz lux -------------------------------------------------------
    def test_interactive_is_redirected_to_lux(self):
        rc, _o, err = self.run_shim(["-Syu"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.real_calls(), [])
        self.assertIn("LuxOS uses lux to manage software.", err)
        self.assertIn("pacman -Syu  →  lux update", err)
        self.assertIn("lux --help", err)
        self.assertIn("LUX_ALLOW_PACMAN=1 pacman -Syu", err)
        self.assertNotIn("\x1b[", err)                      # stderr neni terminal -> bez barev

    def test_mapping(self):
        cases = {
            ("-S", "firefox"): ["lux install firefox"],
            ("-Sy", "firefox", "vlc"): ["lux install firefox vlc"],
            ("-S", "--needed", "--noconfirm", "git"): ["lux install git"],
            ("--sync", "--refresh", "git"): ["lux install git"],
            ("-Syu",): ["lux update"],
            ("-Syyu",): ["lux update"],
            ("-Su",): ["lux update"],
            ("-Sy",): ["lux update"],
            ("--sync", "--sysupgrade", "--refresh"): ["lux update"],
            ("-Syu", "steam"): ["lux update", "lux install steam"],
            ("-Ss", "video", "editor"): ["lux search video editor"],
            ("-Si", "htop"): ["lux info htop"],
            ("-Sc",): ["lux clean"],
            ("-Scc",): ["lux clean"],
            ("-R", "htop"): ["lux remove htop"],
            ("-Rns", "htop", "vlc"): ["lux remove htop vlc"],
            ("--remove", "--recursive", "htop"): ["lux remove htop"],
            ("-U", "./x-1-1-x86_64.pkg.tar.zst"): ["lux install ./x-1-1-x86_64.pkg.tar.zst"],
            ("-Q",): ["lux list"],
            ("-Qi", "bash"): ["lux info bash"],
            ("-Qii", "bash"): ["lux info bash"],
            ("-Q", "bash"): ["lux info bash"],
            ("-Ql", "bash"): ["lux files bash"],
            ("-Qo", "/usr/bin/ls"): ["lux owns /usr/bin/ls"],
            ("-Qs", "fire"): ["lux list fire"],
            ("-Qu",): ["lux list --upgradable"],
            ("-Qdt",): ["lux list --orphans", "lux autoremove"],
            ("-Qdtq",): ["lux list --orphans", "lux autoremove"],
            ("-Qm",): ["lux list --aur"],
            ("-Qe",): ["lux list --explicit"],
            ("-Qk",): ["lux doctor"],
            ("-V",): ["lux --version"],
            ("--version",): ["lux --version"],
            # volby s hodnotou nejsou cile
            ("-S", "--config", "/tmp/p.conf", "htop"): ["lux install htop"],
            ("-r", "/mnt", "-S", "htop"): ["lux install htop"],
            ("-S", "-b", "/tmp/db", "htop"): ["lux install htop"],
            ("-S", "--overwrite", "*", "htop"): ["lux install htop"],
            ("-S", "--", "-odd"): ["lux install -odd"],
            # bez odpovidajiciho prikazu lux: jen obecna napoveda
            (): [], ("-h",): [], ("-Fy",): [], ("-D", "--asdeps", "x"): [], ("-T", "x"): [],
            ("-Sl",): [], ("-Sg",): [], ("-Sw", "x"): [], ("-R",): [], ("-Si",): [],
        }
        for args, want in cases.items():
            os.path.exists(self.log) and os.unlink(self.log)
            rc, _o, err = self.run_shim(args)
            self.assertEqual(rc, 1, (args, err))
            got = re.findall(r"→  (.*)", err)
            self.assertEqual(got, want, (args, err))
            self.assertEqual(self.real_calls(), [], args)
            self.assertIn("LuxOS uses lux", err)

    def test_targets_are_shell_quoted(self):
        rc, _o, err = self.run_shim(["-S", "a b", "c;rm -rf ~"])
        self.assertEqual(rc, 1)
        self.assertIn(r"lux install a\ b c\;rm\ -rf\ ~", err)

    def test_colors_only_on_terminal_and_without_no_color(self):
        # stderr na pty
        master, slave = pty.openpty()
        try:
            p = subprocess.run([self.shim, "-Syu"], stdin=slave, stdout=slave, stderr=slave, env=self.env,
                               timeout=30)
            os.close(slave)
            data = b""
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(master)
        self.assertEqual(p.returncode, 1)
        self.assertIn(b"\x1b[38;2;167;123;255m", data)
        self.assertIn("lux update".encode(), data)

    def test_czech(self):
        rc, _o, err = self.run_shim(["-S", "htop"], env={"LANG": "cs_CZ.UTF-8"})
        self.assertEqual(rc, 1)
        self.assertIn("LuxOS spravuje software pomocí lux.", err)
        self.assertIn("lux install htop", err)
        self.assertIn("Všechny příkazy lux", err)

    def test_all_languages_translate_the_shim(self):
        texts = ["LuxOS uses lux to manage software.", "All lux commands: %s",
                 "Experts can still run pacman directly: %s",
                 "The package manager core is missing (%s). Repair it with: %s"]
        for tsv in sorted(os.listdir(I18N)):
            if not tsv.endswith(".tsv"):
                continue
            with open(os.path.join(I18N, tsv)) as f:
                rows = [line.rstrip("\n").split("\t") for line in f if "\t" in line]
            keys = [r[0] for r in rows]
            for t in texts:
                self.assertEqual(keys.count(t), 1, (tsv, t))
                tr = [r[1] for r in rows if r[0] == t][0]
                self.assertEqual(tr.count("%s"), t.count("%s"), (tsv, t))

    # ---- uniky pro pokrocile -------------------------------------------------------------------
    def test_lux_allow_pacman(self):
        rc, _o, err = self.run_shim(["-Syu"], env={"LUX_ALLOW_PACMAN": "1"})
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.real_calls(), [["-Syu"]])
        for v in ("0", "", "yes"):
            rc, _o, _e = self.run_shim(["-Syu"], env={"LUX_ALLOW_PACMAN": v})
            self.assertEqual(rc, 1, v)
        self.assertEqual(len(self.real_calls()), 1)

    def test_allow_file(self):
        open(self.allow, "w").close()
        rc, _o, err = self.run_shim(["-Rns", "htop"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.real_calls(), [["-Rns", "htop"]])

    @unittest.skipUnless(HAVE_UNSHARE, "unshare -r neni k dispozici")
    def test_sudo_hint(self):
        """Pod sudo (root + SUDO_USER) radi sudo LUX_ALLOW_PACMAN=1 (sudo promennou z prostredi zahodi)."""
        rc, _o, err = self.run_shim([], cmd=["unshare", "-r", self.shim, "-Syu"], env={"SUDO_USER": "tester"})
        self.assertEqual(rc, 1, err)
        self.assertIn("sudo pacman -Syu  →  lux update", err)
        self.assertIn("sudo LUX_ALLOW_PACMAN=1 pacman -Syu", err)

    def test_missing_real_binary(self):
        os.unlink(self.real)
        rc, _o, err = self.run_shim(["-Syu"])
        self.assertEqual(rc, 127)
        self.assertIn("lux reinstall luxos-pacman", err)
        rc, _o, _e = self.run_shim(["-Q"], tty_out=False)
        self.assertNotEqual(rc, 0)

    # ---- nastroje, ktere pacman potrebuji (makepkg, pacstrap...) --------------------------------
    def tool(self, name, body):
        d = os.path.join(self.tmp, "tools")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        self.write(p, "#!/bin/bash\n" + body + "\n", 0o755)
        return p

    def test_called_by_makepkg_directly(self):
        mk = self.tool("makepkg", f'"{self.shim}" -U --noconfirm "$@"; exit $?')
        rc, _o, err = self.run_shim([], cmd=[mk, "x.pkg.tar.zst"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.real_calls(), [["-U", "--noconfirm", "x.pkg.tar.zst"]])

    def test_called_by_makepkg_through_sudo_like_layers(self):
        """makepkg -> sudo -> (sudo monitor) -> pacman: predek se hleda i o nekolik urovni vys."""
        mid = self.tool("sudo", '"$@"; exit $?')
        mk = self.tool("makepkg", f'"{mid}" python3 -c "import subprocess,sys; '
                                   f'sys.exit(subprocess.call([\'{self.shim}\', \'-S\', \'--asdeps\', \'cmake\']))"'
                                   '; exit $?')
        rc, _o, err = self.run_shim([], cmd=[mk])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.real_calls(), [["-S", "--asdeps", "cmake"]])

    def test_called_by_script_run_through_interpreter(self):
        mk = self.tool("makepkg", f'"{self.shim}" -S --asdeps git; exit $?')
        rc, _o, err = self.run_shim([], cmd=["bash", mk])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.real_calls(), [["-S", "--asdeps", "git"]])

    def test_aur_helpers_and_lux(self):
        for name in ("yay", "paru", "lux", "pacstrap"):
            os.path.exists(self.log) and os.unlink(self.log)
            t = self.tool(name, f'"{self.shim}" -S x; exit $?')
            rc, _o, err = self.run_shim([], cmd=[t])
            self.assertEqual(rc, 0, (name, err))
            self.assertEqual(self.real_calls(), [["-S", "x"]], name)

    def test_other_parents_are_not_trusted(self):
        for name in ("makepkg2", "mymakepkg", "pacstrap.sh", "luxe", "bash"):
            t = self.tool(name, f'"{self.shim}" -S x; exit $?')
            rc, _o, err = self.run_shim([], cmd=[t])
            self.assertEqual(rc, 1, (name, err))
        # argument "makepkg" u neinterpretu (napr. editor) nic neznamena
        t = self.tool("editor", f'"{self.shim}" -S x; exit $?')
        rc, _o, _e = self.run_shim([], cmd=[t, "makepkg"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.real_calls(), [])

    @unittest.skipUnless(HAVE_UNSHARE, "unshare -r neni k dispozici")
    def test_pacstrap_in_new_pid_namespace(self):
        """pacstrap spousti pacman pres unshare --fork --pid: getppid() je 0, predek se najde v /proc."""
        ps = self.tool("pacstrap", f'unshare -r --fork --pid "{self.shim}" -r /mnt -Sy base; exit $?')
        rc, _o, err = self.run_shim([], cmd=[ps])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.real_calls(), [["-r", "/mnt", "-Sy", "base"]])
        # stejne bez pacstrapu -> clovek, prikaz lux
        rc, _o, err = self.run_shim([], cmd=["unshare", "-r", "--fork", "--pid", self.shim, "-Sy", "base"])
        self.assertEqual(rc, 1, err)

    def test_speed_of_pass_through(self):
        """Skripty volaji pacman casto: bez terminalu zadne hledani predku ani preklady."""
        with open(SHIM) as f:
            src = f.read()
        fast = src.index("if [[ ${LUX_ALLOW_PACMAN-} == 1 || ! -t 0 || ! -t 1")
        self.assertLess(fast, src.index("i18n.sh ]] && ."))


class Package(unittest.TestCase):
    def pkgbuild(self, expr):
        r = subprocess.run(["bash", "-c", f'set -e; cd "{PKG}"; source PKGBUILD; {expr}'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_syntax(self):
        for f in ("PKGBUILD", "pacman-shim", "makepkg-luxos.conf"):
            r = subprocess.run(["bash", "-n", os.path.join(PKG, f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, (f, r.stderr))

    def test_pkgbuild_metadata(self):
        out = self.pkgbuild('echo "$pkgname|$pkgver|$pkgrel|${provides[*]}|${conflicts[*]}|${replaces[*]}|'
                            '${#source[@]}|${#sha256sums[@]}|${options[*]}|${backup[*]}"').strip().split("|")
        name, ver, rel, provides, conflicts, replaces, nsrc, nsum, options, backup = out
        self.assertEqual(name, "luxos-pacman")
        self.assertEqual(provides.split(), [f"pacman={ver}", "libalpm.so"])
        self.assertEqual(conflicts, "pacman")
        self.assertEqual(replaces, "pacman")
        self.assertEqual(nsrc, nsum)
        self.assertIn("!debug", options)
        self.assertEqual(backup.split(), ["etc/pacman.conf", "etc/makepkg.conf", "etc/makepkg.conf.d/fortran.conf",
                                          "etc/makepkg.conf.d/rust.conf"])
        # verze odpovida tagu Archu v hlavicce a patch level commitu
        self.assertRegex(ver, r"^\d+\.\d+\.\d+(\.r\d+\.g[0-9a-f]{7})?$")
        commit = self.pkgbuild('echo "$_git_patch_level_commit"').strip()
        if ".g" in ver:
            self.assertTrue(commit.startswith(ver.rsplit(".g", 1)[1]))
        with open(os.path.join(PKG, "PKGBUILD")) as f:
            self.assertIn(f"tag {ver}-{rel.split('.')[0]}", f.read())

    def test_local_sources_match_checksums(self):
        """Soubory prevzate z Archu jsou beze zmeny (stejne soucty jako v PKGBUILDu Archu)."""
        pairs = self.pkgbuild('for i in "${!source[@]}"; do echo "${source[i]}|${sha256sums[i]}"; done')
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
        fprs = self.pkgbuild('printf "%s\\n" "${validpgpkeys[@]}"').split()
        self.assertEqual(sorted(f + ".asc" for f in fprs), sorted(os.listdir(os.path.join(PKG, "keys", "pgp"))))

    def test_pacman_conf_is_luxos_installer_conf(self):
        """Stejny obsah jako konfigurace instalatoru: nahrazeni baliku pacman nevytvori .pacnew."""
        with open(os.path.join(PKG, "pacman.conf"), "rb") as a, \
                open(os.path.join(ROOT, "packages", "luxos-installer", "files", "pacman.conf"), "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_makepkg_dropin(self):
        conf = os.path.join(PKG, "makepkg-luxos.conf")
        r = subprocess.run(["bash", "-c", f'unset PACMAN; source "{conf}"; echo "$PACMAN"'],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "/usr/lib/lux/alpm/pacman")
        r = subprocess.run(["bash", "-c", f'PACMAN=powerpill; source "{conf}"; echo "$PACMAN"'],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "powerpill")

    def test_package_installs_shim_and_real_binary(self):
        with open(os.path.join(PKG, "PKGBUILD")) as f:
            text = f.read()
        self.assertIn('mv "$pkgdir/usr/bin/pacman" "$pkgdir/usr/lib/lux/alpm/pacman"', text)
        self.assertIn('install -m755 "$startdir/pacman-shim" "$pkgdir/usr/bin/pacman"', text)
        with open(SHIM) as f:
            self.assertIn("REAL=/usr/lib/lux/alpm/pacman\n", f.read())


if __name__ == "__main__":
    unittest.main()
