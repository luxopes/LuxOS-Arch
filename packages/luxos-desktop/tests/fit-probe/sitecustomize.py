# LuxOS - sonda velikosti oken pro tests/test_luxos_window_fit.py (jen ve virtualni obrazovce testu).
# Po spusteni Gtk.main zapise do $LUXOS_FIT_OUT (JSON) velikost viditelnych oken (X okno vcetne HeaderBar),
# volitelne snimek obrazovky do $LUXOS_FIT_SHOT, pak okna zmensi na 100x100 a zapise nejmensi velikost,
# kterou okno dovoli. Pak proces ukonci.
import importlib.machinery
import json
import os
import sys

# Moduly LuxOS ze zdroju (LUXOS_FIT_PYDIR, oddelene ":"), i kdyz aplikace vlozi /usr/lib/luxos/python na
# zacatek sys.path (na vyvojovem LuxOS jsou tam starsi nainstalovane verze)
_dirs = [d for d in os.environ.get("LUXOS_FIT_PYDIR", "").split(":") if d]
if _dirs:
    class _RepoFinder:
        @staticmethod
        def find_spec(name, path=None, target=None):
            if "." in name:
                return None
            return importlib.machinery.PathFinder.find_spec(name, _dirs)

    sys.meta_path.insert(0, _RepoFinder)

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import GLib, Gdk, Gtk

    _main = Gtk.main
    _state = {"windows": []}

    def _toplevels():
        out = []
        for w in Gtk.Window.list_toplevels():
            if not w.get_visible() or w.get_window_type() != Gtk.WindowType.TOPLEVEL:
                continue
            if w.get_type_hint() not in (Gdk.WindowTypeHint.NORMAL, Gdk.WindowTypeHint.DIALOG):
                continue
            if w.get_window() is None:
                continue
            out.append(w)
        return out

    def _size(w):
        g = w.get_window()
        return {"title": w.get_title() or "", "width": g.get_width(), "height": g.get_height(),
                "resizable": w.get_resizable()}

    def _finish():
        for i, w in enumerate(_toplevels()):
            if i < len(_state["windows"]):
                _state["windows"][i]["min"] = _size(w)
        with open(os.environ["LUXOS_FIT_OUT"], "w") as f:
            json.dump(_state, f)
        os._exit(0)

    def _shrink():
        for w in _toplevels():
            w.resize(100, 100)
        GLib.timeout_add(700, _finish)
        return False

    def _measure():
        wins = _toplevels()
        _state["windows"] = [_size(w) for w in wins]
        screen = Gdk.Screen.get_default()
        _state["screen"] = [screen.get_width(), screen.get_height()]
        shot = os.environ.get("LUXOS_FIT_SHOT")
        if shot:
            root = Gdk.get_default_root_window()
            pb = Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())
            if pb:
                pb.savev(shot, "png", [], [])
        hook = os.environ.get("LUXOS_FIT_HOOK")
        if hook:
            _state["hook"] = eval(hook, {"wins": wins, "Gtk": Gtk})   # noqa: S307 - jen testy
        if os.environ.get("LUXOS_FIT_NO_SHRINK"):
            GLib.timeout_add(100, _finish)
        else:
            GLib.timeout_add(100, _shrink)
        return False

    def main(*a, **k):
        GLib.timeout_add(int(os.environ.get("LUXOS_FIT_DELAY", "2500")), _measure)
        return _main(*a, **k)

    if os.environ.get("LUXOS_FIT_OUT"):
        Gtk.main = main
        _app_run = Gtk.Application.run

        def app_run(self, *a, **k):
            GLib.timeout_add(int(os.environ.get("LUXOS_FIT_DELAY", "2500")), _measure)
            return _app_run(self, *a, **k)

        Gtk.Application.run = app_run
except Exception as e:  # noqa: BLE001
    print("LUXOS-FIT skip", e, file=sys.stderr)
