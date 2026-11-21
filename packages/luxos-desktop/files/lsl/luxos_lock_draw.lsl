# LuxOS - kresba zamku (luxos-lock) a prihlasovaci obrazovky (luxos-greeter) na Waylandu, vse cairem. Vzhled je presna
# kopie X11: zamek luxos-lock-ui.c (xfce4-screensaver) a prihlaseni luxos-greeter (Python, LightDM). Rozmery, pisma,
# barvy, rozvrzeni widgetu GTK (box, popisky se stinem textu, pole pro heslo s kurzorem) i casy animaci jsou prevzate
# odtud; pri zmene X11 vzhledu upravit i tady. Testy: tests/test_luxos_lock_x11_match.py porovnava snimky s X11.
#
#   draw.new_ui(mode)                     stav kresby; mode "lock" nebo "greeter"
#   draw.backdrop(cesta, w, h, scale)     tapeta (vyplnit) a jeji rozmazana zmensenina pro matne prvky
#   draw.paint(image, w, h, ui, bd)       cela plocha do obrazku (pixely zarizeni = w * scale)
#   draw.frame(cr, w, h, ui, bd)          totez do kontextu, jehoz cil uz ma meritko zarizeni (GTK draw)
#                                         ui["hits"] = [[x, y, w, h, [akce, index]]] po kazdem snimku
#   draw.prompt(ui, on)                   prechod klid <-> zadavani; draw.shake(ui) zatreseni pole
#   draw.typed(ui)                        vstup do pole (kurzor znovu sviti)
#   draw.step(ui)                         posun animaci k aktualnimu casu: True = dalsi snimek hned; jinak za ui["wake"] ms
#                                         (blikani kurzoru, 0 = nic)
#   draw.field_rect(w, h, ui)             [x, y, w, h] pole pro heslo (testy, kliknuti)
#   ui["saver"]                           klid zamku jako setric xfce4-screensaver (luxos_saver: "desktop" = tapeta
#                                         plochy a hodiny jako dialog pri t = 0, "wallpapers", "clock", ...)
load cairo, gtk, glib, math
load luxos_glib as lglib
load luxos_lock_sys as sys
load luxos_tokens as tokens
load luxos_saver as saver

PI = cairo.PI
# PangoWeight
THIN = 200
NORMAL = 400
MEDIUM = 500
SEMIBOLD = 600
BOLD = 700
# Pisma jako X11 (cairo_font_options: styl hintovani, metriky, vyhlazovani, poradi subpixelu). Zamek bezi v relaci
# LuxOS (xsettings.xml: Xft hintslight, rgb): popisky GTK subpixelove, text kresleny primo cairem (hodiny, datum,
# inicialy, zastupny text) podle povrchu okna. Prihlaseni pod LightDM bez xsettings: plne hintovani, sede vyhlazovani.
FONT_OPTIONS = {"lock|cr": [2, 2, 0, 1], "lock|gtk": [2, 2, 3, 1], "greeter|cr": [4, 2, 2, 1], "greeter|gtk": [4, 2, 2, 1]}
# GTK: kurzor sviti 2/3 a nesviti 1/3 periody gtk-cursor-blink-time, po gtk-cursor-blink-timeout uz jen sviti
BLINK = 1200
BLINK_TIMEOUT = 10000
TEXTS = 160

state = {"backdrops": {}, "order": [], "texts": {}, "text_order": [], "masks": {}, "faces": {}, "groups": {}, "probe": None,
         "hint_style": "lock", "saver": ""}


function new_ui(mode):
    return {"mode": mode, "font": "Inter", "scale": 1.0, "clock": "", "date": "", "battery": None, "net": None,
            "layout": "US", "layouts": 1, "name": "", "face": None, "length": 0, "text": "", "visible_text": False,
            "placeholder": "", "hint": "", "error": False, "caps": False, "caps_text": "", "busy": False, "lockout": False,
            "power": [], "users": [], "sel": 0, "session": "", "sessions": [], "session_sel": 0, "notice": "",
            "hover": "", "leaving": False, "focus": True, "hits": [], "initial": "",
            "reveal": 0.0, "rev_from": 0.0, "rev_to": 0.0, "rev_start": 0, "shake": 0, "shake_start": 0,
            "input_at": 0, "caret": True, "wake": 0, "lang": "en", "saver": "desktop"}
end

# ---- cisla jako v C / GTK ------------------------------------------------------------------------

function cround(v):
    if v < 0.0:
        return -Int(math.floor(-v + 0.5))
    end
    return Int(math.floor(v + 0.5))
end

# Python round() (prihlaseni X11 je v Pythonu): pul k sude
function pyround(v):
    f = math.floor(v)
    d = v - f
    if d > 0.5 or (d == 0.5 and Int(f) % 2 == 1):
        return Int(f) + 1
    end
    return Int(f)
end

function px(ui, v, lo):
    x = Float(v) * ui["u"]
    r = cround(x)
    if ui["mode"] == "greeter":
        r = pyround(x)
    end
    return max(lo, r)
end

# C celociselne deleni kladnych i zapornych cisel (k nule)
function cdiv(a, b):
    if a < 0:
        return -((-a) // b)
    end
    return a // b
end

function ease(t):
    if t < 0.5:
        return 4.0 * t * t * t
    end
    k = -2.0 * t + 2.0
    return 1.0 - k * k * k / 2.0
end

# gtk_widget_set_opacity drzi alfu v 8 bitech
function opacity8(v):
    return Float(cround(v * 255.0)) / 255.0
end

# ---- text ----------------------------------------------------------------------------------------

function probe():
    if state["probe"] == None:
        surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, 1, 1)
        state["probe"] = cairo.create(surface)
    end
    return state["probe"]
end

function pfloor(v):
    return v // 1024
end

