"""Testy prikazu lux (bash) se zastupnym backendem: ktere volani libalpm/pacmanu z prikazu vznikne.

    python3 -m unittest discover -s packages/lux/tests -v

Bez rootu a bez site: sudo, lux-engine, lux-engine-conf, lux-engine-key, lux-config, curl a backend jsou
nahrazene skripty,
ktere jen zapisi sve argumenty. "lux fix" bezi v uzivatelskem jmennem prostoru (unshare -r).
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LUX = os.path.join(HERE, "..", "lux")

STUB = """#!/bin/bash
n=$(basename "$0")
# nastroj jadra predany v LUX_ENGINE z adresare .../alpm/ se zapisuje zvlast (alpm-lux-engine)
[[ $(basename "$(dirname "$0")") == alpm ]] && n=alpm-$n
printf '%s\\n' "$*" >>"$LOG/$n.log"
case "$(basename "$0")" in
  lux_alpm.py)
    for a in "$@"; do
      case $a in
        available) exit ${ALPM_AVAILABLE_RC:-0} ;;
        check-updates) printf '%b' "${CHECK_OUT-}"; exit ${CHECK_RC:-2} ;;
        resolve) shift_done=1 ;;
      esac
    done
    if [[ " $* " == *" resolve "* ]]; then
      for a in "${@:$#}"; do :; done
      seen=0
      for a in "$@"; do
        ((seen)) && { [[ $a == nope || " ${NOT_IN_REPO-} " == *" $a "* ]] && printf 'none\\t%s\\n' "$a" || printf 'repo\\t%s\\n' "$a"; }
        [[ $a == -- ]] && seen=1
      done
    fi
    exit 0 ;;
  sudo|pkexec) exec "$@" ;;
  lux-engine|pacman)
    case $1 in
      -Qdtq) echo orphan-lib ;;
      -Q) [[ $2 == archlinux-keyring ]] && exit 0; exit 1 ;;
      -Sp|-Sg) for a; do [[ " ${NOT_IN_REPO-} " == *" $a "* ]] && exit 1; done; exit 0 ;;
    esac
    exit 0 ;;
  lux-engine-conf)
    case $1 in
      DBPath) echo "$FAKEDB/" ;;
      CacheDir) echo "$FAKEDB/cache/" ;;
      GPGDir) echo "$FAKEDB/gnupg/" ;;
      LogFile) echo "$FAKEDB/lux.log" ;;
    esac ;;
  lux-config)
    case $1 in
      env) [[ ${LUX_CONFIG_RC:-0} == 0 ]] || { echo "lux: error in the configuration: /etc/lux/lux.conf:3: unknown key 'x'" >&2; exit 1; }
           printf 'AUR=0\nREVIEW_PKGBUILD=1\nFLATPAK=0\nCLEAN_KEEP=3\nLUX_ENGINE_CONF=/run/lux/engine.conf\n' ;;
      check) exit ${LUX_CONFIG_RC:-0} ;;
      mirrors-import) cp "$2" "$4.converted" ;;
    esac ;;
  reflector) for a; do [[ $prev == --save ]] && echo "Server = https://x/\\$repo/os/\\$arch" >"$a"; prev=$a; done ;;
  timedatectl) echo yes ;;
  curl|jq|lux-engine-key|flatpak) exit 1 ;;
