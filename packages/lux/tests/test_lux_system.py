"""Testy lux system (lux_system.py): cely system v jednom souboru LSL.

    python3 -m unittest discover -s packages/lux/tests -v

Bez rootu a bez zasahu do systemu: soubory se ctou a zapisuji v docasnem koreni (LUX_SYSTEM_ROOT),
vsechny nastroje (lux, systemctl, useradd, luxos-care, ...) jsou zastupne skripty v LUX_SYSTEM_BIN,
ktere jen zapisi sve argumenty. Testy, ktere vyhodnocuji LSL, potrebuji prikaz lsl (balik lsl);
bez nej se preskoci (unittest skip "lsl is not installed").
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "system.lsl.example")
LSL = shutil.which("lsl")
need_lsl = unittest.skipUnless(LSL, "lsl is not installed (package lsl)")

spec = importlib.util.spec_from_file_location("lux_system", os.path.join(HERE, "..", "lux_system.py"))
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)

STUB = r"""#!/bin/bash
n=$(basename "$0")
printf '%s %s\n' "$n" "$*" >>"$STUB_LOG"
if [[ -f $FAKE/fail ]] && grep -qx "$n" "$FAKE/fail"; then echo "$n: failed on purpose" >&2; exit 1; fi
case $n in
  lux-engine) case $1 in -Qeq) cat "$FAKE/explicit" ;; -Qq) cat "$FAKE/explicit" "$FAKE/deps" ;;
              -Slq) cat "$FAKE/drivers_repo" 2>/dev/null ;; esac ;;
  nmcli) [[ $* == "-t -f UUID connection show --active" ]] && cat "$FAKE/active" 2>/dev/null ;;
  lpstat)
    [[ -f $FAKE/cups ]] || { echo "lpstat: Scheduler is not running." >&2; exit 1; }
    case $1 in -r) echo "scheduler is running" ;; -v) cat "$FAKE/cups" ;;
                -d) if [[ -f $FAKE/cups_default ]]; then echo "system default destination: $(cat "$FAKE/cups_default")"
                    else echo "no system default destination"; fi ;; esac ;;
  lpoptions) cat "$FAKE/lpoptions_$2" 2>/dev/null ;;
  lpinfo) cat "$FAKE/lpinfo" 2>/dev/null ;;
  lux_alpm.py)
    if [[ $1 == resolve ]]; then
      shift 2
      for a; do if grep -qx -- "$a" "$FAKE/repo"; then printf 'repo\t%s\n' "$a"; else printf 'none\t%s\n' "$a"; fi; done
    fi ;;
  flatpak) [[ $1 == list ]] && cat "$FAKE/flatpaks" ;;
  systemctl) [[ $1 == list-unit-files ]] && cat "$FAKE/units" ;;
  luxos-care)
    if [[ -f $FAKE/snapfail ]]; then echo "Snapshots need the system on Btrfs." >&2; exit 1; fi
    echo "Snapshot 2026-10-26_12-00-00 created." ;;
  chpasswd) cat >>"$STUB_LOG" ;;
