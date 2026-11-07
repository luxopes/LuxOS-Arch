"""Vygenerovane dlazdice mapy pro snimky (skupina b): Mapy, pripadne dalsi aplikace s mapou.

Zadna skutecna sluzba dlazdic ani mezipamet uzivatele: mapa se kresli z deterministicky nahodne
"mestske" site bloku ve stylu OpenStreetMap (pozadi, bloky domu, parky, reka, hlavni silnice).
Skutecne geometrie tras z testovacich dat (packages/luxos-maps/tests/fixtures) se kresli jako ulice,
aby trasa vedla po silnici a pres reku po moste.

    tiles = MapTiles(roads=[[(lat, lon), ...], ...])
    png = tiles.render(z, x, y)
"""
import io
import math
import random

TILE = 256
BG = (0.949, 0.937, 0.914)          # #f2efe9
RESIDENTIAL = (0.878, 0.875, 0.875)  # #e0dfdf
BUILDING = (0.851, 0.816, 0.788)     # #d9d0c9
BUILDING_EDGE = (0.776, 0.733, 0.698)
PARK = (0.804, 0.922, 0.690)         # #cdebb0
PARK_EDGE = (0.698, 0.851, 0.584)
WATER = (0.667, 0.827, 0.875)        # #aad3df
ROAD = (1, 1, 1)
ROAD_CASE = (0.80, 0.78, 0.76)
MAIN = (0.988, 0.839, 0.643)         # #fcd6a4
MAIN_CASE = (0.80, 0.62, 0.40)

# Vltava v Praze (priblizne, jih -> sever -> vychod)
RIVER = [(50.052, 14.4150), (50.060, 14.4142), (50.066, 14.4130), (50.0705, 14.4122), (50.0745, 14.4125),
         (50.0790, 14.4118), (50.0830, 14.4110), (50.0865, 14.4112), (50.0895, 14.4135), (50.0922, 14.4160),
         (50.0942, 14.4205), (50.0952, 14.4265), (50.0958, 14.4330), (50.0968, 14.4395), (50.0995, 14.4460),
         (50.1040, 14.4530), (50.1090, 14.4580)]
RIVER_WIDTH = 210.0  # m
# velke parky (stred, polomer v m): Letna, Petrin, Riegrovy sady, Vysehrad
PARKS = [((50.0985, 14.4210), 520), ((50.0830, 14.3950), 600), ((50.0785, 14.4440), 300),
         ((50.0645, 14.4185), 280)]

LAT0, LON0 = 50.050, 14.360           # oblast mesta
ROWS, COLS = 70, 80
DLAT, DLON = 0.00095, 0.00130         # ~105 x 93 m


def world(lat, lon, z):
    n = TILE * 2 ** z
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def metres_per_px(lat, z):
    return 156543.03 * math.cos(math.radians(lat)) / 2 ** z


def _dist_m(p, a, b):
    """Vzdalenost bodu p od usecky ab v metrech (lat, lon)."""
    ky, kx = 111320.0, 111320.0 * math.cos(math.radians(p[0]))
    px, py = p[1] * kx, p[0] * ky
    ax, ay, bx, by = a[1] * kx, a[0] * ky, b[1] * kx, b[0] * ky
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def river_dist(p):
    return min(_dist_m(p, RIVER[i], RIVER[i + 1]) for i in range(len(RIVER) - 1))