function pceil(v):
    return -((-v) // 1024)
end

# PANGO_PIXELS
function ppix(v):
    return (v + 512) // 1024
end

# Rozvrzeni textu (mezipamet): {"layout", "ink": [x, y, w, h] a "log": pixely vcetne (pango_extents_to_pixels),
# "w", "h": prirozena velikost popisku GTK (zaokrouhleno nahoru)}
# kind: "gtk" pisma popisku z CSS, "cr" pisma kreslena primo v luxos-lock-ui.c (text_layout)
function text(t, size, weight, family, spacing, kind, width):
    hs = state["hint_style"]
    key = t + "|" + String(size) + "|" + String(weight) + "|" + family + "|" + String(spacing) + "|" + kind + "|" + String(width) + "|" + hs
    e = state["texts"].get(key)
    if e != None:
        return e
    end
    fam = family + ",Inter,Cantarell,sans-serif"
    if kind == "cr":
        fam = family + ",Inter,Cantarell,Noto Sans,sans-serif"
    end
    layout = sys.text_layout(probe(), t, size, weight, fam, spacing)
    o = FONT_OPTIONS[hs + ("|cr" if kind == "cr" else "|gtk")]
    call sys.font_options(layout, o[0], o[1], o[2], o[3])
    if width > 0:
        if kind == "wrap":
            call sys.layout_wrap(layout, width)
        else:
            call sys.layout_ellipsize(layout, width)
        end
    end
    x = sys.extents(layout)
    ink = [pfloor(x[0]), pfloor(x[1]), pceil(x[0] + x[2]) - pfloor(x[0]), pceil(x[1] + x[3]) - pfloor(x[1])]
    lg = [pfloor(x[4]), pfloor(x[5]), pceil(x[4] + x[6]) - pfloor(x[4]), pceil(x[5] + x[7]) - pfloor(x[5])]
    e = {"layout": layout, "ink": ink, "log": lg, "w": pceil(x[6]), "h": pceil(x[7]), "raw": x, "lines": sys.line_count(layout)}
    if len(state["text_order"]) >= TEXTS:
        old = state["texts"].pop(state["text_order"].pop(0))
        call sys.layout_unref(old["layout"])
        m = state["masks"].pop(String(old["layout"]), None)
        if m != None:
            call cairo.surface_destroy(m[1])
        end
    end
    state["texts"][key] = e
    state["text_order"].append(key)
    return e
end

# Popisek GTK: prirozena sirka s max-width-chars (vypustka) nebo zalomenim (wrap)
function label(ui, t, size, weight, spacing, max_chars, wrap):
    e = text(t, size, weight, ui["font"], spacing, "gtk", -1)
    if max_chars > 0:
        cw = sys.char_pixels(e["layout"]) * max_chars
        if e["raw"][6] > cw:
            if wrap:
                return text(t, size, weight, ui["font"], spacing, "wrap", cw)
            end
            return text(t, size, weight, ui["font"], spacing, "ell", cw)
        end
    end
    return e
end

function show(cr, e, x, y):
    call cairo.move_to(cr, Float(x), Float(y))
    call sys.show_layout(cr, e["layout"])
    return 0
end

# Stin textu GTK (gtkcssshadowvalue.c): polomer <= 1 kopie textu posunuta o dy, jinak maska A8 rozmazana
# _gtk_cairo_blur_surface v pixelech zarizeni
function shadow_mask(e, radius, scale):
    key = String(e["layout"])
    m = state["masks"].get(key)
    if m != None and m[0] == String(radius) + "@" + String(scale):
        return m[1]
    end
    if m != None:
        call cairo.surface_destroy(m[1])
    end
    ink = e["ink"]
    clip = Int(math.floor(Float(radius) * 1.8799712059732503 * 1.5 + 0.5))
    s = sys.mask_surface(ink[2] + 2 * clip, ink[3] + 2 * clip, scale, -ink[0] + clip, -ink[1] + clip)
    mcr = cairo.create(s)
    call cairo.move_to(mcr, 0.0, 0.0)
    call sys.show_layout(mcr, e["layout"])
    call cairo.destroy(mcr)
    call sys.blur_a8(s, Float(radius) * scale)
    state["masks"][key] = [String(radius) + "@" + String(scale), s]
    return s
end

# Popisek GTK v obsahu x, y, w, h (zarovnani na stred): stin [dy, polomer, alfa] a barva [r, g, b, a]
function draw_label(cr, ui, e, x, y, w, h, color, shadow):
    lg = e["log"]
    lx = Int(math.floor(Float(x) + 0.5 * Float(w - lg[2]))) - lg[0]
    if e["lines"] == 1:
        ly = Int(math.floor(Float(y) + Float(h - lg[3]) * 0.5)) - lg[1]
    else:
        ly = Int(math.floor(Float(y) + max(Float(h - lg[3]) * 0.5, 0.0))) - lg[1]
    end
    if shadow != None and shadow[2] > 0.0:
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, shadow[2])
        if shadow[1] <= 1:
            call show(cr, e, lx, ly + shadow[0])
        else:
            call cairo.save(cr)
            call cairo.translate(cr, Float(lx), Float(ly + shadow[0]))
            call sys.mask(cr, shadow_mask(e, shadow[1], ui["scale"]), 0.0, 0.0)
            call cairo.restore(cr)
        end
    end
    call cairo.set_source_rgba(cr, color[0], color[1], color[2], color[3])
    call show(cr, e, lx, ly)
    return 0
end

# ---- tvary a ikony (luxos-lock-ui.c) ---------------------------------------------------------------

function rounded(cr, x, y, w, h, r):
    r = min(r, min(w / 2.0, h / 2.0))
    call sys.new_sub_path(cr)
    call cairo.arc(cr, x + w - r, y + r, r, -PI / 2.0, 0.0)
    call cairo.arc(cr, x + w - r, y + h - r, r, 0.0, PI / 2.0)
    call cairo.arc(cr, x + r, y + h - r, r, PI / 2.0, PI)
    call cairo.arc(cr, x + r, y + r, r, PI, 1.5 * PI)
    call cairo.close_path(cr)
    return 0
end

function circle(cr, cx, cy, r):
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, 0.0, 2.0 * PI)
    return 0
end

function icon_sleep(cr, cx, cy, s):
    r = s * 0.40
    call cairo.save(cr)
    call circle(cr, cx, cy, r)
    call cairo.clip(cr)
    call circle(cr, cx, cy, r)
    call sys.new_sub_path(cr)
    call cairo.arc(cr, cx + r * 0.55, cy - r * 0.45, r * 0.82, 0.0, 2.0 * PI)
    call sys.fill_rule(cr, 1)
    call cairo.fill(cr)
    call cairo.restore(cr)
    return 0
end

function icon_restart(cr, cx, cy, s):
    r = s * 0.36
    a0 = -PI / 2.0 + 0.25
    a1 = -PI / 2.0 + 2.0 * PI - 0.75
    k = s * 0.2
    call cairo.set_line_width(cr, max(1.4, s * 0.085))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, a0, a1)
    call cairo.stroke(cr)
    ex = cx + r * math.cos(a1)
    ey = cy + r * math.sin(a1)
    tx = -math.sin(a1)
    ty = math.cos(a1)
    nx = math.cos(a1)
    ny = math.sin(a1)
    call cairo.move_to(cr, ex + tx * k * 0.9, ey + ty * k * 0.9)
    call cairo.line_to(cr, ex + nx * k * 0.75 - tx * k * 0.25, ey + ny * k * 0.75 - ty * k * 0.25)
    call cairo.line_to(cr, ex - nx * k * 0.75 - tx * k * 0.25, ey - ny * k * 0.75 - ty * k * 0.25)
    call cairo.close_path(cr)
    call cairo.fill(cr)
    return 0
end

function icon_power(cr, cx, cy, s):
    call cairo.set_line_width(cr, max(1.4, s * 0.085))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy + s * 0.03, s * 0.36, -PI / 2.0 + 0.62, -PI / 2.0 - 0.62 + 2.0 * PI)
    call cairo.stroke(cr)
    call cairo.move_to(cr, cx, cy - s * 0.45)
    call cairo.line_to(cr, cx, cy - s * 0.05)
    call cairo.stroke(cr)
    return 0
end

function icon_session(cr, cx, cy, s):
    q = s * 0.3
    g = s * 0.08
    for dx in [-1, 1]:
        for dy in [-1, 1]:
            x = cx + g / 2.0 if dx > 0 else cx - g / 2.0 - q
            y = cy + g / 2.0 if dy > 0 else cy - g / 2.0 - q
            call rounded(cr, x, y, q, q, q * 0.25)
        end
    end
    call cairo.fill(cr)
    return 0
end

function icon_arrow(cr, cx, cy, s):
    call cairo.set_line_width(cr, max(1.5, s * 0.11))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.move_to(cr, cx - s * 0.3, cy)
    call cairo.line_to(cr, cx + s * 0.3, cy)
    call cairo.move_to(cr, cx + s * 0.05, cy - s * 0.25)
    call cairo.line_to(cr, cx + s * 0.3, cy)
    call cairo.line_to(cr, cx + s * 0.05, cy + s * 0.25)
    call cairo.stroke(cr)
    return 0
end

function icon_caps(cr, cx, cy, s):
    w = s * 0.80
    stem = s * 0.36
    top = cy - s * 0.46
    mid = cy - s * 0.02
    low = cy + s * 0.22
    call cairo.set_line_width(cr, max(1.3, s * 0.09))
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.new_path(cr)
    call cairo.move_to(cr, cx, top)
    call cairo.line_to(cr, cx + w / 2.0, mid)
    call cairo.line_to(cr, cx + stem / 2.0, mid)
    call cairo.line_to(cr, cx + stem / 2.0, low)
    call cairo.line_to(cr, cx - stem / 2.0, low)
    call cairo.line_to(cr, cx - stem / 2.0, mid)
    call cairo.line_to(cr, cx - w / 2.0, mid)
    call cairo.close_path(cr)
    call cairo.stroke(cr)
    call cairo.rectangle(cr, cx - stem / 2.0, cy + s * 0.33, stem, max(1.3, s * 0.11))
    call cairo.fill(cr)
    return 0