esac
exit 0
"""

UNITS = """\
NetworkManager.service enabled disabled
bluetooth.service enabled disabled
cups.socket enabled disabled
sshd.service disabled disabled
getty@.service enabled enabled
systemd-timesyncd.service enabled enabled
dbus-broker.service enabled enabled
luxos-guard.service enabled disabled
luxos-guard-snapshot.timer enabled disabled
ufw.service disabled disabled
lightdm.service enabled disabled
"""

SDBOOT = "title LuxOS\nlinux /vmlinuz-linux-zen\ninitrd /initramfs-linux-zen.img\noptions root=UUID=abc rw quiet splash\n"


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, mode)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lux-system-test-")
        self.root = os.path.join(self.tmp, "root")
        self.bin = os.path.join(self.tmp, "bin")
        self.fake = os.path.join(self.tmp, "fake")
        self.log = os.path.join(self.tmp, "calls.log")
        os.makedirs(self.bin)
        os.makedirs(self.fake)
        for name in list(ls.TOOLS):
            if name == "lsl":
                continue
            write(os.path.join(self.bin, name), STUB, 0o755)
        if LSL:
            os.symlink(LSL, os.path.join(self.bin, "lsl"))
        r = self.root
        write(r + "/etc/hostname", "lux-pc\n")
        write(r + "/usr/share/zoneinfo/Europe/Prague", "TZif")
        write(r + "/usr/share/zoneinfo/Europe/Vienna", "TZif")
        os.makedirs(r + "/etc", exist_ok=True)
        os.symlink("../usr/share/zoneinfo/Europe/Prague", r + "/etc/localtime")
        write(r + "/etc/locale.conf", "LANG=en_US.UTF-8\nLC_TIME=cs_CZ.UTF-8\n")
        write(r + "/etc/locale.gen", "#cs_CZ.UTF-8 UTF-8\nen_US.UTF-8 UTF-8\n")
        write(r + "/usr/share/i18n/SUPPORTED", "cs_CZ.UTF-8 UTF-8\nen_US.UTF-8 UTF-8\nde_DE.UTF-8 UTF-8\n")
        write(r + ls.KEYBOARD_CONF, 'Section "InputClass"\n        Identifier "system-keyboard"\n'
              '        Option "XkbLayout" "us,cz"\n        Option "XkbVariant" ",qwerty"\n'
              '        Option "XkbOptions" "grp:shifts_toggle"\nEndSection\n')
        write(r + "/etc/passwd", "root:x:0:0::/root:/bin/bash\nnobody:x:65534:65534::/:/usr/bin/nologin\n"
              "anna:x:1000:1000:Anna Novakova:/home/anna:/bin/bash\npetr:x:1001:1001:Petr:/home/petr:/bin/bash\n")
        write(r + "/etc/group", "root:x:0:root\nwheel:x:998:anna\naudio:x:995:anna,petr\nanna:x:1000:\n"
              "petr:x:1001:\nfamily:x:1002:anna,petr\n")
        write(r + "/etc/shadow", "anna:$6$salt$old:20000::::::\npetr:!:20000::::::\n", 0o600)
        write(r + "/etc/shells", "/bin/bash\n/usr/bin/bash\n/usr/bin/zsh\n")
        write(r + "/etc/login.defs", "UID_MIN 1000\nUID_MAX 60000\nGID_MIN 1000\nGID_MAX 60000\n")
        write(r + ls.CARE_CONF, "# LuxOS Care\nMODE=carefree\n")
        write(r + "/etc/ufw/ufw.conf", "ENABLED=no\n")
        write(r + "/etc/ufw/user.rules", "### tuple ### allow tcp 22 0.0.0.0/0 any 0.0.0.0/0 in\n"
              "### tuple ### allow any 53 0.0.0.0/0 any 0.0.0.0/0 in\n")
        write(r + "/boot/loader/entries/luxos.conf", SDBOOT)
        write(r + "/boot/loader/entries/luxos-fallback.conf", SDBOOT.replace(" quiet splash", ""))
        write(r + "/boot/loader/entries/luxos-snapshot-2026-10-20_10-00-00.conf", SDBOOT)
        write(r + "/proc/cmdline", "root=UUID=abc rw quiet\n")
        write(self.fake + "/explicit", "base\nlinux-zen\nlux\nfirefox\nvim\nufw\n")
        write(self.fake + "/deps", "glibc\nlibfoo\n")
        write(self.fake + "/repo", "htop\nneovim\nlibfoo\nflatpak\nufw\n")
        write(self.fake + "/flatpaks", "org.signal.Signal\n")
        write(self.fake + "/units", UNITS)
        self.saved = {k: os.environ.get(k) for k in ("LUX_SYSTEM_BIN", "STUB_LOG", "FAKE", "LUX_COLOR", "LANG",
                                                     "LC_ALL", "LC_MESSAGES")}
        os.environ.update({"LUX_SYSTEM_BIN": self.bin, "STUB_LOG": self.log, "FAKE": self.fake,
                           "LUX_COLOR": "never", "LANG": "C.UTF-8"})
        os.environ.pop("LC_ALL", None)
        os.environ.pop("LC_MESSAGES", None)
        self.old_root = ls.ROOT
        ls.ROOT = self.root

    def tearDown(self):
        ls.ROOT = self.old_root
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def calls(self):
        """Zapsana volani nastroju bez dotazu na stav (lux-engine -Q..., list-unit-files, ...)."""
        try:
            with open(self.log) as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        reads = ("lux-engine -Q", "lux-engine -Sl", "systemctl list-unit-files", "flatpak list", "lux_alpm.py resolve",
                 "nmcli -t -f UUID", "lpstat ", "lpoptions ", "lpinfo ")
        return [x for x in lines if not x.startswith(reads)]

    def plan(self, cfg, applied=None):
        norm, errors = ls.normalize(cfg)
        self.assertEqual(errors, [])
        return ls.compute(norm, ls.State(), applied or {})

    def texts(self, plan):
        return [f"{c.section} {c.op} {c.text}" for c in plan.changes]

    def lsl_file(self, body, name="system.lsl"):
        path = os.path.join(self.tmp, "cfg", name)
        write(path, body)
        return path

    def main(self, *args, stdin_tty=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ls.main(["lux_system.py"] + list(args))
        return rc, out.getvalue() + err.getvalue()


class NormalizeTest(Base):
    def test_valid_and_shortcuts(self):
        cfg, errors = ls.normalize({"keyboard": ["us", "cz(qwerty)"], "services": {"enable": ["sshd", "cups.socket"]},
                                    "packages": ["htop", "htop"], "users": {"anna": None}})
        self.assertEqual(errors, [])
        self.assertEqual(cfg["keyboard"], {"layouts": ["us", "cz(qwerty)"], "options": []})
        self.assertEqual(cfg["services"]["enable"], ["sshd.service", "cups.socket"])
        self.assertEqual(cfg["packages"], ["htop"])
        self.assertEqual(cfg["users"], {"anna": {}})

    def test_errors_are_clear(self):
        _cfg, errors = ls.normalize({
            "hostnme": "x", "packages": ["Bad Name"], "timezone": "Mars/Base", "locale": "xx_YY.UTF-8",
            "users": {"anna": {"password": "secret"}, "bob": {"password_hash": "plaintext"}, "root": {}},
            "services": {"enable": ["sshd"], "disable": ["sshd", "dbus-broker"]},
            "kernel": {"params": ["root=/dev/sda1", "quiet"]}, "care": {"mode": "lazy", "keep_snapshots": 1},
            "firewall": {"allow": ["99999/tcp", "22/icmp"]}, "remove_unlisted": "yes",
        })
        text = "\n".join(errors)
        self.assertIn('unknown setting "hostnme" (did you mean "hostname"?)', text)
        self.assertIn('packages[0]: "Bad Name" is not a valid package name', text)
        self.assertIn('unknown time zone "Mars/Base"', text)
        self.assertIn("unknown language setting", text)
        self.assertIn("never write passwords into the file", text)
        self.assertIn("this is not a password hash", text)
        self.assertIn('users.root: "root" is not a valid user name', text)
        self.assertIn("sshd.service is both in enable and disable", text)
        self.assertIn("dbus-broker.service is needed by LuxOS", text)
        self.assertIn("root=/dev/sda1 is set by the installer", text)
        self.assertIn('care.mode: must be "carefree" or "classic"', text)
        self.assertIn("care.keep_snapshots: must be between 2 and 50", text)
        self.assertIn('"99999/tcp" is not a valid port', text)
        self.assertIn('"22/icmp" is not a valid port', text)
        self.assertIn("remove_unlisted: must be True or False", text)

    def test_guard_and_services_overlap(self):
        _cfg, errors = ls.normalize({"guard": {"enable": True}, "services": {"disable": ["luxos-guard"]}})
        self.assertTrue(any('set in "guard"' in e for e in errors), errors)


class StateTest(Base):
    def test_reads_current_system(self):
        st = ls.State()
        self.assertEqual(st.hostname(), "lux-pc")
        self.assertEqual(st.timezone(), "Europe/Prague")
        self.assertEqual(st.locale(), "en_US.UTF-8")
        self.assertEqual(st.keyboard()["layouts"], ["us", "cz(qwerty)"])
        self.assertEqual(st.keyboard()["options"], ["grp:shifts_toggle"])
        self.assertEqual(st.explicit(), {"base", "linux-zen", "lux", "firefox", "vim", "ufw"})
        self.assertEqual(sorted(st.normal_users()), ["anna", "petr"])
        self.assertEqual(st.user_groups("anna"), ["audio", "family", "wheel"])
        self.assertEqual(st.shadow_hash("anna"), "$6$salt$old")
        self.assertEqual(st.firewall(), {"installed": True, "enable": False, "allow": ["22/tcp", "53"]})
        self.assertEqual(st.care(), {"mode": "carefree", "snapshots": True, "keep_snapshots": 5,
                                     "protect": False, "verify": True})
        lay = st.boot()
        self.assertEqual(lay["kind"], "sdboot")
        self.assertEqual([os.path.basename(f) for f in lay["files"]], ["luxos-fallback.conf", "luxos.conf"])
        self.assertEqual(lay["params"], ["root=UUID=abc", "rw", "quiet", "splash"])


class PlanTest(Base):
    def test_nothing_to_do(self):
        plan = self.plan({"hostname": "lux-pc", "timezone": "Europe/Prague", "packages": ["firefox", "vim", "ufw"],
                          "keyboard": {"layouts": ["us", "cz(qwerty)"], "options": ["grp:shifts_toggle"]},
                          "services": {"enable": ["NetworkManager"]}, "care": {"mode": "carefree"},
                          "users": {"anna": {"groups": ["wheel", "audio", "family"], "shell": "/bin/bash"}},
                          "kernel": {"params": ["quiet"]}, "firewall": {"enable": False, "allow": ["22/tcp", "53"]}})
        self.assertEqual(self.texts(plan), [])
        self.assertIn("3 installed packages are not in the file", " ".join(plan.notes))

    def test_packages(self):
        plan = self.plan({"packages": ["firefox", "htop", "libfoo"]}, applied={"packages": ["firefox", "vim", "neovim"]})
        self.assertEqual(self.texts(plan), [
            "packages + install: htop",
            "packages ~ keep as wanted (now only a dependency): libfoo",
            "packages - remove: vim",       # byl v souboru pri poslednim apply, ted neni
        ])
        self.assertEqual(plan.changes[0].data, ["htop"])

    def test_remove_unlisted_keeps_protected(self):
        plan = self.plan({"packages": ["firefox"], "remove_unlisted": True})
        rem = [c for c in plan.changes if c.op == "-"]
        self.assertEqual(rem[0].data, ["ufw", "vim"])
        self.assertIn("base", " ".join(plan.notes))
        self.assertIn("linux-zen", " ".join(plan.notes))

    def test_unknown_package_is_an_error(self):
        norm, _e = ls.normalize({"packages": ["firefx"]})
        with self.assertRaises(ls.UserError) as cm:
            ls.compute(norm, ls.State(), {})
        self.assertIn("not in the repositories: firefx", str(cm.exception))

    def test_flatpaks(self):
        plan = self.plan({"flatpaks": ["org.mozilla.firefox"]})
        self.assertEqual(self.texts(plan), ["flatpaks + install: org.mozilla.firefox"])
        self.assertIn("1 installed Flathub apps", " ".join(plan.notes))
        plan = self.plan({"flatpaks": [], "remove_unlisted": True})
        self.assertEqual(self.texts(plan), ["flatpaks - remove: org.signal.Signal"])

    def test_system_settings(self):
        plan = self.plan({"hostname": "saturn", "timezone": "Europe/Vienna", "locale": "cs_CZ.UTF-8",
                          "keyboard": {"layouts": ["us", "de"]}})
        self.assertEqual(self.texts(plan), [
            "system ~ computer name: lux-pc → saturn",
            "system ~ time zone: Europe/Prague → Europe/Vienna",
            "system ~ language (locale): en_US.UTF-8 → cs_CZ.UTF-8",
            "system ~ keyboard layouts: us cz(qwerty) grp:shifts_toggle → us de",
        ])

    def test_users_and_groups(self):
        plan = self.plan({"groups": ["family", "games"], "users": {
            "anna": {"groups": ["wheel", "games"], "description": "Anna N.", "password_hash": "$6$salt$new"},
            "petr": {"groups": ["audio", "family"], "password_hash": None},
            "eva": {"groups": ["family"], "shell": "/usr/bin/zsh"},
        }})
        self.assertEqual(self.texts(plan), [
            "users + create group games",
            "users + create user eva (family)",
            "users ~ anna: full name → Anna N.",
            "users + anna: add to groups games",
            "users - anna: remove from groups audio, family",
            "users ~ anna: set password (from password_hash)",
        ])
        self.assertIn("User eva has no password yet; set it with: sudo passwd eva", plan.notes)
        # stejny otisk = beze zmeny (otisk se nikdy nevypisuje)
        plan = self.plan({"users": {"anna": {"password_hash": "$6$salt$old"}}})
        self.assertEqual(self.texts(plan), [])

    def test_last_admin_cannot_be_removed(self):
        norm, _e = ls.normalize({"users": {"anna": {"groups": ["audio"]}}})
        with self.assertRaises(ls.UserError) as cm:
            ls.compute(norm, ls.State(), {})
        self.assertIn("administrator", str(cm.exception))

    def test_system_account_not_managed(self):
        norm, _e = ls.normalize({"users": {"nobody": {"groups": []}}})
        with self.assertRaises(ls.UserError):
            ls.compute(norm, ls.State(), {})

    def test_services(self):
        plan = self.plan({"services": {"enable": ["sshd", "NetworkManager", "getty@tty2"], "disable": ["bluetooth"]}},
                         applied={"services_enable": ["cups.socket", "sshd.service"]})
        self.assertEqual(self.texts(plan), [
            "services + turn on sshd.service",
            "services + turn on getty@tty2.service",
            "services - turn off bluetooth.service",
            "services - turn off cups.socket",      # zmizel ze seznamu enable od posledniho apply
        ])
        norm, _e = ls.normalize({"services": {"enable": ["nosuch"]}})
        with self.assertRaises(ls.UserError) as cm:
            ls.compute(norm, ls.State(), {})
        self.assertIn("Unknown service nosuch.service", str(cm.exception))

    def test_guard_care_firewall_kernel(self):
        plan = self.plan({"guard": {"enable": True, "home_snapshots": False},
                          "care": {"mode": "classic", "snapshots": False, "keep_snapshots": 5},
                          "firewall": {"enable": True, "allow": ["22/tcp", "8000:8010/udp"]},
                          "kernel": {"params": ["quiet", "mitigations=auto"]}},
                         applied={"kernel_params": ["quiet", "splash"]})
        self.assertEqual(self.texts(plan), [
            "guard - turn off luxos-guard-snapshot.timer",
            "care ~ mode: carefree → classic, snapshots: True → False",
            "firewall + allow incoming 8000:8010/udp",
            "firewall - stop allowing incoming 53",
            "firewall + turn on the firewall",
            "kernel ~ +mitigations=auto -splash  (after a restart)",
        ])
        self.assertTrue(plan.restart)

    def test_firewall_needs_ufw(self):
        write(self.fake + "/explicit", "base\nlux\n")
        plan = self.plan({"firewall": {"enable": True, "allow": ["22/tcp"]}})
        self.assertEqual(plan.changes[0].text, "install: ufw")
        self.assertIn("firewall + turn on the firewall", self.texts(plan))


class ApplyFilesTest(Base):
    def test_locale_care_kernel_files(self):
        ls.apply_locale("cs_CZ.UTF-8")
        with open(self.root + "/etc/locale.conf") as f:
            self.assertEqual(f.read(), "LANG=cs_CZ.UTF-8\nLC_TIME=cs_CZ.UTF-8\n")
        with open(self.root + "/etc/locale.gen") as f:
            self.assertEqual(f.read(), "cs_CZ.UTF-8 UTF-8\nen_US.UTF-8 UTF-8\n")
        # locale-gen zapisuje do /usr: pri ochrane systemu pres luxos-care protect exec
        self.assertTrue(any(c.startswith("luxos-care protect exec -- ") and c.endswith("/locale-gen")
                            for c in self.calls()), self.calls())
        ls.apply_care({"mode": "classic", "snapshots": False, "keep_snapshots": 8})
        with open(self.root + ls.CARE_CONF) as f:
            self.assertEqual(f.read(), "# LuxOS Care\nMODE=classic\nSNAPSHOTS=no\nSNAPSHOT_KEEP=8\n")
        self.assertNotIn("luxos-care protect apply", self.calls())
        ls.apply_care({"protect": True, "verify": False})
        with open(self.root + ls.CARE_CONF) as f:
            self.assertEqual(f.read(), "# LuxOS Care\nMODE=classic\nSNAPSHOTS=no\nSNAPSHOT_KEEP=8\n"
                                       "PROTECT=yes\nVERIFY=no\n")
        self.assertIn("luxos-care protect apply", self.calls())      # hned, bez restartu
        self.assertEqual(ls.State().care()["protect"], True)
        ls.apply_kernel(ls.State().boot(), ["mitigations=auto"], ["splash"])
        with open(self.root + "/boot/loader/entries/luxos.conf") as f:
            self.assertIn("options root=UUID=abc rw quiet mitigations=auto\n", f.read())
        with open(self.root + "/boot/loader/entries/luxos-snapshot-2026-10-20_10-00-00.conf") as f:
            self.assertEqual(f.read(), SDBOOT)   # snimky se nemeni

    def test_grub(self):
        shutil.rmtree(self.root + "/boot/loader")
        write(self.root + "/boot/grub/grub.cfg", "x")
        write(self.root + "/etc/default/grub", 'GRUB_TIMEOUT=0\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n')
        lay = ls.State().boot()
        self.assertEqual(lay["params"], ["quiet", "splash"])
        ls.apply_kernel(lay, ["nowatchdog"], ["splash"])
        with open(self.root + "/etc/default/grub") as f:
            self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="quiet nowatchdog"', f.read())
        self.assertIn("grub-mkconfig -o /boot/grub/grub.cfg", self.calls())


@need_lsl
class EvaluateTest(Base):
    def test_example_is_valid(self):
        cfg = ls.load(EXAMPLE)
        self.assertEqual(cfg["hostname"], "lux-laptop")
        self.assertIn("tlp", cfg["packages"])                     # config.mkIf(laptop, ...)
        self.assertIn("libreoffice-fresh", cfg["packages"])       # + office
        self.assertEqual(cfg["services"]["enable"], ["sshd.service", "cups.socket", "tlp.service"])

    def test_impure_code_is_refused(self):
        for body, hint in (('load config\nconfig = {"hostname": readfile("/etc/shadow")}\n', "cannot run programs"),
                           ('load config\nload os\nconfig = {"x": os.run("id")}\n', "may only use 'load config'"),
                           ('load config\nconfig = {"packages": ["a", "b",]}\n', "separated by commas")):
            path = self.lsl_file(body)
            with self.assertRaises(ls.UserError) as cm:
                ls.load(path)
            msg = str(cm.exception)
            self.assertIn(hint, msg)
            self.assertIn(path, msg)
            self.assertNotIn("/tmp/lsl-program-", msg)

    def test_assertion_and_imports(self):
        write(os.path.join(self.tmp, "cfg", "laptop.lsl"), 'load config\nconfig = {"packages": ["tlp"]}\n')
        path = self.lsl_file('load config\nimports = ["laptop.lsl"]\nconfig = {"packages": ["htop"]}\n'
                             'assertions = [[config["packages"] != [], "no packages"]]\n')
        self.assertEqual(sorted(ls.load(path)["packages"]), ["htop", "tlp"])
        path = self.lsl_file('load config\nconfig = {"hostname": "x"}\nassertions = [[False, "my own rule"]]\n')
        with self.assertRaises(ls.UserError) as cm:
            ls.load(path)
        self.assertIn("my own rule", str(cm.exception))

    def test_endless_loop_times_out(self):
        old = ls.EVAL_TIMEOUT
        ls.EVAL_TIMEOUT = 3
        try:
            path = self.lsl_file("load config\nx = 0\nwhile True:\n    x = x + 1\nend\nconfig = {}\n")
            with self.assertRaises(ls.UserError) as cm:
                ls.load(path)
            self.assertIn("took too long", str(cm.exception))
        finally:
            ls.EVAL_TIMEOUT = old

    def test_show_then_diff_is_empty(self):
        """Soubor ze soucasneho systemu (show) je platny a nic nemeni (idempotence)."""
        rc, text = self.main("show")
        self.assertEqual(rc, 0)
        self.assertNotIn("$6$", text)          # zadna hesla ani otisky
        self.assertIn('"anna": {', text)
        path = self.lsl_file(text)
        cfg = ls.load(path)
        self.assertEqual(cfg["packages"], ["base", "firefox", "linux-zen", "lux", "ufw", "vim"])
        self.assertEqual(cfg["services"]["enable"], ["NetworkManager.service", "bluetooth.service", "cups.socket",
                                                     "lightdm.service"])
        self.assertEqual(cfg["kernel"]["params"], ["quiet", "splash"])
        plan = ls.compute(cfg, ls.State(), {})
        self.assertEqual(self.texts(plan), [])
        rc, out = self.main("diff", path)
        self.assertEqual(rc, 0)
        self.assertIn("already matches", out)
        rc, out = self.main("diff", "--json", path)
        self.assertEqual(json.loads(out)["changes"], [])

    def test_init_and_apply(self):
        rc, out = self.main("init")
        self.assertEqual(rc, 0, out)
        path = self.root + ls.CONFIG
        self.assertTrue(os.path.isfile(path))
        with open(self.root + ls.APPLIED) as f:
            self.assertIn("vim", json.load(f)["packages"])
        rc, out = self.main("init")
        self.assertEqual(rc, 1)
        self.assertIn("already exists", out)
        # uzivatel smaze vim, prida htop a zmeni jmeno pocitace
        with open(path) as f:
            text = f.read()
        old = '"packages": ["base", "firefox", "linux-zen", "lux", "ufw", "vim"]'
        self.assertIn(old, text)
        text = text.replace(old, '"packages": ["base", "firefox", "linux-zen", "lux", "ufw", "htop"]')
        write(path, text.replace('"lux-pc"', '"saturn"'))
        rc, out = self.main("diff")
        self.assertEqual(rc, 0, out)
        self.assertIn("+ install: htop", out)
        self.assertIn("- remove: vim", out)
        self.assertIn("computer name: lux-pc → saturn", out)
        open(self.log, "w").close()
        rc, out = self.main("apply", "-y")
        self.assertEqual(rc, 0, out)
        calls = self.calls()
        self.assertEqual(calls[0], "luxos-care snapshot --kind system")      # snimek jako prvni
        self.assertEqual(calls[1:], ["lux -y --repo install htop", "hostnamectl set-hostname saturn",
                                     "lux -y remove vim"])
        self.assertIn("lux rollback 2026-10-26_12-00-00", out)
        with open(self.root + ls.APPLIED) as f:
            applied = json.load(f)
        self.assertIn("htop", applied["packages"])
        self.assertNotIn("vim", applied["packages"])
        self.assertEqual(len(os.listdir(self.root + ls.HISTORY_DIR)), 2)      # init a apply
        self.assertEqual(os.stat(self.root + ls.APPLIED).st_mode & 0o777, 0o600)

    def test_apply_needs_confirmation_and_snapshot(self):
        path = self.lsl_file('load config\nconfig = {"hostname": "saturn"}\n')
        rc, out = self.main("apply", path)          # bez terminalu a bez -y nic
        self.assertEqual(rc, 1)
        self.assertIn("Confirm with -y", out)
        self.assertEqual(self.calls(), [])
        write(self.fake + "/snapfail", "")
        rc, out = self.main("apply", "-y", path)
        self.assertEqual(rc, 1)
        self.assertIn("Snapshots need the system on Btrfs.", out)
        self.assertIn("--no-snapshot", out)
        self.assertEqual(self.calls(), ["luxos-care snapshot --kind system"])
        rc, out = self.main("apply", "-y", "--no-snapshot", path)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls()[-1], "hostnamectl set-hostname saturn")

    def test_apply_failure_points_to_rollback(self):
        path = self.lsl_file('load config\nconfig = {"hostname": "saturn", "timezone": "Europe/Vienna"}\n')
        write(self.fake + "/fail", "timedatectl\n")
        rc, out = self.main("apply", "-y", path)
        self.assertEqual(rc, 1)
        self.assertIn("timedatectl: failed on purpose", out)
        self.assertIn("1 of 2 changes were made", out)
        self.assertIn("lux rollback 2026-10-26_12-00-00", out)
        self.assertFalse(os.path.exists(self.root + ls.APPLIED))

    def test_apply_refused_when_booted_from_snapshot(self):
        write(self.root + "/proc/cmdline", "root=UUID=abc luxos.snapshot=2026-10-20_10-00-00\n")
        path = self.lsl_file('load config\nconfig = {"hostname": "saturn"}\n')
        rc, out = self.main("apply", "-y", path)
        self.assertEqual(rc, 1)
        self.assertIn("running from a snapshot", out)
        self.assertEqual(self.calls(), [])

    def test_password_hash_goes_through_stdin(self):
        path = self.lsl_file('load config\nconfig = {"users": {"petr": {"password_hash": "$y$j9T$abc$def"}}}\n')
        rc, out = self.main("apply", "-y", "--no-snapshot", path)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("$y$", out)
        self.assertIn("chpasswd -e", self.calls())
        self.assertIn("petr:$y$j9T$abc$def", self.calls())


class TranslationTest(unittest.TestCase):
    def test_all_strings_translated(self):
        """Kazdy text _("...") a _c("...") z lux_system.py je ve vsech 12 prekladech."""
        import ast
        with open(os.path.join(HERE, "..", "lux_system.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        texts = set()
        for node in ast.walk(tree):
            # _c = komentare vygenerovaneho souboru (v jazyce systemu)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "_c", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant)):
                texts.add(node.args[0].value)
            # head("Nadpis", "radek", ...) a note("text") ve generate() prekladaji pres _c
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("head", "note")):
                texts |= {a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        # nazvy sekci a typy v Checker.typed se prekladaji pres promennou
        texts |= {t for _k, t in ls.SECTIONS}
        texts |= {"a text", "a list of texts", "a dictionary { }", "True or False", "a number", "package name",
                  "Flathub app ID", "service name", "group name", "user name", "computer name", "keyboard layout",
                  "keyboard option", "kernel parameter", "port (e.g. \"22/tcp\")", "IP address", "app ID",
                  "repository name"}
        i18n = os.path.join(HERE, "..", "..", "luxos-i18n", "files")
        for lang in ("cs", "sk", "pl", "uk", "hu", "de", "fr", "es", "it", "pt", "nl", "sv"):
            with open(os.path.join(i18n, lang + ".tsv"), encoding="utf-8") as f:
                tr = dict(line.rstrip("\n").split("\t", 1) for line in f if "\t" in line and not line.startswith("#"))
            missing = sorted(t for t in texts if not tr.get(t))
            self.assertEqual(missing, [], lang)
            for t in texts:
                self.assertEqual(t.count("%s"), tr[t].count("%s"), (lang, t))
                self.assertEqual(t.count("%d"), tr[t].count("%d"), (lang, t))


if __name__ == "__main__":
    unittest.main()
