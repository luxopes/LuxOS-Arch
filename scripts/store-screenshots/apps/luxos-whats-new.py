"""Co je noveho: novinky aktualni verze LuxOS (data z luxos-branding v pracovni kopii)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402


def shots(s):
    s.env["LUXOS_WHATS_NEW_DIR"] = s.src("luxos-branding/files/whats-new")
    s.env["LUXOS_VERSION_FILE"] = s.src("luxos-branding/files/version")
    p = _a.run_python(s, "luxos-desktop/files/bin/luxos-whats-new", modules=("luxos_i18n",))
    win = s.window(pid=p.pid, size=None)
    s.sleep(0.5)
    s.capture("1", win)