end

function icon_person(cr, cx, cy, s):
    call circle(cr, cx, cy - s * 0.16, s * 0.17)
    call cairo.fill(cr)
    call cairo.save(cr)
    call cairo.translate(cr, cx, cy + s * 0.34)
    call cairo.scale(cr, s * 0.32, s * 0.27)
    call cairo.arc(cr, 0.0, 0.0, 1.0, PI, 2.0 * PI)
    call cairo.restore(cr)
    call cairo.close_path(cr)
    call cairo.fill(cr)
    return 0
end

function icon_wifi(cr, x, y, s):
    cx = x + s / 2.0
    cy = y + s * 0.86
    call cairo.set_line_width(cr, max(1.3, s * 0.11))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    for r in [0.3, 0.55, 0.8]:
        call cairo.new_path(cr)
        call cairo.arc(cr, cx, cy, s * r * 0.85, -PI * 0.75, -PI * 0.25)
        call cairo.stroke(cr)
    end
    call cairo.arc(cr, cx, cy, s * 0.08, 0.0, 2.0 * PI)
    call cairo.fill(cr)
    return 0
end

function icon_wired(cr, x, y, s):
    b = s * 0.26
    call rounded(cr, x + s / 2.0 - b / 2.0, y + s * 0.08, b, b, b * 0.2)
    call rounded(cr, x + s * 0.08, y + s * 0.66, b, b, b * 0.2)
    call rounded(cr, x + s * 0.92 - b, y + s * 0.66, b, b, b * 0.2)
    call cairo.fill(cr)
    call cairo.set_line_width(cr, max(1.2, s * 0.08))
    call cairo.move_to(cr, x + s / 2.0, y + s * 0.08 + b)
    call cairo.line_to(cr, x + s / 2.0, y + s * 0.52)
    call cairo.move_to(cr, x + s * 0.08 + b / 2.0, y + s * 0.66)
    call cairo.line_to(cr, x + s * 0.08 + b / 2.0, y + s * 0.52)
    call cairo.line_to(cr, x + s * 0.92 - b / 2.0, y + s * 0.52)
    call cairo.line_to(cr, x + s * 0.92 - b / 2.0, y + s * 0.66)
    call cairo.stroke(cr)
    return 0
end

# Baterie (luxos-lock-battery.c): tmavy stin a podklad, bily obrys, vypln; blesk nad vyplni tmavy, nad prazdnou
# casti bily
function bolt(cr, cx, cy, k):
    call cairo.new_path(cr)
    for p in [[0.14, -1.0], [-0.58, 0.14], [-0.07, 0.14], [-0.14, 1.0], [0.58, -0.14], [0.07, -0.14]]:
        call cairo.line_to(cr, cx + p[0] * k, cy + p[1] * k)
    end
    call cairo.close_path(cr)
    return 0
end

function battery(cr, x, y, h, level, charging):
    w = h * 2.05
    lw = max(1.0, h * 0.09)
    bx = x + lw / 2.0
    by = y + lw / 2.0
    bw = w - h * 0.22 - lw
    bh = h - lw
    br = h * 0.26
    ix = x + lw
    iy = y + lw
    iw = bw - lw
    ih = h - 2.0 * lw
    frac = min(1.0, max(0.0, Float(level) / 100.0))
    fx = ix + h * 0.08
    fy = iy + h * 0.08
    fw = max(h * 0.12, (iw - h * 0.16) * frac)
    fh = ih - h * 0.16
    ring = max(1.0, h * 0.08)
    cx = bx + bw / 2.0
    cy = y + h / 2.0
    k = ih / 2.0 - ring * 0.75
    halo = max(0.75, h * 0.06)
    call cairo.save(cr)
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
    call cairo.set_line_width(cr, lw + 2.0 * halo)
    call rounded(cr, bx, by, bw, bh, br)
    call cairo.stroke(cr)
    call rounded(cr, x + w - h * 0.2 - halo, y + h * 0.33 - halo, h * 0.14 + 2.0 * halo, h * 0.34 + 2.0 * halo, h * 0.06 + halo)
    call cairo.fill(cr)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
    call rounded(cr, ix, iy, iw, ih, br - lw / 2.0)
    call cairo.fill(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.9)
    call cairo.set_line_width(cr, lw)
    call rounded(cr, bx, by, bw, bh, br)
    call cairo.stroke(cr)
    call rounded(cr, x + w - h * 0.2, y + h * 0.33, h * 0.14, h * 0.34, h * 0.06)
    call cairo.fill(cr)
    if level <= 15 and not charging:
        call cairo.set_source_rgba(cr, 1.0, 0.36, 0.33, 1.0)
    else:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    end
    call rounded(cr, fx, fy, fw, fh, h * 0.14)
    call cairo.fill(cr)
    if charging:
        ex = fx + fw
        call cairo.set_line_width(cr, 2.0 * ring)
        if ex > ix:
            call cairo.save(cr)
            call cairo.rectangle(cr, ix, iy, ex - ix, ih)
            call cairo.clip(cr)
            call bolt(cr, cx, cy, k)
            call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
            call cairo.stroke_preserve(cr)
            call cairo.set_source_rgba(cr, 0.10, 0.10, 0.12, 0.92)
            call cairo.fill(cr)
            call cairo.restore(cr)
        end
        if ex < ix + iw:
            call cairo.save(cr)
            call cairo.rectangle(cr, ex, iy, ix + iw - ex, ih)
            call cairo.clip(cr)
            call bolt(cr, cx, cy, k)
            call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.60)
            call cairo.stroke_preserve(cr)
            call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.97)
            call cairo.fill(cr)
            call cairo.restore(cr)
        end
    end
    call cairo.restore(cr)
    return 0
end

# ---- tapeta ----------------------------------------------------------------------------------------

# Tapeta vyplni plochu (zmensena bilinearne jako gdk_pixbuf_scale_simple v luxos-lock-ui.c); meritko muze byt
# zlomkove (wp_fractional_scale), povrch ma pak presne velikost buferu
function backdrop(path, w, h, scale):
    stamp = ""
    if path != "" and exists(path):
        stamp = String(lglib.stat(path))
    end
    key = path + "|" + stamp + "|" + String(w) + "x" + String(h) + "@" + String(scale)
    bd = state["backdrops"].get(key)
    if bd != None:
        return bd
    end
    dw = max(1, cround(Float(w) * scale))
    dh = max(1, cround(Float(h) * scale))
    sharp = cairo.image_surface_create(cairo.FORMAT_RGB24, dw, dh)
    call sys.device_scale(sharp, scale)
    cr = cairo.create(sharp)
    pb = 0
    if path != "" and exists(path):
        pb = gtk.pixbuf_new_from_file(path)
    end
    if pb == 0 and exists("/usr/share/backgrounds/luxos/luxos-light.jpg"):
        pb = gtk.pixbuf_new_from_file("/usr/share/backgrounds/luxos/luxos-light.jpg")
    end
    if pb != 0:
        pw = gtk.pixbuf_get_width(pb)
        ph = gtk.pixbuf_get_height(pb)
        sc = max(Float(w) / Float(pw), Float(h) / Float(ph))
        tw = max(1, cround(Float(pw) * sc))
        th = max(1, cround(Float(ph) * sc))
        scaled = gtk.pixbuf_scale_simple(pb, Int(Float(tw) * scale), Int(Float(th) * scale), 2)
        call cairo.save(cr)
        call cairo.scale(cr, 1.0 / scale, 1.0 / scale)
        call gtk.cairo_set_source_pixbuf(cr, scaled, (Float(w - tw) / 2.0) * scale, (Float(h - th) / 2.0) * scale)
        call cairo.paint(cr)
        call cairo.restore(cr)
        call glib.object_unref(scaled)
        call glib.object_unref(pb)
    else:
        g = cairo.pattern_create_linear(0.0, 0.0, Float(w), Float(h))
        call cairo.pattern_add_color_stop_rgba(g, 0.0, 0.10, 0.11, 0.25, 1.0)
        call cairo.pattern_add_color_stop_rgba(g, 0.6, 0.27, 0.20, 0.52, 1.0)
        call cairo.pattern_add_color_stop_rgba(g, 1.0, 0.55, 0.36, 0.78, 1.0)
        call cairo.set_source(cr, g)
        call cairo.paint(cr)
        call cairo.pattern_destroy(g)
    end
    call cairo.destroy(cr)
    bd = {"key": key, "sharp": sharp, "blur": None, "w": w, "h": h, "scale": scale, "dw": dw, "dh": dh, "veils": {}}
    while len(state["order"]) >= 3:
        old = state["backdrops"].pop(state["order"].pop(0))
        for k in ["sharp", "blur", "dimmed"]:
            if old.get(k) != None:
                call cairo.surface_destroy(old[k])
            end
        end
    end
    state["backdrops"][key] = bd
    state["order"].append(key)
    return bd
