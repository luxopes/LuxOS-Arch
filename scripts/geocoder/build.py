#!/usr/bin/env python3
"""Sestaveni databaze geocoderu LuxOS (naseptavani v Mapach) z dat OpenStreetMap.

    python3 scripts/geocoder/build.py -o geocoder.sqlite czech-republic-latest.osm.pbf slovakia-latest.osm.pbf
    python3 scripts/geocoder/build.py -o tiny.sqlite tests/fixtures/prague.osm      # mala data (testy)

Vstup: vytahy Geofabrik (.osm.pbf, cte pyosmium) nebo maly soubor .osm (XML, jen standardni knihovna).
Zavislosti jen na pocitaci, kde se stavi (ne na serveru): python3 >= 3.9 se sqlite3 s FTS5 a pro .pbf
balicek "osmium" (pyosmium >= 4, `pip install osmium`). Pamet ~1-1,5 GB pro CZ+SK; velke docasne
soubory (index poloh uzlu, mezivysledky) jdou do --work (vychozi vedle vystupu).

Co databaze obsahuje (vse s nazvy a variantami name, name:cs/sk/en/de, alt_name, short_name...):
  mista (obce, mestske casti, osady), ulice (useky se stejnym jmenem v obci slouceny), adresy
  (cislo domu + ulice/cast obce + obec), zajimava mista (amenity/shop/tourism/leisure/historic...),
  zastavky (nadrazi, tramvaj, autobus; nastupiste se stejnym jmenem v obci slouceny do jedne).
Obec, cast obce, kraj a stat se doplni podle hranic (admin_level) prevedenych na mrizku ~150 m.

Rychlost hledani: radky jsou ocislovane podle dulezitosti (nejdulezitejsi = nejmensi rowid), takze
FTS5 "MATCH ... LIMIT n" vraci nejdulezitejsi shody bez razeni vsech shod. Mista v okoli najde druhy
dotaz s tokeny bunek mrizky (viz luxos_geocoder.cell_token).

Dalsi staty: pridat vytah na prikazovy radek a jejich admin_level do COUNTRY_LEVELS.
"""

import argparse
import array
import collections
import datetime
import json
import math
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server", "geocoder"))
import luxos_geocoder as G  # noqa: E402

# role hranic podle statu: (kraj, obec, cast obce)
COUNTRY_LEVELS = {"CZ": (6, 8, 10), "SK": (4, 9, 10)}
ADMIN_LEVELS = (2, 4, 6, 7, 8, 9, 10)
NAME_LANGS = ("cs", "sk", "en", "de", "pl", "hu", "uk")
FILTER_KEYS = ("name", "addr:housenumber", "addr:conscriptionnumber", "addr:streetnumber")

PLACE_IMP = {"city": 0.90, "town": 0.75, "village": 0.55, "suburb": 0.52, "borough": 0.52, "quarter": 0.47,
             "neighbourhood": 0.42, "hamlet": 0.36, "isolated_dwelling": 0.26}
STREET_HW = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
             "living_street", "pedestrian", "service", "road", "busway", "track", "footway", "path", "cycleway",
             "steps", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
STREET_MINOR = {"track", "footway", "path", "cycleway", "steps", "service"}
STOP_RANK = {("railway", "station"): 0.62, ("railway", "halt"): 0.52, ("public_transport", "station"): 0.58,
             ("amenity", "bus_station"): 0.52, ("railway", "tram_stop"): 0.46, ("highway", "bus_stop"): 0.42,
             ("amenity", "ferry_terminal"): 0.46, ("aerialway", "station"): 0.46,
             ("railway", "subway_entrance"): 0.30, ("public_transport", "platform"): 0.40,
             ("railway", "platform"): 0.40, ("highway", "platform"): 0.40,
             ("public_transport", "stop_position"): 0.38, ("railway", "stop"): 0.38}
POI_KEYS = ("amenity", "tourism", "shop", "leisure", "historic", "healthcare", "office", "craft", "aeroway",
            "natural", "man_made", "sport", "club", "emergency", "building")
