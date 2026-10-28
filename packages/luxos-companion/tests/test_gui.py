#!/usr/bin/env python3
"""LuxOS Companion - okno Telefon. Jen ve virtualni obrazovce a soukrome sbernici relace:

    env -u DISPLAY xvfb-run -a dbus-run-session -- python3 -m unittest packages/luxos-companion/tests/test_gui.py
    (vlastni XDG_RUNTIME_DIR; snimky do LUXOS_TEST_SHOTS)
"""
import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402
from helpers import Phone, make_service, pump  # noqa: E402

UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")


@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class TestWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gio, Gtk
        cls.Gtk, cls.Gdk, cls.Gio = Gtk, Gdk, Gio
        if Gdk.Screen.get_default() is None:
            raise unittest.SkipTest("no X display")
        from luxos_companion import store, ui
        cls.ui, cls.store = ui, store
        provider = Gtk.CssProvider()
        provider.load_from_data(ui.CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def setUp(self):
        self.cfg = store_path = self.store.config_path()
        if os.path.exists(store_path):
            os.remove(store_path)

    def shot(self, win, name):
        out = os.environ.get("LUXOS_TEST_SHOTS")
        if not out:
            return
        pump(timeout=0.5)
        gw = win.get_window()
        pix = self.Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
        os.makedirs(out, exist_ok=True)
        pix.savev(os.path.join(out, name), "png", [], [])

    def window(self):
        win = self.ui.CompanionWindow()
        win.show_all()
        self.addCleanup(win.destroy)
        self.assertTrue(pump(lambda: win.get_mapped(), 5))
        return win

    def texts(self, widget):
        out = []

        def walk(w):
            if isinstance(w, self.Gtk.Label):
                out.append(w.get_text())
            elif isinstance(w, self.Gtk.Button) and w.get_label():
                out.append(w.get_label())
            if isinstance(w, self.Gtk.Container):
                for c in w.get_children():
                    walk(c)
        walk(widget)
        return out

    def test_titlebar_icons_and_not_running(self):
        win = self.window()
        bar = win.get_titlebar()
        self.assertIsInstance(bar, self.Gtk.HeaderBar)
        self.assertTrue(bar.get_show_close_button())
        self.assertTrue(bar.get_visible())
        self.assertEqual(bar.get_title(), "Phone")
        sizes = sorted(p.get_width() for p in win.get_icon_list())
        self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])
        self.assertTrue(pump(lambda: win.status_title.get_text() == "The phone service is not running.", 5))
        self.assertTrue(win.start_btn.get_visible())
        self.assertIn("No phone is allowed yet. The first connection from a paired phone asks for permission.",
                      self.texts(win.phones))
        self.shot(win, "companion-not-running.png")

    def test_phones_switches_and_live_status(self):
        st = self.store.Settings()
        st.approve("AA:BB:CC:DD:EE:01", "Pixel Test")
        st.approve("AA:BB:CC:DD:EE:05", "Tablet")
        # bezici sluzba na (soukrome) sbernici relace
        from gi.repository import Gio
        svc = make_service()
        svc.settings = self.store.Settings()
        svc.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        svc.export()
        self.addCleanup(svc.unexport)
        own = Gio.bus_own_name_on_connection(svc.bus, "cz.luxos.Companion1", 0, None, None)
        self.addCleanup(Gio.bus_unown_name, own)
        svc.bt.update(registered=True, available=True)
        win = self.window()
        self.assertTrue(pump(lambda: win.status_title.get_text() == "Ready for the phone", 5))
        self.assertFalse(win.start_btn.get_visible())
        texts = self.texts(win.phones)
        self.assertIn("Pixel Test", texts)
        self.assertIn("Tablet", texts)
        # pripojeny telefon a cekajici dotaz z jineho telefonu
        a, b = socket.socketpair()
        s = svc.new_connection(a.detach(), helpers.PHONE)
        phone = Phone(b)
        phone.send("hello", "h1", protocol=1)
        phone.wait(1)
        self.assertTrue(pump(lambda: win.status_title.get_text() == "Connected: Pixel Test", 5))
        c, d = socket.socketpair()
        s2 = svc.new_connection(c.detach(), {"address": "AA:BB:CC:DD:EE:42", "name": "Nový telefon"})
        p2 = Phone(d)
        p2.send("hello", "h2", protocol=1)
        self.assertTrue(pump(lambda: win.pending_card.get_visible(), 5))
        self.assertIn("Allow “Nový telefon” to connect to LuxOS?", self.texts(win.pending_box))
        self.shot(win, "companion-connected.png")
        allow = [w for w in self.walk(win.pending_box) if isinstance(w, self.Gtk.Button) and w.get_label() == "Allow"]
        allow[0].clicked()
        self.assertTrue(pump(lambda: p2.messages() or s2.state == "open", 5))
        self.assertTrue(pump(lambda: not win.pending_card.get_visible(), 5))
        self.assertTrue(self.store.Settings().is_approved("AA:BB:CC:DD:EE:42"))
        # prepinac -> companion.json -> sluzba (ReloadSettings)
        win.switches["allow_luxai"].set_active(False)
        self.assertFalse(self.store.Settings().get("allow_luxai"))
        self.assertTrue(pump(lambda: not svc.settings.get("allow_luxai"), 5))
        # odebrani telefonu ukonci jeho spojeni
        remove = [w for w in self.walk(win.phones) if isinstance(w, self.Gtk.Button)]
        names = [r for r in self.texts(win.phones) if r in ("Nový telefon", "Pixel Test", "Tablet")]
        self.assertEqual(names, ["Nový telefon", "Pixel Test", "Tablet"])
        remove[1].clicked()          # Pixel Test
        self.assertFalse(self.store.Settings().is_approved("AA:BB:CC:DD:EE:01"))
        self.assertTrue(phone.wait_closed(5))
        self.assertNotIn("Pixel Test", self.texts(win.phones))
        s2.close("test")

    def test_pair_a_phone_button(self):
        """Sparovat telefon…: 3 minuty viditelny (falesny BlueZ na soukrome sbernici), odpocet, konec."""
        import shutil
        if not shutil.which("dbus-daemon"):
            self.skipTest("dbus-daemon missing")
        from test_dbus import ADAPTER, DEV_UNPAIRED, FakeBluez
        proc, address = helpers.private_bus()
        self.addCleanup(proc.wait, 5)
        self.addCleanup(proc.terminate)
        fake = FakeBluez(address)
        self.addCleanup(fake.quit)
        os.environ["LUXOS_COMPANION_BLUEZ_BUS"] = address
        self.addCleanup(os.environ.pop, "LUXOS_COMPANION_BLUEZ_BUS", None)
        win = self.window()
        clock = helpers.Clock()
        win.clock = clock
        discoverable = lambda: fake.adapter["Discoverable"].unpack()  # noqa: E731
        self.assertEqual(win.pair_btn.get_label(), "Pair a Phone…")
        self.assertFalse(win.pair_info.get_visible())
        win.pair_btn.clicked()
        self.assertTrue(pump(discoverable, 5))
        self.assertEqual([(n, v) for p, _i, n, v in fake.sets if p == ADAPTER],
                         [("DiscoverableTimeout", 180), ("Discoverable", True)])
        self.assertTrue(pump(lambda: win.pair_info.get_visible(), 5))
        self.assertIn("pair with “jupiter”", win.pair_info.get_text())
        self.assertEqual(win.pair_status.get_text(), "Visible to phones for 3:00")
        self.assertEqual(win.pair_btn.get_label(), "Cancel")
        clock.advance(61)
        win.pair_tick()
        self.assertEqual(win.pair_status.get_text(), "Visible to phones for 1:59")
        self.shot(win, "companion-pairing.png")
        # telefon se sparoval -> konec viditelnosti, navod na dalsi krok; telefon jeste neni schvaleny
        fake.pair(DEV_UNPAIRED)
        self.assertTrue(pump(lambda: not discoverable(), 5))
        self.assertTrue(pump(lambda: win.pair_info.get_text().startswith("Paired with “Cizí”"), 5))
        self.assertEqual(win.pair_btn.get_label(), "Pair a Phone…")
        self.assertFalse(self.store.Settings().is_approved("AA:BB:CC:DD:EE:02"))
        # zruseni
        win.pair_btn.clicked()
        self.assertTrue(pump(discoverable, 5))
        win.pair_btn.clicked()
        self.assertFalse(discoverable())
        self.assertEqual(win.pair_status.get_text(), "Pairing cancelled. This computer is no longer visible.")
        # vyprseni 3 minut
        win.pair_btn.clicked()
        self.assertTrue(pump(lambda: win.pair_btn.get_label() == "Cancel", 5))
        clock.advance(180)
        win.pair_tick()
        self.assertFalse(discoverable())
        self.assertIn("no longer visible", win.pair_status.get_text())
        # Bluetooth vypnuty
        fake.adapter["Powered"] = helpers.GLib.Variant("b", False)
        win.pair_btn.clicked()
        self.assertTrue(pump(lambda: win.pair_status.get_text() == "Turn on Bluetooth to connect a phone.", 5))
        self.assertFalse(discoverable())

    def walk(self, widget):
        out = [widget]
        if isinstance(widget, self.Gtk.Container):
            for c in widget.get_children():
                out.extend(self.walk(c))
        return out


def tearDownModule():
    import shutil
    shutil.rmtree(helpers.TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
