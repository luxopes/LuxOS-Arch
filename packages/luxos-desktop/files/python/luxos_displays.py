"""LuxOS - monitory: cteni vystupu xrandr, ulozene rozliseni/frekvence/otoceni a velikost textu.

Pouziva aplikace Monitory (luxos-display-settings) i skript luxos-displays:

    python3 -I luxos_displays.py output-args

vypise pro kazdy pripojeny vystup s ulozenym nastavenim radek
"NAZEV --mode M --rate R --rotate X" (overeno proti rezimum, ktere monitor
skutecne nabizi). Vystupy bez zaznamu se nevypisuji - luxos-displays pro ne
pouzije --auto (doporuceny rezim monitoru).

    python3 -I luxos_displays.py rate-cap | rate-restore VYSTUP REZIM FREKVENCE

Sporic baterie: vestaveny displej s vic nez 60 Hz prepne na 60 Hz (vypise
"VYSTUP REZIM PUVODNI_FREKVENCE" pro navrat) a pri vypnuti frekvenci vrati.

Nastaveni je v ~/.config/luxos/displays.json (LUXOS_DISPLAYS_CONF ho prepise,
pouziva se pro zkusebni pouziti pred potvrzenim). Klic "layouts" = rozlozeni monitoru
(luxos_arrange, "layout-args"). Klic zaznamu je nazev vystupu
a otisk EDID, takze jiny monitor na stejnem konektoru dostane svuj doporuceny rezim.
LUXOS_XRANDR prepise prikaz xrandr (testy).
"""
import hashlib
import json
import os
import re
import subprocess
import sys

ROTATIONS = ("normal", "right", "inverted", "left")
# Velikost textu = Xft/DPI v kanalu xsettings (xfsettingsd ji posila GTK, panelu, xfwm4,
# Qt i Firefoxu). None = vychozi (vlastnost se odstrani).
TEXT_SIZES = (84, None, 108, 120, 132)
DEFAULT_DPI = 96


def conf_path():
    env = os.environ.get("LUXOS_DISPLAYS_CONF")
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "luxos", "displays.json")


def xrandr_cmd():
    return os.environ.get("LUXOS_XRANDR") or "xrandr"