POI_SKIP = {
    "amenity": {"parking_space", "bench", "waste_basket", "waste_disposal", "vending_machine", "hunting_stand",
                "grit_bin", "bicycle_parking", "drinking_water", "clock", "post_box", "telephone", "recycling",
                "parking_entrance", "loading_dock", "letter_box", "feeding_place", "water_point",
                "motorcycle_parking", "charging_station", "atm", "toilets", "shelter"},
    "leisure": {"picnic_table", "pitch", "track", "swimming_pool", "firepit", "slipway", "bleachers",
                "outdoor_seating", "common"},
    "tourism": {"information", "picnic_site"},
    "natural": None,             # None = jen vyjmenovane v POI_ONLY
    "man_made": None, "building": None, "aeroway": None, "emergency": None,
}
POI_ONLY = {"natural": {"peak", "cave_entrance", "spring", "saddle", "volcano", "waterfall", "rock", "stone"},
            "man_made": {"tower", "observatory", "lighthouse", "windmill", "watermill", "water_tower"},
            "building": {"church", "cathedral", "chapel", "castle", "train_station", "stadium", "hospital",
                         "university", "school", "museum"},
            "aeroway": {"aerodrome", "terminal", "heliport"}, "emergency": {"ambulance_station"}}
POI_BONUS = {("tourism", "attraction"): 0.08, ("tourism", "museum"): 0.08, ("tourism", "zoo"): 0.1,
             ("historic", "castle"): 0.1, ("amenity", "university"): 0.06, ("amenity", "hospital"): 0.06,
             ("aeroway", "aerodrome"): 0.12, ("tourism", "theme_park"): 0.08, ("leisure", "stadium"): 0.06,
             ("amenity", "theatre"): 0.05, ("shop", "mall"): 0.06, ("natural", "peak"): 0.04}
IMP_STREET, IMP_ADDRESS, IMP_POI = 0.40, 0.20, 0.28


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


# ---- mrizka hranic -------------------------------------------------------------------------------
class Raster:
    """Mrizka nad bbox: v kazde bunce cislo nazvu hranice (0 = nic). Polygony se vyplnuji radkove
    (sudy-lichy pres vsechny kruhy), coz je v cistem Pythonu rychle i pro tisice obci."""
    DLAT, DLON = 0.0013, 0.002

    def __init__(self, south, west, north, east):
        self.s, self.w = south - 0.05, west - 0.05
        self.rows = int(math.ceil((north + 0.05 - self.s) / self.DLAT))
        self.cols = int(math.ceil((east + 0.05 - self.w) / self.DLON))
        self.levels = {}

    def grid(self, level):
        g = self.levels.get(level)
        if g is None:
            g = self.levels[level] = array.array("I", bytes(4 * self.rows * self.cols))
        return g

    def fill(self, level, rings, val):
        grid = self.grid(level)
        rows = collections.defaultdict(list)
        s, w, dlat, dlon, nrows = self.s, self.w, self.DLAT, self.DLON, self.rows
        for ring in rings:
            if len(ring) < 3:
                continue
            py, px = (ring[-1][0] - s) / dlat, (ring[-1][1] - w) / dlon
            for lat, lon in ring:
                y, x = (lat - s) / dlat, (lon - w) / dlon
                if y != py:
                    lo, hi = (py, y) if py < y else (y, py)
                    r0, r1 = max(0, math.ceil(lo - 0.5)), min(nrows - 1, math.ceil(hi - 0.5) - 1)
                    for r in range(r0, r1 + 1):
                        yc = r + 0.5
                        rows[r].append(px + (yc - py) * (x - px) / (y - py))
                py, px = y, x
        cols = self.cols
        for r, xs in rows.items():
            xs.sort()
            base = r * cols
            for i in range(0, len(xs) - 1, 2):
                c0, c1 = max(0, math.ceil(xs[i] - 0.5)), min(cols - 1, math.ceil(xs[i + 1] - 0.5) - 1)
                if c1 >= c0:
                    grid[base + c0:base + c1 + 1] = array.array("I", [val]) * (c1 - c0 + 1)

    def get(self, level, lat, lon, near=True):
        g = self.levels.get(level)
        if g is None:
            return 0
        r, c = int((lat - self.s) / self.DLAT), int((lon - self.w) / self.DLON)
        if 0 <= r < self.rows and 0 <= c < self.cols:
            v = g[r * self.cols + c]
            if v or not near:
                return v
        for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < self.rows and 0 <= cc < self.cols and g[rr * self.cols + cc]:
                return g[rr * self.cols + cc]
        return 0


