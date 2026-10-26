#!/usr/bin/env python3
"""LuxDrop - GUI souboru jineho pocitace: dotaz na pristup, okno Pripojit k pocitaci, Nastaveni.

Jen pod virtualnim displejem:  env -u DISPLAY xvfb-run -a python3 tests/test_remote_gui.py -v
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("LUXDROP_LIB", os.path.abspath(os.path.join(HERE, "..", "files", "lib"))))

TMP = tempfile.mkdtemp(prefix="luxdrop-gui-")
os.environ["HOME"] = os.path.join(TMP, "home")
os.makedirs(os.environ["HOME"])
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
    os.environ.pop(k, None)
os.environ.update({"LUXDROP_NO_MDNS": "1", "LUXDROP_NO_SYSTEMD": "1", "LUXDROP_NON_UNIQUE": "1", "LANGUAGE": "en"})

HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
if HAVE_DISPLAY:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # noqa: E402

    from luxdrop import identity, remote, remote_ui, store  # noqa: E402


def pump(cond, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if cond():
            return True
        time.sleep(0.02)
    return False


def labels(widget):
    out = []
    if isinstance(widget, Gtk.Label):
        out.append(widget.get_text())
    if isinstance(widget, Gtk.Container):
        for c in widget.get_children():
            out += labels(c)
    return out


def all_widgets(w):
    out = [w]
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            out += all_widgets(c)
    return out


def find_window(title):
    for w in Gtk.Window.list_toplevels():
        if w.get_title() == title and w.get_visible():
            return w
    return None


class Side:
    def __init__(self, name):
        base = os.path.join(TMP, name)
        self.identity = identity.Identity.load_or_create(os.path.join(base, "data"))
        self.settings = store.Settings(os.path.join(base, "conf"))
        self.settings.set("name", name)
        self.trust = store.TrustStore(os.path.join(base, "data"))
        self.access = remote.Access(os.path.join(base, "data"))
        self.shares = remote.Shares(os.path.join(base, "conf"))


class AutoConfirm(remote.ConnectCallbacks):
    def __init__(self):
        self.info = None

    def status(self, state, info):
        if state == "waiting":
            self.info = info

    def confirm(self, info, replied):
        return True, True


@unittest.skipUnless(HAVE_DISPLAY, "needs a display (xvfb-run)")
class AccessDialogTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_service_asker_dialog_always_with_write(self):
        bob, alice = Side("Bob-PC"), Side("Alice-PC")
        os.makedirs(os.path.join(os.environ["HOME"], "Public"), exist_ok=True)
        bob.shares.set_enabled(True)
        server = remote.FileServer(bob.identity, bob.settings, bob.trust, bob.shares, bob.access,
                                   remote_ui.ServiceAsker(None, True), bind="127.0.0.1", port=0)
        server.start()
        cb, result = AutoConfirm(), {}

        def client():
            try:
                result["conn"] = remote.connect(alice.identity, alice.settings, alice.trust, "127.0.0.1",
                                                server.port, True, cb)
            except Exception as e:  # noqa: BLE001
                result["err"] = e

        threading.Thread(target=client, daemon=True).start()
        self.assertTrue(pump(lambda: find_window("Access to shared folders") is not None))
        dlg = find_window("Access to shared folders")
        text = "\n".join(labels(dlg))
        self.assertIn("“Alice-PC” wants to access and change your shared folders", text)
        self.assertIn("Public", text)
        self.assertTrue(pump(lambda: cb.info is not None))
        self.assertIn(cb.info["sas"][:3] + " " + cb.info["sas"][3:], text)
        checks = [w for w in all_widgets(dlg) if isinstance(w, Gtk.CheckButton)]
        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0].get_active())  # zapis neni predvybrany
        checks[0].set_active(True)
        dlg.response(2)  # Vzdy povolit
        self.assertTrue(pump(lambda: "conn" in result or "err" in result))
        self.assertNotIn("err", result)
        self.assertTrue(result["conn"].write)
        self.assertEqual(result["conn"].shares, ["Public"])
        self.assertTrue(bob.access.get(alice.identity.fp)["write"])
        self.assertTrue(alice.trust.is_trusted(bob.identity.fp))
        result["conn"].tls.close()
        server.stop()

    def test_deny_and_withdraw(self):
        bob, alice = Side("Bob2"), Side("Carol")
        bob.shares.set_enabled(True)
        server = remote.FileServer(bob.identity, bob.settings, bob.trust, bob.shares, bob.access,
                                   remote_ui.ServiceAsker(None, True), bind="127.0.0.1", port=0)
        server.start()
        result = {}

        def client():
            try:
                remote.connect(alice.identity, alice.settings, alice.trust, "127.0.0.1", server.port, False,
                               AutoConfirm())
            except remote.proto.ProtocolError as e:
                result["code"] = e.code

        threading.Thread(target=client, daemon=True).start()
        self.assertTrue(pump(lambda: find_window("Access to shared folders") is not None))
        dlg = find_window("Access to shared folders")
        self.assertIn("Read-only", "\n".join(labels(dlg)))
        self.assertEqual([w for w in all_widgets(dlg) if isinstance(w, Gtk.CheckButton)], [])
        dlg.response(Gtk.ResponseType.CANCEL)
        self.assertTrue(pump(lambda: "code" in result))
        self.assertEqual(result["code"], remote.proto.E_DECLINED)
        self.assertIsNone(bob.access.get(alice.identity.fp))
        server.stop()



@unittest.skipUnless(HAVE_DISPLAY, "needs a display (xvfb-run)")
class ConnectWindowTest(unittest.TestCase):
    def test_window_code_confirmation(self):
        win = remote_ui.ConnectWindow(want_write=True)
        win.show_all()
        win.refresh_connections()
        win.match_btn.hide()
        pump(lambda: True, 0.3)
        self.assertEqual(win.get_title(), "Connect to Computer")
        self.assertTrue(win.write_cb.get_active())
        text = "\n".join(labels(win))
        self.assertIn("Computers nearby", text)
        self.assertFalse(win.conn_list.get_visible())  # zadne pripojeni
        # Prubeh: kod a potvrzeni
        win.stack.set_visible_child_name("progress")
        win.on_status("waiting", {"peer_name": "Bob-PC", "sas": "123456", "trusted": False})
        replied = threading.Event()
        got = {}
        win.ask_code({"peer_name": "Bob-PC", "sas": "123456"}, replied, lambda v: got.setdefault("v", v))
        pump(lambda: True, 0.2)
        self.assertIn("123 456", "\n".join(labels(win)))
        self.assertTrue(win.match_btn.get_visible())
        win.match_btn.clicked()
        self.assertEqual(got["v"], (True, True))
        self.assertIn("Waiting for “Bob-PC” to allow access…", "\n".join(labels(win)))
        win.failed("“Bob-PC” denied access.")
        self.assertEqual(win.stack.get_visible_child_name(), "list")
        self.assertIn("“Bob-PC” denied access.", "\n".join(labels(win)))
        win.shutdown()
        win.destroy()


@unittest.skipUnless(HAVE_DISPLAY, "needs a display (xvfb-run)")
class SettingsPageTest(unittest.TestCase):
    def test_shared_folders_section(self):
        from luxdrop import gui
        conf = os.path.join(os.environ["HOME"], ".config", "luxdrop")
        os.makedirs(conf, exist_ok=True)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            f.write('{"name": "Gui-PC", "port": 0, "localsend": false}')
        app = gui.App()
        app.register(None)
        win = gui.Window(app)
        win.show_all()
        win.show_page("settings")
        pump(lambda: True, 0.3)
        text = "\n".join(labels(win))
        for s in ("Shared folders", "Share folders", "Computers with access", "No shared folders."):
            self.assertIn(s, text)
        self.assertFalse(win.share_switch.get_active())
        win.share_switch.set_active(True)
        self.assertTrue(pump(lambda: remote.Shares().enabled, 5))
        pump(lambda: "Public" in labels(win.share_list), 3)
        self.assertIn("Public", labels(win.share_list))
        fp = bytes(range(32))
        remote.Access().allow(fp, "Alice-PC", False)
        win.fill_shares()
        self.assertIn("Alice-PC", labels(win.access_list))
        check = [w for w in all_widgets(win.access_list) if isinstance(w, Gtk.CheckButton)][0]
        check.set_active(True)
        self.assertTrue(remote.Access().get(fp)["write"])
        win.destroy()


if __name__ == "__main__":
    unittest.main()
