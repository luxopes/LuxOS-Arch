"""LuxOS - rozlozeni monitoru (jako Usporadani v macOS): geometrie, profily a prikaz xrandr.

Obdelnik monitoru je (x, y, sirka, vyska) v pixelech plochy. Rozlozeni je vzdy
"spojene": kazdy monitor se dotyka aspon jednoho dalsiho celou hranou (alespon
MIN_CONTACT px spolecne hrany), zadne dva se neprekryvaji, levy horni roh celku je 0,0.

Ulozene rozlozeni (v ~/.config/luxos/displays.json, klic "layouts") patri ke konkretni
sade pripojenych monitoru: klic sady = serazene klice vystupu "KONEKTOR|EDID" spojene "+".
Kdyz presne stejna sada neni ulozena, zkusi se shoda jen podle EDID (stejne monitory
v jinych konektorech, napr. po vymene kabelu nebo dokovaci stanice).

    {"primary": "eDP-1|", "mirror": false, "pos": {"eDP-1|": [0, 0], "HDMI-1|ab12..": [1920, 0]}}
"""
import luxos_displays as ld

MIN_CONTACT = 32        # nejmensi spolecna hrana sousednich monitoru (mys musi projit)


# ---- geometrie ------------------------------------------------------------------
def rect_size(mode, rotation):
    w, h = ld.mode_size(mode or "")
    if rotation in ("left", "right"):
        w, h = h, w
    return w, h


def overlaps(a, b):
    """Prekryvaji se dva obdelniky plochou (dotyk hranou neni prekryv)?"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _shared(a0, alen, b0, blen):
    return min(a0 + alen, b0 + blen) - max(a0, b0)


def touches(a, b):
    """Dotykaji se hranou (spolecny usek delky > 0, ne jen rohem)?"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if (ax + aw == bx or bx + bw == ax) and _shared(ay, ah, by, bh) > 0:
        return True
    return (ay + ah == by or by + bh == ay) and _shared(ax, aw, bx, bw) > 0


def connected(rects):
    """Tvori obdelniky jeden celek (kazdy dosazitelny pres dotyky hran)?"""
    items = list(rects.values())
    if len(items) < 2:
        return True
    seen, todo = {0}, [0]
    while todo:
        i = todo.pop()
        for j, r in enumerate(items):
            if j not in seen and touches(items[i], r):
                seen.add(j)
                todo.append(j)
    return len(seen) == len(items)


def valid(rects):
    """Bez prekryvu a bez mezer."""
    items = list(rects.values())
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if overlaps(a, b):
                return False
    return connected(rects)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _align(v, targets, lo, hi, snap):
    """Prichyceni k zarovnani hran (nahore, dole, na stred), je-li blizko."""
    best = None
    for t in targets:
        if lo <= t <= hi and abs(v - t) <= snap and (best is None or abs(v - t) < abs(v - best)):
            best = t
    return v if best is None else best


