"""Testy pro Rozlozeni klavesnice: luxos_keyboard (cteni/zapis systemoveho nastaveni, prikazy
localectl a setxkbmap, katalog rozlozeni) a aplikace luxos-keyboard (jen pod Xvfb).

Spusteni:
  python3 -m unittest packages/luxos-desktop/tests/test_luxos_keyboard.py -v
  env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_keyboard.py -v

GUI cast bezi jen pod xvfb-run (jinak se preskoci) a s falesnymi localectl, setxkbmap
a xfconf-query - skutecne nastaveni systemu ani uzivatele nemeni.
"""
import importlib.machinery
import importlib.util
import os
import stat
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True   # zadny __pycache__ ve files/ (balik instaluje bin/*)
HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.normpath(os.path.join(HERE, "..", "files", "python"))
BIN = os.path.normpath(os.path.join(HERE, "..", "files", "bin"))
I18N = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
sys.path.insert(0, PYDIR)
sys.path.insert(1, I18N)
import luxos_keyboard as kb  # noqa: E402

TMP = tempfile.mkdtemp(prefix="luxos-kbd-unit-")

# 00-keyboard.conf, jak ho zapise systemd-localed (localectl set-x11-keymap cz,us pc105 qwerty, ...)
LOCALED = """# Written by systemd-localed(8), read by systemd-localed and Xorg. It's
# probably wise not to edit this file manually. Use localectl(1) to
# update this file.
Section "InputClass"
        Identifier "system-keyboard"
        MatchIsKeyboard "on"
        Option "XkbLayout" "cz,us"
        Option "XkbModel" "pc105"
        Option "XkbVariant" "qwerty,"
        Option "XkbOptions" "grp:alt_shift_toggle,compose:ralt"
EndSection
"""
# Starsi instalator LuxOS (prazdne XkbOptions, jiny odsazeni)
OLD_INSTALLER = """Section "InputClass"
    Identifier "system-keyboard"
    MatchIsKeyboard "on"
    Option "XkbLayout" "de"
    Option "XkbVariant" ""
    Option "XkbOptions" ""
EndSection
"""


class Parse(unittest.TestCase):
    def test_localed_format(self):
        cfg = kb.parse_conf(LOCALED)
        self.assertEqual(cfg["layouts"], [("cz", "qwerty"), ("us", "")])
        self.assertEqual(cfg["model"], "pc105")
        self.assertEqual(cfg["options"], ["grp:alt_shift_toggle", "compose:ralt"])

    def test_old_installer_format(self):
        cfg = kb.parse_conf(OLD_INSTALLER)
        self.assertEqual(cfg["layouts"], [("de", "")])
        self.assertEqual(cfg["options"], [])

    def test_fewer_variants_than_layouts(self):
        self.assertEqual(kb.from_strings("cz,us,de", "qwerty")["layouts"], [("cz", "qwerty"), ("us", ""), ("de", "")])

    def test_vconsole(self):
        cfg = kb.parse_vconsole('KEYMAP=cz-qwerty\nXKBLAYOUT=cz,us\nXKBVARIANT="qwerty,"\nXKBOPTIONS=grp:caps_toggle\n')
        self.assertEqual(cfg["layouts"], [("cz", "qwerty"), ("us", "")])
        self.assertEqual(cfg["options"], ["grp:caps_toggle"])

    def test_read_system_fallbacks(self):
        with tempfile.TemporaryDirectory() as d:
            conf, vcon = os.path.join(d, "00-keyboard.conf"), os.path.join(d, "vconsole.conf")
            self.assertEqual(kb.read_system(conf, vcon)["layouts"], [("us", "")])   # nic
            with open(vcon, "w") as f:
                f.write("KEYMAP=sk-qwerty\nXKBLAYOUT=sk\nXKBVARIANT=qwerty\n")
            self.assertEqual(kb.read_system(conf, vcon)["layouts"], [("sk", "qwerty")])
            with open(conf, "w") as f:
                f.write(LOCALED)
            self.assertEqual(kb.read_system(conf, vcon)["layouts"], [("cz", "qwerty"), ("us", "")])


