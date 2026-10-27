"""Testy lux-engine-migrate nad falesnym korenem: nova instalace, stare rozlozeni (LuxOS 0.9.5),
prerusena migrace (vypadek proudu), uz migrovany system, uklid.

    python3 -m unittest discover -s packages/lux-engine/tests -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(PKG, "lux-engine-migrate")
sys.path.insert(0, HERE)
from test_lux_config import OLD_PACMAN_CONF  # noqa: E402

LEGACY_LUX_CONF = """# lux - konfigurace spravce baliku LuxOS
# Uzivatelske prepsani: ~/.config/lux/lux.conf

# Povolit AUR (komunitni baliky)
AUR=1
# Pred sestavenim z AUR nabidnout kontrolu PKGBUILD
REVIEW_PKGBUILD=1
# Aktualizovat i aplikace Flatpak (pokud je flatpak nainstalovan)
FLATPAK=1
# Kolik verzi baliku ponechat v cache pri "lux clean"
CLEAN_KEEP=2
"""


class MigrateBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lux-migrate-test-")
        # soubory noveho baliku lux-engine (po extrakci, pred hookem)
        for rel, src in (("usr/share/lux/lux.conf.default", "lux.conf"), ("usr/share/lux/mirrorlist.default", "mirrorlist"),
                         ("etc/lux/mirrorlist", "mirrorlist")):
            os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
            shutil.copy(os.path.join(PKG, src), self.p(rel))
        os.makedirs(self.p("usr/lib/lux/alpm/bin"))
        os.makedirs(self.p("var/lib/lux"))
        os.makedirs(self.p("var/cache/lux/pkg"))
        os.makedirs(self.p("etc/lux/conf.d"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def p(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), "w") as f:
            f.write(text)

    def read(self, rel):
        with open(self.p(rel)) as f:
            return f.read()

    def run_m(self, *args):
        env = dict(os.environ, LUX_LIB=PKG)
        return subprocess.run([sys.executable, SCRIPT] + list(args) + ["--root", self.root],
                              capture_output=True, text=True, env=env)

    def old_layout(self, lux_conf=LEGACY_LUX_CONF, pacman_conf=OLD_PACMAN_CONF, pacsave=False, saved=".pacsave"):
        """Instalace LuxOS 0.9.5 ve chvili hooku: stary lux-engine uz odebral sve soubory."""
        os.makedirs(self.p("var/lib/pacman/local/glibc-2.42-1"))
        self.write("var/lib/pacman/local/ALPM_DB_VERSION", "9\n")
        self.write("var/lib/pacman/local/glibc-2.42-1/desc", "%NAME%\nglibc\n")
        os.makedirs(self.p("var/lib/pacman/sync"))
        self.write("var/lib/pacman/sync/core.db", "db")
        self.write("var/lib/pacman/db.lck", "")             # zamek drzi stary proces jadra
        self.write("var/lib/lux/installed/app.json", "{}")  # balicky .lux
        self.write("var/cache/pacman/pkg/glibc-2.42-1-x86_64.pkg.tar.zst", "pkg")
        self.write("etc/pacman.d/gnupg/pubring.gpg", "keys")
        self.write("etc/pacman.d/hooks/99-luxos-esp-sync.hook", "[Trigger]\n")
        self.write("etc/pacman.d/mirrorlist", "## ranked\nServer = https://fast.example/$repo/os/$arch\n"
                   "Server = https://second.example/$repo/os/$arch\n")
        self.write("var/log/pacman.log", "[2026-10-01T10:00:00+0200] [ALPM] installed glibc (2.42-1)\n")
        if pacman_conf is not None:
            self.write("etc/pacman.conf" + saved if pacsave else "etc/pacman.conf", pacman_conf)
        if lux_conf is not None:
            self.write("etc/lux/lux.conf", lux_conf)
            # novy lux-engine vlastni lux.conf: na disku zustal stary soubor, novy je .pacnew
            shutil.copy(os.path.join(PKG, "lux.conf"), self.p("etc/lux/lux.conf.pacnew"))

    def assert_migrated(self):
        for old, new in (("var/lib/pacman", "lux"), ("var/cache/pacman/pkg", "../lux/pkg"),
                         ("etc/pacman.d/gnupg", "../lux/keyring"), ("etc/pacman.d/hooks", "../lux/hooks"),
                         ("var/log/pacman.log", "lux.log")):
            self.assertTrue(os.path.islink(self.p(old)), old)
            self.assertEqual(os.readlink(self.p(old)), new, old)     # relativni (funguje i s pacman -r)
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/local/glibc-2.42-1/desc")))
        self.assertEqual(self.read("var/lib/lux/local/ALPM_DB_VERSION"), "9\n")
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/sync/core.db")))
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/installed/app.json")))
        self.assertTrue(os.path.isfile(self.p("var/cache/lux/pkg/glibc-2.42-1-x86_64.pkg.tar.zst")))
        self.assertEqual(self.read("etc/lux/keyring/pubring.gpg"), "keys")
        self.assertTrue(os.path.isfile(self.p("etc/lux/hooks/99-luxos-esp-sync.hook")))
        self.assertIn("installed glibc", self.read("var/log/lux.log"))
        self.assertTrue(os.path.exists(self.p("var/lib/lux/migrated-from-pacman/done")))


class Fresh(MigrateBase):
    def test_fresh_install_without_old_files(self):
        shutil.copy(os.path.join(PKG, "lux.conf"), self.p("etc/lux/lux.conf"))
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        self.assertEqual(self.read("etc/lux/lux.conf"), open(os.path.join(PKG, "lux.conf")).read())
        self.assertFalse(os.path.lexists(self.p("var/lib/pacman")))
        self.assertFalse(os.path.lexists(self.p("usr/lib/lux/alpm/bin/pacman")))
        self.assertEqual(self.run_m("status").returncode, 0)

    def test_pacstrap_database_is_moved(self):
        """pacstrap/mkarchiso vytvori databazi v /var/lib/pacman; po hooku je v /var/lib/lux."""
        shutil.copy(os.path.join(PKG, "lux.conf"), self.p("etc/lux/lux.conf"))
        os.makedirs(self.p("var/lib/pacman/local/base-3-2"))
        self.write("var/lib/pacman/db.lck", "")
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.p("var/lib/lux/local/base-3-2")))
        self.assertEqual(os.readlink(self.p("var/lib/pacman")), "lux")
        # zamek hostitele (pacstrap) jde odstranit starou cestou
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.assertFalse(os.path.exists(self.p("var/lib/lux/db.lck")))
        r = self.run_m("finish", "--now")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.lexists(self.p("var/lib/pacman")))
        self.assertFalse(os.path.lexists(self.p("usr/lib/lux/alpm/bin/pacman")))

    def test_admin_lux_conf_is_kept(self):
        """Live ISO / instalator: lux.conf uz v novem formatu - pacman.conf jen pro sestaveni se neprevadi."""
        self.write("etc/lux/lux.conf", "repo luxos\n    server file:///opt/luxos-repo/$repo/$arch\n"
                   "    signatures optional\n")
        shutil.copy(os.path.join(PKG, "lux.conf"), self.p("etc/lux/lux.conf.pacnew"))
        self.write("etc/pacman.conf", "# LuxOS ISO build only (mkarchiso)\n[options]\n")
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("file:///opt/luxos-repo", self.read("etc/lux/lux.conf"))
        self.assertFalse(os.path.exists(self.p("etc/lux/lux.conf.pacnew")))


class OldLayout(MigrateBase):
    def test_upgrade_from_095(self):
        self.old_layout()
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_migrated()
        # stary proces jadra: zamek a log starou cestou
        self.assertTrue(os.path.exists(self.p("var/lib/pacman/db.lck")))
        with open(self.p("var/log/pacman.log"), "a") as f:
            f.write("[ALPM] transaction completed\n")
        self.assertIn("transaction completed", self.read("var/log/lux.log"))
        os.unlink(self.p("var/lib/pacman/db.lck"))
        # konfigurace: vychozi LuxOS (pacman.conf byl vychozi), nastaveni lux zachovana, .pacnew pryc
        self.assertEqual(self.read("etc/lux/lux.conf"), open(os.path.join(PKG, "lux.conf")).read())
        self.assertFalse(os.path.exists(self.p("etc/lux/lux.conf.pacnew")))
        # serazena zrcadla z instalatoru / lux mirrors
        ml = self.read("etc/lux/mirrorlist")
        self.assertIn("\nhttps://fast.example/$repo/os/$arch\nhttps://second.example/$repo/os/$arch\n", ml)
        self.assertNotIn("Server", ml)
        # docasne odkazy pro stary lux/LuxOS Care
        for name, target in (("pacman", "lux-engine"), ("pacman-conf", "lux-engine-conf"), ("pacman-key", "lux-engine-key")):
            self.assertEqual(os.readlink(self.p(f"usr/lib/lux/alpm/bin/{name}")), target)
        # zalohy
        for rel in ("etc/pacman.conf", "etc/pacman.d/mirrorlist", "etc/lux/lux.conf"):
            self.assertTrue(os.path.isfile(self.p("var/lib/lux/migrated-from-pacman/" + rel)), rel)
        self.assertIn("AUR=1", self.read("var/lib/lux/migrated-from-pacman/etc/lux/lux.conf"))
        # vysledna konfigurace je platna (lux-config)
        sys.path.insert(0, PKG)
        import lux_config
        cfg = lux_config.parse("/etc/lux/lux.conf", root=self.root)
        self.assertEqual([u for u, _o in cfg.repo("core").servers][0], "https://fast.example/$repo/os/$arch")

    def test_customized_pacman_conf_and_lux_settings(self):
        self.old_layout(lux_conf=LEGACY_LUX_CONF.replace("AUR=1", "AUR=0").replace("CLEAN_KEEP=2", "CLEAN_KEEP=4"),
                        pacman_conf=OLD_PACMAN_CONF + "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n\n"
                        "[options]\nIgnorePkg = linux\n", pacsave=True)
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        conf = self.read("etc/lux/lux.conf")
        for line in ("hold  linux", "repo multilib\n    mirrors  /etc/lux/mirrorlist", "aur  off", "clean-keep  4"):
            self.assertIn(line + "\n", conf)
        self.assertNotRegex(conf, r"\naur +on")
        self.assertFalse(os.path.exists(self.p("etc/lux/lux.conf.pacnew")))
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/migrated-from-pacman/etc/pacman.conf.pacsave")))

    def test_unchanged_luxconf_replaced_by_package(self):
        """lux.conf (stary format) nezmenena a balik ji uz prepsal novou - nastaveni lux vychozi."""
        self.old_layout(lux_conf=None)
        shutil.copy(os.path.join(PKG, "lux.conf"), self.p("etc/lux/lux.conf"))
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read("etc/lux/lux.conf"), open(os.path.join(PKG, "lux.conf")).read())

    def test_idempotent(self):
        self.old_layout()
        self.assertEqual(self.run_m("hook").returncode, 0)
        conf = self.read("etc/lux/lux.conf")
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        self.assert_migrated()
        self.assertEqual(self.read("etc/lux/lux.conf"), conf)
        self.assertEqual(self.read("var/log/lux.log").count("installed glibc"), 1)


class Interrupted(MigrateBase):
    """Vypadek proudu uprostred migrace: dalsi beh (hook pri dalsi aktualizaci nebo lux) ji dokonci."""

    def test_db_half_moved(self):
        self.old_layout()
        os.replace(self.p("var/lib/pacman/local"), self.p("var/lib/lux/local"))   # jen cast presunuta
        os.unlink(self.p("var/lib/pacman/db.lck"))                                   # po restartu zadny zamek
        r = self.run_m("auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_migrated()

    def test_old_dir_gone_link_missing(self):
        self.old_layout()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        for name in os.listdir(self.p("var/lib/pacman")):
            os.replace(self.p("var/lib/pacman/" + name), self.p("var/lib/lux/" + name))
        os.rmdir(self.p("var/lib/pacman"))                   # vypadek pred vytvorenim odkazu
        r = self.run_m("auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.p("var/lib/lux/local/glibc-2.42-1")))
        self.assertTrue(os.path.islink(self.p("etc/pacman.d/gnupg")))

    def test_log_merged_once(self):
        self.old_layout()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        # nove misto uz ma log (stary obsah na zacatku - spojeni probehlo, odkaz ne)
        self.write("var/log/lux.log", self.read("var/log/pacman.log") + "[ALPM] new\n")
        self.assertEqual(self.run_m("auto").returncode, 0)
        log = self.read("var/log/lux.log")
        self.assertEqual(log.count("installed glibc"), 1)
        self.assertTrue(log.endswith("[ALPM] new\n"))

    def test_log_merge_puts_old_first(self):
        self.old_layout()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.write("var/log/lux.log", "[ALPM] new\n")
        self.assertEqual(self.run_m("auto").returncode, 0)
        self.assertEqual(self.read("var/log/lux.log"),
                         "[2026-10-01T10:00:00+0200] [ALPM] installed glibc (2.42-1)\n[ALPM] new\n")

    def test_config_not_converted_yet(self):
        """Presuny hotove, konverze konfigurace ne (vypadek pred zapisem lux.conf)."""
        self.old_layout()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.assertEqual(self.run_m("hook").returncode, 0)
        os.unlink(self.p("var/lib/lux/migrated-from-pacman/config-done"))
        self.write("etc/lux/lux.conf", LEGACY_LUX_CONF.replace("FLATPAK=1", "FLATPAK=0"))
        self.assertIn("needed: config", self.run_m("status").stdout)
        self.assertEqual(self.run_m("auto").returncode, 0)
        self.assertRegex(self.read("etc/lux/lux.conf"), r"\nflatpak +off ")

    def test_conflicting_entry_kept_aside(self):
        self.old_layout()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.write("var/lib/lux/sync/other.db", "new")         # nove misto uz ma neprazdny sync
        self.assertEqual(self.run_m("auto").returncode, 0)
        self.assertEqual(self.read("var/lib/lux/sync/other.db"), "new")
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/migrated-from-pacman/conflicts/var/lib/pacman/sync/core.db")))


class Finish(MigrateBase):
    def migrated(self):
        self.old_layout()
        self.assertEqual(self.run_m("hook").returncode, 0)

    def test_not_while_locked(self):
        self.migrated()
        r = self.run_m("finish", "--now")
        self.assertIn("cleanup postponed", r.stderr)
        self.assertTrue(os.path.islink(self.p("var/lib/pacman")))

    def test_not_before_reboot(self):
        self.migrated()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.assertEqual(self.run_m("finish").returncode, 0)
        self.assertTrue(os.path.islink(self.p("var/lib/pacman")))     # stare procesy mohou bezet
        self.assertTrue(os.path.islink(self.p("usr/lib/lux/alpm/bin/pacman")))
        # "restart": znacka starsi nez start systemu
        os.utime(self.p("var/lib/lux/migrated-from-pacman/done"), (1, 1))
        self.assertEqual(self.run_m("finish").returncode, 0)
        self.assertFalse(os.path.lexists(self.p("var/lib/pacman")))

    def test_cleanup(self):
        self.migrated()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.write("etc/pacman.d/custom-mirrors", "x")       # vlastni soubor spravce zustane
        r = self.run_m("finish", "--now")
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in ("var/lib/pacman", "var/cache/pacman", "etc/pacman.d/gnupg", "etc/pacman.d/hooks",
                    "var/log/pacman.log", "etc/pacman.conf", "etc/pacman.d/mirrorlist", "usr/lib/lux/alpm/bin/pacman",
                    "usr/lib/lux/alpm/bin/pacman-conf", "usr/lib/lux/alpm/bin/pacman-key", "usr/lib/lux/alpm/pacman"):
            self.assertFalse(os.path.lexists(self.p(rel)), rel)
        self.assertTrue(os.path.isfile(self.p("etc/pacman.d/custom-mirrors")))
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/migrated-from-pacman/etc/pacman.conf")))
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/local/glibc-2.42-1/desc")))
        self.assertEqual(self.run_m("status").returncode, 0)   # custom-mirrors je soubor spravce, ne pozustatek

    def test_package_owned_mirrorlist_stays(self):
        """pacman-mirrorlist jeste nainstalovany: jeho soubor uklid nemaze (odebere ho lux autoremove)."""
        self.migrated()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        os.makedirs(self.p("var/lib/lux/local/pacman-mirrorlist-20260901-1"))
        self.write("var/lib/lux/local/pacman-mirrorlist-20260901-1/files", "%FILES%\netc/\netc/pacman.d/\n"
                   "etc/pacman.d/mirrorlist\n")
        self.assertEqual(self.run_m("finish", "--now").returncode, 0)
        self.assertTrue(os.path.isfile(self.p("etc/pacman.d/mirrorlist")))
        self.assertFalse(os.path.lexists(self.p("etc/pacman.conf")))

    def test_nothing_before_migration(self):
        self.old_layout()
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.assertEqual(self.run_m("finish", "--now").returncode, 0)
        self.assertTrue(os.path.isdir(self.p("var/lib/pacman/local")))


class Suffixes(MigrateBase):
    """LuxOS 1.0: zalohy konfigurace *.luxnew/*.luxsave/*.luxorig misto *.pacnew/*.pacsave/*.pacorig."""

    def migrated_system(self):
        shutil.copy(os.path.join(PKG, "lux.conf"), self.p("etc/lux/lux.conf"))
        self.write("var/lib/lux/migrated-from-pacman/done", "x\n")
        self.write("var/lib/lux/migrated-from-pacman/config-done", "")
        self.write("var/lib/lux/migrated-from-pacman/mirrorlist-done", "")

    def test_renamed_once_without_overwrite(self):
        self.migrated_system()
        self.write("etc/a.conf.pacnew", "new a\n")
        self.write("etc/ssh/sshd_config.pacsave", "saved\n")
        self.write("etc/ssh/sshd_config.pacsave.1", "saved 1\n")
        self.write("etc/c.conf.pacorig", "orig\n")
        self.write("etc/d.conf.pacnew", "old engine\n")
        self.write("etc/d.conf.luxnew", "new engine\n")       # cil existuje - neprepsat
        self.write("etc/e.conf.pacnew.bak", "x")               # jina koncovka - nechat
        os.symlink("a.conf.pacnew", self.p("etc/link.pacnew"))  # odkaz se prejmenuje, necte se
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read("etc/a.conf.luxnew"), "new a\n")
        self.assertEqual(self.read("etc/ssh/sshd_config.luxsave"), "saved\n")
        self.assertEqual(self.read("etc/ssh/sshd_config.luxsave.1"), "saved 1\n")
        self.assertEqual(self.read("etc/c.conf.luxorig"), "orig\n")
        self.assertTrue(os.path.islink(self.p("etc/link.luxnew")))
        for rel in ("etc/a.conf.pacnew", "etc/ssh/sshd_config.pacsave", "etc/ssh/sshd_config.pacsave.1",
                    "etc/c.conf.pacorig", "etc/link.pacnew"):
            self.assertFalse(os.path.lexists(self.p(rel)), rel)
        self.assertEqual(self.read("etc/d.conf.pacnew"), "old engine\n")
        self.assertEqual(self.read("etc/d.conf.luxnew"), "new engine\n")
        self.assertTrue(os.path.isfile(self.p("etc/e.conf.pacnew.bak")))
        self.assertIn("renamed /etc/a.conf.pacnew -> a.conf.luxnew", r.stderr)
        self.assertIn("renamed /etc/ssh/sshd_config.pacsave.1 -> sshd_config.luxsave.1", r.stderr)
        self.assertIn("/etc/d.conf.pacnew not renamed: d.conf.luxnew already exists", r.stderr)
        self.assertTrue(os.path.exists(self.p("var/lib/lux/migrated-from-pacman/suffixes-done")))
        # jen jednou: dalsi aktualizace lux-engine uz nic neprejmenovava
        self.write("etc/f.conf.pacnew", "f\n")
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        self.assertTrue(os.path.isfile(self.p("etc/f.conf.pacnew")))
        self.assertEqual(self.run_m("status").returncode, 0)

    def test_outside_etc_untouched(self):
        self.migrated_system()
        self.write("usr/share/doc/x.pacnew", "x")
        self.write("var/lib/lux/y.pacsave", "y")
        self.assertEqual(self.run_m("hook").returncode, 0)
        self.assertTrue(os.path.isfile(self.p("usr/share/doc/x.pacnew")))
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/y.pacsave")))

    def test_upgrade_from_095_renames_after_migration(self):
        """Stare jadro v transakci vytvori *.pacnew; migrace je precte, prejmenuje az potom."""
        self.old_layout(lux_conf=LEGACY_LUX_CONF.replace("AUR=1", "AUR=0"))
        self.write("etc/lux/lux.conf.pacnew", open(os.path.join(PKG, "lux.conf")).read() + "# zmena\n")
        self.write("etc/locale.gen.pacnew", "cs_CZ.UTF-8 UTF-8\n")
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_migrated()
        self.assertRegex(self.read("etc/lux/lux.conf"), r"\naur +off")
        self.assertTrue(os.path.isfile(self.p("etc/lux/lux.conf.luxnew")))
        self.assertTrue(os.path.isfile(self.p("etc/locale.gen.luxnew")))
        self.assertFalse(os.path.lexists(self.p("etc/locale.gen.pacnew")))

    def test_luxnew_of_lux_conf_dropped(self):
        """Novy lux-engine: lux.conf.luxnew shodna s vychozi konfiguraci se odstrani (jako .pacnew)."""
        self.write("etc/lux/lux.conf", "repo luxos\n    server file:///opt/luxos-repo/$repo/$arch\n"
                   "    signatures optional\n")
        shutil.copy(os.path.join(PKG, "lux.conf"), self.p("etc/lux/lux.conf.luxnew"))
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.p("etc/lux/lux.conf.luxnew")))

    def test_pacman_conf_luxsave_converted_and_cleaned(self):
        """/etc/pacman.conf.luxsave (pacman odebran novym jadrem) se prevede stejne jako .pacsave."""
        self.old_layout(pacman_conf=OLD_PACMAN_CONF + "\n[options]\nIgnorePkg = linux\n", pacsave=True,
                        saved=".luxsave")
        r = self.run_m("hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hold  linux\n", self.read("etc/lux/lux.conf"))
        os.unlink(self.p("var/lib/pacman/db.lck"))
        self.assertEqual(self.run_m("finish", "--now").returncode, 0)
        self.assertFalse(os.path.lexists(self.p("etc/pacman.conf.luxsave")))
        self.assertTrue(os.path.isfile(self.p("var/lib/lux/migrated-from-pacman/etc/pacman.conf.luxsave")))


if __name__ == "__main__":
    unittest.main()