# ---- cteni OSM -----------------------------------------------------------------------------------
def pbf_bbox(path):
    import osmium
    h = osmium.io.Reader(path, osmium.osm.osm_entity_bits.NOTHING).header()
    box = h.box()
    if not box.valid():
        raise SystemExit(f"{path}: no bounding box in the header")
    ts = h.get("osmosis_replication_timestamp") or h.get("timestamp") or ""
    return (box.bottom_left.lat, box.bottom_left.lon, box.top_right.lat, box.top_right.lon), ts


def read_pbf(path, work):
    """(typ, id, tagy, geometrie): n -> (lat, lon), w -> [(lat, lon)...], a -> [kruhy] (jen relace)."""
    import osmium
    idx = os.path.join(work, "nodes.idx")
    if os.path.exists(idx):
        os.unlink(idx)
    fp = (osmium.FileProcessor(path)
          .with_locations(f"sparse_file_array,{idx}")
          .with_areas(osmium.filter.KeyFilter("name"))
          .with_filter(osmium.filter.EmptyTagFilter())
          .with_filter(osmium.filter.KeyFilter(*FILTER_KEYS)))
    try:
        for o in fp:
            if o.is_node():
                loc = o.location
                if loc.valid():
                    yield "n", o.id, {t.k: t.v for t in o.tags}, (loc.lat, loc.lon)
            elif o.is_way():
                pts = [(n.lat, n.lon) for n in o.nodes if n.location.valid()]
                if pts:
                    yield "w", o.id, {t.k: t.v for t in o.tags}, pts
            elif o.is_area() and not o.from_way():
                rings = []
                for outer in o.outer_rings():
                    rings.append([(n.lat, n.lon) for n in outer])
                    for inner in o.inner_rings(outer):
                        rings.append([(n.lat, n.lon) for n in inner])
                yield "a", o.orig_id(), {t.k: t.v for t in o.tags}, rings
    finally:
        del fp
        if os.path.exists(idx):
            os.unlink(idx)


def _join_rings(ways):
    """Usek cest -> uzavrene kruhy (spojovani koncu); neuzavrene zbytky se zahodi."""
    rings, open_ = [], [list(w) for w in ways if len(w) >= 2]
    while open_:
        cur = open_.pop()
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for i, w in enumerate(open_):
                if w[0] == cur[-1]:
                    cur += w[1:]
                elif w[-1] == cur[-1]:
                    cur += w[-2::-1]
                elif w[-1] == cur[0]:
                    cur = w[:-1] + cur
                elif w[0] == cur[0]:
                    cur = w[:0:-1] + cur
                else:
                    continue
                open_.pop(i)
                changed = True
                break
        if cur[0] == cur[-1] and len(cur) >= 4:
            rings.append(cur)
    return rings


def read_xml(path):
    """Maly soubor .osm (testy): stejne vystupy jako read_pbf, bez pyosmium."""
    root = ET.parse(path).getroot()
    nodes, ways = {}, {}
    out_nodes, out_ways, out_areas = [], [], []
    for el in root:
        tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
        if el.tag == "node":
            ll = (float(el.get("lat")), float(el.get("lon")))
            nodes[int(el.get("id"))] = ll
            if tags and any(k in tags for k in FILTER_KEYS):
                out_nodes.append(("n", int(el.get("id")), tags, ll))
        elif el.tag == "way":
            pts = [nodes[int(nd.get("ref"))] for nd in el.findall("nd") if int(nd.get("ref")) in nodes]
            ways[int(el.get("id"))] = pts
            if tags and any(k in tags for k in FILTER_KEYS) and pts:
                out_ways.append(("w", int(el.get("id")), tags, pts))
        elif el.tag == "relation" and tags.get("type") in ("multipolygon", "boundary") and "name" in tags:
            members = [(m.get("role"), ways.get(int(m.get("ref")))) for m in el.findall("member")
                       if m.get("type") == "way"]
            rings = _join_rings([w for role, w in members if w and role in ("outer", "")]) + \
                _join_rings([w for role, w in members if w and role == "inner"])
            if rings:
                out_areas.append(("a", int(el.get("id")), tags, rings))
    yield from out_nodes
    yield from out_ways
    yield from out_areas