def run_xrandr(*args, timeout=15):
    try:
        r = subprocess.run([xrandr_cmd(), *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---- parsovani xrandr ----------------------------------------------------------
HEADER = re.compile(r"^(\S+) (connected|disconnected|unknown connection)(.*)$")
GEOMETRY = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")
RATE = re.compile(r"^(\d+(?:\.\d+)?)([*+]*)$")


def _parse_rates(tokens):
    """Tokeny za nazvem rezimu -> [(frekvence, aktualni, doporucena)].

    xrandr pise priznaky primo za cislo ("60.00*+") nebo oddelene mezerou ("60.00 +").
    """
    rates = []
    for tok in tokens:
        if tok and set(tok) <= set("*+"):
            if rates:
                r, cur, pref = rates[-1]
                rates[-1] = (r, cur or "*" in tok, pref or "+" in tok)
            continue
        m = RATE.match(tok)
        if not m:
            continue
        rates.append((m.group(1), "*" in m.group(2), "+" in m.group(2)))
    return rates


def parse(text):
    """Vystup "xrandr [--current] [--prop]" -> seznam vystupu (slovniky).

    Vystup: name, connected, primary, active, geometry (w, h, x, y) nebo None, rotation,
    rotations (podporovane), mm (sirka, vyska), edid (hex) a modes = [{name, rates:
    [frekvence], current (frekvence nebo None), preferred (frekvence nebo None)}].
    """
    outputs = []
    out = None
    in_edid = False
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            name, status, rest = m.groups()
            out = {"name": name, "connected": status == "connected", "primary": False, "active": False,
                   "geometry": None, "rotation": "normal", "rotations": list(ROTATIONS), "mm": (0, 0),
                   "edid": "", "modes": []}
            outputs.append(out)
            in_edid = False
            head, _sep, tail = rest.partition("(")
            words = head.split()
            if "primary" in words:
                out["primary"] = True
                words.remove("primary")
            if words:
                g = GEOMETRY.fullmatch(words[0])
                if g:
                    out["geometry"] = tuple(int(v) for v in g.groups())
                    out["active"] = True
                    if len(words) > 1 and words[1] in ROTATIONS:
                        out["rotation"] = words[1]
            supported, _sep, after = tail.partition(")")
            rots = [w for w in supported.split() if w in ROTATIONS]
            if rots:
                out["rotations"] = rots
            mm = re.search(r"(\d+)mm x (\d+)mm", after)
            if mm:
                out["mm"] = (int(mm.group(1)), int(mm.group(2)))
            continue
        if out is None:
            continue
        if line.startswith("\t"):
            # Vlastnosti (--prop): EDID je hex na nasledujicich radcich s dvojitym tabulatorem
            stripped = line.strip()
            if stripped.startswith("EDID:"):
                in_edid = True
                continue
            if in_edid and line.startswith("\t\t") and re.fullmatch(r"[0-9a-fA-F]+", stripped):
                out["edid"] += stripped.lower()
                continue
            in_edid = False
            continue
        in_edid = False
        if line.startswith("  ") and not line.startswith("    "):
            parts = line.split()
            if not parts or "x" not in parts[0]:
                continue
            rates = _parse_rates(parts[1:])
            mode = next((md for md in out["modes"] if md["name"] == parts[0]), None)
            if mode is None:
                mode = {"name": parts[0], "rates": [], "current": None, "preferred": None}
                out["modes"].append(mode)
            for rate, cur, pref in rates:
                if rate not in mode["rates"]:
                    mode["rates"].append(rate)
                if cur:
                    mode["current"] = rate
                if pref and mode["preferred"] is None:
                    mode["preferred"] = rate
    return outputs


def query(current=True):
    args = ["--prop"]
    if current:
        args.insert(0, "--current")
    return parse(run_xrandr(*args))


def mode_size(name):
    m = re.match(r"(\d+)x(\d+)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def is_interlaced(name):
    return bool(re.fullmatch(r"\d+x\d+i", name))


def current_mode(out):
    """(rezim, frekvence) prave pouzivane vystupem, nebo (None, None)."""
    for md in out["modes"]:
        if md["current"]:
            return md["name"], md["current"]
    return None, None


def preferred_mode(out):
    """Doporuceny rezim monitoru (EDID "+"), jinak prvni (nejvetsi) v seznamu."""
    for md in out["modes"]:
        if md["preferred"]:
            return md["name"], md["preferred"]
    if out["modes"]:
        md = out["modes"][0]
        return md["name"], (md["rates"][0] if md["rates"] else None)
    return None, None


def find_mode(out, name):
    return next((md for md in out["modes"] if md["name"] == name), None)


def best_rate(mode, preferred=None):
    """Frekvence pro nove vybrany rezim: doporucena, jinak nejvyssi."""
    if not mode["rates"]:
        return None
    if preferred in mode["rates"]:
        return preferred
    if mode["preferred"]:
        return mode["preferred"]
    return max(mode["rates"], key=float)


def resolution_choices(out):
    """[(rezim, doporuceny)] k nabidnuti: bez prokladanych a duplicit, od nejvetsiho."""
    pref, _r = preferred_mode(out)
    cur, _c = current_mode(out)
    seen = []
    for md in out["modes"]:
        name = md["name"]
        if is_interlaced(name) and name != cur:
            continue
        if name in seen:
            continue
        seen.append(name)
    seen.sort(key=lambda n: (mode_size(n)[0] * mode_size(n)[1], mode_size(n)[0]), reverse=True)
    return [(n, n == pref) for n in seen]


def fmt_rate(rate):
    v = float(rate)
    return ("%d Hz" % round(v)) if abs(v - round(v)) < 0.005 else ("%.2f Hz" % v)


def fmt_mode(name):
    w, h = mode_size(name)
    if not w:
        return name
    return f"{w} × {h}" + (" i" if is_interlaced(name) else "")


# ---- nazev monitoru -------------------------------------------------------------
def edid_id(edid_hex):
    return hashlib.md5(edid_hex.encode()).hexdigest()[:12] if edid_hex else ""


def edid_name(edid_hex):
    """Nazev modelu z EDID (deskriptor 0xFC), nebo ""."""
    try:
        data = bytes.fromhex(edid_hex)
    except ValueError:
        return ""
    if len(data) < 128:
        return ""
    for off in (54, 72, 90, 108):
        d = data[off:off + 18]
        if d[0:3] == b"\0\0\0" and d[3] == 0xFC:
            return d[5:18].split(b"\n")[0].decode("ascii", "replace").strip()
    return ""


def is_internal(name):
    return name.startswith(("eDP", "LVDS", "DSI"))


def output_key(out):
    return f"{out['name']}|{edid_id(out['edid'])}"


# ---- ulozene nastaveni ----------------------------------------------------------
def load(path=None):
    try:
        with open(path or conf_path(), encoding="utf-8") as f:
            data = json.load(f)
        outs = data.get("outputs", {})
        return {k: v for k, v in outs.items() if isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def load_layouts(path=None):
    """Ulozena rozlozeni monitoru {klic sady: rozlozeni} (viz luxos_arrange)."""
    try:
        with open(path or conf_path(), encoding="utf-8") as f:
            lays = json.load(f).get("layouts", {})
        return {k: v for k, v in lays.items() if isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def save(entries, path=None, layouts=None):
    """Ulozit zaznamy monitoru; layouts=None ponecha rozlozeni ulozena v souboru."""
    path = path or conf_path()
    if layouts is None:
        layouts = load_layouts(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    data = {"version": 1, "outputs": entries}
    if layouts:
        data["layouts"] = layouts
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def entry_for(out, mode, rate, rotation):
    """Zaznam k ulozeni, nebo None, pokud jde o vychozi stav (doporuceny rezim, bez otoceni)."""
    pmode, prate = preferred_mode(out)
    if mode == pmode and (rate is None or rate == prate) and rotation == "normal":
        return None
    e = {"mode": mode, "rotate": rotation}
    if rate:
        e["rate"] = rate
    return e


def output_args(out, entry):
    """xrandr argumenty pro ulozeny zaznam (bez --output), nebo None, kdyz neplati."""
    if not entry or not out["connected"]:
        return None
    md = find_mode(out, entry.get("mode", ""))
    rot = entry.get("rotate", "normal")
    if rot not in out["rotations"]:
        rot = "normal"
    if md is None:
        # Rezim monitor nenabizi (jiny monitor, zmena ovladace): jen otoceni, rezim automaticky
        return None if rot == "normal" else ["--auto", "--rotate", rot]
    args = ["--mode", md["name"]]
    rate = entry.get("rate")
    if rate and rate in md["rates"]:
        args += ["--rate", rate]
    args += ["--rotate", rot]
    return args


def all_output_args(outputs, entries):
    lines = []
    for out in outputs:
        if not out["connected"]:
            continue
        args = output_args(out, entries.get(output_key(out)))
        if args:
            lines.append((out["name"], args))
    return lines


# ---- Sporic baterie: vestaveny displej nejvys 60 Hz (jako Rezim nizke spotreby v macOS) ----
RATE_CAP = 61.0     # 59.94 / 60.00 / 60.02 Hz projdou, 90/120/144/165 Hz ne


def rate_cap_target(out, limit=RATE_CAP):
    """(rezim, aktualni, nova frekvence) pro snizeni frekvence vestaveneho displeje, nebo None."""
    if not (is_internal(out["name"]) and out["connected"] and out["active"]):
        return None
    name, cur = current_mode(out)
    if name is None or float(cur) <= limit:
        return None
    md = find_mode(out, name)
    low = [r for r in md["rates"] if float(r) <= limit]
    if not low:
        return None
    return name, cur, max(low, key=float)


def rate_cap(outputs):
    """Snizi frekvenci; vrati [(vystup, rezim, puvodni frekvence)] pro pozdejsi navrat."""
    done = []
    for out in outputs:
        t = rate_cap_target(out)
        if t is None:
            continue
        mode, cur, new = t
        run_xrandr("--output", out["name"], "--mode", mode, "--rate", new)
        done.append((out["name"], mode, cur))
    return done


def rate_restore(outputs, name, mode, rate):
    """Vrati puvodni frekvenci, jen kdyz vystup porad pouziva stejny rezim a frekvenci nabizi."""
    out = next((o for o in outputs if o["name"] == name and o["connected"] and o["active"]), None)
    if out is None:
        return False
    cur_mode, cur = current_mode(out)
    md = find_mode(out, mode)
    if cur_mode != mode or md is None or rate not in md["rates"] or cur == rate:
        return False
    run_xrandr("--output", name, "--mode", mode, "--rate", rate)
    return True


# ---- velikost textu (xsettings Xft/DPI) ------------------------------------------
def text_size_index(dpi):
    """Index v TEXT_SIZES pro aktualni Xft/DPI (None/neplatne = vychozi, jinak nejblizsi)."""
    if dpi is None or dpi <= 0 or dpi == DEFAULT_DPI:
        return TEXT_SIZES.index(None)
    return min(range(len(TEXT_SIZES)), key=lambda i: abs((TEXT_SIZES[i] or DEFAULT_DPI) - dpi))


def read_dpi():
    try:
        r = subprocess.run(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI"],
                           capture_output=True, text=True, timeout=5)
        return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def set_text_size(index):
    """Nastavi velikost textu; vychozi krok vlastnost odstrani (navrat k vychozimu DPI)."""
    dpi = TEXT_SIZES[index]
    if dpi is None:
        cmd = ["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-r"]
    else:
        cmd = ["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-n", "-t", "int", "-s", str(dpi)]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main(argv):
    if argv[1:2] == ["output-args"]:
        entries = load()
        if not entries:
            return 0
        for name, args in all_output_args(query(), entries):
            print(name, *args)
        return 0
    if argv[1:2] == ["layout-args"]:
        # Cely prikaz xrandr podle ulozeneho rozlozeni pro pripojenou sadu monitoru (nic = neni).
        # "layout-args extend": Super+P Rozsirit - zrcadleni v rozlozeni vypnout a ulozit
        # python3 -I nepridava adresar skriptu do sys.path
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import luxos_arrange as la
        layouts = load_layouts()
        if not layouts:
            return 0
        outputs = query()
        force = argv[2:3] == ["extend"]
        p = la.plan(outputs, load(), layouts, force_extend=force)
        if p is None:
            return 0
        if force:
            lay, _names = la.find_layout(layouts, outputs)
            if lay.get("mirror"):
                lay["mirror"] = False
                save(load(), layouts=layouts)
        print(" ".join(p["args"]))
        return 0
    if argv[1:2] == ["rate-cap"]:
        for name, mode, rate in rate_cap(query()):
            print(name, mode, rate)
        return 0
    if argv[1:2] == ["rate-restore"] and len(argv) == 5:
        rate_restore(query(), *argv[2:5])
        return 0
    print("usage: luxos_displays.py output-args | layout-args [extend] | rate-cap | rate-restore OUTPUT MODE RATE", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
