"""Lux Guard - okna (GTK) jen ve virtualni obrazovce:

    env -u DISPLAY xvfb-run -a python -m pytest -q packages/luxos-guard/tests/test_gui.py
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
import importlib.machinery
import importlib.util
import os

import pytest

if "xvfb-run" not in os.environ.get("XAUTHORITY", "") and os.environ.get("LUXOS_TEST_X") != "1":
    pytest.skip("GUI tests run only under xvfb-run (never on a real display)", allow_module_level=True)

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    path = os.path.join(HERE, "..", "files", "luxos-guard-gui")
    loader = importlib.machinery.SourceFileLoader("luxos_guard_gui", path)
    spec = importlib.util.spec_from_loader("luxos_guard_gui", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


gui = load()
Gtk = gui.Gtk


def buttons(widget):
    out = []
    if isinstance(widget, Gtk.Button):
        out.append(widget)
    if isinstance(widget, Gtk.Container):
        for c in widget.get_children():
            out.extend(buttons(c))
    return out


def labels(widget):
    out = []
    if isinstance(widget, Gtk.Label):
        out.append(widget.get_text())
    if isinstance(widget, Gtk.Container):
        for c in widget.get_children():
            out.extend(labels(c))
    return out


def flush():
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


RISKY = {"mode": "ask", "path": "/home/anna/Downloads/game.sh", "level": "risky", "kind": "script",
         "interp": "bash", "reasons": [], "notes": ["asks for administrator rights"], "origin": "download"}
CRIT = {"mode": "blocked", "path": "/home/anna/Downloads/codec.sh", "level": "critical", "kind": "script",
        "interp": "bash", "reasons": ["deletes your files, your home folder or the whole system"], "origin": "url"}


@pytest.mark.parametrize("msg,expect", [
    (RISKY, {"Run Anyway": "run", "Run in Sandbox": "sandbox", "Don't Run": "deny"}),
    (CRIT, {"Move to Trash": "trash", "Run in Sandbox": "sandbox", "OK": "close"}),
])
def test_dialog_buttons(msg, expect):
    gui.setup_css()
    for text, choice in expect.items():
        d = gui.GuardDialog(msg)
        flush()
        tb = d.get_titlebar()
        assert tb is not None and tb.get_visible() and tb.get_show_close_button()
        found = {b.get_label(): b for b in buttons(d)}
        assert set(expect) <= set(found), found.keys()
        found[text].clicked()
        flush()
        assert d.choice == choice
    # kriticky: zadne "Presto spustit"
    d = gui.GuardDialog(CRIT)
    assert "Run Anyway" not in {b.get_label() for b in buttons(d)}
    assert any("deletes your files" in t for t in labels(d))
    d.destroy()


def test_dialog_close_means_default():
    d = gui.GuardDialog(RISKY)
    flush()
    d.destroy()
    flush()
    assert d.choice == "deny"
    d = gui.GuardDialog(CRIT)
    d.destroy()
    assert d.choice == "close"


def test_dialog_translated(monkeypatch):
    path = os.path.join(HERE, "..", "..", "luxos-i18n", "files", "cs.tsv")
    tr = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "\t" in line:
                k, v = line.rstrip("\n").split("\t", 1)
                tr[k] = v
    monkeypatch.setattr(gui, "_", lambda t: tr.get(t, t))
    d = gui.GuardDialog(RISKY)
    texts = {b.get_label() for b in buttons(d)}
    assert "Run Anyway" not in texts and tr["Run Anyway"] in texts
    d.destroy()


def test_main_window_without_service(monkeypatch, tmp_path):
    monkeypatch.setenv("LUXOS_GUARD_SOCKET", str(tmp_path / "none.sock"))
    w = gui.GuardWindow()
    for _ in range(50):
        flush()
        if w.badge.get_text():
            break
        import time
        time.sleep(0.05)
    flush()
    assert w.get_titlebar().get_visible()
    assert w.badge.get_text() == "Not running"
    w.destroy()


def test_main_window_hides_deleted_files(tmp_path):
    kept = tmp_path / "game.sh"
    kept.write_text("#!/bin/sh\n")
    w = gui.GuardWindow.__new__(gui.GuardWindow)
    Gtk.Window.__init__(w)
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    w.add(page)
    w.badge = Gtk.Label()
    w.g_files, w.g_log, w.g_snap = (gui.Group(page, t) for t in ("files", "log", "snap"))
    gone = dict(CRIT, path=str(tmp_path / "deleted.sh"), t=2, status="flagged")
    here = dict(CRIT, path=str(kept), t=1, status="flagged")
    w.fill({"op": "status"}, {"entries": [gone, here], "log": []}, [], False)
    texts = labels(w.g_files)
    assert "game.sh" in texts and "deleted.sh" not in texts
    assert len([b for b in buttons(w.g_files) if b.get_label() == "Run in Sandbox"]) == 1
    # jen smazane soubory -> prazdny stav
    w.fill({"op": "status"}, {"entries": [gone], "log": []}, [], False)
    assert labels(w.g_files) == ["No programs from outside this computer yet."]
    w.destroy()


def test_restore_runs_once_at_a_time(monkeypatch, tmp_path):
    import datetime
    import threading
    import time
    started, release, calls = threading.Event(), threading.Event(), []

    def fake_restore(src, dst, overwrite, skip_top, backup=None):
        calls.append(overwrite)
        started.set()
        release.wait(5)
        return 3, 1

    monkeypatch.setattr(gui.snap, "restore", fake_restore)
    w = gui.GuardWindow.__new__(gui.GuardWindow)
    Gtk.Window.__init__(w)
    w.state_label = Gtk.Label()
    w.user_dir = lambda p: str(tmp_path)
    t = datetime.datetime(2026, 11, 16, 10, 0)
    w.restore(t, "p", False)
    assert started.wait(5)
    w.restore(t, "p", True)                      # druhe kliknuti behem obnovy nic nespusti
    release.set()
    for _ in range(100):
        flush()
        if not w.restoring:
            break
        time.sleep(0.02)
    assert calls == [False]
    assert w.state_label.get_text().startswith("Restored 3 files")
    w.restore(t, "p", True)                      # po dokonceni jde obnovit znovu
    for _ in range(100):
        flush()
        if not w.restoring:
            break
        time.sleep(0.02)
    assert calls == [False, True]
    w.destroy()


# ---- okno s vystupem behu bez okna (Zobrazit vystup) -------------------------------------------------
def textview(widget):
    if isinstance(widget, Gtk.TextView):
        return widget
    if isinstance(widget, Gtk.Container):
        for c in widget.get_children():
            r = textview(c)
            if r:
                return r
    return None


def view_text(w):
    b = textview(w).get_buffer()
    return b.get_text(b.get_start_iter(), b.get_end_iter(), True)


@pytest.fixture
def icons():
    """Ikona luxos-guard ze zdroju a ostre ikony okna z luxos-desktop (jako na nainstalovanem systemu)."""
    import sys
    Gtk.IconTheme.get_default().append_search_path(os.path.join(HERE, "..", "files"))
    sys.path.insert(0, os.path.join(HERE, "..", "..", "luxos-desktop", "files", "python"))
    yield
    sys.path.remove(os.path.join(HERE, "..", "..", "luxos-desktop", "files", "python"))


def test_output_window(tmp_path, icons):
    out = tmp_path / "output-1-1.txt"
    out.write_bytes(b"usage: tool [-h] FILE\n\x1b[31merror\x1b[0m: missing FILE\x07\n\xe2\x80\xaertl\n")
    gui.setup_css()
    w = gui.OutputWindow(str(out), "tool.sh")
    flush()
    tb = w.get_titlebar()
    assert tb.get_visible() and tb.get_show_close_button()
    assert tb.get_title() == "Output of tool.sh" and w.get_title() == "Output of tool.sh"
    tv = textview(w)
    assert not tv.get_editable() and not tv.get_cursor_visible() and tv.get_monospace()
    assert view_text(w) == "usage: tool [-h] FILE\nerror: missing FILE\nrtl"
    sizes = sorted(p.get_width() for p in (w.get_icon_list() or []))
    assert sizes and sizes[0] <= 16 and sizes[-1] >= 256, sizes          # ostra ikona v Alt+Tab
    copy = [b for b in buttons(tb) if b.get_label() == "Copy"]
    assert copy
    copy[0].clicked()
    flush()
    assert Gtk.Clipboard.get(gui.Gdk.SELECTION_CLIPBOARD).wait_for_text() == view_text(w)
    # Esc zavre okno
    destroyed = []
    w.connect("destroy", lambda _w: destroyed.append(1))
    ev = gui.Gdk.Event.new(gui.Gdk.EventType.KEY_PRESS)
    ev.keyval = gui.Gdk.KEY_Escape
    w.on_key(w, ev)
    flush()
    assert destroyed


def test_output_window_missing_empty_and_symlink(tmp_path, icons):
    w = gui.OutputWindow(str(tmp_path / "gone.txt"), "x")
    assert view_text(w) == "The output is no longer available."
    w.destroy()
    (tmp_path / "empty.txt").write_text("")
    w = gui.OutputWindow(str(tmp_path / "empty.txt"), "x")
    assert view_text(w) == "The program did not print anything."
    w.destroy()
    secret = tmp_path / "secret"
    secret.write_text("private")
    os.symlink(secret, tmp_path / "link.txt")
    w = gui.OutputWindow(str(tmp_path / "link.txt"), "x")
    assert "private" not in view_text(w)
    w.destroy()


def test_output_command_line_shows_window(tmp_path):
    """luxos-guard-gui output SOUBOR NAZEV jako samostatny proces (spousti ho hlidac behu)."""
    import subprocess
    import sys
    import time
    out = tmp_path / "o.txt"
    out.write_text("hello\n")
    files = os.path.abspath(os.path.join(HERE, "..", "files"))
    # moduly ze zdroju drive nez nainstalovane (/usr/lib/luxos/python si pridavaji samy)
    boot = ("import runpy, sys; sys.path.insert(0, sys.argv[1]); "
            "import luxos_guard_core, luxos_guard_snap, luxos_guard_session; "
            "sys.argv = sys.argv[2:]; runpy.run_path(sys.argv[0], run_name='__main__')")
    p = subprocess.Popen([sys.executable, "-c", boot, files, os.path.join(files, "luxos-guard-gui"), "output",
                          str(out), "demo.sh"], env=dict(os.environ, LC_ALL="C"),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        found = False
        for _ in range(100):
            r = subprocess.run(["xdotool", "search", "--name", "Output of demo.sh"], capture_output=True, text=True)
            if r.stdout.strip():
                found = True
                break
            if p.poll() is not None:
                break
            time.sleep(0.1)
        assert found, p.stderr.read().decode() if p.poll() is not None else "window not found"
    finally:
        p.terminate()                       # jen vlastni proces
        p.wait(5)