end

# Podklad matnych prvku: zmensenina 64 px vysoka rozmazana box_blur(2, 3) se sytosti 1.25, zvetsuje se bilinearne.
# V klidu neni potreba: zamek ho pocita az po prvnim snimku (zamceni nesmi cekat); -> ms
function backdrop_soft(bd):
    if bd["blur"] != None:
        return 0
    end
    t0 = glib.monotonic_time()
    w = bd["w"]
    h = bd["h"]
    sh = 64
    sw = max(8, cround(Float(w) * Float(sh) / Float(h)))
    small = cairo.image_surface_create(cairo.FORMAT_RGB24, sw, sh)
    cr = cairo.create(small)
    call cairo.scale(cr, Float(sw) / Float(w), Float(sh) / Float(h))
    call cairo.set_source_surface(cr, bd["sharp"], 0.0, 0.0)
    # CAIRO_FILTER_GOOD
    call sys.filter(cr, 1)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call sys.box_blur(small, 2, 3, 1.25)
    # zustava zmensenina: frost() ji zvetsuje bilinearne pri kresleni (stejne vzorky jako zvetsena kopie v X11,
    # bez dalsiho povrchu velikosti obrazovky)
    bd["blur"] = small
    bd["sw"] = sw
    bd["sh"] = sh
    return max(1, Int((glib.monotonic_time() - t0) / 1000))
end

# Matny prvek: vyrez rozmazane tapety, svetly zavoj a jemny okraj
function blur_source(cr, bd):
    call cairo.scale(cr, Float(bd["w"]) / Float(bd["sw"]), Float(bd["h"]) / Float(bd["sh"]))
    call cairo.set_source_surface(cr, bd["blur"], 0.0, 0.0)
    # CAIRO_FILTER_BILINEAR, CAIRO_EXTEND_PAD
    call sys.filter(cr, 4)
    call sys.extend(cr, 3)
    return 0
end

function frost(cr, bd, x, y, w, h, r, tint, border):
    call cairo.save(cr)
    call rounded(cr, x, y, w, h, r)
    call cairo.clip(cr)
    call cairo.save(cr)
    call blur_source(cr, bd)
    call cairo.paint(cr)
    call cairo.restore(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, tint)
    call cairo.paint(cr)
    call cairo.restore(cr)
    if border > 0.0:
        call rounded(cr, x + 0.5, y + 0.5, w - 1.0, h - 1.0, r)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, border)
        call cairo.set_line_width(cr, 1.0)
        call cairo.stroke(cr)
    end
    return 0
end

function lin_rgb(c):
    if c <= 0.03928:
        return c / 12.92
    end
    return math.exp(2.4 * math.log((c + 0.055) / 1.055))
end

# Tmavy zavoj pole podle jasu rozmazane tapety pod nim (field_veil v luxos-lock-ui.c)
function field_veil(bd, x, y, w, h, tint):
    key = String(x) + "," + String(y) + "," + String(w) + "," + String(h)
    v = bd["veils"].get(key)
    if v == None:
        v = field_veil_calc(bd, x, y, w, h, tint)
        bd["veils"][key] = v
    end
    return v
end

function field_veil_calc(bd, x, y, w, h, tint):
    s = bd["scale"]
    # rozmazana tapeta pod polem v pixelech zarizeni (jako zvetsena kopie v X11)
    region = cairo.image_surface_create(cairo.FORMAT_RGB24, bd["dw"], max(1, Int(Float(y + h + 2) * s)))
    call sys.device_scale(region, s)
    rcr = cairo.create(region)
    call cairo.rectangle(rcr, Float(x), Float(y), Float(w), Float(h))
    call cairo.clip(rcr)
    call blur_source(rcr, bd)
    call cairo.paint(rcr)
    call cairo.destroy(rcr)
    call cairo.surface_flush(region)
    total = 0.0
    n = 0
    for j in range(1, 6):
        for i in range(1, 16):
            sx = Int((Float(x) + Float(w) * Float(i) / 16.0) * s)
            sy = Int((Float(y) + Float(h) * Float(j) / 6.0) * s)
            if sx < 0 or sy < 0 or sx >= bd["dw"] or sy >= cairo.image_surface_get_height(region):
                continue
            end
            q = sys.pixel_bgr(region, sx, sy)
            b = Float(q[0]) / 255.0 * (1.0 - tint) + tint
            g = Float(q[1]) / 255.0 * (1.0 - tint) + tint
            r = Float(q[2]) / 255.0 * (1.0 - tint) + tint
            total = total + 0.2126 * lin_rgb(r) + 0.7152 * lin_rgb(g) + 0.0722 * lin_rgb(b)
            n = n + 1
        end
    end
    call cairo.surface_destroy(region)
    lum = 0.5
    if n > 0:
        lum = total / Float(n)
    end
    veil = 0.24
    if lum > 0.13:
        veil = 1.0 - math.exp(math.log(0.13 / lum) / 2.2)
    end
    return min(0.62, max(0.24, veil))
end

# ---- rozvrzeni (jako GtkBox a GtkOverlay v X11) ----------------------------------------------------

function sizes(ui, w, h):
    ui["u"] = max(0.55, Float(h) / 1080.0)
    return {"avatar": px(ui, 104, 64), "pw_w": px(ui, 250, 180), "pw_h": px(ui, 36, 28), "round": px(ui, 44, 34),
            "status": px(ui, 16, 12), "pad": px(ui, 18, 10), "pw_pad": px(ui, 16, 11), "pw_font": px(ui, 15, 12)}
end

function shadow_spec(ui):
    return [1, px(ui, 3, 2), 0.45]
end

function status_items(ui, sz):
    items = []
    lab = label(ui, ui["layout"], px(ui, 13, 11), BOLD, 1024, 0, False)
    items.append(["kbd", lab["w"] + 2 * px(ui, 10, 7), lab["h"] + 2 * px(ui, 3, 2), lab])
    net = ui["net"]
    if net != None and net[0] != "none":
        items.append(["net", sz["status"] + 4, sz["status"] + 4, None])
    end
    bat = ui["battery"]
    if bat != None:
        items.append(["bat", Int(math.ceil(Float(sz["status"]) * 0.9 * 2.05)) + 4, sz["status"] + 4, None])
        t = String(bat[0]) + (" %" if ui.get("lang", "") == "cs" else "%")
        t = String(bat[0]) + " %" if ui.get("lang", "") == "cs" else String(bat[0]) + "%"
        lab = label(ui, t, px(ui, 14, 11), SEMIBOLD, 0, 0, False)
        items.append(["batlabel", lab["w"], lab["h"], lab])
    end
    return items