class MapTiles:
    def __init__(self, roads=(), seed=7):
        rnd = random.Random(seed)
        # rohy bloku: zkosena mrizka s nahodnym posunem (spolecne rohy -> ulice mezi bloky)
        corner = {}
        for i in range(ROWS + 1):
            for j in range(COLS + 1):
                jl = rnd.uniform(-0.22, 0.22)
                jo = rnd.uniform(-0.22, 0.22)
                lat = LAT0 + (i + jl) * DLAT + j * DLAT * 0.18
                lon = LON0 + (j + jo) * DLON - i * DLON * 0.12
                corner[i, j] = (lat, lon)
        self.blocks = []        # (druh, [rohy], [domy])
        for i in range(ROWS):
            for j in range(COLS):
                quad = [corner[i, j], corner[i, j + 1], corner[i + 1, j + 1], corner[i + 1, j]]
                c = (sum(p[0] for p in quad) / 4, sum(p[1] for p in quad) / 4)
                if river_dist(c) < RIVER_WIDTH / 2 + 70:
                    continue
                r = rnd.random()
                in_park = any(_dist_m(c, pc, pc) < rad for pc, rad in PARKS)
                kind = "park" if in_park or r < 0.04 else ("empty" if r < 0.07 else "block")
                houses = []
                if kind == "block":
                    # blok domu s dvorem uprostred (jako bloky v centru mesta)
                    k = rnd.uniform(0.38, 0.6)
                    houses = [(c[0] + (p[0] - c[0]) * k, c[1] + (p[1] - c[1]) * k) for p in quad]
                lats = [p[0] for p in quad]
                lons = [p[1] for p in quad]
                self.blocks.append((kind, quad, houses, (min(lats), max(lats), min(lons), max(lons))))
        # hlavni ulice: kazda 6. rada a 7. sloupec mrizky (bez useku pres reku)
        self.mains = []
        for i in range(3, ROWS, 6):
            self._line([corner[i, j] for j in range(COLS + 1)])
        for j in range(4, COLS, 7):
            self._line([corner[i, j] for i in range(ROWS + 1)])
        self.roads = [list(r) for r in roads]

    def _line(self, pts):
        cur = []
        for a, b in zip(pts, pts[1:]):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if river_dist(mid) < RIVER_WIDTH / 2 + 60:
                if len(cur) > 1:
                    self.mains.append(cur)
                cur = []
                continue
            if not cur:
                cur = [a]
            cur.append(b)
        if len(cur) > 1:
            self.mains.append(cur)

    def render(self, z, x, y):
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, TILE, TILE)
        cr = cairo.Context(surf)
        cr.set_source_rgb(*BG)
        cr.paint()
        ox, oy = x * TILE, y * TILE
        n = TILE * 2 ** z
        lon_w = ox / n * 360 - 180
        lon_e = (ox + TILE) / n * 360 - 180

        def lat_of(py):
            return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / n))))
        lat_n, lat_s = lat_of(oy), lat_of(oy + TILE)
        mlat, mlon = (lat_n - lat_s) * 0.2, (lon_e - lon_w) * 0.2
        mpp = metres_per_px((lat_n + lat_s) / 2, z)

        def path(pts, close=False):
            for k, (la, lo) in enumerate(pts):
                px, py = world(la, lo, z)
                (cr.line_to if k else cr.move_to)(px - ox, py - oy)
            if close:
                cr.close_path()

        street = max(0.0, 9.0 / mpp)          # sirka ulice mezi bloky v px
        if z >= 12:
            for kind, quad, houses, (s, nn, w, e) in self.blocks:
                if nn < lat_s - mlat or s > lat_n + mlat or e < lon_w - mlon or w > lon_e + mlon:
                    continue
                path(quad, True)
                if kind == "park":
                    cr.set_source_rgb(*PARK)
                    cr.fill_preserve()
                    cr.set_source_rgb(*PARK_EDGE)
                    cr.set_line_width(1)
                    cr.stroke()
                elif kind == "block":
                    cr.set_source_rgb(*RESIDENTIAL)
                    cr.fill()
                    if z >= 15:
                        path(quad, True)
                        cr.set_source_rgb(*BUILDING)
                        cr.fill_preserve()
                        cr.set_source_rgb(*BUILDING_EDGE)
                        cr.set_line_width(0.8)
                        cr.stroke()
                        path(houses, True)
                        cr.set_source_rgb(*RESIDENTIAL)
                        cr.fill_preserve()
                        cr.set_source_rgb(*BUILDING_EDGE)
                        cr.stroke()
                else:
                    cr.new_path()
            # ulice mezi bloky (obrys bloku barvou pozadi -> jednotna sirka)
            if street >= 1:
                cr.set_line_join(1)
                for kind, quad, houses, (s, nn, w, e) in self.blocks:
                    if nn < lat_s - mlat or s > lat_n + mlat or e < lon_w - mlon or w > lon_e + mlon:
                        continue
                    path(quad, True)
                cr.set_source_rgb(*ROAD)
                cr.set_line_width(street)
                cr.stroke()
                # parky bez ulic uvnitr
                for kind, quad, houses, (s, nn, w, e) in self.blocks:
                    if kind != "park" or nn < lat_s - mlat or s > lat_n + mlat or e < lon_w - mlon \
                            or w > lon_e + mlon:
                        continue
                    path(quad, True)
                cr.set_source_rgb(*PARK)
                cr.fill_preserve()
                cr.set_line_width(street)
                cr.stroke()
        # reka
        path(RIVER)
        cr.set_source_rgb(*WATER)
        cr.set_line_width(max(2.0, RIVER_WIDTH / mpp))
        cr.set_line_cap(1)
        cr.set_line_join(1)
        cr.stroke()
        # hlavni ulice a ulice tras (s okrajem)
        if z >= 11:
            width = max(1.5, 16.0 / mpp)
            for lines, fill, case in ((self.mains, MAIN, MAIN_CASE), (self.roads, MAIN, MAIN_CASE)):
                for pts in lines:
                    path(pts)
                    cr.set_source_rgb(*case)
                    cr.set_line_width(width + 2)
                    cr.stroke()
                for pts in lines:
                    path(pts)
                    cr.set_source_rgb(*fill)
                    cr.set_line_width(width)
                    cr.stroke()
        buf = io.BytesIO()
        surf.write_to_png(buf)
        return buf.getvalue()
