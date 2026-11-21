"""LuxOS - testy Monitoru na X11 nad programy v LSL (drive luxos_displays.py a luxos_arrange.py).

  build(nazev)     prelozi files/lsl/<nazev>.lsl nebo tests/lsl/<nazev>.lsl jednou za beh testu (lslc z PATH nebo
                   LUXOS_LSLC; bez lslc SkipTest)
  helper()         pomocnik luxos-displays (prikazy skriptu, get/try pro okno)
  window()         luxos-displays-settings (odkaz na luxos-settings: stranka Monitory okna Nastaveni)
  ld, la           funkce luxos_xrandr.lsl a geometrie luxos_displays.lsl volane pres tests/lsl/luxos-xrandr-probe.lsl
                   (stejna jmena jako drive moduly v Pythonu; vysledky jsou JSON - seznamy misto n-tic)
"""
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL_DIR = os.environ.get("LUXOS_LSL_DIR") or os.path.normpath(os.path.join(HERE, "..", "files", "lsl"))
SETTINGS_ALIASES = {"luxos-displays-settings", "luxos-display-settings"}
TMP = tempfile.mkdtemp(prefix="luxos-xrandr-lsl-")
atexit.register(shutil.rmtree, TMP, True)
_built = {}


def build(name):
    if name in _built:
        return _built[name]
    lslc = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
    if not lslc:
        raise unittest.SkipTest("lslc (lsl) is not installed")
    src = os.path.join(LSL_DIR, name + ".lsl")
    out = os.path.join(TMP, name)
    if not os.path.exists(src) and name in SETTINGS_ALIASES:
        # stary program je odkaz na luxos-settings (stranka podle jmena)
        os.symlink(build("luxos-settings"), out)
        _built[name] = out
        return out
    if not os.path.exists(src):
        src = os.path.join(HERE, "lsl", name + ".lsl")
    r = subprocess.run([lslc, "--target", "linux-x86_64-gnu", "--system-bindings", LSL_DIR, src, out],
                       capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise AssertionError("lslc failed: " + (r.stdout + r.stderr)[-3000:])
    _built[name] = out
    return out


def helper():
    return build("luxos-displays")


def window():
    return build("luxos-displays-settings")


def probe(func, *args):
    r = subprocess.run([build("luxos-xrandr-probe"), func, json.dumps(list(args))], capture_output=True, text=True,
                       timeout=60)
    if r.returncode:
        raise AssertionError("probe %s failed: %s" % (func, r.stdout + r.stderr))
    return json.loads(r.stdout)


def md5_id(edid):
    """Otisk EDID v klici vystupu (md5 hex, 12 znaku) - stejny jako drive v Pythonu."""
    return hashlib.md5(edid.encode()).hexdigest()[:12] if edid else ""


class ld:
    MODES = ["extend", "mirror", "external", "internal"]
    TEXT_SIZES = [84, None, 108, 120, 132]

    parse = staticmethod(lambda text: probe("parse", text))
    current_mode = staticmethod(lambda o: probe("current_mode", o))
    preferred_mode = staticmethod(lambda o: probe("preferred_mode", o))
    find_mode = staticmethod(lambda o, name: probe("find_mode", o, name))
    resolution_choices = staticmethod(lambda o: probe("resolution_choices", o))
    fmt_rate = staticmethod(lambda r: probe("fmt_rate", r))
    fmt_mode = staticmethod(lambda m: probe("fmt_mode", m))
    best_rate = staticmethod(lambda md, preferred=None: probe("best_rate", md, preferred))
    edid_id = staticmethod(lambda e: probe("edid_id", e))
    edid_name = staticmethod(lambda e: probe("edid_name", e))
    output_key = staticmethod(lambda o: probe("output_key", o))
    set_key = staticmethod(lambda outs: probe("set_key", outs))
    entry_for = staticmethod(lambda o, mode, rate, rot: probe("entry_for", o, mode, rate, rot))
    output_args = staticmethod(lambda o, e: probe("output_args", o, e))
    all_output_args = staticmethod(lambda outs, entries: probe("all_output_args", outs, entries))
    load = staticmethod(lambda path=None: probe("load", path))
    load_layouts = staticmethod(lambda path=None: probe("load_layouts", path))
    load_modes = staticmethod(lambda path=None: probe("load_modes", path))
    save = staticmethod(lambda entries, path=None, layouts=None, modes=None: probe("save", entries, path, layouts, modes))
    text_size_index = staticmethod(lambda dpi: probe("text_size_index", dpi))
    read_dpi = staticmethod(lambda: probe("read_dpi"))
    set_text_size = staticmethod(lambda i: probe("set_text_size", i))
    is_scaled = staticmethod(lambda o: probe("is_scaled", o))
    unscale_args = staticmethod(lambda o: probe("unscale_args", o))
    rate_cap_target = staticmethod(lambda o: probe("rate_cap_target", o))

    @staticmethod
    def query():
        r = subprocess.run(["xrandr", "--current", "--prop"], capture_output=True, text=True, timeout=30)
        return probe("parse", r.stdout)


class la:
    MIN_CONTACT = 32

    rect_size = staticmethod(lambda mode, rot: probe("rect_size", mode, rot))
    overlaps = staticmethod(lambda a, b: probe("overlaps", a, b))
    touches = staticmethod(lambda a, b: probe("touches", a, b))
    valid = staticmethod(lambda rects: probe("valid", rects))
    drop = staticmethod(lambda rects, moving, px, py, primary=None, snap=0:
                        probe("drop", rects, moving, px, py, primary, snap))
    settle = staticmethod(lambda sizes, props, order, snaps=None: probe("settle", sizes, props, order, snaps or {}))
    set_key = staticmethod(lambda outs: probe("set_key", outs))
    make_layout = staticmethod(lambda outs, pos, primary, mirror=False: probe("make_layout", outs, pos, primary, mirror))
    mode_for = staticmethod(lambda outs, modes: probe("mode_for", outs, modes))
    with_mode = staticmethod(lambda modes, outs, mode: probe("with_mode", modes, outs, mode))
    common_mode = staticmethod(lambda outs, wanted: probe("common_mode", outs, wanted))
    mirror_rate = staticmethod(lambda o, name: probe("mirror_rate", o, name))
    mirror_plan = staticmethod(lambda outs, entries, layouts=None, primary=None:
                               probe("mirror_plan", outs, entries, layouts, primary))
    plan = staticmethod(lambda outs, entries, layouts, force_extend=False:
                        probe("plan", outs, entries, layouts, force_extend))
    matches = staticmethod(lambda outs, expected: probe("matches", outs, expected))
    current_rects = staticmethod(lambda outs: probe("current_rects", outs))

    @staticmethod
    def find_layout(layouts, outs):
        """(rozlozeni, {klic: nazev}) jako drive; klic nalezeneho zaznamu je treti polozka vysledku LSL."""
        found = probe("find_layout", layouts, outs)
        return found[0], found[1]