end

function draw_status(cr, ui, bd, w, sz):
    items = status_items(ui, sz)
    sp = px(ui, 14, 8)
    bh = 0
    bw = -sp
    for it in items:
        bh = max(bh, it[2])
        bw = bw + it[1] + sp
    end
    x = w - sz["pad"] - bw
    y = sz["pad"]
    for it in items:
        iw = it[1]
        if it[0] == "kbd":
            hover = ui["hover"] == "layout"
            call frost(cr, bd, Float(x), Float(y), Float(iw), Float(bh), Float(bh) * 0.5, 0.16 + (0.06 if hover else 0.0), 0.18)
            call draw_label(cr, ui, it[3], x + px(ui, 10, 7), y + px(ui, 3, 2), iw - 2 * px(ui, 10, 7), bh - 2 * px(ui, 3, 2),
                            [1.0, 1.0, 1.0, 1.0], shadow_spec(ui))
            ui["hits"].append([x, y, iw, bh, ["layout", 0]])
        elif it[0] == "net":
            s = Float(sz["status"])
            call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
            if ui["net"][0] == "wifi":
                call icon_wifi(cr, Float(x) + (Float(iw) - s) / 2.0, Float(y) + (Float(bh) - s) / 2.0, s)
            else:
                call icon_wired(cr, Float(x) + (Float(iw) - s) / 2.0, Float(y) + (Float(bh) - s) / 2.0, s)
            end
        elif it[0] == "bat":
            hb = Float(sz["status"]) * 0.9
            call battery(cr, Float(x) + 1.0, Float(y) + (Float(bh) - hb) / 2.0, hb, ui["battery"][0], ui["battery"][1])
        else:
            call draw_label(cr, ui, it[3], x, y, iw, bh, [1.0, 1.0, 1.0, 1.0], shadow_spec(ui))
        end
        x = x + iw + sp
    end
    return 0
end

# Datum a velke tenke hodiny (draw_bg): mekky stin z peti posunutych kopii
function shadow_text(cr, e, x, y, alpha, blur):
    for o in [[0.0, 1.0], [0.0, 2.0], [-1.0, 1.5], [1.0, 1.5], [0.0, 3.0]]:
        call cairo.move_to(cr, x + o[0] * blur * 0.35, y + o[1] * blur * 0.45)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.055 * alpha)
        call sys.show_layout(cr, e["layout"])
    end
    call cairo.move_to(cr, x, y)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alpha)
    call sys.show_layout(cr, e["layout"])
    return 0
end

function draw_clock(cr, ui, w, h, e):
    u = ui["u"]
    cx = Float(w) / 2.0
    y0 = Float(h) * 0.105 - e * Float(h) * 0.045
    alpha = 1.0 - 0.12 * e
    dl = text(ui["date"], 27.0 * u, SEMIBOLD, ui["font"], 0, "cr", -1)
    lg = dl["log"]
    call shadow_text(cr, dl, cx - Float(lg[2]) / 2.0, y0, alpha * 0.92, 2.0 * u)
    cl = text(ui["clock"], 180.0 * u, THIN, ui["font"], 0, "cr", -1)
    ink = cl["ink"]
    cy = y0 + Float(lg[3]) + 14.0 * u - Float(ink[1])
    call shadow_text(cr, cl, cx - Float(ink[0]) - Float(ink[2]) / 2.0, cy, alpha, 4.0 * u)
    return 0
end

# Avatar: obrazek predpocitany v presne velikosti (HYPER) nebo prechod s inicialou, stin a tenky okraj
function face_surface(face, size):
    key = String(face) + "|" + String(size)
    f = state["faces"].get(key)
    if f == None:
        pw = gtk.pixbuf_get_width(face)
        ph = gtk.pixbuf_get_height(face)
        sc = max(Float(size) / Float(pw), Float(size) / Float(ph))
        f = gtk.pixbuf_scale_simple(face, max(1, cround(Float(pw) * sc)), max(1, cround(Float(ph) * sc)), 3)
        if len(state["faces"]) > 8:
            for k in List(state["faces"].keys()):
                call glib.object_unref(state["faces"].pop(k))
            end
        end
        state["faces"][key] = f
    end
    return f
end

function draw_avatar(cr, ui, bd, cx, cy, d, face, name, other, border, border_w, full):
    s = ui["scale"]
    call circle(cr, cx, cy + d * 0.03, d / 2.0 + 1.0)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.18)
    call cairo.fill(cr)
    call cairo.save(cr)
    call circle(cr, cx, cy, d / 2.0)
    call cairo.clip(cr)
    if face != None:
        f = face_surface(face, cround(full * s))
        fw = Float(gtk.pixbuf_get_width(f))
        fh = Float(gtk.pixbuf_get_height(f))
        call cairo.translate(cr, cx, cy)
        call cairo.scale(cr, d / full / s, d / full / s)
        call gtk.cairo_set_source_pixbuf(cr, f, -fw / 2.0, -fh / 2.0)
        call sys.filter(cr, 1)
        call cairo.paint(cr)
    elif other:
        call frost(cr, bd, cx - d / 2.0, cy - d / 2.0, d, d, d / 2.0, 0.22, 0.0)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.9)
        call icon_person(cr, cx, cy, d * 0.62)
    else:
        g = cairo.pattern_create_linear(cx - d / 2.0, cy - d / 2.0, cx + d / 2.0, cy + d / 2.0)
        call cairo.pattern_add_color_stop_rgba(g, 0.0, 0.30, 0.52, 1.0, 1.0)
        call cairo.pattern_add_color_stop_rgba(g, 1.0, 0.66, 0.42, 0.98, 1.0)
        call cairo.set_source(cr, g)
        call cairo.paint(cr)
        call cairo.pattern_destroy(g)
        initial = name.strip()
        initial = initial[0].upper() if initial != "" else "?"
        e = text(initial, d * 0.44, MEDIUM, ui["font"], 0, "cr", -1)
        ink = e["ink"]
        call cairo.move_to(cr, cx - Float(ink[0]) - Float(ink[2]) / 2.0, cy - Float(ink[1]) - Float(ink[3]) / 2.0)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.97)
        call sys.show_layout(cr, e["layout"])
    end
    call cairo.restore(cr)
    call circle(cr, cx, cy, d / 2.0 - 0.5)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, border)
    call cairo.set_line_width(cr, border_w)
    call cairo.stroke(cr)
    return 0
end

# Pole pro heslo (pw-box): matny oval, tmavy zavoj, zastupny text nebo tecky (GtkEntry), kurzor a sipka
function field_w(ui, sz):
    if ui["mode"] == "greeter":
        # GtkEntry bez width-chars (luxos-greeter): prirozena sirka 150 px + odsazeni, pak sipka
        return max(sz["pw_w"], 150 + sz["pw_pad"] + sz["pw_h"])
    end
    return sz["pw_w"]
end