def xml_bbox(path):
    root = ET.parse(path).getroot()
    b = root.find("bounds")
    if b is not None:
        return (float(b.get("minlat")), float(b.get("minlon")), float(b.get("maxlat")), float(b.get("maxlon"))), ""
    lats = [float(n.get("lat")) for n in root.iter("node")]
    lons = [float(n.get("lon")) for n in root.iter("node")]
    return (min(lats), min(lons), max(lats), max(lons)), ""


# ---- klasifikace ---------------------------------------------------------------------------------
def name_variants(tags):
    """(hlavni nazev, {jazyk: nazev}, [vsechny dalsi varianty])."""
    name = (tags.get("name") or "").strip()
    langs, alts = {}, []
    for lang in NAME_LANGS:
        v = (tags.get("name:" + lang) or "").strip()
        if v and v != name:
            langs[lang] = v
            alts.append(v)
    for k in ("alt_name", "short_name", "official_name", "loc_name", "old_name"):
        for v in (tags.get(k) or "").split(";"):
            v = v.strip()
            if v and v != name and len(v) <= 120:
                alts.append(v)
    if not name and langs:
        name = langs.get("cs") or langs.get("sk") or langs.get("en") or next(iter(langs.values()))
    return name[:200], langs, alts


def stop_tag(tags):
    best = None
    for (k, v), imp in STOP_RANK.items():
        if tags.get(k) == v and (best is None or imp > STOP_RANK[best]):
            best = (k, v)
    if best == ("railway", "station") and tags.get("station") == "subway":
        return best, STOP_RANK[best] + 0.02
    if best == ("railway", "platform") and tags.get("public_transport") != "platform":
        return None, 0                         # nastupiste bez PT schematu = hrana nastupiste, ne zastavka
    return best, (STOP_RANK[best] if best else 0)


def poi_tag(tags):
    for k in POI_KEYS:
        v = tags.get(k)
        if not v or v in ("yes", "no"):
            continue
        if k in POI_ONLY:
            if v in POI_ONLY[k]:
                return k, v
            continue
        if v in (POI_SKIP.get(k) or ()):
            continue
        return k, v
    return None


def housenumber(tags):
    hn = (tags.get("addr:housenumber") or "").strip()
    if hn:
        return hn[:30]
    cn, sn = (tags.get("addr:conscriptionnumber") or "").strip(), (tags.get("addr:streetnumber") or "").strip()
    return (f"{cn}/{sn}" if cn and sn else cn or sn)[:30]


