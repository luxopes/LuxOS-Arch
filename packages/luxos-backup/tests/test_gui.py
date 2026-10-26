"""LuxOS Zalohy - okno (GTK) jen ve virtualni obrazovce:

    env -u DISPLAY xvfb-run -a python -m unittest packages/luxos-backup/tests/test_gui.py
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    raise unittest.SkipTest("GUI tests run only under xvfb-run (never on a real display)")

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.abspath(os.path.join(HERE, "..", "files"))
sys.path.insert(0, FILES)
os.environ.setdefault("LUXOS_I18N_DIR", os.path.abspath(os.path.join(HERE, "..", "..", "luxos-i18n", "files")))
os.environ["LUXOS_BACKUP_NO_NOTIFY"] = "1"


def load():
    path = os.path.join(FILES, "luxos-backup-gui")
    loader = importlib.machinery.SourceFileLoader("luxos_backup_gui", path)
    spec = importlib.util.spec_from_loader("luxos_backup_gui", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


gui = load()
core = gui.core
Gtk = gui.Gtk


def walk(widget, cls):
    out = [widget] if isinstance(widget, cls) else []
    if isinstance(widget, Gtk.Container):
        for c in widget.get_children():
            out.extend(walk(c, cls))
    return out


def texts(widget):
    return [w.get_text() for w in walk(widget, Gtk.Label)]


def flush(seconds=0.0):
    end = time.time() + seconds
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if time.time() >= end:
            break
        time.sleep(0.02)


class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luxos-backup-gui-")
        self.home = os.path.join(self.tmp, "home")
        self.disk = os.path.join(self.tmp, "disk")
        os.makedirs(os.path.join(self.home, "Documents"))
        os.makedirs(self.disk)
        with open(os.path.join(self.home, "Documents", "plan.txt"), "w") as f:
            f.write("v1")
        self.patches = [
            mock.patch.dict(os.environ, {"LUXOS_BACKUP_HOME": self.home, "LUXOS_BACKUP_HOST": "pc",
                                         "XDG_CONFIG_HOME": os.path.join(self.tmp, "c"),
                                         "XDG_STATE_HOME": os.path.join(self.tmp, "s"),
                                         "LUXOS_BACKUP_ENGINE": "python"}),
            mock.patch.object(core, "fs_uuid", return_value=(None, None)),
            mock.patch.object(core, "fs_type", return_value="ext4"),
            mock.patch.object(core, "secret_clear"),
            mock.patch.object(core, "external_disks", return_value=[]),
        ]
        for p in self.patches:
            p.start()
        gui.setup_css()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_window(self):
        win = gui.BackupWindow()
        win.show_all()
        win.back.hide()
        flush()
        tb = win.get_titlebar()
        self.assertTrue(tb.get_visible() and tb.get_show_close_button())
        self.assertIn("No backups yet", texts(win))
        self.assertIn("No backup disk yet", texts(win))
        self.assertFalse(win.now_btn.get_sensitive())
        # volby se ulozi
        sw = [s for s in walk(win, Gtk.Switch)]
        self.assertEqual(len(sw), 4)
        sw[1].set_active(True)                     # nastaveni systemu
        self.assertTrue(core.load_config()["system"])
        win.destroy()

    def test_backup_and_restore_flow(self):
        cfg = core.load_config()
        core.add_local_disk(cfg, self.disk, "USB")
        self.assertEqual(core.run_backup(manual=True, log=lambda *_a: None), 0)
        win = gui.BackupWindow()
        win.show_all()
        win.back.hide()
        flush()
        self.assertTrue(any(t.startswith("Last backup: Today") for t in texts(win)), texts(win))
        self.assertIn("USB", texts(win))
        self.assertTrue(win.now_btn.get_sensitive())
        win.show_browser()
        for _i in range(100):
            flush(0.05)
            if win.browser.name and len(win.browser.store):
                break
        b = win.browser
        self.assertEqual(len(b.timeline.get_children()), 1)
        self.assertEqual([r[1] for r in b.store], ["Documents"])
        b.view.row_activated(Gtk.TreePath(0), b.view.get_column(0))
        flush()
        self.assertEqual(b.rel, "Documents")
        self.assertEqual([r[1] for r in b.store], ["plan.txt"])
        # existujici soubor se neprepise - obnovi se vedle s novym jmenem
        with open(os.path.join(self.home, "Documents", "plan.txt"), "w") as f:
            f.write("v2")
        b.view.get_selection().select_path(Gtk.TreePath(0))
        flush()
        self.assertTrue(b.restore_btn.get_sensitive())
        b.on_restore(None)
        for _i in range(100):
            flush(0.05)
            if b.state.get_text().startswith("Restored"):
                break
        self.assertTrue(b.state.get_text().startswith("Restored 1"), b.state.get_text())
        names = sorted(os.listdir(os.path.join(self.home, "Documents")))
        self.assertEqual(len(names), 2)
        with open(os.path.join(self.home, "Documents", "plan.txt")) as f:
            self.assertEqual(f.read(), "v2")
        win.show_main()
        self.assertIsNone(b.sess)
        win.destroy()

    def test_add_disk_dialog_password_mismatch(self):
        win = gui.BackupWindow()
        dlg = gui.AddDiskDialog(win)
        flush()
        self.assertTrue(dlg.net_radio.get_active())       # zadny externi disk -> sitovy
        dlg.address.set_text("sftp://anna@nas/backup")
        dlg.encrypt.set_active(True)
        flush()
        self.assertTrue(dlg.pw_box.get_visible())
        dlg.pw1.set_text("a")
        dlg.pw2.set_text("b")
        self.assertEqual(dlg.choice(), (None, False))
        dlg.pw2.set_text("a")
        self.assertEqual(dlg.choice(), (("net", "sftp://anna@nas/backup", ""), "a"))
        dlg.destroy()
        win.destroy()


if __name__ == "__main__":
    unittest.main()