function draw_field(cr, ui, bd, sz, x, y):
    pw = field_w(ui, sz)
    ph = sz["pw_h"]
    ew = pw - ph
    call frost(cr, bd, Float(x), Float(y), Float(pw), Float(ph), Float(ph) * 0.5, 0.20, 0.18)
    call rounded(cr, Float(x) + 1.0, Float(y) + 1.0, Float(pw - 2), Float(ph - 2), Float(ph - 2) * 0.5)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, field_veil(bd, x, y, pw, ph, 0.20))
    call cairo.fill(cr)
    sens = not ui["busy"]
    shown = ui["text"] if ui["visible_text"] else "●" * ui["length"]
    if shown == "" and ui["placeholder"] != "":
        e = text(ui["placeholder"], Float(sz["pw_font"]), NORMAL, ui["font"], 0, "cr", max(1, ew - sz["pw_pad"] - 4) * 1024)
        lg = e["log"]
        tx = Float(x + sz["pw_pad"] + 2)
        ty = Float(y) + Float(ph - lg[3]) / 2.0
        call cairo.move_to(cr, tx, ty + 1.0)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.35 if sens else 0.2)
        call sys.show_layout(cr, e["layout"])
        call cairo.move_to(cr, tx, ty)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.92 if sens else 0.5)
        call sys.show_layout(cr, e["layout"])
    end
    # GtkEntry: text na svisle poloze podle ascent/descent pisma (get_layout_position), kurzor 1 px
    e = text(shown, Float(sz["pw_font"]), NORMAL, ui["font"], 0, "gtk", -1)
    fm = sys.font_metrics(e["layout"])
    area = ph * 1024
    raw = e["raw"]
    # logical_rect.y radku je -baseline
    ypos = cdiv(area - fm[0] - fm[1], 2) + fm[0] - sys.baseline(e["layout"])
    if raw[7] > area:
        ypos = cdiv(area - raw[7], 2)
    elif ypos < 0:
        ypos = 0
    elif ypos + raw[7] > area:
        ypos = area - raw[7]
    end
    ty = y + cdiv(ypos, 1024)
    tx = x + sz["pw_pad"]
    if shown != "":
        call cairo.move_to(cr, Float(tx), Float(ty))
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0 if sens else 0.5)
        call sys.show_layout(cr, e["layout"])
    end
    if ui["focus"] and sens and ui["caret"]:
        c = sys.cursor_x(e["layout"], byte_len(shown))
        hgt = ppix(c[3])
        stem = Int(Float(hgt) * 0.04 + 1.0)
        call cairo.rectangle(cr, Float(tx + ppix(c[0]) - stem // 2), Float(ty + ppix(c[1])), Float(stem), Float(hgt))
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
        call cairo.fill(cr)
    end
    # sipka (go-area)
    gx = x + ew
    d = Float(ph - max(8, cround(Float(ph) * 0.26)))
    cx = Float(gx) + Float(ph) / 2.0 - 2.0
    cy = Float(y) + Float(ph) / 2.0
    has = shown != ""
    hover = ui["hover"] == "go"
    call circle(cr, cx, cy, d / 2.0)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, (0.30 if has else 0.12) + (0.1 if hover else 0.0))
    call cairo.fill(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95 if has else 0.55)
    call icon_arrow(cr, cx, cy, d * 0.62)
    ui["hits"].append([x, y, ew, ph, ["field", 0]])
    ui["hits"].append([gx, y, ph, ph, ["go", 0]])
    return 0
end

# Delka textu v bajtech UTF-8 (index kurzoru pango)
function byte_len(t):
    n = 0
    for ch in t:
        c = ord(ch)
        if c < 128:
            n = n + 1
        elif c < 2048:
            n = n + 2
        elif c < 65536:
            n = n + 3
        else:
            n = n + 4
        end
    end
    return n
end

function power_items(ui):
    out = []
    if ui["mode"] == "greeter" and len(ui["sessions"]) > 1:
        out.append(["session", ui["sessions"][ui["session_sel"]]])
    end
    for p in ui["power"]:
        out.append(p)
    end
    return out
end

function draw_power(cr, ui, bd, w, h, sz):
    items = power_items(ui)
    if len(items) == 0:
        return 0
    end
    aw = sz["round"] + px(ui, 8, 6)
    gap = px(ui, 5, 3)
    sp = px(ui, 40, 26)
    labs = []
    bw = -sp
    bh = 0
    for it in items:
        lab = label(ui, it[1], px(ui, 13, 11), MEDIUM, 0, 0, False)
        labs.append(lab)
        bw = bw + max(aw, lab["w"]) + sp
        bh = max(bh, aw + gap + lab["h"])
    end
    # GtkOverlay centruje dite jako sirka / 2 - pozadavek / 2 (kazde zvlast celociselne)
    x = w // 2 - bw // 2
    y = h - px(ui, 42, 26) - bh
    for i in range(len(items)):
        lab = labs[i]
        iw = max(aw, lab["w"])
        key = items[i][0]
        d = Float(sz["round"])
        ax = Float(x) + Float(iw) / 2.0
        ay = Float(y) + Float(aw) / 2.0
        tint = 0.16 + (0.10 if ui["hover"] == key else 0.0)
        call frost(cr, bd, ax - d / 2.0, ay - d / 2.0, d, d, d / 2.0, tint, 0.18)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
        if key == "suspend":
            call icon_sleep(cr, ax, ay, d * 0.46)
        elif key == "reboot":
            call icon_restart(cr, ax, ay, d * 0.46)
        elif key == "session":
            call icon_session(cr, ax, ay, d * 0.46)
        else:
            call icon_power(cr, ax, ay, d * 0.46)
        end
        call draw_label(cr, ui, lab, x, y + aw + gap, iw, lab["h"], [1.0, 1.0, 1.0, 0.92], shadow_spec(ui))
        ui["hits"].append([x, y, iw, bh, [key, 0]])
        x = x + iw + sp
    end
    return 0
end

# Uzivatele (users-box): jeden v zamku, v prihlaseni rada s vybranym uprostred (ostatni mensi a tlumenejsi)
function user_boxes(ui, sz):
    users = ui["users"]
    if ui["mode"] != "greeter" or len(users) == 0:
        users = [{"real": ui["name"], "face": ui["face"], "other": False}]
    end
    aw = sz["avatar"] + px(ui, 8, 6)
    gap = px(ui, 8, 5)
    out = []
    for u in users:
        lab = label(ui, u["real"], px(ui, 17, 13), SEMIBOLD, 0, 22, False)
        out.append([max(aw, lab["w"]), aw + gap + lab["h"], lab, u])
    end
    return out
end

function draw_users(cr, ui, bd, w, sz, y, boxes, row_w, row_h):
    aw = sz["avatar"] + px(ui, 8, 6)
    gap = px(ui, 8, 5)
    sp = px(ui, 34, 20)
    multi = len(boxes) > 1
    shift = 0
    if multi:
        x = 0
        centre = 0.0
        for i in range(len(boxes)):
            if i == ui["sel"]:
                centre = Float(x) + Float(boxes[i][0]) / 2.0
            end
            x = x + boxes[i][0] + sp
        end
        room = max(0.0, Float(w - (x - sp)) / 2.0)
        shift = pyround(max(-room, min(room, Float(x - sp) / 2.0 - centre)))
    end
    ms = max(0, 2 * shift)
    me = max(0, -2 * shift)
    x = ms + cdiv(w - ms - me - row_w, 2)
    for i in range(len(boxes)):
        b = boxes[i]
        sel = i == ui["sel"] or not multi
        d = Float(sz["avatar"])
        if not sel:
            d = Float(pyround(d * 0.8))
        end
        hover = ui["hover"] == "user" + String(i)
        # zamek: avatar halign center (auth-face-image), prihlaseni: pres celou sirku tlacitka
        cx = Float(x + cdiv(b[0] - aw, 2)) + Float(aw) / 2.0
        if ui["mode"] == "greeter":
            cx = Float(x) + Float(b[0]) / 2.0
        end
        cy = Float(y) + Float(aw) / 2.0
        u = b[3]
        border = 0.55 if (hover and multi) else 0.22
        a = [cx, cy, d, u["face"], u["real"], u["other"], border, 1.5 if hover else 1.0, Float(sz["avatar"]), x, y + aw + gap, b]
        if multi and not sel:
            # nevybrany uzivatel s pruhlednosti (avatar 0.75, jmeno 0.7 jako luxos-greeter): hotovy obrazek skupiny
            r = Int(d / 2.0) + 4
            call cached_group(cr, ui, bd, "avatar", a, Int(cx) - r, Int(cy) - r, 2 * r, 2 * r + 2, opacity8(0.75))
            call cached_group(cr, ui, bd, "name", a, x - 8, y + aw + gap - 8, b[0] + 16, b[2]["h"] + 16, opacity8(0.7))
        else:
            call user_part(cr, ui, bd, "avatar", a)
            call user_part(cr, ui, bd, "name", a)
        end
        ui["hits"].append([x, y, b[0], b[1], ["user", i]])
        x = x + b[0] + sp
    end
    return 0
end

# Skupina s pruhlednosti jen v obdelniku prvku (cairo_push_group jinak alokuje celou plochu)
function user_part(cr, ui, bd, kind, a):
    if kind == "avatar":
        call draw_avatar(cr, ui, bd, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8])
    else:
        call draw_label(cr, ui, a[11][2], a[9], a[10], a[11][0], a[11][2]["h"], [1.0, 1.0, 1.0, 1.0], shadow_spec(ui))
    end
    return 0