class Generate(unittest.TestCase):
    L = [("cz", "qwerty"), ("us", "")]

    def test_strings(self):
        self.assertEqual(kb.xkb_strings(self.L), ("cz,us", "qwerty,"))
        self.assertEqual(kb.xkb_strings([("us", "")]), ("us", ""))

    def test_conf_roundtrip(self):
        for layouts, opts, model in ((self.L, ["grp:alt_shift_toggle"], ""), ([("de", "")], [], "pc105"),
                                     ([("cz", ""), ("us", ""), ("ua", "phonetic"), ("de", "")],
                                      ["grp:caps_toggle", "compose:ralt"], "")):
            text = kb.conf_text(layouts, opts, model)
            self.assertEqual(kb.parse_conf(text), {"layouts": layouts, "model": model, "options": opts})
        self.assertNotIn("XkbVariant", kb.conf_text([("cz", ""), ("us", "")], ["grp:alt_shift_toggle"]))
        self.assertNotIn("XkbOptions", kb.conf_text([("cz", "")]))

    def test_localectl(self):
        self.assertEqual(kb.localectl_cmd(self.L, ["grp:alt_shift_toggle"], "pc105"),
                         ["localectl", "set-x11-keymap", "cz,us", "pc105", "qwerty,", "grp:alt_shift_toggle"])
        self.assertEqual(kb.localectl_cmd([("us", "")]), ["localectl", "set-x11-keymap", "us", "", "", ""])

    def test_setxkbmap_clears_old_options(self):
        self.assertEqual(kb.setxkbmap_cmd(self.L, ["grp:ctrl_shift_toggle"]),
                         ["setxkbmap", "-layout", "cz,us", "-variant", "qwerty,", "-option", "",
                          "-option", "grp:ctrl_shift_toggle"])
        self.assertEqual(kb.setxkbmap_cmd([("us", "")])[-2:], ["-option", ""])

    def test_validate(self):
        bad = [([], []), ([("cz", ""), ("us", ""), ("de", ""), ("fr", ""), ("pl", "")], []),
               ([("cz", ""), ("cz", "")], []), ([('cz"', "")], []), ([("cz", "qw erty")], []),
               ([("CZ", "")], []), ([("cz", "")], ["grp:alt shift"]), ([("cz", "")], ['grp:x"'])]
        for layouts, opts in bad:
            with self.assertRaises(kb.KeyboardError, msg=f"{layouts} {opts}"):
                kb.localectl_cmd(layouts, opts)
        kb.validate([("cz", ""), ("cz", "qwerty"), ("us", ""), ("ua", "phonetic")], ["grp:alt_shift_toggle"])

    def test_switch(self):
        self.assertEqual(kb.switch_of(["compose:ralt", "grp:caps_toggle"]), "grp:caps_toggle")
        self.assertEqual(kb.switch_of(["compose:ralt"]), "")
        self.assertEqual(kb.with_switch(["grp:caps_toggle", "compose:ralt"], "grp:alt_shift_toggle"),
                         ["grp:alt_shift_toggle", "compose:ralt"])
        self.assertEqual(kb.with_switch(["grp:caps_toggle", "compose:ralt"], ""), ["compose:ralt"])
        # Super+Mezernik je v LuxOS Hledani - nesmi byt v nabidce
        self.assertNotIn("grp:win_space_toggle", [o for o, _l in kb.SWITCH_OPTIONS])
        self.assertEqual(kb.SWITCH_OPTIONS[0][0], kb.DEFAULT_SWITCH)
        self.assertEqual(kb.DEFAULT_SWITCH, "grp:shifts_toggle")
        self.assertEqual(kb.SWITCH_OPTIONS[0], ("grp:shifts_toggle", "Both Shift keys"))
        self.assertIn(("grp:alt_shift_toggle", "Alt + Shift"), kb.SWITCH_OPTIONS)   # dal na vyber

    def test_migrate_options(self):
        m = kb.migrate_options
        self.assertEqual(m("grp:alt_shift_toggle"), "grp:shifts_toggle")
        self.assertEqual(m("terminate:ctrl_alt_bksp,grp:alt_shift_toggle,compose:ralt"),
                         "terminate:ctrl_alt_bksp,grp:shifts_toggle,compose:ralt")
        self.assertEqual(m("grp:alt_shift_toggle,grp_led:scroll"), "grp:shifts_toggle,grp_led:scroll")
        for keep in ("", "compose:ralt", "grp:ctrl_shift_toggle", "grp:shifts_toggle", "grp:caps_toggle,compose:ralt",
                     "grp:alt_shift_toggle,grp:caps_toggle", "grp:alt_shift_toggle_bidir"):
            self.assertIsNone(m(keep), keep)

    def migrate_files(self, conf_text, vc_text=None, marker_exists=False):
        d = tempfile.mkdtemp(dir=TMP)
        conf, vc, marker = (os.path.join(d, n) for n in ("00-keyboard.conf", "vconsole.conf", "lib/migrated"))
        if conf_text is not None:
            with open(conf, "w") as f:
                f.write(conf_text)
            os.chmod(conf, 0o644)
        if vc_text is not None:
            with open(vc, "w") as f:
                f.write(vc_text)
        if marker_exists:
            os.makedirs(os.path.dirname(marker))
            open(marker, "w").close()
        changed = kb.migrate_default_switch(conf, vc, marker)

        def rd(p):
            try:
                with open(p) as f:
                    return f.read()
            except FileNotFoundError:
                return None
        return changed, rd(conf), rd(vc), os.path.exists(marker), conf, vc, marker

    def test_migrate_old_default(self):
        old = kb.conf_text([("cz", "qwerty"), ("us", "")], ["grp:alt_shift_toggle", "compose:ralt"], "pc105")
        vc = "KEYMAP=cz-qwerty\nXKBLAYOUT=cz,us\nXKBMODEL=pc105\nXKBVARIANT=qwerty,\nXKBOPTIONS=grp:alt_shift_toggle,compose:ralt\n"
        changed, conf, vcon, marked, cpath, vpath, marker = self.migrate_files(old, vc)
        self.assertTrue(changed)
        self.assertEqual(conf, old.replace("grp:alt_shift_toggle", "grp:shifts_toggle"))
        self.assertEqual(vcon, vc.replace("grp:alt_shift_toggle", "grp:shifts_toggle"))
        self.assertTrue(marked)
        self.assertEqual(stat.S_IMODE(os.stat(cpath).st_mode), 0o644)
        cfg = kb.read_system(cpath, vpath)
        self.assertEqual(cfg["options"], ["grp:shifts_toggle", "compose:ralt"])
        self.assertEqual(cfg["layouts"], [("cz", "qwerty"), ("us", "")])
        self.assertEqual(cfg["model"], "pc105")
        self.assertFalse(os.path.exists(cpath + ".luxos-new"))
        # Podruhe (znacka existuje) uz nic - ani kdyz si uzivatel Alt+Shift pozdeji vybere znovu
        with open(cpath, "w") as f:
            f.write(old)
        self.assertFalse(kb.migrate_default_switch(cpath, vpath, marker))
        with open(cpath) as f:
            self.assertEqual(f.read(), old)

    def test_migrate_quoted_vconsole(self):
        old = kb.conf_text([("de", ""), ("us", "")], ["grp:alt_shift_toggle"])
        changed, conf, vcon, *_r = self.migrate_files(old, 'KEYMAP=de\nXKBOPTIONS="grp:alt_shift_toggle"\n')
        self.assertTrue(changed)
        self.assertIn('Option "XkbOptions" "grp:shifts_toggle"', conf)
        self.assertEqual(vcon, 'KEYMAP=de\nXKBOPTIONS="grp:shifts_toggle"\n')

    def test_migrate_keeps_custom_choice(self):
        for opts in (["grp:ctrl_shift_toggle"], [], ["compose:ralt"], ["grp:caps_toggle", "compose:ralt"]):
            text = kb.conf_text([("cz", ""), ("us", "")], opts)
            changed, conf, _v, marked, *_r = self.migrate_files(text, None)
            self.assertFalse(changed, opts)
            self.assertEqual(conf, text, opts)
            self.assertTrue(marked, opts)       # rozhodnuto - uz nikdy znovu

    def test_migrate_without_config(self):
        # Instalace jeste rozlozeni nezapsala: nic, ani znacka (zkusi se pri dalsi aktualizaci)
        changed, conf, vcon, marked, *_r = self.migrate_files(None, None)
        self.assertFalse(changed)
        self.assertIsNone(conf)
        self.assertFalse(marked)

    def test_migrate_marker_blocks(self):
        old = kb.conf_text([("cz", ""), ("us", "")], ["grp:alt_shift_toggle"])
        changed, conf, *_r = self.migrate_files(old, None, marker_exists=True)
        self.assertFalse(changed)
        self.assertEqual(conf, old)


