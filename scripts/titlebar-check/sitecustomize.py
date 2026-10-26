# LuxOS - kontrola horni listy: po spusteni aplikace (Gtk.main) projde vsechna viditelna okna
# a vypise LUXOS-TITLEBAR ok|FAIL. Pouziva scripts/check-titlebars.sh (jen ve xvfb-run).
import os
import sys

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import GLib, Gdk, Gtk

    _main = Gtk.main

    def _check():
        bad, seen = [], 0
        for w in Gtk.Window.list_toplevels():
            if not w.get_visible() or w.get_window_type() != Gtk.WindowType.TOPLEVEL:
                continue
            if w.get_type_hint() not in (Gdk.WindowTypeHint.NORMAL, Gdk.WindowTypeHint.DIALOG):
                continue
            if not w.get_decorated():
                continue      # zamerne bez ramu (popup, overlay)
            seen += 1
            tb = w.get_titlebar()
            if tb is not None and not tb.get_visible():
                bad.append(w.get_title() or type(w).__name__)
        print("LUXOS-TITLEBAR", "FAIL " + ", ".join(bad) if bad else ("ok %d" % seen if seen else "none"),
              file=sys.stderr, flush=True)
        os._exit(0)

    def main(*a, **k):
        GLib.timeout_add(int(os.environ.get("LUXOS_TITLEBAR_DELAY", "2500")), _check)
        return _main(*a, **k)

    Gtk.main = main
    _app_run = Gtk.Application.run

    def app_run(self, *a, **k):
        GLib.timeout_add(int(os.environ.get("LUXOS_TITLEBAR_DELAY", "2500")), _check)
        return _app_run(self, *a, **k)

    Gtk.Application.run = app_run
except Exception as e:  # noqa: BLE001
    print("LUXOS-TITLEBAR skip", e, file=sys.stderr)