end

# Skupina s pruhlednosti kreslena jednou do obrazku v obdelniku x, y, w, h (cele logicke souradnice = cele pixely
# zarizeni, stejne vzorky jako cairo_push_group), pak jen slozena s alfou
function cached_group(cr, ui, bd, kind, a, x, y, w, h, alpha):
    scale = ui["scale"]
    key = kind + "|" + bd["key"] + "|" + String(a[0]) + "," + String(a[1]) + "," + String(a[2]) + "," + String(a[3]) + a[4] + String(a[6]) + String(x) + "," + String(y) + "@" + String(scale)
    g = state["groups"].get(key)
    if g == None:
        if len(state["groups"]) > 24:
            for k in List(state["groups"].keys()):
                call cairo.surface_destroy(state["groups"].pop(k))
            end
        end
        g = cairo.image_surface_create(cairo.FORMAT_ARGB32, cround(Float(w) * scale), cround(Float(h) * scale))
        call sys.device_scale(g, scale)
        call sys.device_offset(g, -Float(x) * scale, -Float(y) * scale)
        gcr = cairo.create(g)
        call user_part(gcr, ui, bd, kind, a)
        call cairo.destroy(gcr)
        state["groups"][key] = g
    end
    call cairo.set_source_surface(cr, g, 0.0, 0.0)
    call cairo.paint_with_alpha(cr, alpha)
    return 0
end

function material_group(cr, x, y, w, h):
    call cairo.save(cr)
    call cairo.rectangle(cr, Float(x), Float(y), Float(w), Float(h))
    call cairo.clip(cr)
    call cairo_push_group(cr)
    return 0
end

function end_group(cr, alpha):
    call cairo_pop_group(cr)
    call cairo.paint_with_alpha(cr, alpha)
    call cairo.restore(cr)
    return 0
end

