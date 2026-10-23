"""LuxOS - prehravace hudby a videa (MPRIS) rizene udalostmi D-Bus, bez dotazovani.

Jeden sdileny hlidac na proces (v luxos-hub ho pouziva Ovladaci centrum
i volba "neuspavat pri prehravani"):

    w = luxos_mpris.watcher()
    w.connect(callback)        # callback() po zmene (stav, metadata, prehravac prisel/odesel)
    w.current()                # hrajici prehravac (jinak pozastaveny s titulkem) nebo None
    w.playing()                # True, kdyz aspon jeden prehravac hraje
    w.call(name, "PlayPause")  # asynchronni volani; ikona se zmeni hned (optimisticky)

Stav drzi z PropertiesChanged a NameOwnerChanged; dotaz GetAll jen pri
objeveni prehravace (nebo kdyz prehravac hodnoty zneplatni).
"""
from gi.repository import Gio, GLib

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
IFACE = "org.mpris.MediaPlayer2.Player"
PROPS = "org.freedesktop.DBus.Properties"


def player_state(name, props):
    """Slovnik pro UI z vlastnosti MPRIS (cista funkce, testovatelna)."""
    meta = props.get("Metadata") or {}
    artist = meta.get("xesam:artist") or []
    status = props.get("PlaybackStatus") or "Stopped"
    return {"bus": name, "app": name[len(PREFIX):].split(".")[0].capitalize(),
            "title": str(meta.get("xesam:title") or ""),
            "artist": ", ".join(str(a) for a in artist) if isinstance(artist, (list, tuple)) else str(artist),
            "art": str(meta.get("mpris:artUrl") or ""),
            "status": status, "playing": status == "Playing",
            "can_next": bool(props.get("CanGoNext", True)), "can_prev": bool(props.get("CanGoPrevious", True))}


def pick_current(players):
    """{nazev: vlastnosti} -> stav prehravace k zobrazeni: hrajici, jinak pozastaveny nebo s titulkem."""
    best = None
    for name in sorted(players):
        st = player_state(name, players[name])
        if st["playing"]:
            return st
        if best is None and (st["title"] or st["status"] == "Paused"):
            best = st
    return best


class Watcher:
    def __init__(self, bus=None):
        self.bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION)
        self.players = {}       # dobre znamy nazev -> vlastnosti Player
        self.owners = {}        # dobre znamy nazev -> unikatni nazev (odesilatel signalu)
        self.callbacks = []
        self._idle = 0
        self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                  "/org/freedesktop/DBus", "org.mpris.MediaPlayer2",
                                  Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE, self._on_owner)
        self.bus.signal_subscribe(None, PROPS, "PropertiesChanged", PATH, IFACE,
                                  Gio.DBusSignalFlags.NONE, self._on_props)
        self.bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
                      None, GLib.VariantType("(as)"), 0, 3000, None, self._on_names)

    # ---- verejne API ----
    def connect(self, cb):
        self.callbacks.append(cb)

    def current(self):
        return pick_current(self.players)

    def playing(self):
        return any(p.get("PlaybackStatus") == "Playing" for p in self.players.values())

    def call(self, name, method):
        """Ovladani prehravace; PlayPause hned prepne stav lokalne, skutecny stav pak prijde signalem."""
        if name not in self.players:
            return
        if method == "PlayPause":
            props = self.players[name]
            props["PlaybackStatus"] = "Paused" if props.get("PlaybackStatus") == "Playing" else "Playing"
            self._changed()
        self.bus.call(name, PATH, IFACE, method, None, None, 0, 3000, None, self._on_called, name)

    # ---- udalosti ----
    def _changed(self):
        # Davka signalu (stav + metadata) -> jedno volani posluchacu
        if not self._idle:
            self._idle = GLib.idle_add(self._emit)

    def _emit(self):
        self._idle = 0
        for cb in list(self.callbacks):
            try:
                cb()
            except Exception as e:  # noqa: BLE001 - chyba posluchace nesmi zastavit ostatni
                print(f"luxos_mpris: {e}", flush=True)
        return False

    def _on_names(self, bus, res):
        try:
            names = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        for n in names:
            if n.startswith(PREFIX):
                self._add(n, None)

    def _add(self, name, owner):
        self.players.setdefault(name, {})
        if owner:
            self.owners[name] = owner
        else:
            self.bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
                          GLib.Variant("(s)", (name,)), GLib.VariantType("(s)"), 0, 3000, None,
                          self._on_owner_reply, name)
        self._fetch(name)

    def _fetch(self, name):
        self.bus.call(name, PATH, PROPS, "GetAll", GLib.Variant("(s)", (IFACE,)), GLib.VariantType("(a{sv})"),
                      0, 3000, None, self._on_all, name)

    def _on_owner_reply(self, bus, res, name):
        try:
            self.owners[name] = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            pass

    def _on_all(self, bus, res, name):
        try:
            props = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        if name in self.players:
            self.players[name].update(props)
            self._changed()

    def _on_owner(self, _c, _s, _p, _i, _sig, params):
        name, _old, new = params.unpack()
        if not name.startswith(PREFIX):
            return
        if new:
            self._add(name, new)
        else:
            self.players.pop(name, None)
            self.owners.pop(name, None)
            self._changed()

    def _on_props(self, _c, sender, _p, _i, _sig, params):
        _iface, changed, invalidated = params.unpack()
        for name, owner in list(self.owners.items()):
            if owner != sender or name not in self.players:
                continue
            self.players[name].update(changed)
            if invalidated:
                self._fetch(name)
            self._changed()

    def _on_called(self, bus, res, name):
        try:
            bus.call_finish(res)
        except GLib.Error:
            pass
        # Prehravace, ktere zmenu neohlasi signalem: jeden dotaz na skutecny stav
        GLib.timeout_add(700, lambda: self._fetch(name) if name in self.players else None)


_WATCHER = None


def watcher():
    """Sdileny hlidac (vytvori se pri prvnim pouziti)."""
    global _WATCHER
    if _WATCHER is None:
        _WATCHER = Watcher()
    return _WATCHER