def centroid(pts):
    if len(pts) > 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return pts[len(pts) // 2]


def ring_area(ring):
    a = 0.0
    for (y1, x1), (y2, x2) in zip(ring, ring[1:] + ring[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


# ---- staging (mezivysledky na disku, ne v pameti) --------------------------------------------------
STAGE_SQL = """
CREATE TABLE IF NOT EXISTS stage(kind INT, osm INT, name TEXT, names TEXT, alt TEXT, okey TEXT, oval TEXT,
    street TEXT, hn TEXT, postcode TEXT, acity TEXT, asub TEXT, lat REAL, lon REAL, imp REAL, g INT, part INT,
    UNIQUE(osm, kind));
"""


class Collector:
    def __init__(self, db, raster, names):
        self.db, self.raster, self.names = db, raster, names
        self.buf = []
        self.count = collections.Counter()

    def name_id(self, name):
        i = self.names.get(name)
        if i is None:
            i = self.names[name] = len(self.names) + 1
        return i

    def add(self, kind, osm, name, langs, alts, okey, oval, lat, lon, imp, street="", hn="", postcode="",
            acity="", asub=""):
        self.buf.append((kind, osm, name, json.dumps(langs, ensure_ascii=False) if langs else None,
                         "|".join(alts) if alts else None, okey, oval, street, hn, postcode, acity, asub,
                         round(lat, 7), round(lon, 7), imp))
        self.count[G.KINDS[kind]] += 1
        if len(self.buf) >= 50000:
            self.flush()

    def flush(self):
        self.db.executemany("INSERT OR IGNORE INTO stage(kind, osm, name, names, alt, okey, oval, street, hn, "
                            "postcode, acity, asub, lat, lon, imp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            self.buf)
        self.buf = []

    def element(self, typ, oid, tags, geom):
        osm = oid * 4 + {"n": 0, "w": 1, "a": 2}[typ]
        if typ == "a":
            self.area(oid, tags, geom)
            if not any(k in tags for k in ("place", "amenity", "tourism", "leisure", "historic", "shop")):
                return
            outer = max(geom, key=ring_area)
            lat, lon = centroid(outer + outer[:1])
        elif typ == "w":
            lat, lon = centroid(geom)
        else:
            lat, lon = geom
        name, langs, alts = name_variants(tags)
        hn = housenumber(tags)
        street = (tags.get("addr:street") or tags.get("addr:place") or "").strip()[:150]
        if hn and street:
            self.add(G.K_ADDRESS, osm, None, None, None, "place", "house", lat, lon, IMP_ADDRESS, street, hn,
                     (tags.get("addr:postcode") or "").replace(" ", "")[:10],
                     (tags.get("addr:city") or "").strip()[:150], (tags.get("addr:suburb") or "").strip()[:150])
        if not name:
            return
        place = tags.get("place")
        # obce jako plochy (cesty) maji skoro vzdy i bod mista; plochy mestskych casti a osad se hodi
        if place in PLACE_IMP and (typ != "w" or place not in ("city", "town", "village")):
            imp = PLACE_IMP[place]
            try:
                pop = float(re.sub(r"[ ,.]", "", tags.get("population", "")) or 0)
            except ValueError:
                pop = 0
            imp += min(0.08, math.log10(pop + 1) / 80)
            if tags.get("capital") in ("yes", "2"):
                imp += 0.04
            if typ == "n":
                imp += 0.005             # bod mista pred plochou se stejnym jmenem
            self.add(G.K_CITY, osm, name, langs, alts, "place", place, lat, lon, imp)
            return
        st, imp = stop_tag(tags)
        if st and tags.get("disused") != "yes":
            self.add(G.K_STOP, osm, name, langs, alts, st[0], st[1], lat, lon, imp)
            return
        hw = tags.get("highway")
        if typ == "w" and (hw in STREET_HW or place == "square"):
            if hw in STREET_MINOR and not name:
                return
            key, val = ("highway", hw) if hw in STREET_HW else ("place", "square")
            # ulice: jedna radka za usek; slouceni podle jmena a obce az v merge_streets
            self.street_pts.append((name, osm, key, val, langs, alts, geom[0], geom[-1], centroid(geom),
                                    hw in STREET_MINOR))
            return
        pt = poi_tag(tags)
        if pt:
            imp = IMP_POI + POI_BONUS.get(pt, 0) + (0.06 if tags.get("wikidata") else 0) \
                + (0.02 if tags.get("website") or tags.get("contact:website") else 0)
            if pt[0] == "shop":
                imp -= 0.02
            self.add(G.K_POI, osm, name, langs, alts, pt[0], pt[1], lat, lon, imp, street, hn,
                     "", (tags.get("addr:city") or "").strip()[:150])

    def area(self, oid, tags, rings):
        if tags.get("boundary") != "administrative":
            return
        try:
            level = int(tags.get("admin_level", "0"))
        except ValueError:
            return
        if level not in ADMIN_LEVELS:
            return
        if level == 2:
            code = (tags.get("ISO3166-1") or tags.get("ISO3166-1:alpha2") or "").upper()
            if code not in COUNTRY_LEVELS:
                return
            val = self.name_id("#" + code)
        else:
            name = (tags.get("name") or "").strip()
            if not name:
                return
            val = self.name_id(name)
        self.raster.fill(level, rings, val)
        self.count[f"boundary {level}"] += 1


def stage_file(db, path, work, names, street_pts, reader=None):
    is_xml = reader == "xml" or (reader is None and path.endswith((".osm", ".xml")))
    bbox, ts = xml_bbox(path) if is_xml else pbf_bbox(path)
    raster = Raster(*bbox)
    col = Collector(db, raster, names)
    col.street_pts = street_pts
    n = 0
    t0 = time.time()
    for el in (read_xml(path) if is_xml else read_pbf(path, work)):
        col.element(*el)
        n += 1
        if n % 1000000 == 0:
            log(f"  {n} objects, {dict(col.count)}")
    col.flush()
    db.commit()
    log(f"{os.path.basename(path)}: {n} objects in {time.time() - t0:.0f} s, {dict(col.count)}")
    return raster, ts


def geo_lookup(raster, names_by_id):
    """-> funkce (lat, lon) -> (stat, kraj, obec, cast) jako id nazvu (0 = nic)."""
    codes = {i: n[1:] for i, n in names_by_id.items() if n.startswith("#")}

    def look(lat, lon):
        c = raster.get(2, lat, lon)
        cc = codes.get(c)
        if not cc:
            return None
        reg, muni, part = COUNTRY_LEVELS[cc]
        return (c, raster.get(reg, lat, lon), raster.get(muni, lat, lon), raster.get(part, lat, lon, near=False))
    return look


def pack(g):
    """(stat, kraj, obec, cast) -> (cislo pro sloupec g, cislo casti obce); mimo pokryti -> (-1, 0)."""
    if not g:
        return -1, 0
    return g[0] | (g[1] << 20) | (g[2] << 40), g[3]


def unpack(v):
    return v & 0xFFFFF, (v >> 20) & 0xFFFFF, (v >> 40) & 0xFFFFF


# ---- slouceni ------------------------------------------------------------------------------------
def cluster(items, dist_km, key=lambda it: (it[0], it[1])):
    """Hladove shlukovani bodu (seznam se zachovanym poradim); polozka se prida k prvnimu shluku,
    jehoz nektery bod je bliz nez dist_km."""
    groups = []
    for it in items:
        lat, lon = key(it)
        for g in groups:
            if any(G.distance_km(lat, lon, *key(o)) < dist_km for o in g[-50:]):
                g.append(it)
                break
        else:
            groups.append([it])
    return groups


def build(inputs, output, work, reader=None):
    """reader: None = podle pripony (.osm/.xml standardni knihovnou, jinak pyosmium), "osmium", "xml"."""
    os.makedirs(work, exist_ok=True)
    stage_path = os.path.join(work, "stage.sqlite")
    for p in (stage_path, output + ".tmp"):
        if os.path.exists(p):
            os.unlink(p)
    os.environ["SQLITE_TMPDIR"] = work
    db = sqlite3.connect(stage_path)
    db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-200000;"
                     "PRAGMA temp_store=FILE;" + STAGE_SQL)
    names = {}                    # nazev hranice -> id (spolecne pro vsechny vstupy)
    street_pts = []
    stamps = []
    names_by_id = {}
    for path in inputs:
        before = len(street_pts)
        raster, ts = stage_file(db, path, work, names, street_pts, reader)
        stamps.append(ts)
        names_by_id = {i: n for n, i in names.items()}
        look = geo_lookup(raster, names_by_id)
        db.create_function("geo", 2, lambda lat, lon: pack(look(lat, lon))[0], deterministic=True)
        db.create_function("geopart", 2, lambda lat, lon: pack(look(lat, lon))[1], deterministic=True)
        db.execute("UPDATE stage SET g = geo(lat, lon), part = geopart(lat, lon) WHERE g IS NULL")
        # ulice tohoto vstupu: stat/obec podle mrizky tohoto vstupu
        for i in range(before, len(street_pts)):
            sp = street_pts[i]
            street_pts[i] = sp + pack(look(*sp[8]))
        db.commit()
        del raster
    log("stage done:", db.execute("SELECT count(*) FROM stage WHERE g > 0").fetchone()[0], "features inside,",
        db.execute("SELECT count(*) FROM stage WHERE g <= 0").fetchone()[0], "outside")
    finish(db, output, names_by_id, street_pts, stamps)
    db.close()
    os.unlink(stage_path)


class Writer:
    """Konecna databaze: feat (radky podle dulezitosti) + fts + str + tag + meta."""

    def __init__(self, path, names_by_id):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA page_size=4096; PRAGMA cache_size=-200000;
            CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;
            CREATE TABLE str(id INTEGER PRIMARY KEY, v TEXT);
            CREATE TABLE tag(id INTEGER PRIMARY KEY, k TEXT, v TEXT);
            CREATE TABLE feat(id INTEGER PRIMARY KEY, kind INT, name TEXT, names TEXT, alt TEXT, street INT,
                              hn TEXT, postcode TEXT, city INT, district INT, region INT, country TEXT,
                              lat INT, lon INT, osm INT, tag INT, imp INT);
            CREATE TABLE tmp(kind INT, name TEXT, names TEXT, alt TEXT, street INT, hn TEXT, postcode TEXT,
                             city INT, district INT, region INT, country TEXT, lat INT, lon INT, osm INT,
                             tag INT, imp INT, text TEXT);
        """)
        self.strs, self.tags = {}, {}
        self.names_by_id = names_by_id
        self.buf = []

    def s(self, v):
        if not v:
            return None
        i = self.strs.get(v)
        if i is None:
            i = self.strs[v] = len(self.strs) + 1
        return i

    def tag(self, k, v):
        i = self.tags.get((k, v))
        if i is None:
            i = self.tags[(k, v)] = len(self.tags) + 1
        return i

    def add(self, kind, osm, name, names, alt, okey, oval, lat, lon, imp, g, street="", hn="", postcode="",
            city="", district=""):
        c, reg, muni = unpack(g)
        nb = self.names_by_id
        country = nb.get(c, "#")[1:]
        region = nb.get(reg, "")
        muni_name = nb.get(muni, "")
        city = city or (muni_name if kind != G.K_CITY else "")
        district = district if kind != G.K_CITY else ""
        if district == city or (kind == G.K_CITY and district == name):
            district = ""
        alt_f = None
        if alt:
            fn = G.fold(name or "")
            vs = []
            for v in alt.split("|"):
                fv = G.fold(v)
                if fv != fn and fv not in vs:
                    vs.append(fv)
            alt_f = "|".join(vs) or None
        words = [name or "", alt or "", street or "", hn or "", city, district]
        if kind == G.K_CITY:
            words = [name or "", alt or ""]
        r, cc = G.cell_of(lat, lon)
        text = " ".join(G.tokens(" ".join(words))) + " " + G.cell_token(r, cc)
        self.buf.append((kind, name, names, alt_f, self.s(street), hn or None, postcode or None, self.s(city),
                         self.s(district), self.s(region), country or None, round(lat * 1e6), round(lon * 1e6),
                         osm, self.tag(okey, oval), int(round(max(0.0, min(1.0, imp)) * 1000)), text))
        if len(self.buf) >= 50000:
            self.flush()

    def flush(self):
        self.db.executemany("INSERT INTO tmp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self.buf)
        self.buf = []

    def finish(self, meta):
        self.flush()
        db = self.db
        db.executemany("INSERT INTO str VALUES (?, ?)", [(i, v) for v, i in self.strs.items()])
        db.executemany("INSERT INTO tag VALUES (?, ?, ?)", [(i, k, v) for (k, v), i in self.tags.items()])
        log("sorting by importance")
        db.execute("""INSERT INTO feat(kind, name, names, alt, street, hn, postcode, city, district, region, country,
                                       lat, lon, osm, tag, imp)
                      SELECT kind, name, names, alt, street, hn, postcode, city, district, region, country,
                             lat, lon, osm, tag, imp FROM tmp ORDER BY imp DESC, kind, rowid""")
        log("full-text index")
        db.execute("CREATE VIRTUAL TABLE fts USING fts5(t, content='', detail=none, columnsize=0, "
                   "tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')")
        # feat.id = 1..n ve stejnem poradi (prazdna tabulka), takze rowid fts = id feat
        db.execute("INSERT INTO fts(rowid, t) SELECT row_number() OVER (ORDER BY imp DESC, kind, rowid), text "
                   "FROM tmp")
        db.execute("DROP TABLE tmp")
        db.execute("INSERT INTO fts(fts) VALUES('optimize')")
        n = db.execute("SELECT count(*) FROM feat").fetchone()[0]
        meta = dict(meta, features=str(n), schema="1")
        db.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
        db.commit()
        log("vacuum")
        db.execute("VACUUM")
        db.close()
        return n


def finish(stage, output, names_by_id, street_pts, stamps):
    tmp = output + ".tmp"
    w = Writer(tmp, names_by_id)
    counts = collections.Counter()
    # 1) mista, POI, adresy rovnou (mista: duplicitni bod/plocha stejneho jmena do 3 km -> jedno)
    seen_places = collections.defaultdict(list)
    for row in stage.execute("SELECT kind, osm, name, names, alt, okey, oval, street, hn, postcode, acity, asub, "
                             "lat, lon, imp, g, part FROM stage WHERE g > 0 AND kind IN (0, 3, 4) "
                             "ORDER BY kind, imp DESC"):
        kind, osm, name, names, alt, okey, oval, street, hn, postcode, acity, asub, lat, lon, imp, g, prt = row
        if kind == G.K_CITY:
            key = G.fold(name)
            if any(G.distance_km(lat, lon, a, b) < 5 for a, b in seen_places[key]):
                continue
            seen_places[key].append((lat, lon))
        w.add(kind, osm, name, names, alt, okey, oval, lat, lon, imp, g, street, hn, postcode,
              acity if kind in (G.K_ADDRESS, G.K_POI) else "", asub or names_by_id.get(prt, ""))
        counts[G.KINDS[kind]] += 1
    log("places/pois/addresses:", dict(counts))
    # 2) zastavky: stejne jmeno v obci a do 700 m od sebe -> jedna (nastupiste, sloupky, stanice)
    groups = collections.defaultdict(list)
    for row in stage.execute("SELECT name, names, alt, okey, oval, lat, lon, imp, g, osm, part FROM stage "
                             "WHERE g > 0 AND kind = 1 ORDER BY imp DESC, osm"):
        groups[(G.fold(row[0]), unpack(row[8])[2])].append(row)
    for _k, rows in groups.items():
        for grp in cluster(rows, 0.7, key=lambda r: (r[5], r[6])):
            best = grp[0]
            name, names, alt, okey, oval, lat, lon, imp, g, osm, prt = best
            imp = min(0.75, imp + 0.02 * math.log2(len(grp)))
            w.add(G.K_STOP, osm, name, names, alt, okey, oval, lat, lon, imp, g, district=names_by_id.get(prt, ""))
            counts["stop"] += 1
    log("stops:", counts["stop"])
    # 3) ulice: useky se stejnym jmenem v obci, ktere na sebe navazuji (do 1,5 km) -> jedna ulice
    groups = collections.defaultdict(list)
    for sp in street_pts:
        if sp[10] > 0:
            groups[(sp[0], unpack(sp[10])[2])].append(sp)
    street_pts.clear()
    for (name, _muni), segs in groups.items():
        segs.sort(key=lambda s: (s[9], s[1]))              # hlavni silnice pred cestami a chodniky
        for grp in cluster(segs, 1.5, key=lambda s: s[8]):
            lat = sum(s[8][0] for s in grp) / len(grp)
            lon = sum(s[8][1] for s in grp) / len(grp)
            rep = min(grp, key=lambda s: G.distance_km(lat, lon, *s[8]))
            minor = all(s[9] for s in grp)
            imp = IMP_STREET - (0.05 if minor else 0) + min(0.06, 0.012 * math.log2(len(grp)))
            w.add(G.K_STREET, rep[1], name, json.dumps(rep[4], ensure_ascii=False) if rep[4] else None,
                  "|".join(rep[5]) or None, rep[2], rep[3], rep[8][0], rep[8][1], imp, rep[10],
                  district=names_by_id.get(rep[11], ""))
            counts["street"] += 1
    log("streets:", counts["street"])
    meta = {"built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": max(stamps) if stamps and any(stamps) else "",
            "countries": ",".join(sorted(COUNTRY_LEVELS)),
            "attribution": "© OpenStreetMap contributors, ODbL"}
    n = w.finish(meta)
    os.replace(tmp, output)
    log(f"done: {n} features, {os.path.getsize(output) / 1e6:.0f} MB -> {output}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+", help=".osm.pbf (Geofabrik) or small .osm XML files")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--work", help="directory for large temporary files (default: next to the output)")
    a = ap.parse_args(argv)
    build(a.inputs, os.path.abspath(a.output), os.path.abspath(a.work or os.path.dirname(os.path.abspath(a.output))))


if __name__ == "__main__":
    main()