function cairo_push_group(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_push_group"), __lsl_unbox_int(cr))
    end
end

function cairo_pop_group(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_pop_group_to_source"), __lsl_unbox_int(cr))
    end
end

# Svisle rozvrzeni login_window (valign end): uzivatele, pole, radek Caps Lock/rozlozeni, hlaska (a domena)
function login_layout(ui, w, h, sz, e):
    boxes = user_boxes(ui, sz)
    sp = px(ui, 14, 9)
    row_w = -px(ui, 34, 20)
    row_h = 0
    for b in boxes:
        row_w = row_w + b[0] + px(ui, 34, 20)
        row_h = max(row_h, b[1])
    end
    kbd = []
    if ui["caps"]:
        icon = px(ui, 16, 12)
        lab = label(ui, ui["caps_text"], px(ui, 14, 11), SEMIBOLD, 0, 0, False)
        kbd.append(["caps", icon + px(ui, 6, 4) + lab["w"], max(icon, lab["h"]), lab])
    end
    if ui["layouts"] > 1:
        lab = label(ui, ui["layout"], px(ui, 13, 11), BOLD, 1024, 0, False)
        kbd.append(["chip", lab["w"] + 2 * px(ui, 10, 7), lab["h"] + 2 * px(ui, 3, 2), lab])
    end
    kw = -px(ui, 14, 9)
    kh = px(ui, 24, 18)
    for k in kbd:
        kw = kw + k[1] + px(ui, 14, 9)
        kh = max(kh, k[2])
    end
    hint = label(ui, ui["hint"], px(ui, 14, 11), SEMIBOLD if ui["error"] else MEDIUM, 0, 60, True)
    hh = max(px(ui, 22, 16), hint["h"] + 2)
    parts = [row_h, sz["pw_h"], kh, hh]
    notice = None
    if ui["mode"] == "greeter" and ui["notice"] != "":
        notice = label(ui, ui["notice"], px(ui, 13, 10), MEDIUM, 0, 60, True)
        parts.append(notice["h"])
    end
    total = -sp
    for p in parts:
        total = total + p + sp
    end
    if ui["mode"] == "greeter":
        bottom = h - (cround(150.0 * ui["u"]) - pyround((1.0 - e) * 24.0 * ui["u"]))
    else:
        bottom = h - (px(ui, 150, 110) - cround((1.0 - e) * 24.0 * ui["u"]))
    end
    top = bottom - total
    return {"boxes": boxes, "row_w": row_w, "row_h": row_h, "kbd": kbd, "kw": kw, "kh": kh, "hint": hint, "hh": hh,
            "notice": notice, "top": top, "sp": sp,
            "pw_y": top + row_h + sp, "kbd_y": top + row_h + sp + sz["pw_h"] + sp,
            "hint_y": top + row_h + sp + sz["pw_h"] + sp + kh + sp}
end

# Posun pole pri zatreseni: okraje 2*dx na jedne strane, GTK_ALIGN_CENTER drzi stred
function field_x(ui, w, sz):
    dx = ui["shake"]
    ms = max(0, 2 * dx)
    me = max(0, -2 * dx)
    return ms + cdiv(w - ms - me - field_w(ui, sz), 2)
end

function field_rect(w, h, ui):
    sz = sizes(ui, w, h)
    m = login_layout(ui, w, h, sz, 1.0)
    return [field_x(ui, w, sz), m["pw_y"], field_w(ui, sz), sz["pw_h"]]
end

function draw_login(cr, ui, bd, w, h, sz, e):
    m = login_layout(ui, w, h, sz, e)
    call draw_users(cr, ui, bd, w, sz, m["top"], m["boxes"], m["row_w"], m["row_h"])
    call draw_field(cr, ui, bd, sz, field_x(ui, w, sz), m["pw_y"])
    x = cdiv(w - m["kw"], 2)
    y = m["kbd_y"]
    kh = m["kh"]
    for k in m["kbd"]:
        if k[0] == "caps":
            icon = px(ui, 16, 12)
            iy = y + cdiv(kh - icon, 2)
            s = Float(icon)
            call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.30)
            call icon_caps(cr, Float(x) + s / 2.0, Float(iy) + s / 2.0 + 1.0, s)
            call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
            call icon_caps(cr, Float(x) + s / 2.0, Float(iy) + s / 2.0, s)
            lx = x + icon + px(ui, 6, 4)
            call draw_label(cr, ui, k[3], lx, y, k[3]["w"], kh, [1.0, 1.0, 1.0, 1.0], [1, 3, 0.7])
        else:
            cy = y + cdiv(kh - k[2], 2)
            hover = ui["hover"] == "chip"
            call frost(cr, bd, Float(x), Float(cy), Float(k[1]), Float(k[2]), Float(k[2]) * 0.5, 0.16 + (0.06 if hover else 0.0), 0.18)
            call draw_label(cr, ui, k[3], x + px(ui, 10, 7), cy + px(ui, 3, 2), k[1] - 2 * px(ui, 10, 7), k[2] - 2 * px(ui, 3, 2),
                            [1.0, 1.0, 1.0, 1.0], shadow_spec(ui))
            ui["hits"].append([x, cy, k[1], k[2], ["chip", 0]])
        end
        x = x + k[1] + px(ui, 14, 9)
    end
    hint = m["hint"]
    hw = hint["w"] + 20
    hx = cdiv(w - hw, 2)
    hy = m["hint_y"]
    if ui["error"] and ui["hint"] != "":
        call rounded(cr, Float(hx), Float(hy), Float(hw), Float(m["hh"]), 9.0)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
        call cairo.fill(cr)
    end
    if ui["hint"] != "":
        color = [1.0, 0.7058823529411765, 0.6784313725490196, 1.0] if ui["error"] else [1.0, 1.0, 1.0, 0.88]
        call draw_label(cr, ui, hint, hx + 10, hy + 1, hint["w"], m["hh"] - 2, color, shadow_spec(ui))
    end
    if m["notice"] != None:
        n = m["notice"]
        call draw_label(cr, ui, n, cdiv(w - n["w"], 2), hy + m["hh"] + m["sp"], n["w"], n["h"], [1.0, 1.0, 1.0, 0.78], shadow_spec(ui))
    end
    return 0
end

# Kreslit pres skupinu s pruhlednosti widgetu (gtk_widget_set_opacity), pri 1 primo
function begin_opacity(cr, a, x, y, w, h):
    if a >= 1.0:
        return False
    end
    call material_group(cr, x, y, w, h)
    return True
end

function end_opacity(cr, grouped, a):
    if grouped:
        call end_group(cr, a)
    end
    return 0
end

# ---- cela plocha -----------------------------------------------------------------------------------

# Zamek v klidu se setricem jineho stylu nez "desktop": X11 tehdy ukazuje okno setrice, dialog az po vstupu
function saver_idle(ui):
    return ui["mode"] == "lock" and ui["saver"] != "desktop" and ui["reveal"] <= 0.0 and ui["rev_to"] <= 0.0
end

# Testy: setric zacal pred `elapsed` sekundami
function saver_start(ui, elapsed):
    call saver.saver_init(ui["saver"], "")
    saver.S["start"] = saver.S["start"] - elapsed
    state["saver"] = ui["saver"]
    return 0
end

function frame(cr, w, h, ui, bd):
    ui["hits"] = []
    state["hint_style"] = ui["mode"]
    if saver_idle(ui):
        if state["saver"] != ui["saver"]:
            call saver.saver_init(ui["saver"], "")
            state["saver"] = ui["saver"]
        end
        call saver.draw(cr, w, h, True)
        return 0
    end
    sz = sizes(ui, w, h)
    e = ease(ui["reveal"])
    # tapeta ztmavena o 0.10 + 0.14 e (X11: tapeta a pres ni cerna): cerny podklad a tapeta s alfou jsou jeden
    # pruchod pres celou plochu mene (rozdil zaokrouhleni nejvys 1)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    if e == 0.0 or e == 1.0:
        # v klidu i ve vyzve hotova ztmavena kopie: snimek ji jen zkopiruje
        call cairo.set_source_surface(cr, dimmed(bd, e), 0.0, 0.0)
        call cairo.paint(cr)
        call cairo.set_operator(cr, cairo.OPERATOR_OVER)
    else:
        call dim_paint(cr, bd, e)
    end
    if ui["leaving"]:
        return 0
    end
    call draw_clock(cr, ui, w, h, e)
    a = opacity8(e)
    # v prihlaseni je stav vpravo nahore videt i v klidu
    sa = 1.0 if ui["mode"] == "greeter" else a
    if sa > 0.0:
        call backdrop_soft(bd)
        g = begin_opacity(cr, sa, 0, 0, w, sz["pad"] + sz["status"] * 3)
        call draw_status(cr, ui, bd, w, sz)
        call end_opacity(cr, g, sa)
    end
    if a > 0.0:
        call backdrop_soft(bd)
        g = begin_opacity(cr, a, 0, h // 3, w, h - h // 3)
        call draw_login(cr, ui, bd, w, h, sz, e)
        call end_opacity(cr, g, a)
        g = begin_opacity(cr, a, 0, h - h // 4, w, h // 4)
        call draw_power(cr, ui, bd, w, h, sz)
        call end_opacity(cr, g, a)
    end
    return 0
end

function dim_paint(cr, bd, e):
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 1.0)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    call cairo.paint(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_OVER)
    call cairo.set_source_surface(cr, bd["sharp"], 0.0, 0.0)
    call cairo.paint_with_alpha(cr, 1.0 - (0.10 + 0.14 * e))
    return 0
end

function dimmed(bd, e):
    if bd.get("dim_e", -1.0) != e:
        if bd.get("dimmed") == None:
            # ARGB32 jako bufer wl_shm: kopie je prosty memcpy
            bd["dimmed"] = cairo.image_surface_create(cairo.FORMAT_ARGB32, bd["dw"], bd["dh"])
            call sys.device_scale(bd["dimmed"], bd["scale"])
        end
        dcr = cairo.create(bd["dimmed"])
        call dim_paint(dcr, bd, e)
        call cairo.destroy(dcr)
        bd["dim_e"] = e
    end
    return bd["dimmed"]
end

function paint(image, w, h, ui, bd):
    call sys.device_scale(image, ui["scale"])
    cr = cairo.create(image)
    call frame(cr, w, h, ui, bd)
    call cairo.destroy(cr)
    call sys.device_scale(image, 1.0)
    return 0
end

# ---- animace (casy z luxos-lock-ui.c / luxos-greeter) ------------------------------------------------

function prompt(ui, on):
    target = 1.0 if on else 0.0
    if ui["rev_to"] == target:
        return False
    end
    ui["rev_from"] = ui["reveal"]
    ui["rev_to"] = target
    ui["rev_start"] = glib.monotonic_time()
    if on:
        call typed(ui)
    end
    return True
end

function shake(ui):
    ui["shake_start"] = glib.monotonic_time()
    return 0
end

function typed(ui):
    ui["input_at"] = glib.monotonic_time()
    ui["caret"] = True
    return 0
end

function step(ui):
    now = glib.monotonic_time()
    more = False
    if ui["reveal"] != ui["rev_to"]:
        span = Float(tokens.MOTION["lock_enter"]) * 1000.0
        if ui["rev_to"] < ui["rev_from"]:
            # luxos-greeter odchazi do klidu pomaleji nez zamek
            span = 520000.0 if ui["mode"] == "greeter" else Float(tokens.MOTION["lock_leave"]) * 1000.0
        end
        p = min(1.0, Float(now - ui["rev_start"]) / span)
        ui["reveal"] = ui["rev_from"] + (ui["rev_to"] - ui["rev_from"]) * p
        more = p < 1.0
    end
    ui["shake"] = 0
    if ui["shake_start"] != 0:
        p = Float(now - ui["shake_start"]) / (Float(tokens.MOTION["shake"]) * 1000.0)
        if p >= 1.0:
            ui["shake_start"] = 0
        else:
            ui["shake"] = cround(math.sin(p * PI * 8.0) * (1.0 - p) * 16.0 * ui.get("u", 1.0))
            more = True
        end
    end
    # kurzor jako GtkEntry: sviti 800 ms, 400 ms ne, po 10 s bez vstupu uz jen sviti; ui["wake"] = ms do dalsi zmeny
    ui["wake"] = 0
    if saver_idle(ui) and state["saver"] == ui["saver"]:
        ui["wake"] = 1000 // saver.fps()
    end
    if ui["input_at"] != 0 and ui["reveal"] > 0.0:
        ms = (now - ui["input_at"]) // 1000
        if ms >= BLINK_TIMEOUT:
            ui["caret"] = True
        else:
            phase = ms % BLINK
            ui["caret"] = phase < BLINK * 2 // 3
            ui["wake"] = max(1, (BLINK * 2 // 3 - phase) if ui["caret"] else (BLINK - phase))
        end
    end
    return more
end
