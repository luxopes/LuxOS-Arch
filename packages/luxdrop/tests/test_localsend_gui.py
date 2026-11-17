#!/usr/bin/env python3
"""LuxDrop - GUI zarizeni LocalSend (L-04): oznaceni "neovereno", kratky kod, zmena klice.

Jen pod virtualnim displejem:  env -u DISPLAY xvfb-run -a python3 tests/test_localsend_gui.py -v
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("LUXDROP_LIB", os.path.abspath(os.path.join(HERE, "..", "files", "lib"))))

TMP = tempfile.mkdtemp(prefix="luxdrop-lsgui-")
os.environ["HOME"] = os.path.join(TMP, "home")
os.makedirs(os.environ["HOME"])
os.environ["XDG_RUNTIME_DIR"] = os.path.join(TMP, "run")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700)
os.environ["LANGUAGE"] = "en"

HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
if HAVE_DISPLAY:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # noqa: E402

    from luxdrop import dialogs, transfer  # noqa: E402


def pump():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def labels(w):
    out = []
    if isinstance(w, Gtk.Label):
        out.append(w.get_text())
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            out += labels(c)
    return out


def find(w, cls):
    out = [w] if isinstance(w, cls) else []
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            out += find(c, cls)
    return out


@unittest.skipUnless(HAVE_DISPLAY, "needs a virtual display (xvfb-run)")
class AcceptDialog(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TMP, ignore_errors=True)

    def request(self, sas=None, **kw):
        t = transfer.Transfer("in", "Phone", "4badde53a7f7cdee")
        t.items, t.total = ["a.jpg"], 10
        args = dict(protocol="localsend", can_trust=True, verified=True, device_model="Samsung",
                    short_code="4BAD DE53 A7F7 CDEE")
        args.update(kw)
        return transfer.IncomingRequest(t, b"x" * 32, False, sas, False, [{}], [], **args)

    def test_unverified_and_code(self):
        got = []
        dlg = dialogs.accept_dialog(self.request(), got.append)
        pump()
        text = " ".join(labels(dlg))
        self.assertIn("not verified with a code", text)
        self.assertIn("Device code: 4BAD DE53 A7F7 CDEE", text)
        self.assertNotIn("different key", text)
        ok = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        self.assertTrue(ok.get_sensitive())
        dlg.response(Gtk.ResponseType.OK)
        pump()
        self.assertEqual(got, [(True, False)])  # duvera se nezaskrtava sama

    def test_key_changed_needs_confirm(self):
        got = []
        dlg = dialogs.accept_dialog(self.request(key_changed=True), got.append)
        pump()
        text = " ".join(labels(dlg))
        self.assertIn("with a different key", text)
        ok = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        self.assertFalse(ok.get_sensitive())
        self.assertIn("destructive-action", ok.get_style_context().list_classes())
        confirm = [c for c in find(dlg, Gtk.CheckButton) if "really is this device" in c.get_label()]
        self.assertEqual(len(confirm), 1)
        confirm[0].set_active(True)
        pump()
        self.assertTrue(ok.get_sensitive())
        confirm[0].set_active(False)
        dlg.response(Gtk.ResponseType.OK)   # i kdyby "Prijmout" prislo bez potvrzeni -> odmitnuto
        pump()
        self.assertEqual(got, [(False, False)])

    def test_luxdrop_has_no_localsend_notice(self):
        dlg = dialogs.accept_dialog(self.request(protocol="luxdrop", sas="123456", short_code=""), lambda v: None)
        pump()
        self.assertNotIn("not verified with a code", " ".join(labels(dlg)))
        dlg.destroy()

    def test_message_key_changed(self):
        dlg = dialogs.accept_dialog(self.request(message="hi", key_changed=True), lambda v: None)
        pump()
        self.assertIn("with a different key", " ".join(labels(dlg)))
        self.assertFalse([c for c in find(dlg, Gtk.CheckButton) if "really is" in c.get_label()])
        dlg.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