class Catalog(unittest.TestCase):
    def test_fake_rules(self):
        with tempfile.NamedTemporaryFile("w", suffix=".lst", delete=False) as f:
            f.write("! model\n  pc105  Generic 105-key PC\n\n! layout\n  us   English (US)\n  cz   Czech\n"
                    "  ara  Arabic\n\n! variant\n  qwerty  cz: Czech (QWERTY)\n  phonetic ua: Ukrainian (phonetic)\n"
                    "\n! option\n  grp:alt_shift_toggle  Alt+Shift\n")
        try:
            cat = kb.load_catalog(f.name)
        finally:
            os.unlink(f.name)
        keys = [k for k, _d in cat]
        self.assertEqual(keys[0], ("us", ""))                       # bezna nahore
        self.assertEqual(len(keys), len(set(keys)))                 # bez duplicit
        self.assertIn(("ara", ""), keys)
        self.assertIn(("ua", "phonetic"), keys)
        self.assertNotIn(("grp:alt_shift_toggle", ""), keys)        # volby nejsou rozlozeni
        self.assertEqual(kb.describe(("ua", "phonetic"), cat), "Ukrainian (phonetic)")
        self.assertEqual(kb.describe(("cz", "qwerty"), cat), "Czech (QWERTY)")
        self.assertEqual(kb.describe(("xx", "yy")), "xx (yy)")
        self.assertEqual(kb.short(("cz", "qwerty")), "CZ qwerty")

    @unittest.skipUnless(os.path.exists("/usr/share/X11/xkb/rules/evdev.lst"), "no evdev.lst")
    def test_real_rules(self):
        keys = [k for k, _d in kb.load_catalog("/usr/share/X11/xkb/rules/evdev.lst")]
        self.assertGreater(len(keys), 300)
        for k in keys:   # vse z katalogu musi projit kontrolou pred zapisem
            kb.validate([k])


