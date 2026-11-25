"""Testy psani vietnamsky (luxos_input_method, luxos-input-method, 55-luxos-input-method.sh).

Spusteni:
  python3 -m unittest packages/luxos-desktop/tests/test_luxos_input_method.py -v

Vse v docasnem HOME s falesnym fcitx5 a xfconf-query - skutecny fcitx5 ani nastaveni uzivatele se nemeni.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.normpath(os.path.join(HERE, "..", "files"))
sys.path.insert(0, os.path.join(FILES, "python"))
import luxos_input_method as im  # noqa: E402

ENV_SH = os.path.join(FILES, "xinit", "55-luxos-input-method.sh")
CLI = os.path.join(FILES, "bin", "luxos-input-method")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-im-")
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        self.addons = os.path.join(self.tmp, "addons")
        for d in (self.home, self.bin, self.addons):
            os.makedirs(d)
        open(os.path.join(self.addons, "bamboo.conf"), "w").close()
        self.log = os.path.join(self.tmp, "calls.log")
        for name in ("fcitx5", "xfconf-query"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(f'#!/bin/sh\necho "{name} $*" >> "{self.log}"\n')
            os.chmod(path, 0o755)
        self.saved = dict(os.environ)
        os.environ.update(HOME=self.home, LUXOS_IM_FCITX5=os.path.join(self.bin, "fcitx5"),
                          LUXOS_IM_XFCONF=os.path.join(self.bin, "xfconf-query"), LUXOS_IM_ADDONS=self.addons,
                          LANG="en_US.UTF-8")
        for v in ("XDG_CONFIG_HOME", "LC_ALL", "LC_CTYPE"):
            os.environ.pop(v, None)
        # stop()/start() by sahaly na skutecne procesy - v testech jen zaznam
        self.orig = (im.stop, im.start, im.system_layouts)
        im.stop = lambda: None
        self.started = []
        im.start = lambda: self.started.append(True)
        im.system_layouts = lambda: [("us", "")]

    def tearDown(self):
        im.stop, im.start, im.system_layouts = self.orig
        os.environ.clear()
        os.environ.update(self.saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def calls(self):
        try:
            with open(self.log) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def cfg(self, *parts):
        return os.path.join(self.home, ".config", *parts)

    def read(self, *parts):
        with open(self.cfg(*parts), encoding="utf-8") as f:
            return f.read()

    def write(self, text, *parts):
        os.makedirs(os.path.dirname(self.cfg(*parts)), exist_ok=True)
        with open(self.cfg(*parts), "w", encoding="utf-8") as f:
            f.write(text)


class ActiveRule(Base):
    def test_off_by_default(self):
        self.assertEqual(im.active(), "")
        self.assertIsNone(im.autostart())
        self.assertEqual(self.calls(), [])

    def test_vietnamese_locale_turns_it_on_once(self):
        os.environ["LANG"] = "vi_VN.UTF-8"
        self.assertEqual(im.active(), "vi")
        argv = im.autostart()
        self.assertEqual(argv, [os.environ["LUXOS_IM_FCITX5"]])
        self.assertIn("IM=vi", self.read("luxos", "input-method"))
        self.assertIn("Name=bamboo", self.read("fcitx5", "profile"))
        self.assertIn("InputMethod=Telex", self.read("fcitx5", "conf", "bamboo.conf"))
        self.assertIn("xfconf-query -c xsettings -p /Gtk/IMModule -n -t string -s fcitx", self.calls())

    def test_coerced_c_locale_is_ignored(self):
        # Python bez vygenerovaneho vi_VN nastavi LC_CTYPE=C.UTF-8 (PEP 538) - rozhoduje LANG
        os.environ.update(LANG="vi_VN.UTF-8", LC_CTYPE="C.UTF-8")
        self.assertEqual(im.active(), "vi")
        os.environ.update(LANG="en_US.UTF-8", LC_CTYPE="vi_VN.UTF-8")
        self.assertEqual(im.active(), "vi")
        os.environ.update(LC_CTYPE="en_US.UTF-8", LANG="vi_VN.UTF-8")
        self.assertEqual(im.active(), "")

    def test_explicit_off_wins_over_locale(self):
        os.environ["LANG"] = "vi_VN.UTF-8"
        im.disable(live=False)
        self.assertEqual(im.active(), "")
        self.assertIsNone(im.autostart())

    def test_own_fcitx5_setup_is_left_alone(self):
        own = "[Groups/0]\nName=Mine\nDefault Layout=us\nDefaultIM=pinyin\n\n[Groups/0/Items/0]\nName=pinyin\n"
        self.write(own, "fcitx5", "profile")
        self.assertEqual(im.active(), "user")
        self.assertEqual(im.autostart(), [os.environ["LUXOS_IM_FCITX5"]])
        self.assertEqual(self.read("fcitx5", "profile"), own)   # nic neprepsano
        self.assertFalse(os.path.exists(self.cfg("luxos", "input-method")))

    def test_vietnamese_user_with_own_setup_is_left_alone(self):
        # Vietnamec s vlastnim fcitx5 (Unikey): jazyk vi_* jeho nastaveni neprepise
        os.environ["LANG"] = "vi_VN.UTF-8"
        own = "[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=unikey\n\n[Groups/0/Items/0]\nName=unikey\n"
        self.write(own, "fcitx5", "profile")
        self.write("[Hotkey/TriggerKeys]\n0=Shift+space\n", "fcitx5", "config")
        self.assertEqual(im.active(), "user")
        self.assertEqual(im.autostart(), [os.environ["LUXOS_IM_FCITX5"]])
        self.assertEqual(self.read("fcitx5", "profile"), own)
        self.assertEqual(self.read("fcitx5", "config"), "[Hotkey/TriggerKeys]\n0=Shift+space\n")
        self.assertFalse(os.path.exists(self.cfg("luxos", "input-method")))

    def test_style_keeps_method_on(self):
        # drive: zmena stylu pred prvnim prihlasenim zapsala volbu bez IM= a vietnamstinu tim vypnula
        os.environ["LANG"] = "vi_VN.UTF-8"
        im.set_style("VNI", live=False)
        self.assertEqual(im.active(), "vi")
        self.assertEqual(im.read_choice(), {"IM": "vi", "VI_STYLE": "VNI"})
        self.assertEqual(im.autostart(), [os.environ["LUXOS_IM_FCITX5"]])
        self.assertIn("InputMethod=VNI", self.read("fcitx5", "conf", "bamboo.conf"))

    def test_style_without_opt_in_changes_nothing(self):
        with self.assertRaises(ValueError):
            im.set_style("VNI", live=False)
        self.assertEqual(im.active(), "")
        self.assertFalse(os.path.exists(self.cfg("luxos", "input-method")))
        self.write("[Groups/0]\nName=Default\n", "fcitx5", "profile")   # vlastni fcitx5: taky beze zmeny
        with self.assertRaises(ValueError):
            im.set_style("VNI", live=False)
        self.assertEqual(im.active(), "user")

    def test_missing_module_resets_xsettings(self):
        im.enable("vi", live=False)
        os.remove(os.path.join(self.addons, "bamboo.conf"))
        self.assertIsNone(im.autostart())
        self.assertIn("xfconf-query -c xsettings -p /Gtk/IMModule -r", self.calls())

    def test_not_installed_never_starts(self):
        os.environ["LANG"] = "vi_VN.UTF-8"
        os.environ["LUXOS_IM_FCITX5"] = os.path.join(self.tmp, "missing")
        self.assertIsNone(im.autostart())


class Enable(Base):
    def test_enable_writes_luxos_defaults(self):
        im.enable("vi", "VNI")
        self.assertEqual(im.read_choice(), {"IM": "vi", "VI_STYLE": "VNI"})
        prof = self.read("fcitx5", "profile")
        self.assertIn("Name=keyboard-us", prof)
        self.assertIn("DefaultIM=bamboo", prof)
        conf = self.read("fcitx5", "config")
        self.assertIn("0=Control+space", conf)
        self.assertIn("[Hotkey/AltTriggerKeys]", conf)   # prazdne: samotny Shift neprepina
        self.assertIn("ShareInputState=All", conf)
        self.assertIn("ActiveByDefault=True", conf)
        self.assertIn("0=clipboard", conf)
        self.assertIn("Allow Overriding System XKB Settings=False", self.read("fcitx5", "conf", "xcb.conf"))
        self.assertIn("InputMethod=VNI", self.read("fcitx5", "conf", "bamboo.conf"))
        self.assertEqual(self.started, [True])

    def test_keyboard_item_follows_first_system_layout(self):
        im.system_layouts = lambda: [("cz", "qwerty"), ("us", "")]
        im.enable("vi")
        prof = self.read("fcitx5", "profile")
        self.assertIn("Name=keyboard-cz-qwerty", prof)
        self.assertIn("Default Layout=cz-qwerty", prof)

    def test_existing_profile_gets_bamboo_added_once(self):
        im.write_choice({"IM": "none"})
        self.write("[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=mozc\n\n"
                   "[Groups/0/Items/0]\nName=keyboard-us\nLayout=\n\n[Groups/0/Items/1]\nName=mozc\nLayout=\n\n"
                   "[GroupOrder]\n0=Default\n", "fcitx5", "profile")
        im.enable("vi")
        im.enable("vi")
        prof = self.read("fcitx5", "profile")
        self.assertEqual(prof.count("Name=bamboo"), 1)
        self.assertIn("Name=mozc", prof)
        self.assertIn("DefaultIM=mozc", prof)   # vlastni vychozi metoda zustane

    def test_other_config_keys_are_kept(self):
        self.write("[Hotkey]\nEnumerateForwardKeys=\n\n[Behavior]\nPreeditEnabledByDefault=False\n", "fcitx5", "config")
        self.write("Spell Check=False\nInputMethod=Telex 2\n", "fcitx5", "conf", "bamboo.conf")
        im.enable("vi")
        conf = self.read("fcitx5", "config")
        self.assertIn("PreeditEnabledByDefault=False", conf)
        self.assertIn("EnumerateForwardKeys=", conf)
        bamboo = self.read("fcitx5", "conf", "bamboo.conf")
        self.assertIn("Spell Check=False", bamboo)
        self.assertIn("InputMethod=Telex 2", bamboo)   # vlastni zpusob Bamboo se zachova
        self.assertEqual(im.style(), "Telex 2")

    def test_user_setup_enable_then_disable_restores_it(self):
        own = ("[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=mozc\n\n[Groups/0/Items/0]\n"
               "Name=keyboard-us\nLayout=\n\n[Groups/0/Items/1]\nName=mozc\nLayout=\n\n[GroupOrder]\n0=Default\n")
        self.write(own, "fcitx5", "profile")
        self.write("[Hotkey/TriggerKeys]\n0=Shift+space\n", "fcitx5", "config")
        self.assertEqual(im.active(), "user")
        im.enable("vi")
        self.assertEqual(im.active(), "vi")
        self.assertIn("Name=bamboo", self.read("fcitx5", "profile"))
        self.assertEqual(self.read("fcitx5", "config"), "[Hotkey/TriggerKeys]\n0=Shift+space\n")  # zkratky zustaly
        im.disable()
        self.assertEqual(im.active(), "user")   # vlastni fcitx5 bezi dal
        prof = self.read("fcitx5", "profile")
        self.assertNotIn("bamboo", prof)
        self.assertIn("Name=mozc", prof)
        self.assertIn("DefaultIM=mozc", prof)
        self.assertNotIn("xfconf-query -c xsettings -p /Gtk/IMModule -r", self.calls())

    def test_unreadable_profile_is_never_overwritten(self):
        bad = "Foo=1\n[Groups/0]\nName=Default\nDefaultIM=unikey\n"
        self.write(bad, "fcitx5", "profile")
        self.write("x", "luxos", "input-method")   # bez IM= - neni vlastni nastaveni, zkusi se LuxOS
        os.remove(self.cfg("luxos", "input-method"))
        with open(self.cfg("fcitx5", "config"), "wb") as f:
            f.write(b"[Hotkey]\n\xff\n")
        os.rename(self.cfg("fcitx5", "profile"), self.cfg("fcitx5", "profile.keep"))
        with self.assertRaises(im.ConfigError):
            im.enable("vi")
        self.assertFalse(os.path.exists(self.cfg("fcitx5", "profile")))   # nic nezapsano
        self.assertFalse(os.path.exists(self.cfg("luxos", "input-method")))
        os.rename(self.cfg("fcitx5", "profile.keep"), self.cfg("fcitx5", "profile"))
        os.remove(self.cfg("fcitx5", "config"))
        im.write_choice({"IM": "none"})
        with self.assertRaises(im.ConfigError):
            im.enable("vi")
        self.assertEqual(self.read("fcitx5", "profile"), bad)

    def test_config_merge_keeps_user_lists(self):
        self.write("[Hotkey/TriggerKeys]\n0=Super+F1\n\n[Behavior/DisabledAddons]\n0=kimpanel\n", "fcitx5", "config")
        im.write_choice({"IM": "none"})   # bez vlastniho profilu, LuxOS nastavuje
        im.enable("vi")
        conf = self.read("fcitx5", "config")
        self.assertIn("0=Super+F1", conf)
        self.assertNotIn("Control+space", conf)
        for a in ("kimpanel", "clipboard", "quickphrase"):
            self.assertIn(a, conf)

    def test_profile_item_gap(self):
        self.write("[Groups/0]\nName=Default\nDefaultIM=mozc\n\n[Groups/0/Items/0]\nName=keyboard-us\n\n"
                   "[Groups/0/Items/2]\nName=mozc\n", "fcitx5", "profile")
        im.write_choice({"IM": "none"})
        im.enable("vi")
        prof = self.read("fcitx5", "profile")
        self.assertIn("Name=mozc", prof)
        self.assertIn("[Groups/0/Items/3]\nName=bamboo", prof)

    def test_disable_and_style(self):
        im.enable("vi")
        im.set_style("VIQR")
        self.assertIn("InputMethod=VIQR", self.read("fcitx5", "conf", "bamboo.conf"))
        im.disable()
        self.assertEqual(im.read_choice()["IM"], "none")
        self.assertEqual(im.read_choice()["VI_STYLE"], "VIQR")
        self.assertIn("xfconf-query -c xsettings -p /Gtk/IMModule -r", self.calls())
        with self.assertRaises(ValueError):
            im.set_style("Bogus")
        with self.assertRaises(ValueError):
            im.enable("xx")


class LoginEnv(Base):
    def env_after(self, extra=None):
        env = {"HOME": self.home, "PATH": self.bin + ":/usr/bin:/bin", "LANG": os.environ["LANG"],
               "LUXOS_IM_ADDONS": self.addons}
        env.update(extra or {})
        out = subprocess.run(["sh", "-c", f'. "{ENV_SH}"; echo "GTK=${{GTK_IM_MODULE:-}} X=${{XMODIFIERS:-}}"'],
                             env=env, capture_output=True, text=True, check=True).stdout.strip()
        return out

    def test_nothing_for_normal_user(self):
        self.assertEqual(self.env_after(), "GTK= X=")

    def test_vietnamese_locale(self):
        os.environ["LANG"] = "vi_VN.UTF-8"
        self.assertEqual(self.env_after(), "GTK=fcitx X=@im=fcitx")

    def test_locale_order_and_c_locale(self):
        os.environ["LANG"] = "vi_VN.UTF-8"
        self.assertEqual(self.env_after({"LC_CTYPE": "C.UTF-8"}), "GTK=fcitx X=@im=fcitx")
        self.assertEqual(self.env_after({"LC_CTYPE": "en_US.UTF-8"}), "GTK= X=")
        os.environ["LANG"] = "en_US.UTF-8"
        self.assertEqual(self.env_after({"LC_ALL": "vi_VN.UTF-8"}), "GTK=fcitx X=@im=fcitx")

    def test_choice_file_both_ways(self):
        im.enable("vi")
        self.assertEqual(self.env_after(), "GTK=fcitx X=@im=fcitx")
        im.disable()
        os.environ["LANG"] = "vi_VN.UTF-8"
        self.assertEqual(self.env_after(), "GTK= X=")

    def test_user_and_whitespace_in_choice(self):
        self.write("IM = user \r\n", "luxos", "input-method")
        self.assertEqual(self.env_after(), "GTK=fcitx X=@im=fcitx")
        self.write("# nic\n", "luxos", "input-method")   # bez IM= jako bez volby
        os.environ["LANG"] = "vi_VN.UTF-8"
        self.assertEqual(self.env_after(), "GTK=fcitx X=@im=fcitx")
        self.assertEqual(im.active(), "vi")

    def test_vi_without_module_no_env(self):
        os.environ["LANG"] = "vi_VN.UTF-8"
        os.remove(os.path.join(self.addons, "bamboo.conf"))
        self.assertEqual(self.env_after(), "GTK= X=")

    def test_own_profile_beats_locale(self):
        self.write("[Groups/0]\nName=Default\n", "fcitx5", "profile")
        self.assertEqual(self.env_after(), "GTK=fcitx X=@im=fcitx")

    def test_own_value_wins(self):
        im.enable("vi")
        self.assertEqual(self.env_after({"GTK_IM_MODULE": "ibus"}), "GTK=ibus X=@im=fcitx")

    def test_without_fcitx5_nothing(self):
        im.enable("vi")
        os.remove(os.path.join(self.bin, "fcitx5"))
        env = {"HOME": self.home, "PATH": self.bin, "LANG": "vi_VN.UTF-8"}
        out = subprocess.run(["/bin/sh", "-c", f'. "{ENV_SH}"; echo "GTK=${{GTK_IM_MODULE:-}}"'],
                             env=env, capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "GTK=")


class Cli(Base):
    def cli(self, *args):
        env = dict(os.environ, PYTHONPATH=os.path.join(FILES, "python"))
        return subprocess.run([sys.executable, CLI, *args], env=env, capture_output=True, text=True)

    def test_status_and_usage(self):
        r = self.cli("status")
        self.assertEqual(r.returncode, 0)
        self.assertIn("input-method: none", r.stdout)
        self.assertEqual(self.cli("bogus").returncode, 2)
        self.assertEqual(self.cli("style", "Bogus").returncode, 2)

    def test_enable_needs_packages(self):
        os.environ["LUXOS_IM_ADDONS"] = os.path.join(self.tmp, "none")
        r = self.cli("enable", "vi")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not installed", r.stderr)

    def test_autostart_off_exits_quietly(self):
        r = self.cli("autostart")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("fcitx5", "\n".join(self.calls()))


if __name__ == "__main__":
    unittest.main()
