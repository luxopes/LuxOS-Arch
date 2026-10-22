"""Testy prikazu lux (bash) se zastupnym backendem: ktere volani libalpm/pacmanu z prikazu vznikne.

    python3 -m unittest discover -s packages/lux/tests -v

Bez rootu a bez site: sudo, pacman, pacman-conf, pacman-key, curl a backend jsou nahrazene skripty,
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
# pacman predany v LUX_PACMAN z adresare .../alpm/ se zapisuje zvlast (alpm-pacman)
[[ $(basename "$(dirname "$0")") == alpm ]] && n=alpm-$n
printf '%s\\n' "$*" >>"$LOG/$n.log"
case "$(basename "$0")" in
  lux_alpm.py)
    for a in "$@"; do
      case $a in
        available) exit ${ALPM_AVAILABLE_RC:-0} ;;
        resolve) shift_done=1 ;;
      esac
    done
    if [[ " $* " == *" resolve "* ]]; then
      for a in "${@:$#}"; do :; done
      seen=0
      for a in "$@"; do
        ((seen)) && { [[ $a == nope ]] && printf 'none\\t%s\\n' "$a" || printf 'repo\\t%s\\n' "$a"; }
        [[ $a == -- ]] && seen=1
      done
    fi
    exit 0 ;;
  sudo|pkexec) exec "$@" ;;
  pacman)
    case $1 in
      -Qdtq) echo orphan-lib ;;
      -Q) [[ $2 == archlinux-keyring ]] && exit 0; exit 1 ;;
    esac
    exit 0 ;;
  pacman-conf)
    case $1 in
      DBPath) echo "$FAKEDB/" ;;
      CacheDir) echo "$FAKEDB/cache/" ;;
      GPGDir) echo "$FAKEDB/gnupg/" ;;
      LogFile) echo "$FAKEDB/pacman.log" ;;
    esac ;;
  timedatectl) echo yes ;;
  curl|jq|paccache|pacman-key|flatpak) exit 1 ;;
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
        for name in ("lux_alpm.py", "sudo", "pkexec", "pacman", "pacman-conf", "pacman-key", "timedatectl",
                     "curl", "jq", "paccache", "flatpak"):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(STUB)
            os.chmod(p, 0o755)
        with open(os.path.join(self.tmp, "cfg", "lux", "lux.conf"), "w") as f:
            f.write("AUR=0\nFLATPAK=0\n")
        with open(os.path.join(self.db, "pacman.log"), "w") as f:
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

    def test_help(self):
        rc, out = self.lux("--help")
        self.assertEqual(rc, 0)
        for cmd in ("install", "remove", "update, upgrade", "reinstall", "autoremove", "owns", "fix",
                    "list --upgradable", "history"):
            self.assertIn(cmd, out)
        self.assertNotIn("pacman", out)

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
        """Nastroje jadra jsou mimo PATH: lux je prida na zacatek (pro sebe, makepkg, checkupdates...)."""
        probe = os.path.join(self.bin, "lux-path-probe")
        out = subprocess.run(["bash", "-c", f'source <(sed -n "1,/^# --- Vystup/p" "{LUX}"); echo "$PATH"'],
                             env=dict(self.env, LUX_ENGINE_BIN="/opt/engine"), capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "/opt/engine:" + self.env["PATH"], out.stderr)
        out = subprocess.run(["bash", "-c", f'source <(sed -n "1,/^# --- Vystup/p" "{LUX}"); echo "$PATH"'],
                             env=dict(self.env, LUX_ENGINE_BIN="/opt/engine", PATH="/usr/bin:/opt/engine"),
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "/usr/bin:/opt/engine")          # bez duplicit
        self.assertFalse(os.path.exists(probe))

    def test_configs_runs_pacdiff_with_engine_tools(self):
        """lux configs: pacdiff (vola pacman a pacman-conf jmenem) bezi jako root s nastroji jadra v PATH."""
        for name, body in (("pacdiff", 'printf "%s|%s\\n" "$*" "$PATH" >>"$LOG/pacdiff.log"\n'),
                           ("find", 'echo /etc/pacman.conf.pacnew\n')):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write("#!/bin/bash\n" + body)
            os.chmod(p, 0o755)
        rc, out = self.lux("configs", "--output")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.calls("sudo")), 1)
        args, path = self.calls("pacdiff")[0].split("|")
        self.assertEqual(args, "--output")
        self.assertEqual(path, f"{self.bin}:/usr/local/sbin:/usr/local/bin:/usr/bin")
        # bez novych konfiguracnich souboru se nic nespousti
        with open(os.path.join(self.bin, "find"), "w") as f:
            f.write("#!/bin/bash\nexit 0\n")
        os.remove(os.path.join(self.log, "pacdiff.log"))
        rc, out = self.lux("configs")
        self.assertEqual(rc, 0, out)
        self.assertIn("No pending config files", out)
        self.assertEqual(self.calls("pacdiff"), [])

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

    def test_fallback_to_pacman(self):
        for env in ({"LUX_BACKEND": "pacman"}, {"ALPM_AVAILABLE_RC": "3"}):
            shutil.rmtree(self.log)
            os.makedirs(self.log)
            rc, out = self.lux("-y", "install", "htop", env=env)
            self.assertEqual(rc, 0, out)
            self.assertIn("-S --needed --noconfirm htop", self.calls("pacman"))
            self.assertEqual(self.backend(), [])
            rc, out = self.lux("-y", "remove", "htop", env=env)
            self.assertIn("-Rns --noconfirm htop", self.calls("pacman"))
            rc, out = self.lux("-y", "autoremove", env=env)
            self.assertIn("-Rns --noconfirm orphan-lib", self.calls("pacman"))
            rc, out = self.lux("-y", "reinstall", "htop", env=env)
            self.assertIn("-S --noconfirm htop", self.calls("pacman"))
            rc, out = self.lux("list", "--upgradable", env=env)
            self.assertIn("-Qu", self.calls("pacman"))

    def test_fallback_uses_real_pacman_not_shim(self):
        """Zalozni cesta vola pacman z LUX_PACMAN (v LuxOS /usr/lib/lux/alpm/bin/pacman z lux-engine)."""
        alpm = os.path.join(self.tmp, "alpm")
        os.makedirs(alpm)
        real = os.path.join(alpm, "pacman")
        with open(real, "w") as f:
            f.write(STUB)
        os.chmod(real, 0o755)
        env = {"LUX_BACKEND": "pacman", "LUX_PACMAN": real}
        for args in (("-y", "install", "htop"), ("-y", "remove", "htop"), ("-y", "autoremove"),
                     ("-y", "reinstall", "htop"), ("list", "--upgradable"), ("list",), ("files", "htop"),
                     ("owns", "/usr/bin/htop"), ("info", "htop"), ("search", "htop"), ("doctor",)):
            self.lux(*args, env=env)
        real_calls = self.calls("alpm-pacman")
        for want in ("-S --needed --noconfirm htop", "-Rns --noconfirm htop", "-Rns --noconfirm orphan-lib",
                     "-S --noconfirm htop", "-Qu", "-Q", "-Qlq -- htop", "-Qo -- /usr/bin/htop"):
            self.assertIn(want, real_calls)
        self.assertTrue(any(x.startswith("-Ss") for x in real_calls), real_calls)
        self.assertEqual(self.calls("pacman"), [])
        # neexistujici LUX_PACMAN -> pacman z PATH (system bez lux-engine)
        shutil.rmtree(self.log)
        os.makedirs(self.log)
        rc, out = self.lux("-y", "install", "htop", env={"LUX_BACKEND": "pacman", "LUX_PACMAN": "/nonexistent"})
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

    @unittest.skipUnless(shutil.which("unshare") and subprocess.run(["unshare", "-r", "true"]).returncode == 0,
                         "unshare -r neni k dispozici")
    def test_fix_removes_stale_lock_and_refreshes_keys(self):
        lock = os.path.join(self.db, "db.lck")
        open(lock, "w").close()
        open(os.path.join(self.db, "cache", "x.pkg.tar.zst.part"), "w").close()
        rc, out = self.lux("-y", "__fix", prefix=("unshare", "-r"))
        self.assertEqual(rc, 1, out)                 # pacman-key (zastupny) selze -> srozumitelna chyba
        self.assertIn("Could not load the signing keys", out)
        self.assertFalse(os.path.exists(lock))
        self.assertFalse(os.path.exists(os.path.join(self.db, "cache", "x.pkg.tar.zst.part")))
        # s fungujicim pacman-key: klice se obnovi pres backend
        with open(os.path.join(self.bin, "pacman-key"), "w") as f:
            f.write("#!/bin/bash\nprintf '%s\\n' \"$*\" >>\"$LOG/pacman-key.log\"\n")
        rc, out = self.lux("-y", "__fix", prefix=("unshare", "-r"))
        self.assertEqual(rc, 0, out)
        self.assertIn("--populate", self.calls("pacman-key"))
        self.assertIn("install --refresh --needed -- archlinux-keyring", self.backend())
        self.assertIn("Package manager repaired", out)

    def test_fix_needs_root_and_keeps_live_lock(self):
        rc, out = self.lux("__fix")
        self.assertEqual(rc, 1)
        # bezici spravce baliku: zamek zustane
        lock = os.path.join(self.db, "db.lck")
        open(lock, "w").close()
        # proces se jmenem "pacman" (prctl PR_SET_NAME) = bezici spravce baliku: zamek zustane
        fake = subprocess.Popen(["python3", "-c", "import time, ctypes; "
                                 "ctypes.CDLL(None).prctl(15, b'pacman', 0, 0, 0); time.sleep(10)"])
        try:
            time.sleep(0.3)
            rc, out = self.lux("-y", "__fix", prefix=("unshare", "-r"))
            self.assertIn("Another package manager is running (pacman)", out)
            self.assertTrue(os.path.exists(lock))
        finally:
            fake.kill()
            fake.wait()

if __name__ == "__main__":
    unittest.main()
