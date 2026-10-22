"""Testy prikazu znamych z Debianu/Ubuntu v baliku luxos-shell: adduser/deluser/addgroup/delgroup,
service, update-grub a napovedy /usr/lib/luxos/command-hint (apt, dnf, ifconfig, ...).

    python3 -m unittest discover -s packages/luxos-shell/tests -v

Bez roota a bez zasahu do systemu: useradd, userdel, groupadd, groupdel, gpasswd, passwd, getent, id,
sudo, pgrep, systemctl a grub-mkconfig jsou atrapy (PATH), ktere jen zapisuji do docasnych souboru
passwd/group a do logu. Skutecny terminal je pseudoterminal (pty).
"""
import os
import pty
import re
import select
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(PKG, "..", ".."))
FILES = os.path.join(PKG, "files")
I18N = os.path.join(ROOT, "packages", "luxos-i18n", "files")
NEW_TR = os.path.join(ROOT, "out", "i18n-shell.tsv")
LANGS = ["en", "cs", "de", "es", "fr", "hu", "it", "nl", "pl", "pt", "sk", "sv", "uk"]

# Atrapy programu: pracuji s $FAKE/passwd a $FAKE/group, vse zapisuji do $FAKE/log
MOCKS = {
    "getent": r'''#!/bin/bash
db=$FAKE/$1
[[ -f $db ]] || exit 2
if (($# == 1)); then cat "$db"; exit 0; fi
grep -m1 "^$2:" "$db" || exit 2
''',
    "id": r'''#!/bin/bash
[[ $1 == -u ]] && { echo "${MOCK_UID:-0}"; exit 0; }
exit 1
''',
    "sudo": r'''#!/bin/bash
echo "sudo $*" >> "$FAKE/log"
''',
    "pgrep": r'''#!/bin/bash
exit "${MOCK_PGREP_RC:-1}"
''',
    "logname": r'''#!/bin/bash
[[ -n ${MOCK_LOGNAME-} ]] && echo "$MOCK_LOGNAME" && exit 0
exit 1
''',
    "useradd": r'''#!/bin/bash
echo "useradd $*" >> "$FAKE/log"
home="" shell=/usr/bin/lsh comment="" g="" G="" U=0 uid=""
while (($#)); do
    case $1 in
        -d) home=$2; shift ;; -s) shell=$2; shift ;; -c) comment=$2; shift ;; -g) g=$2; shift ;;
        -G) G=$2; shift ;; -u) uid=$2; shift ;; -U) U=1 ;; --) shift; name=$1 ;;
        -*) ;; *) name=$1 ;;
    esac
    shift
done
[[ -n $uid ]] || uid=$(( $(cut -d: -f3 "$FAKE/passwd" | sort -n | tail -1) + 1 ))
((uid < 1000)) && uid=1000
if ((U)); then gid=$uid; echo "$name:x:$gid:" >> "$FAKE/group"
else gid=$(grep -m1 -E "^($g):|^[^:]*:x:$g:" "$FAKE/group" | cut -d: -f3); fi
echo "$name:x:$uid:$gid:$comment:${home:-/home/$name}:$shell" >> "$FAKE/passwd"
IFS=, read -ra gs <<< "$G"
for x in "${gs[@]}"; do
    sed -i -E "s/^($x:[^:]*:[^:]*:)(.+)$/\1\2,$name/; s/^($x:[^:]*:[^:]*:)$/\1$name/" "$FAKE/group"
done
exit "${MOCK_USERADD_RC:-0}"
''',
    "userdel": r'''#!/bin/bash
echo "userdel $*" >> "$FAKE/log"
name=${!#}
sed -i "/^$name:/d" "$FAKE/passwd"
sed -i "/^$name:x:[0-9]*:$/d" "$FAKE/group"
[[ $* == *-r* ]] && echo "userdel: $name mail spool (/var/mail/$name) not found" >&2
exit 0
''',
    "groupadd": r'''#!/bin/bash
echo "groupadd $*" >> "$FAKE/log"
name=${!#}
echo "$name:x:2000:" >> "$FAKE/group"
''',
    "groupdel": r'''#!/bin/bash
echo "groupdel $*" >> "$FAKE/log"
name=${!#}
sed -i "/^$name:/d" "$FAKE/group"
''',
    "gpasswd": r'''#!/bin/bash
echo "gpasswd $*" >> "$FAKE/log"
op=$1 user=$2 grp=$3
if [[ $op == -a ]]; then
    sed -i -E "s/^($grp:[^:]*:[^:]*:)(.+)$/\1\2,$user/; s/^($grp:[^:]*:[^:]*:)$/\1$user/" "$FAKE/group"
else
    line=$(grep "^$grp:" "$FAKE/group"); m=${line##*:}
    m=$(tr , '\n' <<< "$m" | grep -vx "$user" | paste -sd,)
    sed -i "s/^\($grp:[^:]*:[^:]*:\).*/\1$m/" "$FAKE/group"
fi
''',
    "passwd": r'''#!/bin/bash
echo "passwd $*" >> "$FAKE/log"
n=0; [[ -f $FAKE/passwd-fails ]] && n=$(<"$FAKE/passwd-fails")
if ((n > 0)); then echo $((n - 1)) > "$FAKE/passwd-fails"; echo "passwd: Authentication token manipulation error" >&2; exit 10; fi
exit 0
''',
    "systemctl": r'''#!/bin/bash
echo "systemctl $*" >> "$FAKE/log"
if [[ $1 == list-units ]]; then
    printf 'cups.service loaded active running CUPS Scheduler\n'
    printf 'sshd.service loaded inactive dead OpenSSH Daemon\n'
    printf 'getty@tty1.service loaded active running Getty on tty1\n'
fi
''',
    "grub-mkconfig": r'''#!/bin/bash
echo "grub-mkconfig $*" >> "$FAKE/log"
''',
}