def under_xvfb():
    return bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


FAKE_TOOL = """#!/bin/sh
printf '%s\\n' "$(basename "$0") $*" >> "$KBD_TEST_LOG"
case "$(basename "$0") $1" in
    "setxkbmap -query") printf 'rules:      evdev\\nmodel:      pc105\\nlayout:     de\\noptions:    compose:ralt\\n' ;;
    "xfconf-query -c") case "$*" in *" -s "*) ;; *) echo "${KBD_TEST_XKBDISABLE:-true}" ;; esac ;;
    "localectl set-x11-keymap") [ -n "$KBD_TEST_DENY" ] && { echo "Access denied" >&2; exit 1; } ;;
esac
exit 0
"""


@unittest.skipUnless(under_xvfb(), "GUI only under xvfb-run (never on a real display)")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="luxos-kbd-")
        fake = os.path.join(cls.tmp, "bin")
        os.makedirs(fake)
        for tool in ("setxkbmap", "localectl", "xfconf-query", "xfce4-keyboard-settings"):
            p = os.path.join(fake, tool)
            with open(p, "w") as f:
                f.write(FAKE_TOOL)
            os.chmod(p, stat.S_IRWXU)
        os.environ["PATH"] = fake + ":" + os.environ["PATH"]
        os.environ["KBD_TEST_LOG"] = cls.log = os.path.join(cls.tmp, "log")
        conf = os.path.join(cls.tmp, "00-keyboard.conf")
        with open(conf, "w") as f:
            f.write(kb.conf_text([("cz", ""), ("us", "")], ["grp:alt_shift_toggle"]))
        kb.CONF, kb.VCONSOLE = conf, os.path.join(cls.tmp, "vconsole.conf")
        os.environ["LUXOS_I18N_DIR"] = I18N
        loader = importlib.machinery.SourceFileLoader("luxos_keyboard_app", os.path.join(BIN, "luxos-keyboard"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.app = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.app)
        from gi.repository import Gtk
        cls.Gtk = Gtk

    def setUp(self):
        open(self.log, "w").close()
        os.environ.pop("KBD_TEST_DENY", None)
        os.environ.pop("KBD_TEST_XKBDISABLE", None)

    def pump(self, until=None, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            while self.Gtk.events_pending():
                self.Gtk.main_iteration_do(False)
            if until is None or until():
                return True
            time.sleep(0.02)
        return False

    def calls(self, prefix):
        with open(self.log) as f:
            return [ln.strip() for ln in f if ln.startswith(prefix)]

    def test_edit_and_apply(self):
        w = self.app.KeyboardSettings()
        w.show_all()
        w.update()
        self.pump()
        self.assertEqual(w.layouts, [("cz", ""), ("us", "")])
        self.assertEqual(w.switch.get_active_id(), "grp:alt_shift_toggle")
        self.assertFalse(w.apply_btn.get_sensitive())            # nic se nezmenilo
        self.assertFalse(w.note.get_visible())
        # pridat (dialog s hledanim), presunout, odebrat
        dlg = self.app.AddDialog(w, w.catalog, set(w.layouts))
        dlg.show_all()
        dlg.entry.set_text("german")
        self.pump()
        visible = [r for r in dlg.lb.get_children() if dlg.flt(r)]
        self.assertTrue(visible and all("german" in r.hay for r in visible))
        self.assertNotIn(("cz", ""), [r.key for r in dlg.lb.get_children()])   # uz pouzite chybi
        dlg.lb.select_row(next(r for r in visible if r.key == ("de", "")))
        self.assertEqual(dlg.chosen(), ("de", ""))
        dlg.destroy()
        w.layouts.append(("de", ""))
        w.changed()
        w.move(2, -1)
        self.assertEqual(w.layouts, [("cz", ""), ("de", ""), ("us", "")])
        w.move(0, -1)                                             # mimo rozsah - nic
        w.remove(2)
        self.assertEqual(w.layouts, [("cz", ""), ("de", "")])
        w.switch.set_active_id("grp:caps_toggle")
        self.pump()
        self.assertTrue(w.apply_btn.get_sensitive())
        # nahled v relaci
        self.assertIn("setxkbmap -layout cz,de -variant , -option  -option grp:caps_toggle", self.calls("setxkbmap"))
        # pouziti pro cely system
        open(self.log, "w").close()
        w.on_apply(None)
        self.assertTrue(self.pump(lambda: not w.busy))
        self.assertEqual(self.calls("localectl"), ["localectl set-x11-keymap cz,de  , grp:caps_toggle"])
        self.assertIn("xfconf-query -c keyboard-layout -p /Default/XkbDisable -n -t bool -s true",
                      self.calls("xfconf-query"))
        self.assertTrue(self.calls("setxkbmap -layout cz,de"))
        self.assertFalse(w.apply_btn.get_sensitive())
        self.assertFalse(w.dirty())
        # zavreni bez dalsich zmen: zadny navrat
        open(self.log, "w").close()
        w.on_close()
        self.assertEqual(self.calls("setxkbmap"), [])
        w.destroy()

    def test_remove_last_and_limit(self):
        w = self.app.KeyboardSettings()
        w.show_all()
        w.remove(1)
        w.remove(0)                                               # posledni zustane
        self.assertEqual(w.layouts, [("cz", "")])
        w.layouts += [("us", ""), ("de", ""), ("fr", "")]
        w.changed()
        add = [c for c in self._walk(w) if isinstance(c, self.Gtk.Button) and c.get_label() == self.app._("Add Layout…")]
        self.assertTrue(add and not add[0].get_sensitive())       # 4 = maximum
        w.destroy()

    def test_switch_offered_when_second_layout_added(self):
        with open(kb.CONF) as f:
            saved = f.read()
        with open(kb.CONF, "w") as f:
            f.write(kb.conf_text([("de", "")]))
        try:
            w = self.app.KeyboardSettings()
            self.assertEqual(w.switch.get_active_id(), "none")
            orig = self.app.AddDialog
            self.app.AddDialog = type("D", (), {"__init__": lambda s, *a: None, "show_all": lambda s: None,
                                                "run": lambda s: self.Gtk.ResponseType.OK,
                                                "chosen": lambda s: ("us", ""), "destroy": lambda s: None})
            try:
                w.on_add(None)
            finally:
                self.app.AddDialog = orig
            self.assertEqual(w.layouts, [("de", ""), ("us", "")])
            self.assertEqual(w.options, ["grp:shifts_toggle"])     # vychozi: obe klavesy Shift
            self.assertEqual(w.switch.get_active_id(), "grp:shifts_toggle")
            w.destroy()
        finally:
            with open(kb.CONF, "w") as f:
                f.write(saved)

    def test_denied_and_revert_on_close(self):
        os.environ["KBD_TEST_DENY"] = "1"
        w = self.app.KeyboardSettings()
        w.show_all()
        w.move(0, 1)
        w.on_apply(None)
        self.assertTrue(self.pump(lambda: not w.busy))
        self.assertIn("cancelled", w.status.get_text())
        self.assertTrue(w.dirty())
        self.assertEqual(self.calls("xfconf-query -c keyboard-layout -p /Default/XkbDisable -n"), [])
        open(self.log, "w").close()
        w.on_close()
        # navrat do stavu relace pred otevrenim (falesny setxkbmap -query: de + compose:ralt)
        self.assertEqual(self.calls("setxkbmap"), ["setxkbmap -layout de -variant  -option  -option compose:ralt"])
        w.destroy()

    def test_user_override_note(self):
        os.environ["KBD_TEST_XKBDISABLE"] = "false"
        w = self.app.KeyboardSettings()
        w.show_all()
        w.update()
        self.pump()
        self.assertTrue(w.note.get_visible())
        self.assertTrue(w.apply_btn.get_sensitive())              # i beze zmeny: vratit uzivatele k systemu
        w.destroy()

    def _walk(self, w):
        yield w
        if isinstance(w, self.Gtk.Container):
            for c in w.get_children():
                yield from self._walk(c)


if __name__ == "__main__":
    unittest.main()
