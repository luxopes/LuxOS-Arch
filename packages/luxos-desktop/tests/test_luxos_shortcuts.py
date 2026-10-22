"""Testy pro Klavesove zkratky: luxos_shortcuts (nazvy zkratek, xfconf, kolize, vlastni zkratky)
a okno luxos-shortcuts (jen pod Xvfb).

Spusteni:  python3 -m unittest packages/luxos-desktop/tests/test_luxos_shortcuts.py -v
GUI cast:  env -u DISPLAY xvfb-run -a -s "-screen 0 1280x900x24" python3 -m unittest \
               packages/luxos-desktop/tests/test_luxos_shortcuts.py -v
LUXOS_SHOT_DIR=/slozka ulozi snimky okna pro vizualni kontrolu.
Vsechna volani xfconf-query jdou na falesny prikaz z fake-shortcuts (LUXOS_XFCONF_QUERY),
skutecne nastaveni uzivatele se nemeni.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.normpath(os.path.join(HERE, "..", "files", "python"))
BIN = os.path.normpath(os.path.join(HERE, "..", "files", "bin"))
FAKE_XFCONF = os.path.join(HERE, "fake-shortcuts", "xfconf-query")
DEFAULTS_XML = os.path.normpath(os.path.join(
    HERE, "..", "files", "xdg", "xfce4", "xfconf", "xfce-perchannel-xml", "xfce4-keyboard-shortcuts.xml"))

TMP = tempfile.mkdtemp(prefix="luxos-shortcuts-test-")
# Nikdy skutecny xfconf ani konfigurace uzivatele - nastavit pred importem modulu
os.environ.update({
    "LUXOS_XFCONF_QUERY": FAKE_XFCONF,
    "FAKE_XFCONF_DEFAULTS": DEFAULTS_XML,
    "FAKE_XFCONF": os.path.join(TMP, "xfconf.json"),
    "FAKE_XFCONF_LOG": os.path.join(TMP, "xfconf.log"),
    "LUXOS_SHORTCUTS_DEFAULTS": DEFAULTS_XML,
    "LUXOS_XKB_CONF": os.path.join(TMP, "00-keyboard.conf"),
    "XDG_CONFIG_HOME": os.path.join(TMP, "config"),
    "LUXOS_PYDIR": PYDIR,
    "LANG": "en_US.UTF-8",
})
os.environ.pop("LC_ALL", None)
os.environ.pop("LC_MESSAGES", None)
os.environ.pop("FAKE_XFCONF_FAIL", None)
sys.path.insert(0, PYDIR)
sys.path.insert(1, os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
import luxos_shortcuts as ls  # noqa: E402


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def reset_fake():
    for p in (os.environ["FAKE_XFCONF"], os.environ["FAKE_XFCONF_LOG"], ls.store_path(),
              os.environ["LUXOS_XKB_CONF"]):
        if os.path.exists(p):
            os.unlink(p)


def user_values():
    try:
        with open(os.environ["FAKE_XFCONF"]) as f:
            return json.load(f)
    except OSError:
        return {}


def calls():
    try:
        with open(os.environ["FAKE_XFCONF_LOG"]) as f:
            return [json.loads(line) for line in f]
    except OSError:
        return []


def writes():
    return [c for c in calls() if "-s" in c or "-r" in c]


def action(model, aid):
    return next(a for a in model.actions() if a.id == aid)


class Accel(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(ls.parse_accel("<Super><Shift>4"), (frozenset({"super", "shift"}), "4"))
        self.assertEqual(ls.parse_accel("XF86Calculator"), (frozenset(), "XF86Calculator"))
        self.assertEqual(ls.parse_accel("<Super>A"), (frozenset({"super"}), "a"))
        for bad in ("", None, "<Super>", "<Foo>a", "<Super", "<Super>a b", 5):
            self.assertIsNone(ls.parse_accel(bad), bad)

    def test_normalize(self):
        self.assertEqual(ls.normalize("<Shift><Super>Down"), ls.normalize("<Super><Shift>Down"))
        self.assertEqual(ls.normalize("<Super><Shift>3"), "<Shift><Super>3")
        self.assertEqual(ls.normalize("<Control><Alt>Delete"), "<Primary><Alt>Delete")
        self.assertEqual(ls.normalize("<Mod4>space"), "<Super>space")
        self.assertEqual(ls.normalize("<Mod1>F4"), "<Alt>F4")
        self.assertEqual(ls.normalize("<Super>E"), "<Super>e")
        self.assertNotEqual(ls.normalize("<Super>Tab"), ls.normalize("<Super><Shift>Tab"))
        # Tvar z make_accel se znovu rozpozna stejne
        for t in ("<Primary><Shift><Alt><Super>x", "F11", "<Super>KP_1"):
            self.assertEqual(ls.normalize(ls.normalize(t)), ls.normalize(t))

    def test_format(self):
        f = ls.format_accel
        self.assertEqual(f("<Super><Shift>4"), "Super + Shift + 4")
        self.assertEqual(f("<Shift><Super>4"), "Super + Shift + 4")
        self.assertEqual(f("<Primary><Super>f"), "Ctrl + Super + F")
        self.assertEqual(f("<Super><Alt>Escape"), "Super + Alt + Esc")
        self.assertEqual(f("<Primary><Alt>Delete"), "Ctrl + Alt + Delete")
        self.assertEqual(f("<Super>comma"), "Super + ,")
        self.assertEqual(f("<Super>space"), "Super + Space")
        self.assertEqual(f("<Super>Up"), "Super + ↑")
        self.assertEqual(f("<Super>grave"), "Super + `")
        self.assertEqual(f("XF86Calculator"), "Calculator")
        self.assertEqual(f("XF86AudioPlay"), "Audio Play")
        self.assertEqual(f("<Super>KP_1"), "Super + Num 1")
        self.assertEqual(f("<Alt><Shift>Page_Down"), "Alt + Shift + Page Down")
        self.assertEqual(f("<Shift>Print"), "Shift + Print Screen")
        self.assertNotIn("⌘", f("<Super>q"))

    def test_allowed(self):
        a = ls.accel_allowed
        self.assertTrue(a("<Super>e"))
        self.assertTrue(a("<Primary><Alt>t"))
        self.assertTrue(a("F11"))
        self.assertTrue(a("Print"))
        self.assertTrue(a("XF86Calculator"))
        self.assertFalse(a("e"))                  # pismeno bez modifikatoru by blokovalo psani
        self.assertFalse(a("<Shift>e"))
        self.assertFalse(a("Escape"))
        self.assertFalse(a("<Super>Shift_L"))     # jen modifikatory
        self.assertFalse(a(""))


class Parsing(unittest.TestCase):
    def test_listing(self):
        text = ("/commands/custom/<Super>e                  thunar\n"
                "/commands/custom/<Super>t                  xfce4-terminal --drop-down\n"
                "/commands/custom/<Super>t/startup-notify   true\n"
                "/commands/custom/<Super>x\n"
                "/commands/custom/override                  true\n"
                "/commands/default/<Alt>F2                  xfrun4\n"
                "/xfwm4/custom/<Super>q                     close_window_key\n"
                "/xfwm4/default/<Alt>F4                     close_window_key\n")
        out = ls.parse_listing(text)
        self.assertEqual(out["cmd"], {"<Super>e": "thunar", "<Super>t": "xfce4-terminal --drop-down",
                                      "<Super>x": ""})
        self.assertEqual(out["wm"], {"<Super>q": "close_window_key"})
        self.assertEqual(ls.parse_listing(""), {"cmd": {}, "wm": {}})

    def test_defaults_xml(self):
        d = ls.read_defaults(DEFAULTS_XML)
        self.assertEqual(d["cmd"]["<Super>e"], "thunar")
        self.assertEqual(d["cmd"]["<Super><Shift>4"], "luxos-screenshot --portion")
        self.assertEqual(d["wm"]["<Super>q"], "close_window_key")
        self.assertNotIn("override", d["cmd"])
        self.assertEqual(ls.read_defaults(os.path.join(TMP, "missing.xml")), {"cmd": {}, "wm": {}})

    def test_layout_switch(self):
        p = os.path.join(TMP, "kb.conf")
        with open(p, "w") as f:
            f.write('Section "InputClass"\n  Option "XkbLayout" "cz,us"\n'
                    '  Option "XkbOptions" "terminate:ctrl_alt_bksp,grp:alt_shift_toggle"\nEndSection\n')
        self.assertEqual(ls.layout_switch(p), "Alt + Shift")
        with open(p, "w") as f:
            f.write('Option "XkbOptions" "grp:win_space_toggle"\n')
        self.assertEqual(ls.layout_switch(p), "Super + Space")
        with open(p, "w") as f:
            f.write('Option "XkbLayout" "us"\n')
        self.assertIsNone(ls.layout_switch(p))
        self.assertIsNone(ls.layout_switch(os.path.join(TMP, "none.conf")))

    def test_short_label(self):
        self.assertEqual(ls.short_label("exo-open --launch WebBrowser"), "Web Browser")
        self.assertEqual(ls.short_label("/usr/bin/xfce4-appfinder --collapsed"), "xfce4-appfinder")
        self.assertEqual(ls.short_label("exo-open --launch"), "exo-open")
        self.assertEqual(ls.short_label("bad 'quote"), "bad")

    def test_field_codes(self):
        self.assertEqual(ls.strip_field_codes("firefox %u"), "firefox")
        self.assertEqual(ls.strip_field_codes("env A=1 'my app' --file=%f"), "env A=1 'my app' --file=")
        self.assertEqual(ls.strip_field_codes("echo 100%%"), "echo 100%")


class Store(unittest.TestCase):
    def setUp(self):
        reset_fake()

    def test_roundtrip_and_broken(self):
        p = os.path.join(TMP, "s", "shortcuts.json")
        self.assertEqual(ls.load_names(p), {})
        ls.save_names({"<Super>n": {"name": "Notes", "command": "mousepad"}}, p)
        self.assertEqual(ls.load_names(p), {"<Super>n": {"name": "Notes", "command": "mousepad"}})
        with open(p, "w") as f:
            f.write("{broken")
        self.assertEqual(ls.load_names(p), {})
        with open(p, "w") as f:
            json.dump({"custom": {"<Mod4>n": {"name": "A", "command": "a"}, "bad<": {"name": "x", "command": "y"},
                                  "<Super>m": "nope", "<Super>k": {"name": 1, "command": "z"}}}, f)
        self.assertEqual(ls.load_names(p), {"<Super>n": {"name": "A", "command": "a"}})
        with open(p, "w") as f:
            json.dump([1, 2], f)
        self.assertEqual(ls.load_names(p), {})


class Model(unittest.TestCase):
    def setUp(self):
        reset_fake()
        self.m = ls.Shortcuts()

    def test_initial(self):
        m = self.m
        self.assertTrue(m.available)
        self.assertEqual(m.accels_for(action(m, "close")), ["<Super>q", "<Alt>F4"])
        self.assertEqual(m.accels_for(action(m, "hide")), ["<Super>m", "<Super>h", "<Super>Down"])
        self.assertEqual(m.accels_for(action(m, "shot-region")), ["<Shift><Super>4", "<Shift>Print"])
        self.assertEqual(m.accels_for(action(m, "search")), ["<Super>space"])
        self.assertTrue(all(m.is_default(a) for a in m.actions()))
        self.assertEqual(m.custom_actions(), [])
        self.assertEqual(writes(), [])            # cteni nic nezapisuje
        self.assertTrue(all(c[:2] == ["-c", "xfce4-keyboard-shortcuts"] for c in calls()))

    def test_conflict(self):
        m = self.m
        files = action(m, "files")
        self.assertIsNone(m.conflict(files, "<Super>e"))           # vlastni zkratka
        self.assertIsNone(m.conflict(files, "<Super>y"))           # volna
        self.assertEqual(m.conflict(files, "<Super>t"), "Terminal")
        self.assertEqual(m.conflict(files, "<Super>q"), "Close window")   # napric prikazy / xfwm4
        self.assertEqual(m.conflict(action(m, "close"), "<Super>e"), "Files")
        self.assertEqual(m.conflict(None, ls.normalize("<Super><Shift>3")), "Screenshot")
        self.assertEqual(m.conflict(files, "<Primary><Super>1"), "Go to workspace 1")

    def test_change_and_restore(self):
        m = self.m
        files = action(m, "files")
        self.assertTrue(m.assign(files, "<Super>f", replace="<Super>e"))
        self.assertEqual(m.accels_for(files), ["<Super>f"])
        self.assertFalse(m.is_default(files))
        u = user_values()
        self.assertEqual(u["/commands/custom/<Super>e"], "")       # systemova zkratka vypnuta prazdnou hodnotou
        self.assertEqual(u["/commands/custom/<Super>f"], "thunar")
        self.assertTrue(m.restore(files))
        self.assertEqual(m.accels_for(files), ["<Super>e"])
        self.assertTrue(m.is_default(files))
        self.assertEqual(user_values(), {})                         # zadne zbytky

    def test_replace_conflict(self):
        m = self.m
        files, term = action(m, "files"), action(m, "terminal")
        m.assign(files, "<Super>t", replace="<Super>e")
        self.assertEqual(m.accels_for(files), ["<Super>t"])
        self.assertEqual(m.accels_for(term), ["<Primary><Alt>t"])   # druha zkratka Terminalu zustala
        self.assertEqual(m.owner_label("<Super>t"), "Files")
        m.restore(term)
        self.assertEqual(m.accels_for(term), ["<Super>t", "<Primary><Alt>t"])
        self.assertEqual(m.accels_for(files), [])                   # Soubory zkratku vratily

    def test_cross_kind_conflict(self):
        m = self.m
        lp = action(m, "launchpad")
        m.assign(lp, "<Super>q", replace="<Super>a")
        self.assertEqual(m.accels_for(action(m, "close")), ["<Alt>F4"])
        self.assertEqual(user_values()["/xfwm4/custom/<Super>q"], "")
        self.assertEqual(m.accels_for(lp), ["<Super>q", "XF86LaunchA"])

    def test_raw_property_name_reused(self):
        # Systemova vlastnost je "<Super><Shift>4" - zapis musi pouzit stejny nazev, ne kanonicky
        m = self.m
        shot = action(m, "shot-region")
        m.assign(shot, "<Primary><Super>4", replace=ls.normalize("<Super><Shift>4"))
        u = user_values()
        self.assertEqual(u["/commands/custom/<Super><Shift>4"], "")
        self.assertEqual(u["/commands/custom/<Primary><Super>4"], "luxos-screenshot --portion")
        self.assertNotIn("/commands/custom/<Shift><Super>4", u)

    def test_same_accel_noop(self):
        m = self.m
        files = action(m, "files")
        m.assign(files, "<Super>e", replace="<Super>e")
        self.assertEqual(user_values(), {})
        self.assertEqual(m.accels_for(files), ["<Super>e"])

    def test_disable(self):
        m = self.m
        close = action(m, "close")
        self.assertTrue(m.disable(close))
        self.assertEqual(m.accels_for(close), [])
        self.assertIsNone(m.owner("<Super>q"))
        m.restore(close)
        self.assertEqual(m.accels_for(close), ["<Super>q", "<Alt>F4"])

    def test_custom(self):
        m = self.m
        self.assertTrue(m.save_custom("Notes", "mousepad", "<Super>n"))
        cust = m.custom_actions()
        self.assertEqual([(a.label, a.value) for a in cust], [("Notes", "mousepad")])
        self.assertEqual(ls.load_names(), {"<Super>n": {"name": "Notes", "command": "mousepad"}})
        self.assertEqual(m.conflict(action(m, "files"), "<Super>n"), "Notes")
        # Zmena zkratky a nazvu
        self.assertTrue(m.save_custom("My Notes", "mousepad ~/notes.txt", "<Super><Alt>n", old="<Super>n"))
        self.assertIsNone(m.owner("<Super>n"))
        self.assertEqual([(a.label, a.value) for a in m.custom_actions()],
                         [("My Notes", "mousepad ~/notes.txt")])
        self.assertEqual(list(ls.load_names()), ["<Alt><Super>n"])
        # Smazani
        self.assertTrue(m.delete_custom("<Alt><Super>n"))
        self.assertEqual(m.custom_actions(), [])
        self.assertEqual(ls.load_names(), {})
        self.assertEqual(user_values(), {})

    def test_custom_overrides_default_then_delete(self):
        m = self.m
        m.save_custom("Browser", "firefox", "<Super>l")
        self.assertEqual(m.accels_for(action(m, "lock")), ["<Primary><Super>q"])
        self.assertEqual(m.owner_label("<Super>l"), "Browser")
        m.delete_custom("<Super>l")
        self.assertEqual(m.accels_for(action(m, "lock")), ["<Primary><Super>q", "<Super>l"])

    def test_named_custom_with_catalog_command(self):
        # Vlastni zkratka se stejnym prikazem jako katalog patri do Vlastnich, ne k Souborum
        m = self.m
        m.save_custom("Second Files", "thunar", "<Super>j")
        self.assertEqual(m.accels_for(action(m, "files")), ["<Super>e"])
        self.assertEqual([a.label for a in m.custom_actions()], ["Second Files"])

    def test_unnamed_custom_from_xfconf(self):
        ls.xfconf("-p", "/commands/custom/<Super>g", "-n", "-t", "string", "-s", "gimp")
        m = ls.Shortcuts()
        self.assertEqual([(a.label, a.value, a.id) for a in m.custom_actions()],
                         [("gimp", "gimp", "custom:<Super>g")])
        # Pojmenovany zaznam s jinym prikazem se nepouzije
        ls.save_names({"<Super>g": {"name": "Old", "command": "inkscape"}})
        m.reload()
        self.assertEqual(m.custom_actions()[0].label, "gimp")

    def test_restore_all(self):
        m = self.m
        m.save_custom("Notes", "mousepad", "<Super>n")
        m.save_custom("Browser", "firefox", "<Super>l")             # prebira vychozi zkratku
        m.assign(action(m, "files"), "<Super>f", replace="<Super>e")
        m.disable(action(m, "close"))
        self.assertTrue(m.restore_all())
        self.assertTrue(all(m.is_default(a) for a in m.catalog))
        self.assertEqual([a.label for a in m.custom_actions()], ["Notes"])
        self.assertEqual(ls.load_names(), {"<Super>n": {"name": "Notes", "command": "mousepad"}})
        self.assertEqual(user_values(), {"/commands/custom/<Super>n": "mousepad"})

    def test_other_actions(self):
        # Vychozi prikazy mimo katalog (tady zadne krome katalogovych) a xfwm4 mimo katalog se nezobrazi
        defaults = {"cmd": {"<Super>e": "thunar", "<Alt>F2": "xfrun4", "<Super>r": "xfrun4"},
                    "wm": {"<Super>q": "close_window_key"}}
        m = ls.Shortcuts(defaults=defaults)
        other = m.other_actions()
        self.assertEqual([(a.id, a.label) for a in other], [("other:xfrun4", "xfrun4")])
        self.assertEqual(m.accels_for(other[0]), [])          # falesny xfconf je ma vypnute (nejsou v XML)

    def test_xfconf_unavailable(self):
        os.environ["FAKE_XFCONF_FAIL"] = "1"
        try:
            m = ls.Shortcuts()
            self.assertFalse(m.available)
            self.assertEqual(m.accels_for(action(m, "files")), ["<Super>e"])   # zobrazi vychozi
            self.assertFalse(m.assign(action(m, "files"), "<Super>f", replace="<Super>e"))
        finally:
            del os.environ["FAKE_XFCONF_FAIL"]
        self.assertEqual(user_values(), {})

    def test_never_real_xfconf(self):
        self.assertEqual(ls.xfconf_cmd(), FAKE_XFCONF)


def load_app():
    loader = importlib.machinery.SourceFileLoader("luxos_shortcuts_app", os.path.join(BIN, "luxos-shortcuts"))
    spec = importlib.util.spec_from_loader("luxos_shortcuts_app", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# Jen virtualni X z xvfb-run (nebo vyslovne LUXOS_TEST_X=1 ve VM) - nikdy skutecna obrazovka
@unittest.skipUnless(os.environ.get("DISPLAY") and ("xvfb-run" in os.environ.get("XAUTHORITY", "")
                                                    or os.environ.get("LUXOS_TEST_X") == "1"),
                     "potrebuje virtualni X (xvfb-run)")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()
        from gi.repository import Gdk, GLib, Gtk
        cls.Gdk, cls.GLib, cls.Gtk = Gdk, GLib, Gtk
        provider = Gtk.CssProvider()
        provider.load_from_data(cls.app.CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def setUp(self):
        reset_fake()
        with open(os.environ["LUXOS_XKB_CONF"], "w") as f:
            f.write('Option "XkbOptions" "grp:alt_shift_toggle"\n')
        self.asked = []
        self.answer = True
        self.app.ask = self.fake_ask
        self.app.warn = lambda _p, text: self.asked.append(("warn", text))
        self.win = self.app.ShortcutsWindow()
        self.win.show_all()
        self.pump(0.3)

    def tearDown(self):
        self.win.destroy()
        self.pump(0.1)

    def fake_ask(self, _parent, text, secondary, ok_label, destructive=False):
        self.asked.append(("ask", text))
        return self.answer

    def pump(self, seconds):
        end = time.time() + seconds
        ctx = self.GLib.MainContext.default()
        while time.time() < end:
            while ctx.pending():
                ctx.iteration(False)
            time.sleep(0.01)

    def labels(self, widget):
        out = []

        def collect(w):
            if isinstance(w, self.Gtk.Label):
                out.append(w.get_text())
            elif isinstance(w, self.Gtk.Button) and w.get_label():
                out.append(w.get_label())
            if isinstance(w, self.Gtk.Container):
                w.foreach(collect)
        collect(widget)
        return out

    def shot(self, name, row=None):
        d = os.environ.get("LUXOS_SHOT_DIR")
        if not d:
            return
        os.makedirs(d, exist_ok=True)
        self.pump(0.3)
        if row is not None:
            # Posunout seznam k radku (spodni sekce nejsou bez posunuti videt)
            _x, y = row.translate_coordinates(self.win.page, 0, 0)
            self.win.scroll.get_vadjustment().set_value(max(0, y - 200))
            self.pump(0.3)
        win = self.win.get_window()
        w, h = win.get_width(), win.get_height()
        pix = self.Gdk.pixbuf_get_from_window(win, 0, 0, w, h)
        pix.savev(os.path.join(d, name + ".png"), "png", [], [])

    def key_event(self, keyval, state=0):
        Gdk = self.Gdk
        ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        ev.keyval = keyval
        ev.state = Gdk.ModifierType(state)
        ok, keys = Gdk.Keymap.get_for_display(Gdk.Display.get_default()).get_entries_for_keyval(keyval)
        ev.hardware_keycode = keys[0].keycode if ok and keys else 0
        ev.group = 0
        return ev

    def test_window(self):
        page = self.labels(self.win.page)
        for title in ("Windows", "Apps & System", "Screenshots", "Custom Shortcuts", "Other Xfce Shortcuts"):
            if title == "Other Xfce Shortcuts":
                continue                     # zdrojove XML LuxOS nema prikazy mimo katalog
            self.assertIn(title, page)
        self.assertIn("Super + Q, Alt + F4", page)
        self.assertIn("Super + Shift + 4, Shift + Print Screen", page)
        self.assertIn("Switch keyboard layout", page)
        self.assertIn("Alt + Shift", page)
        self.assertIn("Add Shortcut…", page)
        self.assertFalse(any("⌘" in t for t in page))
        self.assertEqual(writes(), [])
        self.shot("shortcuts-window")
        self.shot("shortcuts-window-apps", self.win.rows["search"])

    def test_capture_dialog_keys(self):
        Gdk = self.Gdk
        dlg = self.app.CaptureDialog(self.win, "Files")
        dlg.show_all()
        self.pump(0.2)
        responses = []
        dlg.connect("response", lambda _d, r: responses.append(r))
        # Pismeno bez modifikatoru se neprijme
        dlg.on_key(dlg, self.key_event(Gdk.KEY_e))
        self.assertIsNone(dlg.result)
        self.assertIn("Use at least one", dlg.hint.get_text())
        # Super + Shift + 4 (keyval dollar se prevede na zakladni klavesu 4)
        dlg.on_key(dlg, self.key_event(Gdk.KEY_dollar, Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.SHIFT_MASK))
        self.assertEqual(ls.normalize(dlg.result[1]), "<Shift><Super>4")
        self.assertEqual(responses, [self.Gtk.ResponseType.OK])
        dlg.destroy()

        dlg = self.app.CaptureDialog(self.win, "Files")
        dlg.show_all()
        dlg.on_key(dlg, self.key_event(Gdk.KEY_BackSpace))
        self.assertEqual(dlg.result, ("off", None))
        dlg.destroy()

        dlg = self.app.CaptureDialog(self.win, "Files")
        dlg.show_all()
        responses = []
        dlg.connect("response", lambda _d, r: responses.append(r))
        dlg.on_key(dlg, self.key_event(Gdk.KEY_Escape))
        self.assertIsNone(dlg.result)
        self.assertEqual(responses, [self.Gtk.ResponseType.CANCEL])
        dlg.destroy()

        # Pri pridavani vlastni zkratky Backspace nic nevypina
        dlg = self.app.CaptureDialog(self.win, "New", allow_disable=False)
        dlg.show_all()
        self.shot_dialog(dlg, "shortcuts-capture")
        dlg.on_key(dlg, self.key_event(Gdk.KEY_BackSpace))
        self.assertNotEqual(dlg.result, ("off", None))
        dlg.destroy()

    def shot_dialog(self, dlg, name):
        d = os.environ.get("LUXOS_SHOT_DIR")
        if not d:
            return
        os.makedirs(d, exist_ok=True)
        self.pump(0.3)
        win = dlg.get_window()
        pix = self.Gdk.pixbuf_get_from_window(win, 0, 0, win.get_width(), win.get_height())
        pix.savev(os.path.join(d, name + ".png"), "png", [], [])

    def test_change_with_conflict(self):
        m = self.win.model
        files = action(m, "files")
        self.answer = False
        self.assertFalse(self.win.apply_change(files, ("set", "<Super>t")))
        self.assertEqual(self.asked[0][0], "ask")
        self.assertIn("Terminal", self.asked[0][1])
        self.assertEqual(writes(), [])                 # odmitnuti nic nezapise
        self.answer = True
        self.assertTrue(self.win.apply_change(files, ("set", "<Super>t")))
        self.assertEqual(self.win.model.accels_for(action(self.win.model, "files")), ["<Super>t"])
        self.pump(0.2)
        # Zmeneny radek ma tlacitko Obnovit
        row = self.win.rows["files"]
        tips = []
        row.foreach(lambda w: tips.append(w.get_tooltip_text()))
        self.assertIn("Restore Default", tips)
        self.shot("shortcuts-changed", self.win.rows["files"])

    def test_change_free_and_off(self):
        m = self.win.model
        self.assertTrue(self.win.apply_change(action(m, "calculator"), ("set", "<Super><Alt>c")))
        self.assertEqual(self.asked, [])               # volna zkratka - bez dotazu
        self.assertEqual(self.win.model.accels_for(action(self.win.model, "calculator")), ["<Alt><Super>c"])
        self.assertTrue(self.win.apply_change(action(self.win.model, "calculator"), ("off", None)))
        self.assertEqual(self.win.model.accels_for(action(self.win.model, "calculator")), [])
        self.assertIn("Off", self.labels(self.win.rows["calculator"]))

    def test_custom_dialog(self):
        dlg = self.app.CustomDialog(self.win, self.win.model)
        dlg.show_all()
        self.assertFalse(dlg.save.get_sensitive())
        dlg.name.set_text("Notes")
        dlg.command.set_text("mousepad")
        self.assertFalse(dlg.save.get_sensitive())     # chybi zkratka
        dlg.accel = "<Super>e"
        dlg.update()
        self.assertTrue(dlg.save.get_sensitive())
        self.assertIn("Files", dlg.note.get_text())    # upozorneni na kolizi
        dlg.accel = "<Super>n"
        dlg.update()
        self.assertEqual(dlg.note.get_text(), "")
        self.assertEqual(dlg.values(), ("Notes", "mousepad", "<Super>n"))
        self.shot_dialog(dlg, "shortcuts-add")
        dlg.destroy()
        self.assertTrue(self.win.model.save_custom("Notes", "mousepad", "<Super>n"))
        self.win.build()
        self.pump(0.2)
        self.assertIn("custom:<Super>n", self.win.rows)
        self.assertIn("Notes", self.labels(self.win.rows["custom:<Super>n"]))
        self.assertIn("Super + N", self.labels(self.win.rows["custom:<Super>n"]))
        self.shot("shortcuts-custom", self.win.rows["custom:<Super>n"])
        # Zmena zkratky vlastni polozky pres zachyceni
        cust = self.win.model.custom_actions()[0]
        self.assertTrue(self.win.apply_change(cust, ("set", "<Super>j")))
        self.assertEqual(list(ls.load_names()), ["<Super>j"])
        self.assertEqual(ls.load_names()["<Super>j"]["name"], "Notes")
        # Smazani
        self.win.delete_custom(self.win.model.custom_actions()[0])
        self.assertEqual(self.win.model.custom_actions(), [])
        self.assertEqual(user_values(), {})

    def test_app_chooser(self):
        dlg = self.app.AppChooser(self.win)
        dlg.show_all()
        self.pump(0.2)
        rows = dlg.listbox.get_children()
        if rows:
            dlg.listbox.select_row(rows[0])
            name, command = dlg.chosen()
            self.assertTrue(name and command)
            self.assertNotIn("%u", command)
            self.assertNotIn("%U", command)
        dlg.destroy()

    def test_restore_all(self):
        m = self.win.model
        m.assign(action(m, "files"), "<Super>f", replace="<Super>e")
        self.win.restore_all()
        self.assertTrue(all(self.win.model.is_default(a) for a in self.win.model.catalog))
        self.asked.clear()
        self.answer = False
        m = self.win.model
        m.assign(action(m, "files"), "<Super>f", replace="<Super>e")
        self.win.restore_all()                          # zruseno v dotazu
        self.assertFalse(self.win.model.is_default(action(self.win.model, "files")))

    def test_write_failure_warns(self):
        os.environ["FAKE_XFCONF_FAIL"] = "1"
        try:
            self.win.apply_change(action(self.win.model, "calculator"), ("set", "<Super><Alt>c"))
        finally:
            del os.environ["FAKE_XFCONF_FAIL"]
        self.assertEqual(self.asked[-1], ("warn", "The shortcut could not be saved."))


if __name__ == "__main__":
    unittest.main()