PASSWD = """root:x:0:0::/root:/usr/bin/lsh
bin:x:1:1::/:/usr/bin/nologin
anna:x:1000:1000:Anna:/home/anna:/usr/bin/lsh
petr:x:1001:1001:Petr:/home/petr:/usr/bin/lsh
"""
GROUP = """root:x:0:root
sys:x:3:anna
wheel:x:998:anna
audio:x:995:anna,petr
video:x:986:anna
users:x:984:
input:x:974:
lp:x:991:
network:x:90:
rfkill:x:977:
anna:x:1000:
petr:x:1001:
docker:x:1500:
team:x:1501:petr
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-shell-test-")
        self.fake = os.path.join(self.tmp, "fake")
        self.mock = os.path.join(self.tmp, "mock")
        self.bin = os.path.join(self.tmp, "bin")
        for d in (self.fake, self.mock, self.bin):
            os.makedirs(d)
        for name, src in MOCKS.items():
            self.write(os.path.join(self.mock, name), src, 0o755)
        # domovske slozky stavajicich uzivatelu v docasnem adresari (dotaz na smazani slozky)
        self.home = os.path.join(self.tmp, "home")
        for u in ("anna", "petr"):
            os.makedirs(os.path.join(self.home, u))
        self.write(os.path.join(self.fake, "passwd"), PASSWD.replace(":/home/", f":{self.home}/"))
        self.write(os.path.join(self.fake, "group"), GROUP)
        self.write(os.path.join(self.fake, "log"), "")
        # i18n.sh a preklady: stavajici tsv + nove retezce z out/i18n-shell.tsv
        self.i18n_dir = os.path.join(self.tmp, "i18n")
        os.makedirs(self.i18n_dir)
        for lang in LANGS[1:]:
            shutil.copy(os.path.join(I18N, lang + ".tsv"), os.path.join(self.i18n_dir, lang + ".tsv"))
        if os.path.exists(NEW_TR):
            with open(NEW_TR) as f:
                rows = [l.rstrip("\n").split("\t") for l in f if l.strip() and not l.startswith("#")]
            for i, lang in enumerate(LANGS[1:], start=1):
                with open(os.path.join(self.i18n_dir, lang + ".tsv"), "a") as f:
                    for r in rows[1:]:
                        f.write(f"{r[0]}\t{r[i]}\n")
        with open(os.path.join(I18N, "i18n.sh")) as f:
            i18n = f.read().replace("/usr/share/luxos/i18n", self.i18n_dir)
        self.i18n = os.path.join(self.tmp, "i18n.sh")
        self.write(self.i18n, i18n)
        for name in ("adduser", "service", "update-grub"):
            self.install(os.path.join(FILES, "bin", name), name)
        for name in ("deluser", "addgroup", "delgroup"):
            os.symlink("adduser", os.path.join(self.bin, name))
        self.install(os.path.join(FILES, "command-hint"), "command-hint")
        self.env = {"PATH": f"{self.mock}:{self.bin}:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": self.tmp,
                    "FAKE": self.fake}

    def install(self, src, name):
        with open(src) as f:
            text = f.read()
        self.assertIn("/usr/lib/luxos/i18n.sh", text)
        self.write(os.path.join(self.bin, name), text.replace("/usr/lib/luxos/i18n.sh", self.i18n), 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def write(path, text, mode=0o644):
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def read(self, name):
        with open(os.path.join(self.fake, name)) as f:
            return f.read()

    def log(self):
        return self.read("log").splitlines()

    def run_cmd(self, argv, env=None, tty=False, answers=()):
        """Spusti prikaz; s tty=True v pseudoterminalu a odpovi na otazky (radky answers)."""
        e = dict(self.env, **(env or {}))
        argv = [os.path.join(self.bin, argv[0])] + list(argv[1:])
        if not tty:
            p = subprocess.run(argv, env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)
            return p.returncode, p.stdout + p.stderr
        master, slave = pty.openpty()
        p = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=e)
        os.close(slave)
        data = b""
        pending = list(answers)
        deadline = time.time() + 30
        while time.time() < deadline:
            r, _w, _x = select.select([master], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
                # otazka konci "? [y/N] " nebo ":" -> poslat dalsi odpoved
                if pending and re.search(rb"(\]|:) $", data):
                    os.write(master, pending.pop(0).encode() + b"\n")
            elif p.poll() is not None:
                break
        os.close(master)
        p.wait(timeout=10)
        return p.returncode, re.sub(r"\x1b\[[0-9;]*m", "", data.decode(errors="replace"))


class AddUser(Base):
    def test_create_noninteractive(self):
        rc, out = self.run_cmd(["adduser", "--comment", "Jana Nova", "jana"])
        self.assertEqual(rc, 0, out)
        self.assertIn("User jana created.", out)
        self.assertIn("No password is set", out)
        ua = [l for l in self.log() if l.startswith("useradd")]
        self.assertEqual(len(ua), 1)
        self.assertIn("-m", ua[0].split())
        self.assertIn("-U", ua[0].split())
        self.assertIn("-c Jana Nova", ua[0])
        # vychozi skupiny LuxOS (jen existujici), bez wheel - nikdo se neptal
        self.assertIn("-G video,audio,input,lp,network,rfkill", ua[0])
        self.assertNotIn("wheel", ua[0])
        self.assertFalse(any(l.startswith("passwd") for l in self.log()))
        self.assertIn("jana:x:1002:1002:Jana Nova:/home/jana:", self.read("passwd"))

    def test_create_interactive_admin(self):
        rc, out = self.run_cmd(["adduser"], tty=True, answers=["jana", "Jana Nova", "y"])
        self.assertEqual(rc, 0, out)
        self.assertIn("Full name (optional):", out)
        self.assertIn("administrator", out)
        ua = [l for l in self.log() if l.startswith("useradd")][0]
        self.assertIn("-G video,audio,input,lp,network,rfkill,wheel,sys", ua)
        self.assertIn("passwd jana", self.log())
        self.assertIn("Administrator: yes", out)
        self.assertIn("Home folder: /home/jana", out)
        self.assertRegex(self.read("group"), r"wheel:x:998:anna,jana")

    def test_password_retry(self):
        self.write(os.path.join(self.fake, "passwd-fails"), "1")
        rc, out = self.run_cmd(["adduser", "--no-admin", "--comment", "", "jana"], tty=True, answers=["y"])
        self.assertEqual(rc, 0, out)
        self.assertEqual([l for l in self.log() if l.startswith("passwd")], ["passwd jana", "passwd jana"])
        self.assertNotIn("No password is set", out)

    def test_password_give_up(self):
        self.write(os.path.join(self.fake, "passwd-fails"), "5")
        rc, out = self.run_cmd(["adduser", "--no-admin", "--comment", "", "jana"], tty=True, answers=["n"])
        self.assertEqual(rc, 0, out)
        self.assertIn("sudo passwd jana", out)

    def test_existing_and_invalid(self):
        rc, out = self.run_cmd(["adduser", "anna"])
        self.assertEqual(rc, 1)
        self.assertIn("already exists", out)
        rc, out = self.run_cmd(["adduser", "docker"])          # skupina se stejnym jmenem
        self.assertEqual(rc, 1)
        self.assertIn("--ingroup docker", out)
        rc, out = self.run_cmd(["adduser", "Jana.Nova"])
        self.assertEqual(rc, 1)
        self.assertIn("not a valid name", out)
        self.assertIn("adduser jananova", out)
        for bad in ("-x", "1abc", "a:b", "x" * 33):
            rc, out = self.run_cmd(["adduser", "--", bad])
            self.assertEqual(rc, 1, bad)
        rc, out = self.run_cmd(["adduser", "--comment", "a:b", "jana"])
        self.assertEqual(rc, 1)
        self.assertFalse(any(l.startswith("useradd") for l in self.log()))

    def test_system_user(self):
        rc, out = self.run_cmd(["adduser", "--system", "svc"])
        self.assertEqual(rc, 0, out)
        ua = [l for l in self.log() if l.startswith("useradd")][0]
        self.assertIn("-r", ua.split())
        self.assertIn("-M", ua.split())
        self.assertIn("-s /usr/bin/nologin", ua)
        self.assertNotIn("-G", ua)

    def test_options(self):
        rc, out = self.run_cmd(["adduser", "--disabled-login", "--ingroup", "users", "--uid", "1234",
                                "--shell", "/bin/zsh", "--no-create-home", "jana"])
        self.assertEqual(rc, 0, out)
        ua = [l for l in self.log() if l.startswith("useradd")][0]
        self.assertIn("-g users -N", ua)
        self.assertIn("-u 1234", ua)
        self.assertIn("-M", ua.split())
        self.assertIn("-s /usr/bin/nologin", ua)
        rc, out = self.run_cmd(["adduser", "--uid", "abc", "x"])
        self.assertEqual(rc, 1)
        rc, out = self.run_cmd(["adduser", "--ingroup", "nope", "x"])
        self.assertEqual(rc, 1)
        self.assertIn("addgroup nope", out)

    def test_add_to_group(self):
        rc, out = self.run_cmd(["adduser", "petr", "sudo"])     # sudo z Ubuntu -> wheel
        self.assertEqual(rc, 0, out)
        self.assertIn("gpasswd -a petr wheel", self.log())
        self.assertIn("administrators are in the group wheel", out)
        self.assertIn("petr is now an administrator", out)
        rc, out = self.run_cmd(["adduser", "petr", "wheel"])
        self.assertEqual(rc, 0)
        self.assertIn("already a member", out)
        rc, out = self.run_cmd(["addgroup", "petr", "docker"])
        self.assertEqual(rc, 0, out)
        self.assertIn("gpasswd -a petr docker", self.log())
        rc, out = self.run_cmd(["adduser", "nobody2", "docker"])
        self.assertEqual(rc, 1)
        rc, out = self.run_cmd(["adduser", "petr", "nogroup"])
        self.assertEqual(rc, 1)
        self.assertIn("addgroup nogroup", out)

    def test_not_root_uses_sudo(self):
        rc, out = self.run_cmd(["adduser", "--comment", "J", "jana"], env={"MOCK_UID": "1000"})
        self.assertEqual(rc, 0, out)
        log = self.log()
        self.assertEqual(len(log), 1)
        self.assertTrue(log[0].startswith("sudo -- ") and log[0].endswith("adduser --comment J jana"), log)
        # napoveda nepotrebuje roota
        rc, out = self.run_cmd(["adduser", "--help"], env={"MOCK_UID": "1000"})
        self.assertEqual(rc, 0)
        self.assertIn("adduser USER GROUP", out)
        self.assertEqual(len(self.log()), 1)

    def test_help_and_usage_errors(self):
        for cmd in ("adduser", "deluser", "addgroup", "delgroup"):
            rc, out = self.run_cmd([cmd, "--help"])
            self.assertEqual(rc, 0, cmd)
            self.assertIn("Usage:", out)
            self.assertIn(cmd, out)
        rc, out = self.run_cmd(["adduser", "--bogus"])
        self.assertEqual(rc, 1)
        self.assertIn("Unknown option", out)
        rc, out = self.run_cmd(["adduser", "a", "b", "c"])
        self.assertEqual(rc, 1)
        rc, out = self.run_cmd(["adduser"])                     # bez terminalu se nepta
        self.assertEqual(rc, 1)
        self.assertIn("Missing user name", out)

    def test_groups(self):
        rc, out = self.run_cmd(["addgroup", "media"])
        self.assertEqual(rc, 0, out)
        self.assertIn("groupadd -- media", self.log())
        rc, out = self.run_cmd(["adduser", "--group", "--system", "--gid", "321", "svcgrp"])
        self.assertEqual(rc, 0, out)
        self.assertIn("groupadd -r -g 321 -- svcgrp", self.log())
        rc, out = self.run_cmd(["addgroup", "docker"])
        self.assertEqual(rc, 1)
        self.assertIn("already exists", out)


class Localized(Base):
    def test_czech(self):
        env = {"LANG": "cs_CZ.UTF-8"}
        rc, out = self.run_cmd(["adduser", "--help"], env=env)
        self.assertEqual(rc, 0)
        self.assertIn("Použití:", out)
        self.assertIn("vytvoří uživatele s domovskou složkou", out)
        # odpoved "a" (ano) na otazku v cestine
        rc, out = self.run_cmd(["adduser", "--comment", "", "jana"], env=env, tty=True, answers=["a"])
        self.assertEqual(rc, 0, out)
        self.assertIn("Má být jana správcem", out)
        self.assertIn("Uživatel jana byl vytvořen.", out)
        self.assertIn("wheel", [l for l in self.log() if l.startswith("useradd")][0])

    def test_other_languages(self):
        for lang, word in (("de_DE.UTF-8", "Verwendung:"), ("uk_UA.UTF-8", "Використання:"), ("sk_SK.UTF-8", "Použitie:")):
            rc, out = self.run_cmd(["deluser", "--help"], env={"LANG": lang})
            self.assertEqual(rc, 0)
            self.assertIn(word, out, lang)


class DelUser(Base):
    def test_delete_with_confirmation(self):
        rc, out = self.run_cmd(["deluser", "petr"], tty=True, answers=["y", "y"],
                               env={"MOCK_LOGNAME": "anna"})
        self.assertEqual(rc, 0, out)
        self.assertIn("userdel -r -- petr", self.log())
        self.assertNotIn("mail spool", out)
        self.assertIn("User petr removed.", out)
        self.assertIn(f"Home folder {self.home}/petr deleted.", out)
        self.assertNotIn("petr:", self.read("passwd"))

    def test_delete_cancelled(self):
        rc, out = self.run_cmd(["deluser", "petr"], tty=True, answers=["n", "n"])
        self.assertEqual(rc, 1, out)
        self.assertIn("Nothing was changed.", out)
        self.assertFalse(any(l.startswith("userdel") for l in self.log()))

    def test_delete_noninteractive(self):
        rc, out = self.run_cmd(["deluser", "petr"])
        self.assertEqual(rc, 0, out)
        self.assertIn("userdel -- petr", self.log())
        rc, out = self.run_cmd(["deluser", "--remove-home", "--yes", "petr"])
        self.assertEqual(rc, 1)                                 # uz neexistuje
        self.assertIn("does not exist", out)

    def test_safety(self):
        rc, out = self.run_cmd(["deluser", "root"])
        self.assertEqual(rc, 1)
        self.assertIn("root account", out)
        rc, out = self.run_cmd(["deluser", "bin"])
        self.assertEqual(rc, 1)
        self.assertIn("--system", out)
        rc, out = self.run_cmd(["deluser", "anna"])             # posledni administrator
        self.assertEqual(rc, 1)
        self.assertIn("last administrator", out)
        rc, out = self.run_cmd(["deluser", "anna", "wheel"])
        self.assertEqual(rc, 1)
        self.assertIn("last administrator", out)
        rc, out = self.run_cmd(["deluser", "petr"], env={"SUDO_USER": "petr"})
        self.assertEqual(rc, 1)
        self.assertIn("logged in with", out)
        rc, out = self.run_cmd(["deluser", "petr"], env={"MOCK_PGREP_RC": "0"})
        self.assertEqual(rc, 1)
        self.assertIn("loginctl terminate-user petr", out)
        self.assertFalse(any(l.startswith(("userdel", "gpasswd")) for l in self.log()))
        # s dalsim administratorem uz jde
        self.run_cmd(["adduser", "petr", "wheel"])
        rc, out = self.run_cmd(["deluser", "anna", "wheel"])
        self.assertEqual(rc, 0, out)
        self.assertIn("gpasswd -d anna wheel", self.log())

    def test_remove_from_group(self):
        rc, out = self.run_cmd(["deluser", "petr", "team"])
        self.assertEqual(rc, 0, out)
        self.assertIn("gpasswd -d petr team", self.log())
        self.assertIn("team:x:1501:\n", self.read("group"))
        rc, out = self.run_cmd(["deluser", "petr", "team"])
        self.assertEqual(rc, 0)
        self.assertIn("not a member", out)
        rc, out = self.run_cmd(["delgroup", "petr", "petr"])    # primarni skupina
        self.assertEqual(rc, 1)
        self.assertIn("primary group", out)

    def test_delgroup(self):
        rc, out = self.run_cmd(["delgroup", "--only-if-empty", "team"])
        self.assertEqual(rc, 1)
        self.assertIn("still has members", out)
        rc, out = self.run_cmd(["delgroup", "team"])
        self.assertEqual(rc, 0, out)
        self.assertIn("groupdel -- team", self.log())
        for g, word in (("wheel", "system group"), ("audio", "--system"), ("petr", "primary group"),
                        ("nope", "does not exist")):
            rc, out = self.run_cmd(["delgroup", g])
            self.assertEqual(rc, 1, g)
            self.assertIn(word, out, g)
        rc, out = self.run_cmd(["deluser", "--group", "docker"])
        self.assertEqual(rc, 0, out)
        self.assertIn("groupdel -- docker", self.log())


class Service(Base):
    def test_actions(self):
        units = os.path.join(self.tmp, "units")
        rc, out = self.run_cmd(["service", "cups", "restart"])
        self.assertEqual(rc, 0, out)
        self.assertIn("systemctl restart cups.service", self.log())
        rc, out = self.run_cmd(["service", "cups.service", "force-reload"])
        self.assertIn("systemctl reload-or-restart cups.service", self.log())
        rc, out = self.run_cmd(["service", "cups", "explode"])
        self.assertEqual(rc, 1)
        self.assertIn("Unknown action", out)
        rc, out = self.run_cmd(["service", "cups"])
        self.assertEqual(rc, 1)
        rc, out = self.run_cmd(["service"])
        self.assertEqual(rc, 1)
        self.assertIn("Usage:", out)
        rc, out = self.run_cmd(["service", "--help"])
        self.assertEqual(rc, 0)

    def test_status_all(self):
        rc, out = self.run_cmd(["service", "--status-all"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, " [ + ]  cups\n [ - ]  sshd\n")


class UpdateGrub(Base):
    def test_no_grub(self):
        if os.path.exists("/boot/grub/grub.cfg") or os.path.isdir("/boot/loader/entries"):
            self.skipTest("na tomto pocitaci je bootloader - test chce prazdny /boot")
        rc, out = self.run_cmd(["update-grub"])
        self.assertEqual(rc, 1)
        self.assertIn("No GRUB configuration", out)

    def test_in_namespace(self):
        """GRUB a systemd-boot: /boot podvrzeny v uzivatelskem namespace (bez roota)."""
        if subprocess.run(["unshare", "-rm", "true"], capture_output=True).returncode:
            self.skipTest("unshare -rm neni k dispozici")
        boot = os.path.join(self.tmp, "boot")
        os.makedirs(os.path.join(boot, "grub"))
        self.write(os.path.join(boot, "grub", "grub.cfg"), "")
        ug = os.path.join(self.bin, "update-grub")
        env = dict(self.env)
        p = subprocess.run(["unshare", "-rm", "sh", "-c", f'mount --bind "$1" /boot && "$2"', "sh", boot, ug],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("grub-mkconfig -o /boot/grub/grub.cfg", self.log())
        os.remove(os.path.join(boot, "grub", "grub.cfg"))
        os.makedirs(os.path.join(boot, "loader", "entries"))
        p = subprocess.run(["unshare", "-rm", "sh", "-c", f'mount --bind "$1" /boot && "$2"', "sh", boot, ug],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("systemd-boot", p.stdout)
        self.assertIn("bootctl list", p.stdout)


class CommandHint(Base):
    def hint(self, *args):
        p = subprocess.run([os.path.join(self.bin, "command-hint")] + list(args), env=self.env,
                           capture_output=True, text=True, timeout=30)
        return p.returncode, p.stdout, p.stderr

    def test_mapping(self):
        cases = {
            ("apt", "install", "-y", "vim", "git"): "apt install -y vim git  →  lux install vim git",
            ("apt-get", "update"): "→  lux update",
            ("apt", "full-upgrade"): "→  lux update",
            ("apt", "remove", "vim"): "→  lux remove vim",
            ("apt", "purge", "vim"): "→  lux remove vim",
            ("apt", "search", "video"): "→  lux search video",
            ("apt", "show", "vim"): "→  lux info vim",
            ("apt", "list", "--installed"): "→  lux list",
            ("apt", "list", "--upgradable"): "→  lux list --upgradable",
            ("apt", "autoremove"): "→  lux autoremove",
            ("apt-cache", "policy", "vim"): "→  lux info vim",
            ("dpkg", "-l"): "→  lux list",
            ("dpkg", "-L", "bash"): "→  lux files bash",
            ("dpkg", "-S", "/usr/bin/ls"): "→  lux owns /usr/bin/ls",
            ("dpkg", "-r", "vim"): "→  lux remove vim",
            ("dnf", "install", "htop"): "→  lux install htop",
            ("yum", "update"): "→  lux update",
            ("dnf", "provides", "/usr/bin/ls"): "→  lux owns /usr/bin/ls",
            ("zypper", "in", "vim"): "→  lux install vim",
            ("zypper", "dup"): "→  lux update",
            ("snap", "install", "code"): "→  lux install code",
            ("ifconfig",): "→  ip address",
            ("ifconfig", "eth0"): "→  ip address show eth0",
            ("netstat", "-tulpn"): "→  ss -tulpn",
            ("netstat", "-rn"): "→  ip route",
            ("netstat", "-i"): "→  ip -statistics link",
            ("netstat", "--program"): "→  ss -tulpn",
            ("route", "-n"): "→  ip route",
            ("arp",): "→  ip neighbour",
            ("nslookup", "example.com"): "→  resolvectl query example.com",
            ("dig", "+short", "example.com"): "→  resolvectl query example.com",
            ("traceroute", "1.1.1.1"): "→  tracepath 1.1.1.1",
            ("which", "ls"): "→  command -v ls",
            ("dpkg-reconfigure", "tzdata"): "→  timedatectl list-timezones",
        }
        for args, want in cases.items():
            rc, out, err = self.hint(*args)
            self.assertEqual(rc, 1, args)
            self.assertEqual(out, "", args)
            self.assertIn(want, err, args)
            self.assertNotIn("\x1b[", err)

    def test_texts(self):
        _rc, _o, err = self.hint("apt", "install", "./app.deb")
        self.assertIn("can't install .deb", err)
        self.assertNotIn("lux install ./app.deb", err)
        _rc, _o, err = self.hint("ifconfig")
        self.assertIn("ifconfig is not installed", err)
        self.assertIn("lux install net-tools", err)
        _rc, _o, err = self.hint("apt")
        self.assertIn("LuxOS uses lux to manage software.", err)
        self.assertIn("lux --help", err)
        rc, _o, err = self.hint("foo")
        self.assertEqual((rc, err), (2, ""))

    def test_never_runs_anything(self):
        with open(os.path.join(FILES, "command-hint")) as f:
            src = f.read()
        for word in ("exec ", "sudo ", "eval "):
            self.assertNotIn(word, src)
        _rc, _o, err = self.hint("apt", "install", "$(touch /tmp/x)", ";rm")
        self.assertIn(r"lux install \$\(touch\ /tmp/x\) \;rm", err)

    def test_shell_handlers(self):
        """bashrc i zshrc volaji command-hint jen pro prikazy, ktere v systemu nejsou."""
        for rc_name in ("bashrc", "zshrc"):
            with open(os.path.join(FILES, rc_name)) as f:
                src = f.read()
            self.assertIn("/usr/lib/luxos/command-hint", src)
            self.assertIn("apt|apt-get|apt-cache|aptitude|dpkg|dpkg-reconfigure|dnf|yum|zypper|snap|", src)
        # skutecne volani z bashe: handler z bashrc, cesta k napovede v docasnem adresari
        with open(os.path.join(FILES, "bashrc")) as f:
            src = f.read()
        start = src.index("command_not_found_handle() {")
        end = src.index("\n}\n", start) + 3
        func = src[start:end].replace("/usr/lib/luxos/command-hint", os.path.join(self.bin, "command-hint"))
        script = func + "\napt-get install vim\necho rc=$?\nnotacommand_xyz\necho rc=$?\n"
        # PATH jen s atrapami: skutecny apt-get hostitele (Debian) se nesmi spustit
        env = dict(self.env, PATH=f"{self.mock}:{self.bin}")
        p = subprocess.run([shutil.which("bash"), "-c", script], env=env, capture_output=True, text=True,
                           timeout=30)
        self.assertIn("rc=127", p.stdout)
        self.assertIn("apt-get: command not found", p.stderr)
        self.assertIn("lux install vim", p.stderr)
        self.assertIn("notacommand_xyz: command not found", p.stderr)


class Translations(unittest.TestCase):
    """Kazdy retezec T "..." z novych skriptu ma preklad do vsech jazyku se stejnymi %s."""

    def test_all_strings_translated(self):
        known = {}
        for lang in LANGS[1:]:
            with open(os.path.join(I18N, lang + ".tsv")) as f:
                for line in f:
                    k, _, v = line.rstrip("\n").partition("\t")
                    if v:
                        known.setdefault(k, set()).add(lang)
        self.assertTrue(os.path.exists(NEW_TR), NEW_TR)
        with open(NEW_TR) as f:
            rows = [l.rstrip("\n").split("\t") for l in f if l.strip()]
        self.assertEqual(rows[0], LANGS)
        new = {}
        for r in rows[1:]:
            self.assertEqual(len(r), len(LANGS), r[0])
            for i, v in enumerate(r[1:], start=1):
                self.assertTrue(v.strip(), (r[0], LANGS[i]))
                self.assertEqual(re.findall(r"%[sd]", r[0]), re.findall(r"%[sd]", v), (r[0], LANGS[i]))
            new[r[0]] = r
        used = set()
        for path in (os.path.join(FILES, "bin", n) for n in ("adduser", "service", "update-grub")):
            with open(path) as f:
                used |= set(re.findall(r'\$\(T "((?:[^"\\]|\\.)*)"', f.read()))
        with open(os.path.join(FILES, "command-hint")) as f:
            used |= set(re.findall(r'\$\(T "((?:[^"\\]|\\.)*)"', f.read()))
        self.assertGreater(len(used), 50)
        missing = sorted(s for s in used if s not in new and len(known.get(s, ())) < len(LANGS) - 1)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
