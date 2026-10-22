"""Testy napovedy pro zvyk z Arch Linuxu (/usr/lib/lux/pacman-hint) a obsluhy "command not found"
v shellu LuxOS (luxos-shell: bashrc, zshrc). Prikaz pacman v LuxOS neni; kdo ho napise, dostane
odpovidajici prikaz lux.

    python3 -m unittest discover -s packages/lux/tests -v

Bez rootu a bez site; skutecny terminal je pseudoterminal (pty).
"""
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
HINT = os.path.join(PKG, "pacman-hint")
LUX = os.path.join(PKG, "lux")
I18N = os.path.join(ROOT, "packages", "luxos-i18n", "files")
SHELL = os.path.join(ROOT, "packages", "luxos-shell", "files")
HAVE_ZSH = bool(shutil.which("zsh"))


class Hint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pacman-hint-test-")
        # i18n.sh z repozitare, preklady z packages/luxos-i18n/files
        with open(os.path.join(I18N, "i18n.sh")) as f:
            i18n = f.read().replace("/usr/share/luxos/i18n", I18N)
        self.i18n = os.path.join(self.tmp, "i18n.sh")
        self.write(self.i18n, i18n)
        with open(HINT) as f:
            src = f.read()
        self.assertIn("/usr/lib/luxos/i18n.sh", src)
        self.hint = os.path.join(self.tmp, "pacman-hint")
        self.write(self.hint, src.replace("/usr/lib/luxos/i18n.sh", self.i18n), 0o755)
        self.env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": self.tmp}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def write(path, text, mode=0o644):
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def run_hint(self, args, env=None, tty=False):
        e = dict(self.env, **(env or {}))
        if not tty:
            p = subprocess.run([self.hint] + list(args), env=e, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=30)
            return p.returncode, p.stdout, p.stderr
        master, slave = pty.openpty()
        try:
            p = subprocess.run([self.hint] + list(args), stdin=slave, stdout=slave, stderr=slave, env=e,
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
        return p.returncode, "", data.decode()

    def test_hint_text(self):
        rc, out, err = self.run_hint(["-Syu"])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("LuxOS uses lux to manage software.", err)
        self.assertIn("pacman -Syu  →  lux update", err)
        self.assertIn("lux --help", err)
        self.assertNotIn("LUX_ALLOW_PACMAN", err)           # pacman se lidem nenabizi
        self.assertNotIn("\x1b[", err)                      # stderr neni terminal -> bez barev

    def test_never_runs_anything(self):
        """Napoveda nic nespousti: ani s promennymi byvale kompatibilni vrstvy."""
        with open(HINT) as f:
            src = f.read()
        for word in ("exec ", "/usr/lib/lux/alpm", "LUX_ALLOW_PACMAN", "sudo"):
            self.assertNotIn(word, src)
        rc, _o, err = self.run_hint(["-S", "x"], env={"LUX_ALLOW_PACMAN": "1", "LUX_PACMAN_HINT": "0"})
        self.assertEqual(rc, 1)
        self.assertIn("lux install x", err)

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
            rc, _o, err = self.run_hint(args)
            self.assertEqual(rc, 1, (args, err))
            self.assertEqual(re.findall(r"→  (.*)", err), want, (args, err))
            self.assertIn("LuxOS uses lux", err)

    def test_targets_are_shell_quoted(self):
        rc, _o, err = self.run_hint(["-S", "a b", "c;rm -rf ~"])
        self.assertEqual(rc, 1)
        self.assertIn(r"lux install a\ b c\;rm\ -rf\ ~", err)

    def test_colors_only_on_terminal_and_without_no_color(self):
        rc, _o, data = self.run_hint(["-Syu"], tty=True)
        self.assertEqual(rc, 1)
        self.assertIn("\x1b[38;2;167;123;255m", data)
        self.assertIn("lux update", data)
        rc, _o, data = self.run_hint(["-Syu"], tty=True, env={"NO_COLOR": "1"})
        self.assertNotIn("\x1b[", data)

    def test_czech(self):
        rc, _o, err = self.run_hint(["-S", "htop"], env={"LANG": "cs_CZ.UTF-8"})
        self.assertEqual(rc, 1)
        self.assertIn("LuxOS spravuje software pomocí lux.", err)
        self.assertIn("lux install htop", err)
        self.assertIn("Všechny příkazy lux", err)

    def test_all_languages_translate_the_hint(self):
        texts = ["LuxOS uses lux to manage software.", "All lux commands: %s"]
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

    def test_lux_dash_options_show_hint(self):
        """lux -Syu (zvyk z pacmanu) ukaze prikaz lux pres pacman-hint vedle skriptu."""
        p = subprocess.run([LUX, "-Syu"], env=dict(self.env, LUX_HINT=self.hint), capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("pacman -Syu  →  lux update", p.stderr)
        p = subprocess.run([LUX, "-Rns", "x"], env=self.env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        self.assertIn("lux remove x", p.stderr)          # bez LUX_HINT: pacman-hint vedle skriptu


class ShellNotFound(unittest.TestCase):
    """Obsluha "command not found" z bashrc a zshrc (luxos-shell) s napovedou lux."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pacman-cnf-test-")
        self.log = os.path.join(self.tmp, "hint.log")
        # zastupna napoveda: zapise argumenty (skutecnou testuje Hint)
        self.hint = os.path.join(self.tmp, "pacman-hint")
        with open(self.hint, "w") as f:
            f.write('#!/bin/bash\nprintf "%s\\n" "$#" "$@" >>"$HINT_LOG"\necho "HINT $*" >&2\nexit 1\n')
        os.chmod(self.hint, 0o755)
        self.env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": self.tmp, "HINT_LOG": self.log}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rc_block(self, name, marker_start, marker_end):
        """Cast bashrc/zshrc s obsluhou (bez ble.sh, aliasu atd.), cesta k napovede do tmp."""
        with open(os.path.join(SHELL, name)) as f:
            src = f.read()
        block = src[src.index(marker_start):src.index(marker_end)]
        self.assertIn("/usr/lib/lux/pacman-hint", block)
        return block.replace("/usr/lib/lux/pacman-hint", self.hint)

    def calls(self):
        try:
            with open(self.log) as f:
                lines = f.read().split("\n")
        except OSError:
            return []
        out, i = [], 0
        while i < len(lines) and lines[i] != "":
            n = int(lines[i])
            out.append(lines[i + 1:i + 1 + n])
            i += 1 + n
        return out

    def bash(self, script, pre=""):
        block = self.rc_block("bashrc", "# Software spravuje lux", "command -v zoxide")
        p = subprocess.run(["bash", "-c", pre + "\n" + block + "\n" + script], env=self.env,
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout, p.stderr

    def zsh(self, script, pre=""):
        block = self.rc_block("zshrc", "# Software spravuje lux", "command -v zoxide")
        p = subprocess.run(["zsh", "-f", "-c", pre + "\n" + block + "\n" + script], env=self.env,
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout, p.stderr

    def test_bash_pacman(self):
        rc, _o, err = self.bash('pacman -S "a b" htop; echo "rc=$?" >&2')
        self.assertIn("pacman: command not found", err)
        self.assertIn("rc=127", err)
        self.assertEqual(self.calls(), [["-S", "a b", "htop"]])

    def test_bash_other_pacman_tools_get_general_hint(self):
        rc, _o, err = self.bash("pacman-key --init; pacman-conf DBPath")
        self.assertIn("pacman-key: command not found", err)
        self.assertIn("pacman-conf: command not found", err)
        self.assertEqual(self.calls(), [[], []])

    def test_bash_other_commands_unchanged(self):
        rc, _o, err = self.bash('nosuchcmd-xyz; echo "rc=$?" >&2; pacmanx')
        self.assertIn("nosuchcmd-xyz: command not found", err)
        self.assertIn("pacmanx: command not found", err)
        self.assertIn("rc=127", err)
        self.assertEqual(self.calls(), [])

    def test_bash_keeps_existing_handler_and_survives_reload(self):
        pre = 'command_not_found_handle() { echo "OLD $1" >&2; return 127; }'
        block = self.rc_block("bashrc", "# Software spravuje lux", "command -v zoxide")
        # druhe nacteni bashrc nesmi vest k nekonecne rekurzi
        rc, _o, err = self.bash(block + '\nnosuch-a; pacman -Q', pre=pre)
        self.assertIn("OLD nosuch-a", err)
        self.assertEqual(self.calls(), [["-Q"]])

    def test_bash_without_hint_installed(self):
        os.unlink(self.hint)
        rc, _o, err = self.bash('pacman -Syu; echo "rc=$?" >&2')
        self.assertIn("pacman: command not found", err)
        self.assertIn("rc=127", err)

    @unittest.skipUnless(HAVE_ZSH, "zsh neni k dispozici")
    def test_zsh_pacman(self):
        rc, _o, err = self.zsh('pacman -Rns htop; echo "rc=$?" >&2; pacman-key --populate; nosuch-b')
        self.assertIn("zsh: command not found: pacman", err)
        self.assertIn("zsh: command not found: pacman-key", err)
        self.assertIn("zsh: command not found: nosuch-b", err)
        self.assertIn("rc=127", err)
        self.assertEqual(self.calls(), [["-Rns", "htop"], []])

    @unittest.skipUnless(HAVE_ZSH, "zsh neni k dispozici")
    def test_zsh_keeps_existing_handler_and_survives_reload(self):
        pre = 'command_not_found_handler() { print -u2 "OLD $1"; return 127; }'
        block = self.rc_block("zshrc", "# Software spravuje lux", "command -v zoxide")
        rc, _o, err = self.zsh(block + '\nnosuch-c; pacman -Q', pre=pre)
        self.assertIn("OLD nosuch-c", err)
        self.assertEqual(self.calls(), [["-Q"]])


if __name__ == "__main__":
    unittest.main()
