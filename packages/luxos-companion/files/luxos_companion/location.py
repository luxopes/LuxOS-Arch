"""Poloha z telefonu: posledni cerstvy fix (location.update), platny nejvys 15 s.

Stari fixu se pocita z monotonnich hodin PC v okamziku prijeti minus age_ms z telefonu - hodiny
telefonu a PC se nikdy neporovnavaji (timestamp_ms je jen informace). location.status enabled:false,
odpojeni nebo timeout spojeni polohu telefonu okamzite zrusi. Pred zverejnenim se kontroluji rozsahy.
"""
import time

from .wire import is_finite_number

FRESH_S = 15.0               # fix starsi nez 15 s neplati
MAX_ACCURACY_M = 100000.0    # horsi presnost nema pro mapu smysl


class InvalidLocation(ValueError):
    pass


def _num(msg, key, lo, hi, required=True):
    v = msg.get(key)
    if v is None and not required:
        return None
    if not is_finite_number(v) or not lo <= v <= hi:
        raise InvalidLocation(key)
    return float(v)


def parse_update(msg):
    """location.update -> slovnik fixu (bez casu prijeti). Neplatne hodnoty -> InvalidLocation."""
    fix = {
        "latitude": _num(msg, "latitude", -90.0, 90.0),
        "longitude": _num(msg, "longitude", -180.0, 180.0),
        "accuracy": _num(msg, "accuracy_m", 0.0, MAX_ACCURACY_M),
        "age_ms": _num(msg, "age_ms", 0, FRESH_S * 1000),
        "altitude": _num(msg, "altitude_m", -20000.0, 100000.0, False),
        "speed": _num(msg, "speed_mps", 0.0, 3000.0, False),
        "bearing": _num(msg, "bearing_deg", 0.0, 360.0, False),
    }
    ts = msg.get("timestamp_ms")
    if type(ts) is not int or not 0 <= ts < 2 ** 53:
        raise InvalidLocation("timestamp_ms")
    fix["timestamp_ms"] = ts
    mock = msg.get("mock", False)
    if not isinstance(mock, bool):
        raise InvalidLocation("mock")
    fix["mock"] = mock
    return fix


class LocationState:
    """Fixy z pripojenych telefonu; zverejnuje se nejnovejsi cerstvy. on_change(snapshot) pri zmene."""

    def __init__(self, clock=time.monotonic, on_change=None):
        self.clock = clock
        self.on_change = on_change
        self.enabled = True          # sdileni polohy s Mapami (nastaveni)
        self.fixes = {}              # klic spojeni -> fix + "received" (monotonni cas fixu na PC) + device
        self.status = {}             # klic spojeni -> enabled z location.status
        self._last_valid = False

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.fixes.clear()
        self._changed()

    def set_status(self, key, enabled):
        self.status[key] = bool(enabled)
        if not enabled and key in self.fixes:
            del self.fixes[key]
            self._changed()

    def update(self, key, msg, device=""):
        """Prijaty location.update. Vraci True, pokud byl fix prijat."""
        fix = parse_update(msg)          # InvalidLocation projde ven
        if not self.enabled or self.status.get(key) is False:
            return False
        fix["received"] = self.clock() - fix["age_ms"] / 1000.0
        fix["device"] = device
        old = self.fixes.get(key)
        if old and fix["received"] < old["received"]:
            return False                 # starsi nez posledni (preusporadani) - ignorovat
        self.fixes[key] = fix
        self._changed()
        return True

    def drop(self, key):
        """Odpojeni nebo timeout spojeni."""
        self.status.pop(key, None)
        if self.fixes.pop(key, None) is not None:
            self._changed()

    def current(self):
        """Nejnovejsi cerstvy fix nebo None (zastarale se zahodi)."""
        now = self.clock()
        best = None
        for key, fix in list(self.fixes.items()):
            if now - fix["received"] >= FRESH_S:
                del self.fixes[key]
                continue
            if best is None or fix["received"] > best["received"]:
                best = fix
        return best

    def snapshot(self):
        """Stav pro D-Bus: {"valid": bool, ...}; age_ms podle hodin PC v okamziku dotazu."""
        fix = self.current() if self.enabled else None
        if fix is None:
            return {"valid": False}
        out = {"valid": True, "latitude": fix["latitude"], "longitude": fix["longitude"],
               "accuracy": fix["accuracy"], "timestamp_ms": fix["timestamp_ms"],
               "age_ms": max(0, int(round((self.clock() - fix["received"]) * 1000))),
               "mock": fix["mock"], "device": fix["device"]}
        for k in ("altitude", "speed", "bearing"):
            if fix[k] is not None:
                out[k] = fix[k]
        return out

    def expires_in(self):
        """Za kolik sekund zastara nejnovejsi fix (pro casovac); None bez fixu."""
        fix = self.current()
        if fix is None:
            return None
        return max(0.0, FRESH_S - (self.clock() - fix["received"]))

    def check(self):
        """Volat casovacem: pri zastarani posle zmenu (valid false)."""
        valid = self.current() is not None
        if valid != self._last_valid:
            self._changed()

    def _changed(self):
        snap = self.snapshot()
        self._last_valid = snap["valid"]
        if self.on_change:
            self.on_change(snap)
