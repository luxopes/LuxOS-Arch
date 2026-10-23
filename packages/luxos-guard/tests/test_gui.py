"""Lux Guard - okna (GTK) jen ve virtualni obrazovce:

    env -u DISPLAY xvfb-run -a python -m pytest -q packages/luxos-guard/tests/test_gui.py
"""
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
