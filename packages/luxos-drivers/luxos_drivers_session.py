"""LuxOS Ovladace - kontrola po prihlaseni (bezi uvnitr luxos-hub, zadny dalsi proces).

Nejvys jednou za start pocitace (boot_id) chvili po prihlaseni spusti luxos-hwdetect --json
(~0,1 s, jen sysfs) a porovna ho s nainstalovanymi baliky. Kdyz nejaky ovladac chybi
(nova grafika, USB adapter...), ukaze upozorneni, ktere otevre aplikaci Ovladace.
"Neupozornovat" si zapamatuje chybejici baliky - znovu se ozve jen pri jinem hardwaru.
V live systemu mlci: ovladace nainstaluje instalator.
"""
import os
import subprocess
import sys
import threading

sys.path.insert(0, "/usr/lib/luxos/python")
import luxos_drivers as drv  # noqa: E402
from luxos_i18n import _  # noqa: E402

from gi.repository import Gio, GLib  # noqa: E402

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "luxos")
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "luxos")
CHECKED = os.path.join(CACHE, "drivers-checked")      # boot_id posledni kontroly
IGNORED = os.path.join(CONFIG, "drivers-ignored")     # chybejici baliky, ktere uzivatel odmitl
APP = "luxos-drivers"
DELAY = 45                                            # s po prihlaseni (start relace ma prednost)

_state = {"bus": None, "ids": set()}


def log(msg):
    print(f"luxos-hub: drivers: {msg}", file=sys.stderr, flush=True)


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text + "\n")
    os.replace(tmp, path)


def should_check(boot):
    """Jednou za start pocitace; mimo live system."""
    if os.path.isdir(drv.P("/run/archiso")):
        return False
    return not boot or _read(CHECKED) != boot


def should_notify(states, ignored):
    """Upozornit, kdyz chybi baliky, ktere uzivatel jeste neodmitl."""
    missing = set(drv.missing_packages(states))
    return bool(missing - set(ignored.split()))


def notify(states):
    bus = _state["bus"]
    if bus is None:
        return
    names = []
    for s in states:
        if s["status"] == drv.AVAILABLE:
            t = _(s["device"].get("title", ""))
            if t and t not in names:
                names.append(t)
    body = (", ".join(names[:3]) + "\n" if names else "") + _("Open Drivers to install them with one click.")
    actions = ["default", _("Show drivers"), "open", _("Show drivers"), "ignore", _("Don't remind me")]

    def done(b, res):
        try:
            _state["ids"].add(b.call_finish(res).unpack()[0])
            _state["key"] = drv.notify_key(states)
        except GLib.Error as e:
            log(f"notify: {e.message}")
    bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
             "org.freedesktop.Notifications", "Notify",
             GLib.Variant("(susssasa{sv}i)", ("LuxOS", 0, "luxos-drivers", _("Additional drivers are available"),
                                              body, actions, {"desktop-entry": GLib.Variant("s", APP)}, -1)),
             GLib.VariantType("(u)"), 0, 5000, None, done)


def on_action(_c, _s, _p, _i, _sig, params):
    nid, action = params.unpack()
    if nid not in _state["ids"]:
        return
    _state["ids"].discard(nid)
    if action in ("open", "default"):
        try:
            subprocess.Popen([APP], stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            log(f"{APP}: {e}")
    elif action == "ignore":
        try:
            _write(IGNORED, _state.get("key", ""))
        except OSError as e:
            log(f"ignore: {e}")


def check():
    """Bezi ve vlakne: detekce a porovnani; upozorneni v hlavni smycce."""
    boot = drv.boot_id()
    if not should_check(boot):
        return
    try:
        states = drv.evaluate(drv.detect(timeout=30))
    except Exception as e:  # noqa: BLE001 - kontrola nesmi shodit luxos-hub
        log(f"detect: {e}")
        return
    try:
        _write(CHECKED, boot)
    except OSError as e:
        log(f"state: {e}")
    if should_notify(states, _read(IGNORED)):
        GLib.idle_add(lambda: notify(states) or False)


def subscribe():
    """Volano z luxos-hub pri startu relace."""
    try:
        _state["bus"] = Gio.bus_get_sync(Gio.BusType.SESSION)
        _state["bus"].signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications",
                                       "ActionInvoked", "/org/freedesktop/Notifications", None, 0, on_action)
    except GLib.Error as e:
        log(f"session bus: {e.message}")
    GLib.timeout_add_seconds(DELAY, lambda: threading.Thread(target=check, daemon=True).start() or False)
