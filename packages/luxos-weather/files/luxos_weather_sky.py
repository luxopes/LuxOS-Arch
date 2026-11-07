"""LuxOS Pocasi - kreslene pozadi okna podle pocasi a denni doby (vlastni grafika, zadne obrazky).

  palette(kind, tod, dark)   tri barvy oblohy shora dolu, ztmavene tak, aby bily text byl citelny
  Sky                        scena: set_scene(scene, dark), set_motion(bool), advance(dt), draw(cr, w, h)
                             fps() = kolik snimku za sekundu scena potrebuje (0 = staticka)

Vse se kresli procedurne v cairo: gradient oblohy, slunce, mesic (podle skutecne faze), hvezdy,
mraky, mlha, dest, snih a blesky. Usporne: staticka cast (obloha, slunce/mesic, hvezdy) se kresli
jednou do pomocneho povrchu, mraky a mlha jsou predkreslene sprity, ktere se za snimek jen posunou,
dest a snih jsou jedna cesta na vrstvu. Animace jen tam, kde se neco hybe (jasny den je staticky).
Scena se meni plynule (prolnuti 0,8 s).
"""
import math
import random

import cairo

TAU = 2 * math.pi
TEXT_CONTRAST = 3.3         # minimalni kontrast bileho textu proti kazde barve oblohy (WCAG)
REF_AREA = 900 * 680        # pocty castic jsou pro okno teto velikosti, jinak umerne plose
FADE = 0.8                  # prolnuti pri zmene sceny (s)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def mix(a, b, k):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def luminance(rgb):
    """Relativni jas podle WCAG 2 (sRGB)."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_white(rgb):
    return 1.05 / (luminance(rgb) + 0.05)


def darken_to(rgb, target=TEXT_CONTRAST):
    """Ztmavi barvu (zachova odstin) jen tolik, aby kontrast s bilou byl aspon target."""
    if contrast_white(rgb) >= target:
        return tuple(rgb)
    lo, hi = 0.0, 1.0
    for _i in range(24):
        mid = (lo + hi) / 2
        if contrast_white(tuple(c * mid for c in rgb)) >= target:
            lo = mid
        else:
            hi = mid
    return tuple(c * lo for c in rgb)


# Jasna obloha a zatazena obloha pro kazdou denni dobu (shora, uprostred, u obzoru)
CLEAR = {
    "day": ("#1c5fd4", "#3f88e6", "#7db9f2"),
    "night": ("#040a1d", "#0b1736", "#1c2f5e"),
    "dawn": ("#28447f", "#8f6fa3", "#f0a97c"),
    "dusk": ("#1c2052", "#7f4a7a", "#ec8156"),
}
OVERCAST = {
    "day": ("#53637a", "#718096", "#97a5b7"),
    "night": ("#10141c", "#1a202b", "#2f3747"),
    "dawn": ("#474e6d", "#76697d", "#a98d84"),
    "dusk": ("#38395a", "#64546a", "#97746d"),
}
CLOUDINESS = {"clear": 0.0, "partly": 0.18, "cloudy": 0.8, "fog": 0.92, "drizzle": 0.72,
              "rain": 0.86, "storm": 1.0, "snow": 0.68}
SHADE = {"storm": -0.3, "rain": -0.1, "drizzle": -0.04, "snow": 0.14, "fog": 0.16}
NONE = ("#3d5b84", "#56759d", "#7a94b6")     # bez dat (nacitani, chyba)


def palette(kind, tod, dark=False):
    """Barvy oblohy pro druh pocasi a denni dobu; tmavy vzhled o neco tlumi denni oblohu."""
    if kind is None:
        stops = [hex_rgb(c) for c in NONE]
    else:
        stops = []
        for c, o in zip(CLEAR[tod], OVERCAST[tod]):
            rgb = mix(hex_rgb(c), hex_rgb(o), CLOUDINESS[kind])
            sh = SHADE.get(kind, 0.0)
            rgb = mix(rgb, (0, 0, 0), -sh) if sh < 0 else mix(rgb, (0.84, 0.88, 0.94), sh)
            stops.append(rgb)
    if dark and tod != "night":
        stops = [tuple(v * 0.8 for v in rgb) for rgb in stops]
    return [darken_to(rgb) for rgb in stops]


def moon_phase(epoch):
    """Faze mesice 0..1 (0 nov, 0,5 uplnek) podle synodickeho mesice od novu 6. 1. 2000 18:14 UTC."""
    return ((epoch - 947182440) / 86400 / 29.530588853) % 1.0


class _Layer:
    """Castice jedne vrstvy (dest, snih, hvezdy) - jednoduche seznamy, zadne objekty na castici."""

    def __init__(self):
        self.items = []


class Sky:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.kind = None
        self.tod = "day"
        self.intensity = 0.0
        self.dark = False
        self.motion = True
        self.scale = 1
        self.w = self.h = 0
        self.t = 0.0
        self.epoch = None           # cas pro fazi mesice (None = ted)
        self._bg = None             # staticka cast sceny (povrch)
        self._sprites = None        # mraky a mlha
        self._old = None            # snimek predchozi sceny pro prolnuti
        self._fade = 0.0
        self.clouds = []
        self.fog = []
        self.rain = []
        self.snow = []
        self.stars = []
        self.twinkle = []
        self.flash_at = 0.0
        self.flash_t = None
        self.bolt = None

    # ---- nastaveni ----
    def name(self):
        return f"{self.kind}-{self.tod}" if self.kind else "none"

    def set_scene(self, scene, dark=False, fade=True):
        """scene = luxos_weather.scene(...) nebo None (bez dat). Vraci True, kdyz se scena zmenila."""
        kind = scene["kind"] if scene else None
        tod = scene["time"] if scene else "day"
        intensity = float(scene.get("intensity", 0.5)) if scene else 0.0
        if (kind, tod, round(intensity, 2), dark) == (self.kind, self.tod, round(self.intensity, 2), self.dark):
            return False
        self._old = self._snapshot() if fade and self._bg is not None else None
        self._fade = FADE if self._old is not None else 0.0
        self.kind, self.tod, self.intensity, self.dark = kind, tod, intensity, dark
        self._rebuild()
        return True

    def finish_fade(self):
        """Ukonci rozjete prolnuti (okno prestalo byt videt). Vraci True, kdyz nejake bezelo."""
        running = self._fade > 0
        self._fade, self._old = 0.0, None
        return running

    def set_motion(self, on):
        self.motion = bool(on)

    def fps(self):
        """Snimky za sekundu, ktere scena potrebuje; 0 = nic se nehybe (staticka scena)."""
        if self._fade > 0:
            return 30
        if not self.motion or self.kind is None:
            return 0
        if self.kind in ("rain", "storm"):
            return 30               # rychle kapky potrebuji plynuly pohyb
        if self.kind == "drizzle":
            return 24
        if self.kind == "snow":
            return 20               # vlocky padaji pomalu (20-75 px/s), 20 snimku staci
        if self.kind in ("partly", "cloudy", "fog"):
            return 15
        if self.kind == "clear" and self.tod == "night":
            return 8                # jen mrkajici hvezdy
        return 0

    def resize(self, w, h, scale=1):
        w, h = max(1, int(w)), max(1, int(h))
        if (w, h, scale) != (self.w, self.h, self.scale):
            self.w, self.h, self.scale = w, h, scale
            self._rebuild()

    # ---- castice ----
    def _count(self, base):
        return max(0, int(base * self.w * self.h / REF_AREA))

    def _rebuild(self):
        self._bg = None
        self._sprites = None
        r = self.rng
        w, h, k = self.w, self.h, self.kind
        self.clouds, self.fog, self.rain, self.snow, self.stars, self.twinkle = [], [], [], [], [], []
        self.bolt, self.flash_t = None, None
        self.flash_at = self.t + r.uniform(2.5, 5.0)
        if not w or k is None:
            return
        night = self.tod == "night"
        if night and k in ("clear", "partly"):
            n = self._count(110 if k == "clear" else 50)
            for _i in range(n):
                y = r.random() ** 1.4 * h * 0.72     # vic hvezd nahore
                self.stars.append((r.uniform(0, w), y, r.uniform(0.45, 1.25), r.uniform(0.35, 0.95)))
            for _i in range(max(1, n // 5)):
                self.twinkle.append([r.uniform(0, w), r.random() ** 1.4 * h * 0.72, r.uniform(0.7, 1.4),
                                     r.uniform(0, TAU), r.uniform(0.8, 2.2)])
        ncloud = {"partly": 2 + round(3 * self.intensity), "cloudy": 9, "drizzle": 6, "rain": 6, "storm": 7,
                  "snow": 5}.get(k, 0)
        if k == "clear" and self.tod in ("dawn", "dusk"):
            ncloud = 2                                  # tenke obl. pruhy v barvach usvitu
        for i in range(ncloud):
            near = i >= ncloud // 2
            self.clouds.append({
                "sprite": i % 4, "x": r.uniform(-0.3 * w, w), "y": r.uniform(-0.06, 0.42 if near else 0.3) * h,
                "speed": r.uniform(7, 14) if near else r.uniform(3, 7), "near": near,
                "scale": r.uniform(0.85, 1.25) if near else r.uniform(0.55, 0.8)})
        self.clouds.sort(key=lambda c: c["near"])
        if k == "fog":
            for i, y in enumerate((0.18, 0.42, 0.64, 0.84)):
                self.fog.append({"y": y * h, "x": r.uniform(0, w), "speed": (6 + 3 * i) * (1 if i % 2 else -1),
                                 "sprite": i % 2})
        if k in ("rain", "storm", "drizzle"):
            base = (110 if k == "drizzle" else 170) * (0.5 + self.intensity)
            for _i in range(min(420, self._count(base))):
                near = r.random() < 0.45
                if k == "drizzle":
                    length, speed = r.uniform(5, 9), r.uniform(260, 380) * (1.25 if near else 1.0)
                else:
                    length = r.uniform(14, 24) if near else r.uniform(8, 14)
                    speed = r.uniform(900, 1150) if near else r.uniform(600, 780)
                self.rain.append([r.uniform(0, w), r.uniform(0, h), length, speed, near])
        if k == "snow":
            for _i in range(min(360, self._count(150 * (0.5 + self.intensity)))):
                near = r.random() < 0.4
                self.snow.append([r.uniform(0, w), r.uniform(0, h), r.uniform(1.9, 3.2) if near else r.uniform(0.9, 1.8),
                                  r.uniform(45, 75) if near else r.uniform(20, 40), r.uniform(0, TAU),
                                  r.uniform(0.3, 0.8), r.uniform(6, 18), near])

    def advance(self, dt):
        """Posune scenu o dt sekund (dt omezeno: po pauze se nic neprohoupne)."""
        dt = max(0.0, min(float(dt), 0.25))
        self.t += dt
        if self._fade > 0:
            self._fade = max(0.0, self._fade - dt)
            if self._fade == 0:
                self._old = None
        if not self.motion:
            return
        w, h = self.w, self.h
        for c in self.clouds:
            c["x"] += c["speed"] * dt
            if c["x"] > w + 20:
                c["x"] = -min(w * 0.55, 520) * 1.2 * c["scale"] - 20
        for f in self.fog:
            f["x"] = (f["x"] + f["speed"] * dt) % max(1, w)
        slant = 0.18 if self.kind == "storm" else 0.08
        for d in self.rain:
            d[1] += d[3] * dt
            d[0] += d[3] * dt * slant
            if d[1] > h:
                d[1] -= h + d[2]
                d[0] = self.rng.uniform(-0.1 * w, w)
        for s in self.snow:
            s[1] += s[3] * dt
            s[4] += s[5] * dt
            if s[1] > h + 4:
                s[1] = -4
                s[0] = self.rng.uniform(0, w)
        if self.kind == "storm":
            if self.flash_t is None and self.t >= self.flash_at:
                self.flash_t = self.t
                self.bolt = self._make_bolt()
                self.flash_at = self.t + self.rng.uniform(5.0, 11.0)
            elif self.flash_t is not None and self.t - self.flash_t > 0.7:
                self.flash_t, self.bolt = None, None

    def _make_bolt(self):
        r, w, h = self.rng, self.w, self.h
        x, y = r.uniform(0.15, 0.85) * w, 0.0
        pts = [(x, y)]
        end = r.uniform(0.45, 0.7) * h
        while y < end:
            y += r.uniform(0.03, 0.07) * h
            x += r.uniform(-0.035, 0.035) * w
            pts.append((x, y))
        return pts

    def flash_alpha(self):
        """Jas zablesku 0..1 (jeden zablesk + slabsi ozvena, nejvys 2 za sekundu, nic bez pohybu)."""
        if self.flash_t is None or not self.motion:
            return 0.0
        a = self.t - self.flash_t
        if a < 0.07:
            return 1.0
        if a < 0.15:
            return 0.25
        if a < 0.24:
            return 0.75
        return max(0.0, 0.75 * math.exp(-(a - 0.24) * 9))

    # ---- kresleni ----
    def _surface(self, target, w, h):
        try:
            s = target.create_similar(cairo.CONTENT_COLOR_ALPHA, int(math.ceil(w)), int(math.ceil(h)))
        except (cairo.Error, AttributeError):
            s = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(math.ceil(w)), int(math.ceil(h)))
        return s

    def _draw_static(self, cr):
        w, h = self.w, self.h
        stops = palette(self.kind, self.tod, self.dark)
        g = cairo.LinearGradient(0, 0, 0, h)
        for pos, c in zip((0.0, 0.55, 1.0), stops):
            g.add_color_stop_rgb(pos, *c)
        cr.set_source(g)
        cr.paint()
        k, tod = self.kind, self.tod
        if k is None:
            return
        m = min(w, h)
        if tod in ("dawn", "dusk") and k in ("clear", "partly", "cloudy"):
            # zare u obzoru: teple svetlo zespodu (pri zatazeni slabsi)
            a = {"clear": 0.4, "partly": 0.32}.get(k, 0.14)
            cx = w * (0.25 if tod == "dawn" else 0.75)
            glow = cairo.RadialGradient(cx, h * 1.08, 0, cx, h * 1.08, max(w, h) * 0.85)
            glow.add_color_stop_rgba(0, 1.0, 0.74, 0.46, a)
            glow.add_color_stop_rgba(0.5, 1.0, 0.6, 0.45, a * 0.4)
            glow.add_color_stop_rgba(1, 1.0, 0.55, 0.45, 0)
            cr.set_source(glow)
            cr.paint()
        if tod == "day" and k in ("clear", "partly"):
            sx, sy = w * 0.8, h * 0.13
            glow = cairo.RadialGradient(sx, sy, 0, sx, sy, m * 0.75)
            glow.add_color_stop_rgba(0, 1.0, 0.97, 0.85, 0.5)
            glow.add_color_stop_rgba(0.12, 1.0, 0.95, 0.8, 0.28)
            glow.add_color_stop_rgba(0.45, 1.0, 0.95, 0.85, 0.07)
            glow.add_color_stop_rgba(1, 1.0, 1.0, 1.0, 0)
            cr.set_source(glow)
            cr.paint()
            cr.arc(sx, sy, m * 0.04, 0, TAU)
            cr.set_source_rgba(1.0, 0.98, 0.9, 0.95)
            cr.fill()
        if tod == "day" and k in ("cloudy", "drizzle", "snow", "fog"):
            # rozptylene svetlo za mraky
            glow = cairo.RadialGradient(w * 0.7, -h * 0.1, 0, w * 0.7, -h * 0.1, max(w, h) * 0.8)
            glow.add_color_stop_rgba(0, 1, 1, 1, 0.16)
            glow.add_color_stop_rgba(1, 1, 1, 1, 0)
            cr.set_source(glow)
            cr.paint()
        for x, y, r, a in self.stars:
            cr.arc(x, y, r, 0, TAU)
            cr.set_source_rgba(0.92, 0.95, 1.0, a)
            cr.fill()
        if tod == "night" and k in ("clear", "partly"):
            self._draw_moon(cr, w * 0.78, h * 0.16, m * 0.042, stops[0])

    def _draw_moon(self, cr, cx, cy, r, sky):
        import time
        phase = moon_phase(time.time() if self.epoch is None else self.epoch)
        glow = cairo.RadialGradient(cx, cy, r * 0.8, cx, cy, r * 5)
        lit = (1 - math.cos(TAU * phase)) / 2           # osvetlena cast 0..1
        glow.add_color_stop_rgba(0, 0.85, 0.9, 1.0, 0.05 + 0.18 * lit)
        glow.add_color_stop_rgba(1, 0.85, 0.9, 1.0, 0)
        cr.set_source(glow)
        cr.paint()
        cr.arc(cx, cy, r, 0, TAU)                       # popelavy svit neosvetlene casti
        cr.set_source_rgba(*mix(sky, (0.8, 0.85, 0.95), 0.22), 1)
        cr.fill()
        # osvetlena cast: polovina disku + elipsa terminatoru (dorusta vpravo, ubyva vlevo)
        k = math.cos(TAU * phase)
        right = phase < 0.5
        cr.save()
        cr.translate(cx, cy)
        cr.new_path()
        if right:
            cr.arc(0, 0, r, -math.pi / 2, math.pi / 2)
        else:
            cr.arc(0, 0, r, math.pi / 2, 3 * math.pi / 2)
        cr.save()
        cr.scale(max(abs(k), 0.001), 1)
        if right == (k > 0):        # srpek: terminator se vydouva k osvetlene strane
            if right:
                cr.arc_negative(0, 0, r, math.pi / 2, -math.pi / 2)
            else:
                cr.arc_negative(0, 0, r, 3 * math.pi / 2, math.pi / 2)
        else:                       # vic nez polovina
            if right:
                cr.arc(0, 0, r, math.pi / 2, 3 * math.pi / 2)
            else:
                cr.arc(0, 0, r, -math.pi / 2, math.pi / 2)
        cr.restore()
        cr.close_path()
        cr.set_source_rgba(0.96, 0.95, 0.88, 0.95)
        cr.fill()
        cr.restore()

    def _cloud_colors(self):
        stops = palette(self.kind, self.tod, self.dark)
        if self.tod == "night":
            top, bottom, alpha = mix(stops[1], (0.7, 0.75, 0.85), 0.28), mix(stops[0], (0.5, 0.55, 0.65), 0.2), 0.7
        elif self.kind in ("rain", "storm", "drizzle"):
            top, bottom, alpha = mix(stops[1], (0.85, 0.88, 0.92), 0.3), mix(stops[0], (0, 0, 0), 0.15), 0.72
        elif self.kind in ("clear", "partly") and self.tod in ("dawn", "dusk"):
            top, bottom, alpha = (1.0, 0.86, 0.78), mix(stops[2], (0.9, 0.5, 0.45), 0.4), 0.5
        elif self.kind == "partly":
            top, bottom, alpha = (0.97, 0.98, 1.0), mix(stops[1], (1, 1, 1), 0.45), 0.62
        else:
            top, bottom, alpha = mix(stops[2], (1, 1, 1), 0.32), mix(stops[1], (1, 1, 1), 0.08), 0.6
        return top, bottom, alpha

    def _make_cloud(self, target, cw, top, bottom, seed, flat=False, alpha=1.0):
        r = random.Random(seed)
        ch = cw * (0.28 if flat else 0.5)
        pad = cw * 0.1
        sw, sh = cw + 2 * pad, ch + 2 * pad
        s = self._surface(target, sw, sh)
        cr = cairo.Context(s)
        n = r.randint(4, 6)
        base = pad + ch * 0.82
        circles = []
        for i in range(n):
            x = pad + cw * (0.14 + 0.72 * i / (n - 1)) + r.uniform(-0.03, 0.03) * cw
            rad = cw * r.uniform(0.12, 0.2) * (1.2 if 0 < i < n - 1 else 0.8) * (0.55 if flat else 1)
            circles.append((x, base - rad * r.uniform(0.35, 0.8), rad))

        def path(grow):
            cr.new_path()
            for x, y, rad in circles:
                cr.new_sub_path()
                cr.arc(x, y, rad + grow, 0, TAU)
            x0, x1 = pad + cw * 0.12 - grow, pad + cw * 0.88 + grow
            y0, y1 = base - ch * 0.22 - grow, base + grow
            rr = (y1 - y0) / 2
            cr.new_sub_path()
            cr.arc(x0 + rr, y0 + rr, rr, math.pi / 2, 3 * math.pi / 2)
            cr.arc(x1 - rr, y0 + rr, rr, -math.pi / 2, math.pi / 2)
            cr.close_path()
        soft = cw * 0.012
        for i in range(7, 0, -1):          # mekky okraj: siri obrysy s malou pruhlednosti
            path(i * soft)
            cr.set_source_rgba(1, 1, 1, 0.1)
            cr.fill()
        path(0)
        cr.set_source_rgba(1, 1, 1, 1)
        cr.fill()
        cr.set_operator(cairo.OPERATOR_ATOP)   # obarvit (svetle nahore, tmavsi spodek), pruhlednost zustava
        g = cairo.LinearGradient(0, pad, 0, pad + ch)
        g.add_color_stop_rgb(0, *top)
        g.add_color_stop_rgb(1, *bottom)
        cr.set_source(g)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_DEST_IN)   # pruhlednost mraku primo ve spritu (rychlejsi kresleni)
        cr.set_source_rgba(0, 0, 0, alpha)
        cr.paint()
        return s, sw, sh

    def _make_fog(self, target, fw, fh, seed):
        r = random.Random(seed)
        s = self._surface(target, fw, fh)
        cr = cairo.Context(s)
        cy = fh / 2
        for _i in range(22):
            x = r.uniform(0, fw)
            rx, ry = r.uniform(0.15, 0.35) * fw, r.uniform(0.3, 0.5) * fh
            for dx in (-fw, 0, fw):            # navazuje na sebe pri opakovani vodorovne
                cr.save()
                cr.translate(x + dx, cy + r.uniform(-0.1, 0.1) * fh)
                cr.scale(rx, ry)
                g = cairo.RadialGradient(0, 0, 0, 0, 0, 1)
                g.add_color_stop_rgba(0, 0.95, 0.97, 1.0, 0.085)
                g.add_color_stop_rgba(1, 0.95, 0.97, 1.0, 0)
                cr.set_source(g)
                cr.arc(0, 0, 1, 0, TAU)
                cr.fill()
                cr.restore()
        return s, fw, fh

    def _ensure(self, target):
        if self._bg is None:
            self._bg = self._surface(target, self.w, self.h)
            self._draw_static(cairo.Context(self._bg))
        if self._sprites is None:
            self._sprites = {"cloud": [], "fog": []}
            if self.clouds:
                top, bottom, alpha = self._cloud_colors()
                flat = self.kind == "clear"
                cw = min(self.w * 0.55, 520)
                # kazdy mrak ma vlastni sprite uz ve sve velikosti: za snimek jen posun o cele body
                # (bez zmeny meritka a filtrovani), proto je kresleni levne
                for c in self.clouds:
                    a = alpha * (1.0 if c["near"] else 0.75)
                    sprite = self._make_cloud(target, cw * c["scale"], top, bottom, 1000 + c["sprite"], flat, a)
                    self._sprites["cloud"].append(sprite)
            if self.fog:
                for i in range(2):
                    self._sprites["fog"].append(self._make_fog(target, self.w, self.h * 0.3, 2000 + i))

    def draw(self, cr, w, h, scale=1):
        """Nakresli scenu do cr (velikost w x h v logickych bodech)."""
        self.resize(w, h, scale)
        self._ensure(cr.get_target())
        cr.save()
        cr.set_source_surface(self._bg, 0, 0)
        cr.paint()
        self._draw_dynamic(cr)
        if self._fade > 0 and self._old is not None:
            cr.set_source_surface(self._old, 0, 0)
            cr.paint_with_alpha(self._fade / FADE)
        cr.restore()

    def _snapshot(self):
        """Posledni podoba stare sceny pro prolnuti (obloha + mraky, bez castic)."""
        try:
            s = self._bg.create_similar(cairo.CONTENT_COLOR_ALPHA, self.w, self.h)
        except cairo.Error:
            return None
        c = cairo.Context(s)
        c.set_source_surface(self._bg, 0, 0)
        c.paint()
        self._draw_clouds(c)
        return s

    def _draw_clouds(self, cr):
        sprites = self._sprites["cloud"] if self._sprites else []
        for c, (s, sw, _sh) in zip(self.clouds, sprites):       # vzdalene mraky jsou v seznamu prvni
            if c["x"] > self.w or c["x"] + sw < 0:
                continue
            cr.set_source_surface(s, round(c["x"]), round(c["y"]))
            cr.paint()

    def _draw_dynamic(self, cr):
        t = self.t
        if self.twinkle:
            for x, y, r, ph, sp in self.twinkle:
                a = 0.55 + 0.45 * math.sin(t * sp + ph)
                cr.arc(x, y, r, 0, TAU)
                cr.set_source_rgba(0.95, 0.97, 1.0, a)
                cr.fill()
        self._draw_clouds(cr)
        for f in self.fog:
            s, fw, fh = self._sprites["fog"][f["sprite"]]
            for dx in (f["x"] - fw, f["x"]):
                cr.set_source_surface(s, round(dx), round(f["y"] - fh / 2))
                cr.paint()
        if self.rain:
            slant = 0.18 if self.kind == "storm" else 0.08
            drizzle = self.kind == "drizzle"
            for near in (False, True):
                cr.new_path()
                for x, y, ln, _sp, n in self.rain:
                    if n == near:
                        cr.move_to(x, y)
                        cr.line_to(x + ln * slant, y + ln)
                cr.set_line_width((1.5 if near else 1.0) * (0.9 if drizzle else 1.0))
                cr.set_source_rgba(0.82, 0.89, 1.0, (0.42 if near else 0.24) * (0.85 if drizzle else 1.0))
                cr.stroke()
        if self.snow:
            for near in (False, True):
                cr.new_path()
                for x, y, r, _sp, ph, _f, amp, n in self.snow:
                    if n == near:
                        sx = x + math.sin(ph) * amp
                        cr.new_sub_path()
                        cr.arc(sx, y, r, 0, TAU)
                cr.set_source_rgba(1, 1, 1, 0.88 if near else 0.5)
                cr.fill()
        fa = self.flash_alpha()
        if fa > 0:
            cr.set_source_rgba(0.92, 0.94, 1.0, 0.2 * fa)
            cr.paint()
            if self.bolt and self.t - self.flash_t < 0.26:
                cr.new_path()
                cr.move_to(*self.bolt[0])
                for p in self.bolt[1:]:
                    cr.line_to(*p)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.set_source_rgba(0.8, 0.85, 1.0, 0.25 * fa)
                cr.set_line_width(7)
                cr.stroke_preserve()
                cr.set_source_rgba(1, 1, 1, 0.9 * fa)
                cr.set_line_width(1.8)
                cr.stroke()