def candidates(w, h, px, py, placed, snap=0):
    """Polohy obdelniku w x h u nektere hrany umistenych monitoru, co nejbliz navrhu (px, py)."""
    for bx, by, bw, bh in placed:
        c = min(MIN_CONTACT, h, bh)
        lo, hi = by - h + c, by + bh - c
        y = _align(_clamp(py, lo, hi), (by, by + bh - h, by + (bh - h) // 2), lo, hi, snap)
        yield bx - w, y          # vlevo
        yield bx + bw, y         # vpravo
        c = min(MIN_CONTACT, w, bw)
        lo, hi = bx - w + c, bx + bw - c
        x = _align(_clamp(px, lo, hi), (bx, bx + bw - w, bx + (bw - w) // 2), lo, hi, snap)
        yield x, by - h          # nahore
        yield x, by + bh         # dole


def place(w, h, px, py, placed, snap=0):
    """Nejblizsi platna poloha (dotyk hranou, bez prekryvu) k navrhu (px, py)."""
    if not placed:
        return px, py
    best, dist = None, None
    for x, y in candidates(w, h, px, py, placed, snap):
        r = (x, y, w, h)
        if any(overlaps(r, p) for p in placed):
            continue
        d = (x - px) ** 2 + (y - py) ** 2
        if dist is None or d < dist:
            best, dist = (x, y), d
    if best is None:
        # Nemelo by nastat (vpravo od celku je vzdy misto): vpravo nahoru
        best = (max(p[0] + p[2] for p in placed), min(p[1] for p in placed))
    return best


def normalize(pos):
    """Posunout tak, aby levy horni roh celku byl 0,0 (xrandr nezna zaporne polohy)."""
    if not pos:
        return {}
    x0 = min(p[0] for p in pos.values())
    y0 = min(p[1] for p in pos.values())
    return {n: (p[0] - x0, p[1] - y0) for n, p in pos.items()}


def settle(sizes, proposals, order, snaps=None):
    """Postupne umistit monitory v poradi `order`: prvni zustane, kazdy dalsi se prichyti
    k uz umistenym co nejbliz sve navrzene poloze. Vysledek {nazev: (x, y)} od 0,0."""
    snaps = snaps or {}
    placed, out = [], {}
    for name in order:
        w, h = sizes[name]
        px, py = proposals[name]
        x, y = place(w, h, px, py, placed, snaps.get(name, 0))
        out[name] = (x, y)
        placed.append((x, y, w, h))
    return normalize(out)


def _center_dist(a, b):
    return (a[0] + a[2] / 2 - b[0] - b[2] / 2) ** 2 + (a[1] + a[3] / 2 - b[1] - b[3] / 2) ** 2


def settle_order(rects, anchor):
    """Poradi pro settle: kotva, pak ostatni od nejblizsich (stredy)."""
    rest = sorted((n for n in rects if n != anchor), key=lambda n: (_center_dist(rects[n], rects[anchor]), n))
    return [anchor] + rest


def drop_anchor(rects, moving, primary=None):
    """Monitor, ktery se pri pretazeni `moving` urcite nepohne (hlavni, jinak nejvetsi z ostatnich)."""
    others = {n: r for n, r in rects.items() if n != moving}
    if not others:
        return None
    return primary if primary in others else max(others, key=lambda n: (others[n][2] * others[n][3], n))


def drop(rects, moving, px, py, primary=None, snap=0):
    """Pustenim monitoru `moving` na (px, py): nove polohy vsech monitoru (bez mezer a prekryvu).

    Ostatni zustanou, kde jsou (jen kdyz by bez presunuteho monitoru zustaly odtrzene,
    prichyti se ke zbytku), presunuty monitor se prichyti k nejblizsi hrane."""
    others = {n: r for n, r in rects.items() if n != moving}
    if not others:
        return {moving: (0, 0)}
    anchor = drop_anchor(rects, moving, primary)
    order = settle_order(others, anchor) + [moving]
    sizes = {n: (r[2], r[3]) for n, r in rects.items()}
    proposals = {n: (r[0], r[1]) for n, r in rects.items()}
    proposals[moving] = (px, py)
    return settle(sizes, proposals, order, {moving: snap})


# ---- profily (sady monitoru) ------------------------------------------------------
def set_key(outputs):
    return "+".join(sorted(ld.output_key(o) for o in outputs if o["connected"]))


def _edid_of(key):
    return key.partition("|")[2]


def find_layout(layouts, outputs):
    """Ulozene rozlozeni pro pripojene monitory: (rozlozeni, {klic vystupu: nazev}) nebo (None, {}).

    Nejdriv presna sada konektor+EDID, pak sada podle EDID (vsechny monitory s EDID, kazdy jiny)."""
    conn = [o for o in outputs if o["connected"]]
    if len(conn) < 2:
        return None, {}
    key = set_key(outputs)
    lay = layouts.get(key)
    if isinstance(lay, dict):
        return lay, {ld.output_key(o): o["name"] for o in conn}
    ids = [ld.edid_id(o["edid"]) for o in conn]
    if not all(ids) or len(set(ids)) != len(ids):
        return None, {}
    by_edid = {ld.edid_id(o["edid"]): o["name"] for o in conn}
    for k in sorted(layouts):
        lay = layouts[k]
        if not isinstance(lay, dict):
            continue
        keys = k.split("+")
        edids = [_edid_of(x) for x in keys]
        if sorted(edids) == sorted(ids):
            return lay, {x: by_edid[_edid_of(x)] for x in keys}
    return None, {}


def make_layout(outputs, pos, primary, mirror=False):
    """Zaznam k ulozeni z poloh {nazev: (x, y)} a nazvu hlavniho monitoru."""
    keys = {o["name"]: ld.output_key(o) for o in outputs if o["connected"]}
    return {"primary": keys.get(primary, ""), "mirror": bool(mirror),
            "pos": {keys[n]: [int(p[0]), int(p[1])] for n, p in pos.items() if n in keys}}


# ---- prikaz xrandr ----------------------------------------------------------------
def effective(out, entry):
    """(argumenty rezimu, rezim, otoceni) pro vystup se zaznamem z Monitoru nebo bez nej."""
    args = ld.output_args(out, entry)
    pmode, _r = ld.preferred_mode(out)
    if not args:
        rot = "normal"
        return ["--auto"] + (["--rotate", rot] if rot in out["rotations"] else []), pmode, rot
    mode = args[args.index("--mode") + 1] if "--mode" in args else pmode
    rot = args[args.index("--rotate") + 1] if "--rotate" in args else "normal"
    return args, mode, rot


def plan(outputs, entries, layouts, force_extend=False):
    """Prikaz xrandr podle ulozeneho rozlozeni, nebo None (zadne pro tuto sadu monitoru).

    Vysledek: {"args": [...], "pos": {nazev: (x, y)}, "primary": nazev, "mirror": bool}.
    Polohy se znovu "usadi" podle aktualnich velikosti (jine rozliseni nebo otoceni
    nesmi vytvorit mezeru ani prekryv). force_extend: zrcadleni vypnout (Super+P Rozsirit)."""
    lay, names = find_layout(layouts, outputs)
    if lay is None:
        return None
    conn = {o["name"]: o for o in outputs if o["connected"]}
    stored = lay.get("pos") if isinstance(lay.get("pos"), dict) else {}
    sizes, proposals, margs = {}, {}, {}
    for key, name in names.items():
        out = conn[name]
        args, mode, rot = effective(out, entries.get(ld.output_key(out)))
        margs[name] = args
        sizes[name] = rect_size(mode, rot)
        p = stored.get(key)
        try:
            proposals[name] = (int(p[0]), int(p[1]))
        except (TypeError, ValueError, IndexError):
            proposals[name] = None
    # Monitor bez ulozene polohy: vpravo od ostatnich
    right = max([p[0] + sizes[n][0] for n, p in proposals.items() if p] or [0])
    for n in sorted(proposals):
        if proposals[n] is None:
            proposals[n] = (right, 0)
            right += sizes[n][0]
    primary = names.get(lay.get("primary"))
    if primary not in conn:
        primary = next((n for n in sorted(conn) if ld.is_internal(n)), sorted(conn)[0])
    mirror = bool(lay.get("mirror")) and not force_extend
    if mirror:
        pos = {n: (0, 0) for n in conn}
    else:
        rects = {n: (*proposals[n], *sizes[n]) for n in conn}
        pos = settle(sizes, proposals, settle_order(rects, primary))
    args = []
    for out in outputs:
        if not out["connected"]:
            args += ["--output", out["name"], "--off"]
    for name in [primary] + sorted(n for n in conn if n != primary):
        args += ["--output", name, *margs[name]]
        if mirror and name != primary:
            args += ["--same-as", primary]
        else:
            args += ["--pos", "%dx%d" % pos[name]]
        if name == primary:
            args.append("--primary")
    return {"args": args, "pos": pos, "primary": primary, "mirror": mirror}


def matches(outputs, expected):
    """Odpovida skutecny stav (xrandr) planu? Polohy aktivnich monitoru a hlavni monitor."""
    act = {o["name"]: o for o in outputs if o["connected"] and o["geometry"]}
    for name, (x, y) in expected["pos"].items():
        o = act.get(name)
        if o is None or (o["geometry"][2], o["geometry"][3]) != (x, y):
            return False
    prim = act.get(expected["primary"])
    return prim is not None and prim["primary"]


def current_rects(outputs):
    """{nazev: (x, y, w, h)} aktivnich monitoru podle xrandr."""
    return {o["name"]: (o["geometry"][2], o["geometry"][3], o["geometry"][0], o["geometry"][1])
            for o in outputs if o["connected"] and o["geometry"]}