esac
exit 0
"""


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lux-cli-test-")
        self.bin = os.path.join(self.tmp, "bin")
        self.log = os.path.join(self.tmp, "log")
        self.db = os.path.join(self.tmp, "db")
        for d in (self.bin, self.log, self.db, os.path.join(self.tmp, "cfg", "lux"),
                  os.path.join(self.db, "gnupg"), os.path.join(self.db, "cache")):
            os.makedirs(d)
        with open(os.path.join(self.db, "gnupg", "pubring.gpg"), "w") as f:
            f.write("x")
        for name in ("lux_alpm.py", "sudo", "pkexec", "lux-engine", "lux-engine-conf", "lux-engine-key", "lux-config",
                     "timedatectl", "curl", "jq", "flatpak", "reflector", "lux_system.py"):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(STUB)
            os.chmod(p, 0o755)
        with open(os.path.join(self.db, "lux.log"), "w") as f:
            f.write("[2026-10-20T10:00:00+0200] [ALPM] installed htop (3.3.0-1)\n"
                    "[2026-10-21T11:00:00+0200] [ALPM] upgraded firefox (130.0-1 -> 131.0-1)\n"
                    "[2026-10-21T12:00:00+0200] [ALPM] removed vlc (3.0.21-1)\n"
                    "[2026-10-21T12:00:01+0200] [ALPM] transaction completed\n")
        self.env = {
            "PATH": self.bin + ":/usr/bin:/bin",
            "HOME": self.tmp,
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "cfg"),
            "XDG_CACHE_HOME": os.path.join(self.tmp, "cache"),
            "LUX_ALPM": os.path.join(self.bin, "lux_alpm.py"),
            "LUX_CONFIG": os.path.join(self.bin, "lux-config"),
            "LUX_SYSTEM": os.path.join(self.bin, "lux_system.py"),
            # nastroje jadra (v LuxOS /usr/lib/lux/alpm/bin): zastupne skripty, i v PATH pro roota
            "LUX_ENGINE_BIN": self.bin,
            "LOG": self.log,
            "FAKEDB": self.db,
            "LANG": "C.UTF-8",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lux(self, *args, env=None, prefix=()):
        e = dict(self.env, **(env or {}))
        r = subprocess.run(list(prefix) + ["bash", LUX] + list(args), env=e, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def calls(self, name):
        try:
            with open(os.path.join(self.log, name + ".log")) as f:
                return [x for x in f.read().splitlines()]
        except OSError:
            return []

    def backend(self):
        """Volani backendu bez uvodnich voleb (--color, --lang...)."""
        out = []
        for line in self.calls("lux_alpm.py"):
            if line == "available":
                continue
            words = line.split()
            while words and words[0].startswith("-") and words[0] != "--":
                words.pop(0)
                if words and words[0] in ("C.UTF-8",):
                    words.pop(0)
            out.append(" ".join(words))
        return out

    def test_domain(self):
        """lux domain: preda vse prikazu lux-domain (balik luxos-domain), -y jako --yes; bez baliku rada."""
        stub = os.path.join(self.bin, "lux-domain")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, 0o755)
        rc, out = self.lux("-y", "domain", "join", "firma.local", "-U", "admin", env={"LUX_DOMAIN": stub})
        self.assertEqual(rc, 0, out)
        rc, out = self.lux("domain", "status", "--json", env={"LUX_DOMAIN": stub})
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls("lux-domain"), ["join firma.local -U admin --yes", "status --json"])
        rc, out = self.lux("domain", "status", env={"LUX_DOMAIN": os.path.join(self.tmp, "missing")})
        self.assertEqual(rc, 1)
        self.assertIn("lux install luxos-domain", out)

    def test_system(self):
        """lux system: show/check bez roota, diff/apply/init pres sudo, -y se preda dal."""
        rc, out = self.lux("system", "show")
        self.assertEqual(rc, 0, out)
        rc, out = self.lux("-y", "system", "apply", "--no-snapshot", "/tmp/x.lsl")
        self.assertEqual(rc, 0, out)
        rc, out = self.lux("sys", "diff", "--json")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls("lux_system.py"), ["show", "apply -y --no-snapshot /tmp/x.lsl", "diff --json"])
        sudo = self.calls("sudo")
        self.assertEqual(len(sudo), 2)                   # apply a diff, show ne
        self.assertTrue(all("lux_system.py" in c for c in sudo), sudo)
        rc, out = self.lux("system")
        self.assertEqual(rc, 0)
        self.assertIn("lux system <", out)
        self.assertIn("man luxos-system", out)
        rc, out = self.lux("system", "nonsense")
        self.assertEqual(rc, 1)
        rc, out = self.lux("system", "edit", env={"LUX_SYSTEM_FILE": os.path.join(self.tmp, "missing.lsl")})
        self.assertEqual(rc, 1)
        self.assertIn("lux system init", out)

    def test_help(self):
        rc, out = self.lux("--help")
        self.assertEqual(rc, 0)
        for cmd in ("install", "remove", "update, upgrade", "reinstall", "autoremove", "owns", "fix",
                    "list --upgradable", "history"):
            self.assertIn(cmd, out)
        self.assertNotIn("pacman", out)
        self.assertIn("config check, edit", out)

    def test_man_page_covers_help(self):
        """lux(1) popisuje kazdy prikaz a volbu z lux --help (pri novem prikazu doplnit i lux.1)."""
        import re
        rc, out = self.lux("--help", env={"NO_COLOR": "1"})
        self.assertEqual(rc, 0)
        with open(os.path.join(HERE, "..", "lux.1")) as f:
            man = f.read().replace("\\-", "-")
        words = set()
        for line in out.splitlines():
            m = re.match(r"^  (\S.*?)\s{2,}\S", line)
            if not m or m.group(1).startswith("("):
                continue
            for w in re.split(r"[ ,]+", m.group(1)):
                if w and not w.startswith(("<", "[")):
                    words.add(w.strip("[]"))
        self.assertIn("check", words)
        self.assertIn("--verbose", words)
        missing = sorted(w for w in words if not re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", man))
        self.assertEqual(missing, [], "lux.1 does not describe: " + ", ".join(missing))

    def test_check_lists_updates(self):
        """lux check: dostupne aktualizace z docasne kopie seznamu (bez roota), pocet a co dal."""
        rc, out = self.lux("check", env={"NO_COLOR": "1", "CHECK_RC": "0",
                                         "CHECK_OUT": "firefox 131.0-1 -> 132.0-1\\nvlc 3.0.21-1 -> 3.0.22-1\\n"})
        self.assertEqual(rc, 0, out)
        self.assertIn("firefox 131.0-1 → 132.0-1", out)
        self.assertIn("2 update(s) available - run: lux update", out)
        self.assertIn("check-updates", self.backend())
        self.assertEqual(self.calls("sudo"), [])
        rc, out = self.lux("check-updates", env={"NO_COLOR": "1"})       # CHECK_RC 2 = zadne
        self.assertEqual(rc, 0, out)
        self.assertIn("System up to date", out)
        rc, out = self.lux("check", env={"NO_COLOR": "1", "CHECK_RC": "1",
                                         "CHECK_OUT": "The package lists could not be refreshed.\\n"})
        self.assertEqual(rc, 1)
        self.assertIn("could not be refreshed", out)

    def test_broken_config_refuses(self):
        """Chyba v /etc/lux/lux.conf: lux nic neudela, rekne soubor a radek a jak to zkontrolovat."""
        rc, out = self.lux("install", "htop", env={"LUX_CONFIG_RC": "1"})
        self.assertEqual(rc, 1)
        self.assertIn("/etc/lux/lux.conf:3: unknown key 'x'", out)
        self.assertIn("lux config check", out)
        self.assertEqual(self.backend(), [])
        rc, out = self.lux("config", "check", env={"LUX_CONFIG_RC": "1"})
        self.assertEqual(rc, 1)
        self.assertEqual(self.calls("lux-config")[-1], "check")
        rc, out = self.lux("--help", env={"LUX_CONFIG_RC": "1"})
        self.assertEqual(rc, 0)

    def test_settings_from_lux_config(self):
        """AUR/FLATPAK/CLEAN_KEEP z lux-config env (lux.conf + ~/.config/lux/lux.conf)."""
        rc, out = self.lux("clean")
        self.assertEqual(rc, 0, out)
        self.assertIn("keeping 3 versions", out)
        self.assertIn("clean --keep 3 --keep-uninstalled 0", self.backend())
        self.assertEqual(self.calls("paccache"), [])

    @unittest.skipUnless(shutil.which("unshare") and subprocess.run(["unshare", "-r", "true"]).returncode == 0,
                         "unshare -r neni k dispozici")
    def test_mirrors_converts_reflector_output(self):
        ml = os.path.join(self.tmp, "mirrorlist")
        rc, out = self.lux("mirrors", env={"LUX_MIRRORLIST": ml}, prefix=("unshare", "-r"))
        self.assertEqual(rc, 0, out)
        self.assertTrue(any("--save" in c for c in self.calls("reflector")))
        imp = [c for c in self.calls("lux-config") if c.startswith("mirrors-import")][0]
        self.assertTrue(imp.endswith("--output " + ml))
        with open(ml + ".converted") as f:
            self.assertIn("Server = https://x/", f.read())

    def test_install_through_backend_as_root(self):
        rc, out = self.lux("install", "htop")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.backend(), ["resolve -- htop", "install --needed -- htop"])
        sudo = self.calls("sudo")
        self.assertEqual(len(sudo), 1)
        # sudo nastavi vlastni PATH: lux preda pevnou cestu s nastroji jadra (hooky, skriptlety), ne PATH uzivatele
        self.assertIn(f"/usr/bin/env PATH={self.bin}:/usr/local/sbin:/usr/local/bin:/usr/bin LUX_COLOR=never LANG=C.UTF-8",
                      sudo[0])
        self.assertNotIn(":/bin ", sudo[0])
        self.assertIn("--color=never", sudo[0])
        self.assertNotIn(" -y ", sudo[0])                     # bez -y se nic nepotvrzuje samo

    def test_engine_tools_on_path(self):
        """Nastroje jadra jsou mimo PATH: lux je prida na zacatek (pro sebe, makepkg, hooky...)."""
        probe = os.path.join(self.bin, "lux-path-probe")
        out = subprocess.run(["bash", "-c", f'source <(sed -n "1,/^# --- Vystup/p" "{LUX}"); echo "$PATH"'],
                             env=dict(self.env, LUX_ENGINE_BIN="/opt/engine"), capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "/opt/engine:" + self.env["PATH"], out.stderr)
        out = subprocess.run(["bash", "-c", f'source <(sed -n "1,/^# --- Vystup/p" "{LUX}"); echo "$PATH"'],
                             env=dict(self.env, LUX_ENGINE_BIN="/opt/engine", PATH="/usr/bin:/opt/engine"),
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "/usr/bin:/opt/engine")          # bez duplicit
        self.assertFalse(os.path.exists(probe))

    @unittest.skipUnless(shutil.which("unshare") and subprocess.run(["unshare", "-r", "true"]).returncode == 0,
                         "unshare -r neni k dispozici")
    def test_configs_own_implementation(self):
        """lux configs: vlastni porovnani .pacnew/.pacsave (bez pacdiff); s -y se nic nemeni."""
        etc = os.path.join(self.tmp, "etc")
        os.makedirs(etc)
        for name, text in (("a.conf", "old\n"), ("a.conf.pacnew", "new\n"), ("b.conf.pacsave", "saved\n")):
            with open(os.path.join(etc, name), "w") as f:
                f.write(text)
        env = {"LUX_CONFIGS_ROOT": etc}
        rc, out = self.lux("-y", "configs", env=env, prefix=("unshare", "-r"))
        self.assertEqual(rc, 0, out)
        self.assertIn("a.conf", out)
        self.assertIn("-old", out)                   # rozdil
        self.assertIn("+new", out)
        self.assertIn("b.conf.pacsave", out)
        self.assertEqual(sorted(os.listdir(etc)), ["a.conf", "a.conf.pacnew", "b.conf.pacsave"])
        for name in os.listdir(etc):
            os.unlink(os.path.join(etc, name))
        rc, out = self.lux("configs", env=env, prefix=("unshare", "-r"))
        self.assertEqual(rc, 0, out)
        self.assertIn("No pending config files", out)
        self.assertEqual(self.calls("sudo"), [])

    def test_install_not_found_installs_nothing(self):
        rc, out = self.lux("install", "htop", "nope")
        self.assertEqual(rc, 1)
        self.assertIn("Package 'nope' not found", out)
        self.assertEqual(self.backend(), ["resolve -- htop nope"])

    def test_yes_and_verbose_passed(self):
        rc, out = self.lux("-y", "--verbose", "upgrade")
        self.assertEqual(rc, 0, out)
        line = [x for x in self.calls("lux_alpm.py") if "update" in x][0]
        self.assertIn(" -y ", " " + line + " ")
        self.assertIn("--verbose", line)
        self.assertTrue(line.endswith("update"))

    def test_commands_map_to_backend(self):
        for args, want in ((("remove", "htop"), "remove -- htop"),
                           (("reinstall", "htop"), "reinstall -- htop"),
                           (("autoremove",), "autoremove"),
                           (("list", "--upgradable"), "list --upgradable"),
                           (("list",), "list --installed"),
                           (("list", "fire"), "list --installed -- fire"),
                           (("files", "htop"), "files -- htop"),
                           (("owns", "/usr/bin/htop"), "owns -- /usr/bin/htop"),
                           (("owner", "/usr/bin/htop"), "owns -- /usr/bin/htop"),
                           (("search", "vim"), "search -- vim"),
                           (("info", "htop"), "info -- htop")):
            os.unlink(os.path.join(self.log, "lux_alpm.py.log")) if self.calls("lux_alpm.py") else None
            rc, out = self.lux(*args)
            self.assertIn(want, self.backend(), (args, out))

    def test_datasaver_flag(self):
        os.makedirs(os.path.join(self.tmp, "cfg", "luxos"))
        open(os.path.join(self.tmp, "cfg", "luxos", "datasaver"), "w").close()
        self.lux("install", "htop")
        self.assertTrue(any("--datasaver" in x for x in self.calls("lux_alpm.py") if "install" in x))

    def test_no_color_and_lang(self):
        self.lux("search", "vim", env={"LANG": "cs_CZ.UTF-8", "NO_COLOR": "1"})
        line = [x for x in self.calls("lux_alpm.py") if "search" in x][0]
        self.assertIn("--color=never", line)
        self.assertIn("--lang cs_CZ.UTF-8", line)

    def test_fallback_to_engine(self):
        for env in ({"LUX_BACKEND": "engine"}, {"ALPM_AVAILABLE_RC": "3"}):
            shutil.rmtree(self.log)
            os.makedirs(self.log)
            rc, out = self.lux("-y", "install", "htop", env=env)
            self.assertEqual(rc, 0, out)
            self.assertIn("-S --needed --noconfirm htop", self.calls("lux-engine"))
            self.assertEqual(self.backend(), [])
            rc, out = self.lux("-y", "remove", "htop", env=env)
            self.assertIn("-Rns --noconfirm htop", self.calls("lux-engine"))
            rc, out = self.lux("-y", "autoremove", env=env)
            self.assertIn("-Rns --noconfirm orphan-lib", self.calls("lux-engine"))
            rc, out = self.lux("-y", "reinstall", "htop", env=env)
            self.assertIn("-S --noconfirm htop", self.calls("lux-engine"))
            rc, out = self.lux("list", "--upgradable", env=env)
            self.assertIn("-Qu", self.calls("lux-engine"))

    def test_fallback_uses_engine_tool(self):
        """Zalozni cesta vola nastroj jadra z LUX_ENGINE (v LuxOS /usr/lib/lux/alpm/bin/lux-engine)."""
        alpm = os.path.join(self.tmp, "alpm")
        os.makedirs(alpm)
        real = os.path.join(alpm, "lux-engine")
        with open(real, "w") as f:
            f.write(STUB)
        os.chmod(real, 0o755)
        env = {"LUX_BACKEND": "engine", "LUX_ENGINE": real}
        for args in (("-y", "install", "htop"), ("-y", "remove", "htop"), ("-y", "autoremove"),
                     ("-y", "reinstall", "htop"), ("list", "--upgradable"), ("list",), ("files", "htop"),
                     ("owns", "/usr/bin/htop"), ("info", "htop"), ("search", "htop"), ("doctor",)):
            self.lux(*args, env=env)
        real_calls = self.calls("alpm-lux-engine")
        for want in ("-S --needed --noconfirm htop", "-Rns --noconfirm htop", "-Rns --noconfirm orphan-lib",
                     "-S --noconfirm htop", "-Qu", "-Q", "-Qlq -- htop", "-Qo -- /usr/bin/htop"):
            self.assertIn(want, real_calls)
        self.assertTrue(any(x.startswith("-Ss") for x in real_calls), real_calls)
        self.assertEqual(self.calls("lux-engine"), [])

    def test_luxos_090_engine_before_replacement(self):
        """LuxOS 0.9.0 (luxos-pacman): jen alpm/pacman a bez lux-config - lux funguje, lux update jadro vymeni."""
        alpm = os.path.join(self.tmp, "old-alpm")
        os.makedirs(alpm)
        with open(os.path.join(alpm, "pacman"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(alpm, "pacman"), 0o755)
        rc, out = self.lux("-y", "install", "htop", env={"LUX_BACKEND": "engine", "LUX_ENGINE_BIN": alpm,
                                                         "LUX_CONFIG": "/nonexistent"})
        self.assertEqual(rc, 0, out)
        self.assertIn("-S --needed --noconfirm htop", self.calls("pacman"))

    def test_history(self):
        rc, out = self.lux("history")
        self.assertEqual(rc, 0, out)
        lines = out.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("upgraded", lines[1])
        self.assertIn("firefox", lines[1])
        self.assertIn("2026-10-21 11:00", lines[1])
        rc, out = self.lux("history", "htop")
        self.assertEqual(len(out.splitlines()), 1)
        rc, out = self.lux("history", "1")
        self.assertIn("vlc", out)
        self.assertEqual(len(out.splitlines()), 1)

    # -- snimky systemu (luxos-care) --
    SNAPS = ('[{"name": "2026-10-25_10-00-00", "label": "LuxOS (before update of 2026-10-25 10:00)"},'
             ' {"name": "2026-10-26_14-03-12", "label": "LuxOS (before update of 2026-10-26 14:03)"}]')

    def care_stub(self, cmdline="quiet splash"):
        care = os.path.join(self.bin, "luxos-care")
        with open(care, "w") as f:
            f.write('#!/bin/bash\nprintf "%s\\n" "$*" >>"$LOG/luxos-care.log"\n'
                    '[[ $1 == snapshots && $2 == --json ]] && printf "%s" "$SNAPS"\nexit 0\n')
        os.chmod(care, 0o755)
        os.unlink(os.path.join(self.bin, "jq"))           # skutecny jq
        cl = os.path.join(self.tmp, "cmdline")
        with open(cl, "w") as f:
            f.write(cmdline + "\n")
        return {"LUX_CARE": care, "LUX_CMDLINE": cl, "SNAPS": self.SNAPS, "NO_COLOR": "1"}

    def lux_input(self, text, *args, env=None):
        r = subprocess.run(["bash", LUX] + list(args), env=dict(self.env, **(env or {})), input=text,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr

    @unittest.skipUnless(shutil.which("jq"), "jq")
    def test_snapshots_and_snapshot(self):
        env = self.care_stub()
        rc, out = self.lux("snapshots", env=env)
        self.assertEqual(rc, 0, out)
        rc, out = self.lux("snapshot", env=env)
        self.assertEqual(self.calls("luxos-care"), ["snapshots", "snapshot"])

    @unittest.skipUnless(shutil.which("jq"), "jq")
    def test_rollback_choose_and_confirm(self):
        env = self.care_stub()
        rc, out = self.lux_input("1\ny\n", "rollback", env=env)
        self.assertEqual(rc, 0, out)
        self.assertLess(out.index("2026-10-26 14:03"), out.index("2026-10-25 10:00"))     # nejnovejsi prvni
        self.assertEqual(self.calls("luxos-care"), ["snapshots --json", "rollback 2026-10-26_14-03-12 --yes"])

    @unittest.skipUnless(shutil.which("jq"), "jq")
    def test_rollback_default_no(self):
        env = self.care_stub()
        rc, out = self.lux_input("2\n\n", "rollback", env=env)
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.calls("luxos-care"), ["snapshots --json"])
        rc, out = self.lux_input("", "rollback", "2020-01-01_00-00-00", env=env)
        self.assertIn("No such snapshot", out)

    @unittest.skipUnless(shutil.which("jq"), "jq")
    def test_rollback_booted_snapshot(self):
        env = self.care_stub("rw luxos.snapshot=2026-10-25_10-00-00 systemd.volatile=overlay")
        rc, out = self.lux("-y", "rollback", env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("running from a snapshot", out)
        self.assertEqual(self.calls("luxos-care")[-1], "rollback 2026-10-25_10-00-00 --yes")

    def test_rollback_without_care(self):
        rc, out = self.lux("rollback", env={"LUX_CARE": "/nonexistent"})
        self.assertNotEqual(rc, 0)
        self.assertIn("LuxOS Care", out)

    @unittest.skipUnless(shutil.which("unshare") and subprocess.run(["unshare", "-r", "true"]).returncode == 0,
                         "unshare -r neni k dispozici")
    def test_fix_removes_stale_lock_and_refreshes_keys(self):
        lock = os.path.join(self.db, "db.lck")
        open(lock, "w").close()
        open(os.path.join(self.db, "cache", "x.pkg.tar.zst.part"), "w").close()
        rc, out = self.lux("-y", "__fix", prefix=("unshare", "-r"))
        self.assertEqual(rc, 1, out)                 # lux-engine-key (zastupny) selze -> srozumitelna chyba
        self.assertIn("Could not load the signing keys", out)
        self.assertFalse(os.path.exists(lock))
        self.assertFalse(os.path.exists(os.path.join(self.db, "cache", "x.pkg.tar.zst.part")))
        # s fungujicim lux-engine-key: klice se obnovi pres backend
        with open(os.path.join(self.bin, "lux-engine-key"), "w") as f:
            f.write("#!/bin/bash\nprintf '%s\\n' \"$*\" >>\"$LOG/lux-engine-key.log\"\n")
        rc, out = self.lux("-y", "__fix", prefix=("unshare", "-r"))
        self.assertEqual(rc, 0, out)
        self.assertIn("--populate", self.calls("lux-engine-key"))
        self.assertIn("install --refresh --needed -- archlinux-keyring", self.backend())
        self.assertIn("Package manager repaired", out)

    def test_fix_needs_root_and_keeps_live_lock(self):
        rc, out = self.lux("__fix")
        self.assertEqual(rc, 1)
        # bezici spravce baliku: zamek zustane
        lock = os.path.join(self.db, "db.lck")
        open(lock, "w").close()
        # proces se jmenem "lux-engine" (prctl PR_SET_NAME) = bezici spravce baliku: zamek zustane
        fake = subprocess.Popen(["python3", "-c", "import time, ctypes; "
                                 "ctypes.CDLL(None).prctl(15, b'lux-engine', 0, 0, 0); time.sleep(10)"])
        try:
            time.sleep(0.3)
            rc, out = self.lux("-y", "__fix", prefix=("unshare", "-r"))
            self.assertIn("Another package manager is running (lux-engine)", out)
            self.assertTrue(os.path.exists(lock))
        finally:
            fake.kill()
            fake.wait()

if __name__ == "__main__":
    unittest.main()
