# LuxOS - spolecna kresba zamku (luxos-lock) a prihlasovaci obrazovky (luxos-greeter) na Waylandu, vse cairem.
# Dva stavy: klid = ostra tapeta se zavojem nahore a dole, datum, velke hodiny a stav vpravo nahore (rozlozeni,
# sit, baterie); zadavani = rozmazana a ztmavena tapeta (prolnuti), avatar, jmeno, pole pro heslo, hlasky
# (chyba, Caps Lock, otisk prstu, zamceny ucet) a u prihlaseni navic uzivatele, relace a napajeni.
# Rozmery a barvy: tokens.LOCK (navrh 1.1.0, sekce zamku a prihlaseni).
#
#   draw.new_ui(mode)                     stav kresby; mode "lock" nebo "greeter"
#   draw.backdrop(cesta, w, h, scale)     ostra tapeta se zavojem v pixelech zarizeni (mezipamet podle tapety a velikosti)
#   draw.backdrop_soft(bd)                rozmazana verze (jednou; volat po prvnim snimku, ne pri kazdem)
#   draw.frame(cr, w, h, ui, bd)          cela plocha v logickych souradnicich; ui["hits"] = [[x, y, w, h, akce]]
#   draw.prompt(ui, on)                   prechod klid <-> zadavani (lock_enter / lock_leave)
#   draw.shake(ui)                        zatreseni pole a cerveny okraj po chybe
#   draw.step(ui)                         posun animaci k aktualnimu casu; True = kreslit dalsi snimek
#   draw.field_rect(w, h, dx)             [x, y, w, h] pole pro heslo v klidove poloze (testy)
#
# Vykon: tapeta i rozmazani jsou hotove povrchy (rozmazani ve ctvrtinovem rozliseni, jednou na tapetu a velikost),
# hodiny s mekkym stinem jsou povrch platny do zmeny minuty; snimek jen sklada povrchy a par kratkych textu.
load cairo, pango, gtk, glib, math
load luxos_glib as lglib
load luxos_gtk as lgtk
load luxos_material as material
load luxos_tokens as tokens
load luxos_lock_sys as sys

PI = cairo.PI
L = tokens.LOCK
BACKDROPS = 4

state = {"backdrops": {}, "order": [], "clock_key": "", "clock": None, "layouts": {}, "sprites": {}, "sprite_order": []}


function px(u, v, lo):
    return max(Float(lo), Float(Int(Float(v) * u + 0.5)))
end

function unit(h):
    return max(L["unit_floor"], Float(h) / 1080.0)
end

function font(ui, weight, size):
    return ui["font"] + ",Inter,Cantarell,Noto Sans " + weight + " " + String(Int(size + 0.5)) + "px"
end

function new_ui(mode):
    return {"mode": mode, "font": "Inter", "scale": 1.0, "clock": "", "date": "", "battery": None, "net": None,
            "layout": "", "name": "", "face": None, "length": 0, "placeholder": "", "hint": "", "hint_icon": "",
            "error": False, "caps": False, "caps_text": "", "busy": False, "lockout": False, "users": [], "sel": 0,
            "session": "", "sessions": [], "session_sel": 0, "menu": False, "power": [], "notice": "",
            "hover": "", "leaving": False, "visible_text": False, "initial": "", "hits": [],
            "reveal": 0.0, "rev_from": 0.0, "rev_to": 0.0, "rev_start": 0, "shake": 0.0, "shake_start": 0,
            "rim": 0.0, "rim_start": 0, "spin_start": 0}
end

function rgba(cr, c, alpha):
    call cairo.set_source_rgba(cr, Float(c[0]) / 255.0, Float(c[1]) / 255.0, Float(c[2]) / 255.0, Float(c[3]) * alpha)
    return 0
end

# Jedno rozvrzeni na popis pisma po celou dobu behu: nove PangoContext pri kazdem textu by pokazde znovu
# hledalo pismo (fontconfig) a snimek by stal milisekundy navic. Nevolat layout_unref.
function text_layout(cr, text, desc):
    layout = state["layouts"].get(desc)
    if layout == None:
        layout = pango.cairo_create_layout(cr)
        call pango.layout_set_font(layout, desc)
        state["layouts"][desc] = layout
    else:
        call pango.cairo_update_layout(cr, layout)
        call pango.layout_set_width(layout, -1)
        call pango.layout_set_ellipsize(layout, 0)
    end
    call pango.layout_set_text(layout, text)
    return layout
end

# Bily text s mekkym stinem o pixel niz (citelny i na svetle tapete)
function show(cr, layout, x, y, alpha, u):
    call cairo.move_to(cr, x, y + max(1.0, u))
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.22 * alpha)
    call pango.cairo_show_layout(cr, layout)
    call cairo.move_to(cr, x, y)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alpha)
    call pango.cairo_show_layout(cr, layout)
    return 0
end

function text_at(cr, text, desc, x, y, alpha, u):
    layout = text_layout(cr, text, desc)
    size = pango.layout_get_pixel_size(layout)
    call show(cr, layout, x, y, alpha, u)
    return size
end

function centered(cr, text, desc, cx, y, alpha, u):
    layout = text_layout(cr, text, desc)
    size = pango.layout_get_pixel_size(layout)
    call show(cr, layout, cx - Float(size[0]) / 2.0, y, alpha, u)
    return size
end

function text_width(cr, text, desc):
    layout = text_layout(cr, text, desc)
    size = pango.layout_get_pixel_size(layout)
    return Float(size[0])
end

function pill(cr, x, y, w, h):
    call material.rounded_path(cr, x, y, w, h, h / 2.0)
    return 0
end

function circle(cr, cx, cy, r):
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, 0.0, 2.0 * PI)
    return 0
end

function hit(ui, x, y, w, h, action):
    ui["hits"].append([x, y, w, h, action])
    return 0
end

# Hotovy obrazek prvku (avatar, tlacitko): kresli se jednou do povrchu, pak jen sklada. f(cr, a) kresli v souradnicich
# plochy; obdelnik x, y, w, h ho musi obsahovat.
function sprite(cr, key, x, y, w, h, scale, f, a, alpha):
    x0 = Float(Int(x * scale)) / scale
    y0 = Float(Int(y * scale)) / scale
    key = key + "|" + String(Int((x - x0) * 64.0)) + "," + String(Int((y - y0) * 64.0)) + "@" + String(scale)
    s = state["sprites"].get(key)
    if s == None:
        s = cairo.image_surface_create(cairo.FORMAT_ARGB32, Int((w + 2.0) * scale + 0.5), Int((h + 2.0) * scale + 0.5))
        scr = cairo.create(s)
        call cairo.scale(scr, scale, scale)
        call cairo.translate(scr, -x0, -y0)
        call f(scr, a)
        call cairo.destroy(scr)
        call material.set_device_scale(s, scale)
        if len(state["sprite_order"]) >= 48:
            call cairo.surface_destroy(state["sprites"].pop(state["sprite_order"].pop(0)))
        end
        state["sprites"][key] = s
        state["sprite_order"].append(key)
    end
    call cairo.set_source_surface(cr, s, x0, y0)
    if alpha >= 1.0:
        call cairo.paint(cr)
    else:
        call cairo.paint_with_alpha(cr, alpha)
    end
    return 0
end

# ---- pozadi -------------------------------------------------------------------------------------

# Zavoj: nahore pod hodinami, uprostred nic, dole pod tlacitky
function scrim(cr, w, h):
    g = cairo.pattern_create_linear(0.0, 0.0, 0.0, Float(h))
    call cairo.pattern_add_color_stop_rgba(g, 0.0, 0.0, 0.0, 0.0, L["scrim_top"])
    call cairo.pattern_add_color_stop_rgba(g, L["scrim_top_end"], 0.0, 0.0, 0.0, 0.0)
    call cairo.pattern_add_color_stop_rgba(g, L["scrim_mid_end"], 0.0, 0.0, 0.0, 0.0)
    call cairo.pattern_add_color_stop_rgba(g, 1.0, 0.0, 0.0, 0.0, L["scrim_bottom"])
    call cairo.set_source(cr, g)
    call cairo.paint(cr)
    call cairo.pattern_destroy(g)
    return 0
end

# Tapeta zvetsena na celou plochu (styl vyplnit) v plnem rozliseni zarizeni
function paint_wallpaper(cr, path, dw, dh):
    fb = tokens.GLASS["fallback"]
    g = cairo.pattern_create_linear(0.0, 0.0, 0.0, Float(dh))
    call cairo.pattern_add_color_stop_rgba(g, 0.0, fb[0] * 0.8, fb[1] * 0.9, fb[2] * 1.6, 1.0)
    call cairo.pattern_add_color_stop_rgba(g, 1.0, fb[0] * 0.5, fb[1] * 0.5, fb[2] * 0.8, 1.0)
    call cairo.set_source(cr, g)
    call cairo.paint(cr)
    call cairo.pattern_destroy(g)
    if path == "" or not exists(path):
        return 0
    end
    dims = material.image_size(path)
    if dims[0] <= 0 or dims[1] <= 0:
        return 0
    end
    k = max(Float(dw) / Float(dims[0]), Float(dh) / Float(dims[1]))
    pb = gtk.pixbuf_new_from_file_at_scale(path, max(dw, Int(Float(dims[0]) * k + 0.5)), max(dh, Int(Float(dims[1]) * k + 0.5)), False)
    if pb == 0:
        return 0
    end
    pw = gtk.pixbuf_get_width(pb)
    ph = gtk.pixbuf_get_height(pb)
    call gtk.cairo_set_source_pixbuf(cr, pb, Float(dw - pw) / 2.0, Float(dh - ph) / 2.0)
    call cairo.paint(cr)
    call glib.object_unref(pb)
    return 0
end

function backdrop(path, w, h, scale):
    dw = max(1, Int(Float(w) * scale + 0.5))
    dh = max(1, Int(Float(h) * scale + 0.5))
    stamp = ""
    if path != "" and exists(path):
        stamp = String(lglib.stat(path))
    end
    key = path + "|" + stamp + "|" + String(dw) + "x" + String(dh) + "@" + String(scale)
    bd = state["backdrops"].get(key)
    if bd != None:
        return bd
    end
    sharp = cairo.image_surface_create(cairo.FORMAT_RGB24, dw, dh)
    cr = cairo.create(sharp)
    call paint_wallpaper(cr, path, dw, dh)
    call scrim(cr, dw, dh)
    call cairo.destroy(cr)
    call cairo.surface_flush(sharp)
    call material.set_device_scale(sharp, scale)
    bd = {"key": key, "sharp": sharp, "soft": None, "w": w, "h": h, "scale": scale, "dw": dw, "dh": dh}
    while len(state["order"]) >= BACKDROPS:
        old = state["backdrops"].pop(state["order"].pop(0))
        call cairo.surface_destroy(old["sharp"])
        if old["soft"] != None:
            call cairo.surface_destroy(old["soft"])
        end
    end
    state["backdrops"][key] = bd
    state["order"].append(key)
    return bd
end

# Rozmazani: ctvrtinova zmensenina, tri krabicove pruchody (~Gauss se sigmou L["blur"] px), sytost, zpet na plnou
# velikost s linearni interpolaci a ztmaveni. Jednou na tapetu a velikost; snimky pak jen skladaji.
function backdrop_soft(bd):
    if bd["soft"] != None:
        return 0
    end
    t0 = glib.monotonic_time()
    q = Float(L["blur_scale"])
    sw = max(1, Int(Float(bd["dw"]) / q + 0.5))
    sh = max(1, Int(Float(bd["dh"]) / q + 0.5))
    small = cairo.image_surface_create(cairo.FORMAT_RGB24, sw, sh)
    cr = cairo.create(small)
    call cairo.scale(cr, Float(sw) / Float(bd["w"]), Float(sh) / Float(bd["h"]))
    call cairo.set_source_surface(cr, bd["sharp"], 0.0, 0.0)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call cairo.surface_flush(small)
    call cairo.image_surface_blur(small, max(1, Int(3.0 * Float(L["blur"]) * bd["scale"] / q + 0.5)))
    call cairo.image_surface_saturate(small, L["saturate"])
    soft = cairo.image_surface_create(cairo.FORMAT_RGB24, bd["dw"], bd["dh"])
    cr = cairo.create(soft)
    call cairo.save(cr)
    call cairo.scale(cr, Float(bd["dw"]) / Float(sw), Float(bd["dh"]) / Float(sh))
    call cairo.set_source_surface(cr, small, 0.0, 0.0)
    call sys.source_pad(cr)
    call cairo.paint(cr)
    call cairo.restore(cr)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, L["dim"])
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call cairo.surface_destroy(small)
    call cairo.surface_flush(soft)
    call material.set_device_scale(soft, bd["scale"])
    bd["soft"] = soft
    return Int((glib.monotonic_time() - t0) / 1000)
end

function paint_surface(cr, surface, alpha, op):
    call cairo.set_source_surface(cr, surface, 0.0, 0.0)
    if op:
        call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    end
    if alpha >= 1.0:
        call cairo.paint(cr)
    else:
        call cairo.paint_with_alpha(cr, alpha)
    end
    call cairo.set_operator(cr, cairo.OPERATOR_OVER)
    return 0
end

function background(cr, bd, t):
    if t <= 0.0 or bd["soft"] == None:
        call paint_surface(cr, bd["sharp"], 1.0, True)
    elif t >= 1.0:
        call paint_surface(cr, bd["soft"], 1.0, True)
    else:
        call paint_surface(cr, bd["sharp"], 1.0, True)
        call paint_surface(cr, bd["soft"], t, False)
    end
    return 0
end

# ---- datum a hodiny -----------------------------------------------------------------------------

function clock_markup(ui, u):
    track = Int(Float(L["clock_tracking"]) * u * 1024.0)
    return "<span font_features=\"tnum\" letter_spacing=\"" + String(track) + "\">" + ui["clock"] + "</span>"
end

# Povrch s datem a hodinami (mekky stin 0 2px 12px, rozmazany v polovicnim rozliseni); [povrch, x, y]
function clock_surface(w, h, ui, u):
    scale = ui["scale"]
    key = ui["clock"] + "|" + ui["date"] + "|" + String(w) + "x" + String(h) + "@" + String(scale) + ui["font"]
    if key == state["clock_key"]:
        return state["clock"]
    end
    if state["clock"] != None:
        call cairo.surface_destroy(state["clock"][0])
    end
    probe = cairo.image_surface_create(cairo.FORMAT_ARGB32, 1, 1)
    pcr = cairo.create(probe)
    date = pango.cairo_create_layout(pcr)
    call pango.layout_set_font(date, font(ui, "Semi-Bold", px(u, L["date"], 12)))
    call pango.layout_set_text(date, ui["date"])
    big = px(u, L["clock"], 40)
    clock = pango.cairo_create_layout(pcr)
    call pango.layout_set_font(clock, font(ui, "Light", big))
    call pango.layout_set_markup(clock, clock_markup(ui, u))
    ds = pango.layout_get_pixel_size(date)
    cs = pango.layout_get_pixel_size(clock)
    # hodiny: horni hrana cislic (vyska verzalek Inter ~0.73) kousek pod datem; baseline je v px
    gap = px(u, 10.0, 7) - (Float(pango.layout_get_baseline(clock)) - 0.73 * big)
    pad = px(u, 24.0, 16)
    bw = Float(max(ds[0], cs[0])) + 2.0 * pad
    bh = Float(ds[1]) + gap + Float(cs[1]) + 2.0 * pad
    x0 = Float(Int((Float(w) - bw) / 2.0))
    y0 = Float(Int(Float(h) * L["date_y"] - pad))
    dw = max(1, Int(bw * scale + 0.5))
    dh = max(1, Int(bh * scale + 0.5))
    places = [[(bw - Float(ds[0])) / 2.0, pad, date, 0.90], [(bw - Float(cs[0])) / 2.0, pad + Float(ds[1]) + gap, clock, 0.95]]
    # stin: texty cerne do polovicniho rozliseni, rozmazat, pak pod bile texty
    half = cairo.image_surface_create(cairo.FORMAT_ARGB32, max(1, dw // 2), max(1, dh // 2))
    scr = cairo.create(half)
    call cairo.scale(scr, scale / 2.0, scale / 2.0)
    call cairo.set_source_rgba(scr, 0.0, 0.0, 0.0, 1.0)
    for p in places:
        call cairo.move_to(scr, p[0], p[1])
        call pango.cairo_show_layout(scr, p[2])
    end
    call cairo.destroy(scr)
    call cairo.surface_flush(half)
    call cairo.image_surface_blur(half, max(1, Int(9.0 * u * scale / 2.0 + 0.5)))
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, dw, dh)
    cr = cairo.create(surface)
    call cairo.scale(cr, scale, scale)
    call cairo.save(cr)
    call cairo.translate(cr, 0.0, px(u, 2.0, 1))
    call cairo.scale(cr, 2.0 / scale, 2.0 / scale)
    call cairo.set_source_surface(cr, half, 0.0, 0.0)
    call cairo.paint_with_alpha(cr, 0.25)
    call cairo.restore(cr)
    for p in places:
        call cairo.move_to(cr, p[0], p[1] + max(1.0, u))
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.14)
        call pango.cairo_show_layout(cr, p[2])
        call cairo.move_to(cr, p[0], p[1])
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, p[3])
        call pango.cairo_show_layout(cr, p[2])
    end
    call cairo.destroy(cr)
    call cairo.surface_destroy(half)
    call pango.layout_unref(date)
    call pango.layout_unref(clock)
    call cairo.destroy(pcr)
    call cairo.surface_destroy(probe)
    call material.set_device_scale(surface, scale)
    state["clock"] = [surface, x0, y0]
    state["clock_key"] = key
    return state["clock"]
end

function clock(cr, w, h, ui, u):
    c = clock_surface(w, h, ui, u)
    call cairo.set_source_surface(cr, c[0], c[1], c[2])
    call cairo.paint(cr)
    return 0
end

# ---- stav vpravo nahore: rozlozeni, sit, baterie ------------------------------------------------

function bolt_path(cr, cx, cy, k):
    call cairo.new_path(cr)
    for p in [[0.14, -1.0], [-0.58, 0.14], [-0.07, 0.14], [-0.14, 1.0], [0.58, -0.14], [0.07, -0.14]]:
        call cairo.line_to(cr, cx + p[0] * k, cy + p[1] * k)
    end
    call cairo.close_path(cr)
    return 0
end

# Obrys baterie s vyplni podle nabiti; nabijeni = blesk pres stred
function battery(cr, x, y, h, level, charging):
    w = h * 2.05
    lw = max(1.0, h * 0.09)
    bw = w - h * 0.22 - lw
    br = h * 0.26
    ix = x + lw
    iy = y + lw
    iw = bw - lw
    ih = h - 2.0 * lw
    fw = max(h * 0.12, (iw - h * 0.16) * min(1.0, max(0.0, Float(level) / 100.0)))
    call cairo.save(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.92)
    call cairo.set_line_width(cr, lw)
    call material.rounded_path(cr, x + lw / 2.0, y + lw / 2.0, bw, h - lw, br)
    call cairo.stroke(cr)
    call material.rounded_path(cr, x + w - h * 0.2, y + h * 0.33, h * 0.14, h * 0.34, h * 0.06)
    call cairo.fill(cr)
    if level <= 15 and not charging:
        call rgba(cr, tokens.COLORS["error"], 1.0)
    end
    call material.rounded_path(cr, ix + h * 0.08, iy + h * 0.08, fw, ih - h * 0.16, h * 0.14)
    call cairo.fill(cr)
    if charging:
        call bolt_path(cr, x + lw / 2.0 + bw / 2.0, y + h / 2.0, ih / 2.0 + lw * 0.6)
        call cairo.set_line_width(cr, max(1.0, h * 0.12))
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.55)
        call cairo.stroke_preserve(cr)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
        call cairo.fill(cr)
    end
    call cairo.restore(cr)
    return w
end

# Wi-Fi: tri oblouky a tecka, nesvitici dilky slabe; level 0-3
function wifi_icon(cr, cx, by, s, level):
    call cairo.save(cr)
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.set_line_width(cr, max(1.4, s * 0.13))
    for i in range(3):
        r = s * (0.30 + 0.30 * Float(i))
        call cairo.new_path(cr)
        call cairo.arc(cr, cx, by, r, -PI * 0.75, -PI * 0.25)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.92 if level > i else 0.32)
        call cairo.stroke(cr)
    end
    call circle(cr, cx, by - s * 0.02, max(1.2, s * 0.09))
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.92)
    call cairo.fill(cr)
    call cairo.restore(cr)
    return 0
end

# Kabel: tri ctverecky spojene do stromu (jako ikona site v liste)
function wired_icon(cr, cx, cy, s):
    q = s * 0.30
    call cairo.save(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.92)
    call material.rounded_path(cr, cx - q / 2.0, cy - s * 0.5, q, q, q * 0.2)
    call cairo.fill(cr)
    for dx in [-0.33, 0.33]:
        call material.rounded_path(cr, cx + dx * s - q / 2.0, cy + s * 0.5 - q, q, q, q * 0.2)
        call cairo.fill(cr)
    end
    call cairo.set_line_width(cr, max(1.2, s * 0.09))
    call cairo.move_to(cr, cx, cy - s * 0.5 + q)
    call cairo.line_to(cr, cx, cy)
    call cairo.move_to(cr, cx - s * 0.33, cy + s * 0.5 - q)
    call cairo.line_to(cr, cx - s * 0.33, cy)
    call cairo.line_to(cr, cx + s * 0.33, cy)
    call cairo.line_to(cr, cx + s * 0.33, cy + s * 0.5 - q)
    call cairo.stroke(cr)
    call cairo.restore(cr)
    return 0
end

function status(cr, w, ui, u):
    s = px(u, 16.0, 12)
    cy = px(u, L["status_top"], 12) + s / 2.0
    x = Float(w) - px(u, L["status_right"], 14)
    gap = px(u, L["status_gap"], 10)
    desc = font(ui, "Semi-Bold", px(u, L["status"], 11))
    bat = ui["battery"]
    if bat != None:
        bh = s * 0.72
        x = x - bh * 2.05
        call battery(cr, x, cy - bh / 2.0, bh, bat[0], bat[1])
        layout = text_layout(cr, String(bat[0]) + " %", desc)
        size = pango.layout_get_pixel_size(layout)
        x = x - px(u, 6.0, 4) - Float(size[0])
        call show(cr, layout, x, cy - Float(size[1]) / 2.0, 0.92, u)
        x = x - gap
    end
    net = ui["net"]
    if net != None and net[0] != "none":
        x = x - s
        if net[0] == "wifi":
            call wifi_icon(cr, x + s / 2.0, cy + s * 0.42, s, net[1])
        else:
            call wired_icon(cr, x + s / 2.0, cy, s * 0.9)
        end
        x = x - gap
    end
    if ui["layout"] != "":
        # kratky stitek v tenkem obrysu, ne plny box (jako lista)
        layout = text_layout(cr, ui["layout"], font(ui, "Bold", px(u, L["layout_label"], 10)))
        size = pango.layout_get_pixel_size(layout)
        lw = Float(size[0]) + px(u, 9.0, 7)
        lh = px(u, 16.0, 13)
        x = x - lw
        call material.rounded_path(cr, x + 0.5, cy - lh / 2.0 + 0.5, lw - 1.0, lh - 1.0, px(u, 4.0, 3))
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.55)
        call cairo.set_line_width(cr, 1.0)
        call cairo.stroke(cr)
        call show(cr, layout, x + (lw - Float(size[0])) / 2.0, cy - Float(size[1]) / 2.0, 0.92, u)
    end
    return 0
end

# ---- avatar ---------------------------------------------------------------------------------------

function avatar(cr, cx, cy, d, face, name, font_name, u, scale, alpha):
    m = px(u, 10.0, 6)
    key = "avatar|" + String(face) + "|" + name + "|" + font_name + "|" + String(d) + "|" + String(u)
    call sprite(cr, key, cx - d / 2.0 - m, cy - d / 2.0 - m, d + 2.0 * m, d + 2.0 * m + px(u, 6.0, 3), scale,
                avatar_paint, [cx, cy, d, face, name, font_name, u], alpha)
    return 0
end

function avatar_paint(cr, a):
    cx = a[0]
    cy = a[1]
    d = a[2]
    face = a[3]
    name = a[4]
    font_name = a[5]
    u = a[6]
    r = d / 2.0
    # stin 0 6px 18px: soustredne kruhy se slabou alfou
    for i in range(6):
        k = Float(i) / 5.0
        call circle(cr, cx, cy + px(u, 6.0, 3), r + px(u, 9.0, 5) * (1.0 - k))
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.05)
        call cairo.fill(cr)
    end
    call cairo.save(cr)
    call circle(cr, cx, cy, r)
    call cairo.clip(cr)
    if face != None:
        fw = Float(gtk.pixbuf_get_width(face))
        fh = Float(gtk.pixbuf_get_height(face))
        sc = max(d / fw, d / fh)
        call cairo.translate(cr, cx - fw * sc / 2.0, cy - fh * sc / 2.0)
        call cairo.scale(cr, sc, sc)
        call gtk.cairo_set_source_pixbuf(cr, face, 0.0, 0.0)
        call cairo.paint(cr)
    else:
        g = cairo.pattern_create_linear(cx - r, cy - r, cx + r, cy + r)
        call cairo.pattern_add_color_stop_rgba(g, 0.0, 0.30, 0.52, 1.0, 1.0)
        call cairo.pattern_add_color_stop_rgba(g, 1.0, 0.66, 0.42, 0.98, 1.0)
        call cairo.set_source(cr, g)
        call cairo.paint(cr)
        call cairo.pattern_destroy(g)
        initial = name.strip()
        if initial == "":
            initial = "?"
        end
        layout = text_layout(cr, initial[0].upper(), font_name + ",Inter,Cantarell,Noto Sans Medium " + String(Int(d * 0.42 + 0.5)) + "px")
        size = pango.layout_get_pixel_size(layout)
        call cairo.move_to(cr, cx - Float(size[0]) / 2.0, cy - Float(size[1]) / 2.0)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.97)
        call pango.cairo_show_layout(cr, layout)
    end
    call cairo.restore(cr)
    call circle(cr, cx, cy, r - 0.75)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.35)
    call cairo.set_line_width(cr, 1.5)
    call cairo.stroke(cr)
    return 0
end

# ---- ikony ------------------------------------------------------------------------------------------

function arrow(cr, cx, cy, s):
    call cairo.set_line_width(cr, max(1.5, s * 0.12))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.new_path(cr)
    call cairo.move_to(cr, cx - s * 0.32, cy)
    call cairo.line_to(cr, cx + s * 0.32, cy)
    call cairo.move_to(cr, cx + s * 0.04, cy - s * 0.27)
    call cairo.line_to(cr, cx + s * 0.32, cy)
    call cairo.line_to(cr, cx + s * 0.04, cy + s * 0.27)
    call cairo.stroke(cr)
    return 0
end

# Caps Lock: obrys sipky nahoru s carkou pod ni (jako na klavese)
function caps_icon(cr, cx, cy, s):
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

# Otisk prstu: soustredne oblouky otevrene dole
function fingerprint_icon(cr, cx, cy, s):
    call cairo.save(cr)
    call cairo.set_line_width(cr, max(1.2, s * 0.075))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    for i in range(4):
        r = s * (0.12 + 0.12 * Float(i))
        open = 0.55 - 0.08 * Float(i)
        call cairo.new_path(cr)
        call cairo.arc(cr, cx, cy + s * 0.06, r, PI * (0.5 + open), PI * (2.5 - open))
        call cairo.stroke(cr)
    end
    call cairo.move_to(cr, cx, cy + s * 0.06)
    call cairo.line_to(cr, cx, cy + s * 0.34)
    call cairo.stroke(cr)
    call cairo.restore(cr)
    return 0
end

# Zamek (zamceny ucet): telo a oblouk
function lock_icon(cr, cx, cy, s):
    call cairo.save(cr)
    call material.rounded_path(cr, cx - s * 0.36, cy - s * 0.06, s * 0.72, s * 0.52, s * 0.1)
    call cairo.fill(cr)
    call cairo.set_line_width(cr, max(1.3, s * 0.11))
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy - s * 0.12, s * 0.22, PI, 2.0 * PI)
    call cairo.line_to(cr, cx + s * 0.22, cy - s * 0.04)
    call cairo.move_to(cr, cx - s * 0.22, cy - s * 0.04)
    call cairo.line_to(cr, cx - s * 0.22, cy - s * 0.12)
    call cairo.stroke(cr)
    call cairo.restore(cr)
    return 0
end

function icon_power(cr, cx, cy, s):
    call cairo.set_line_width(cr, max(1.6, s * 0.10))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy + s * 0.04, s * 0.38, -PI / 2.0 + 0.62, -PI / 2.0 - 0.62 + 2.0 * PI)
    call cairo.stroke(cr)
    call cairo.move_to(cr, cx, cy - s * 0.46)
    call cairo.line_to(cr, cx, cy - s * 0.04)
    call cairo.stroke(cr)
    return 0
end

function icon_restart(cr, cx, cy, s):
    r = s * 0.38
    call cairo.set_line_width(cr, max(1.6, s * 0.10))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    a0 = -PI / 2.0 + 0.25
    a1 = -PI / 2.0 + 2.0 * PI - 0.75
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, a0, a1)
    call cairo.stroke(cr)
    ex = cx + r * math.cos(a1)
    ey = cy + r * math.sin(a1)
    tx = -math.sin(a1)
    ty = math.cos(a1)
    nx = math.cos(a1)
    ny = math.sin(a1)
    k = s * 0.22
    call cairo.move_to(cr, ex + tx * k * 0.9, ey + ty * k * 0.9)
    call cairo.line_to(cr, ex + nx * k * 0.75 - tx * k * 0.25, ey + ny * k * 0.75 - ty * k * 0.25)
    call cairo.line_to(cr, ex - nx * k * 0.75 - tx * k * 0.25, ey - ny * k * 0.75 - ty * k * 0.25)
    call cairo.close_path(cr)
    call cairo.fill(cr)
    return 0
end

function icon_sleep(cr, cx, cy, s):
    r = s * 0.40
    call cairo.save(cr)
    call circle(cr, cx, cy, r)
    call cairo.clip(cr)
    call circle(cr, cx, cy, r)
    call cairo.move_to(cr, cx + r * 0.55 + r * 0.82, cy - r * 0.45)
    call cairo.arc(cr, cx + r * 0.55, cy - r * 0.45, r * 0.82, 0.0, 2.0 * PI)
    call lgtk.cairo_set_fill_rule(cr, 1)
    call cairo.fill(cr)
    call cairo.restore(cr)
    return 0
end

function chevron(cr, cx, cy, s, up):
    k = -1.0 if up else 1.0
    call cairo.set_line_width(cr, max(1.3, s * 0.16))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.new_path(cr)
    call cairo.move_to(cr, cx - s * 0.4, cy - k * s * 0.2)
    call cairo.line_to(cr, cx, cy + k * s * 0.2)
    call cairo.line_to(cr, cx + s * 0.4, cy - k * s * 0.2)
    call cairo.stroke(cr)
    return 0
end

function check_icon(cr, cx, cy, s):
    call cairo.set_line_width(cr, max(1.4, s * 0.16))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.new_path(cr)
    call cairo.move_to(cr, cx - s * 0.38, cy)
    call cairo.line_to(cr, cx - s * 0.1, cy + s * 0.3)
    call cairo.line_to(cr, cx + s * 0.4, cy - s * 0.3)
    call cairo.stroke(cr)
    return 0
end

function monitor_icon(cr, cx, cy, s):
    call cairo.set_line_width(cr, max(1.2, s * 0.1))
    call material.rounded_path(cr, cx - s * 0.48, cy - s * 0.38, s * 0.96, s * 0.62, s * 0.1)
    call cairo.stroke(cr)
    call cairo.move_to(cr, cx - s * 0.22, cy + s * 0.44)
    call cairo.line_to(cr, cx + s * 0.22, cy + s * 0.44)
    call cairo.stroke(cr)
    return 0
end

# ---- rozmisteni -------------------------------------------------------------------------------------

# Svisle polohy shluku pro zadavani: avatar uprostred na avatar_y, pod nim jmeno, pole a hlasky
function metrics(w, h):
    u = unit(h)
    d = px(u, L["avatar"], 64)
    ay = Float(Int(Float(h) * L["avatar_y"]))
    name_y = ay + d / 2.0 + px(u, L["name_gap"], 9)
    name_h = Float(Int(px(u, L["name"], 13) * 1.3 + 0.5))
    fw = px(u, L["field_w"], 220)
    fh = px(u, L["field_h"], 30)
    fy = name_y + name_h + px(u, L["name_gap"], 9)
    return {"u": u, "d": d, "ay": ay, "name_y": name_y, "fx": Float(Int((Float(w) - fw) / 2.0)), "fy": fy, "fw": fw,
            "fh": fh, "my": fy + fh + px(u, L["message_gap"], 7)}
end

function field_rect(w, h, dx):
    m = metrics(w, h)
    return [m["fx"] + dx, m["fy"], m["fw"], m["fh"]]
end

# ---- pole pro heslo ---------------------------------------------------------------------------------

function field(cr, ui, m, y):
    u = m["u"]
    x = m["fx"] + ui["shake"] * u
    fw = m["fw"]
    fh = m["fh"]
    dim = 1.0
    if ui["busy"] or ui["lockout"]:
        dim = 0.6
    end
    # pole: svetle sklo nad rozmazanou tapetou, vnitrni okraj svetlejsi nahore, prstenec zamereni venku
    call pill(cr, x - 1.0, y - 1.0, fw + 2.0, fh + 2.0)
    call cairo.set_line_width(cr, 2.0)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.55 * dim)
    if ui["rim"] > 0.0:
        call cairo.stroke_preserve(cr)
        call rgba(cr, tokens.COLORS["error"], 0.9 * ui["rim"])
    end
    call cairo.stroke(cr)
    call pill(cr, x, y, fw, fh)
    call rgba(cr, L["field_fill"], dim)
    call cairo.fill(cr)
    g = cairo.pattern_create_linear(0.0, y, 0.0, y + fh)
    call cairo.pattern_add_color_stop_rgba(g, 0.0, 1.0, 1.0, 1.0, 0.45 * dim)
    call cairo.pattern_add_color_stop_rgba(g, 1.0, 1.0, 1.0, 1.0, 0.15 * dim)
    call pill(cr, x + 0.5, y + 0.5, fw - 1.0, fh - 1.0)
    call cairo.set_source(cr, g)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    call cairo.pattern_destroy(g)

    pad = px(u, 16.0, 12)
    sd = px(u, L["submit"], 22)
    room = fw - pad - sd - px(u, 12.0, 8)
    length = ui["length"]
    if length == 0:
        layout = text_layout(cr, ui["placeholder"], font(ui, "Regular", px(u, L["field_text"], 12)))
        call pango.layout_set_width(layout, Int(room * 1024.0))
        call pango.layout_set_ellipsize(layout, 3)
        size = pango.layout_get_pixel_size(layout)
        call cairo.move_to(cr, x + pad, y + (fh - Float(size[1])) / 2.0)
        alpha = 0.70
        if ui["visible_text"]:
            alpha = 0.95
        end
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alpha * dim)
        call pango.cairo_show_layout(cr, layout)
    else:
        r = px(u, L["dot"], 6) / 2.0
        step = px(u, L["dot_pitch"], 10)
        count = min(length, Int(room / step))
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95 * dim)
        for i in range(count):
            call circle(cr, x + pad + r + Float(i) * step, y + fh / 2.0, r)
            call cairo.fill(cr)
        end
    end
    # odeslat: kruh vpravo, akcent kdyz je co odeslat; behem overeni tocici se oblouk
    cx = x + fw - px(u, 6.0, 4) - sd / 2.0
    cy = y + fh / 2.0
    if ui["busy"]:
        a = Float(glib.monotonic_time() - ui["spin_start"]) / 1000000.0 * 2.0 * PI * 1.1
        call cairo.set_line_width(cr, max(1.6, 2.0 * u))
        call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
        call cairo.new_path(cr)
        call cairo.arc(cr, cx, cy, px(u, 8.0, 6), a, a + PI * 1.4)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.9)
        call cairo.stroke(cr)
    elif not ui["lockout"]:
        call circle(cr, cx, cy, sd / 2.0)
        if length > 0 or ui["visible_text"]:
            call rgba(cr, tokens.COLORS["accent"], 1.0)
        else:
            call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.25)
        end
        call cairo.fill(cr)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
        call arrow(cr, cx, cy, sd * 0.62)
    end
    call hit(ui, x, y, fw, fh, ["field", 0])
    return 0
end

# ---- hlasky pod polem ---------------------------------------------------------------------------------

# Pilulka s textem (a ikonou): chyba svetle cervena, ostatni bile; tmavy podklad pro svetlou tapetu
function message(cr, w, y, text, icon, error, ui, u, alpha):
    desc = font(ui, "Semi-Bold", px(u, L["message"], 11))
    layout = text_layout(cr, text, desc)
    call pango.layout_set_width(layout, Int(Float(w) * 0.7 * 1024.0))
    call pango.layout_set_ellipsize(layout, 3)
    size = pango.layout_get_pixel_size(layout)
    tw = Float(size[0])
    th = Float(size[1])
    isz = 0.0
    if icon != "":
        isz = px(u, 16.0, 12)
    end
    gap = px(u, 6.0, 4) if icon != "" else 0.0
    padx = px(u, 10.0, 8)
    pady = px(u, 4.0, 3)
    total = isz + gap + tw
    x = Float(Int((Float(w) - total) / 2.0))
    ph = th + 2.0 * pady
    call material.rounded_path(cr, x - padx, y, total + 2.0 * padx, ph, px(u, L["radius_message"], 8))
    call rgba(cr, L["message_bg"], (1.0 if error else 0.75) * alpha)
    call cairo.fill(cr)
    c = tokens.COLORS["error_soft"] if error else tokens.COLORS["white"]
    call rgba(cr, c, (1.0 if error else 0.95) * alpha)
    cy = y + ph / 2.0
    if icon == "caps":
        call caps_icon(cr, x + isz / 2.0, cy, isz)
    elif icon == "fingerprint":
        call fingerprint_icon(cr, x + isz / 2.0, cy, isz)
    elif icon == "lock":
        call lock_icon(cr, x + isz / 2.0, cy, isz)
    end
    call cairo.move_to(cr, x + isz + gap, y + pady)
    call pango.cairo_show_layout(cr, layout)
    return ph
end

function messages(cr, w, y, ui, u, alpha):
    lines = []
    if ui["hint"] != "":
        lines.append([ui["hint"], ui["hint_icon"], ui["error"]])
    end
    if ui["caps"] and ui["hint"].find("Caps") < 0:
        lines.append([ui["caps_text"], "caps", False])
    end
    if ui["notice"] != "":
        lines.append([ui["notice"], "", False])
    end
    for line in lines:
        y = y + message(cr, w, y, line[0], line[1], line[2], ui, u, alpha) + px(u, 6.0, 4)
    end
    return y
end

# ---- prihlaseni: uzivatele, relace, napajeni ----------------------------------------------------------

function users_row(cr, w, ui, m):
    users = ui["users"]
    if len(users) < 2:
        return 0
    end
    u = m["u"]
    ds = px(u, L["avatar_small"], 48)
    gap = px(u, L["user_gap"], 20)
    cx = Float(w) / 2.0
    desc = font(ui, "Medium", px(u, 12.0, 10))
    for i in range(len(users)):
        k = i - ui["sel"]
        if k == 0:
            continue
        end
        side = 1.0 if k > 0 else -1.0
        x = cx + side * (m["d"] / 2.0 + gap + ds / 2.0 + Float(abs(k) - 1) * (ds + gap))
        if x < ds or x > Float(w) - ds:
            continue
        end
        other = users[i]
        alpha = 1.0 if ui["hover"] == "user" + String(i) else 0.72
        key = "user|" + String(other["face"]) + "|" + other["real"] + "|" + String(other["other"]) + "|" + String(ds) + desc
        call sprite(cr, key, x - (ds + gap) / 2.0, m["ay"] - ds / 2.0 - px(u, 10.0, 6), ds + gap, ds + px(u, 44.0, 30), ui["scale"],
                    user_paint, [x, m["ay"], ds, gap, other, ui, u, desc], alpha)
        call hit(ui, x - ds / 2.0 - gap / 2.0, m["ay"] - ds / 2.0, ds + gap, ds + px(u, 28.0, 20), ["user", i])
    end
    return 0
end

function user_paint(cr, a):
    x = a[0]
    ds = a[2]
    other = a[4]
    u = a[6]
    call avatar_paint(cr, [x, a[1], ds, other["face"], "+" if other["other"] else other["real"], a[5]["font"], u])
    layout = text_layout(cr, other["real"], a[7])
    call pango.layout_set_width(layout, Int((ds + a[3] - px(u, 4.0, 2)) * 1024.0))
    call pango.layout_set_ellipsize(layout, 3)
    size = pango.layout_get_pixel_size(layout)
    call show(cr, layout, x - Float(size[0]) / 2.0, a[1] + ds / 2.0 + px(u, 8.0, 5), 0.9, u)
    return 0
end

# Spodni rada prihlaseni: svisly stred tlacitek napajeni (a pilulky relace)
function bottom_row(h, u):
    d = px(u, L["power"], 34)
    label = Float(Int(px(u, L["power_label"], 10) * 1.35 + 0.5))
    return Float(h) - px(u, L["bottom"], 26) - label - px(u, 8.0, 5) - d / 2.0
end

function power_buttons(cr, w, h, ui, u):
    kinds = ui["power"]
    if len(kinds) == 0:
        return 0
    end
    d = px(u, L["power"], 34)
    cy = bottom_row(h, u)
    pitch = px(u, L["power_pitch"], 70)
    x = Float(w) / 2.0 - Float(len(kinds) - 1) * pitch / 2.0
    desc = font(ui, "Medium", px(u, L["power_label"], 10))
    label_h = Float(Int(px(u, L["power_label"], 10) * 1.35 + 0.5))
    for p in kinds:
        key = "power|" + p[0] + "|" + p[1] + "|" + String(ui["hover"] == p[0]) + "|" + String(u) + desc
        call sprite(cr, key, x - pitch / 2.0, cy - d / 2.0 - 2.0, pitch, d + px(u, 10.0, 6) + label_h + 4.0, ui["scale"],
                    power_paint, [p, x, cy, d, desc, ui["hover"] == p[0], u], 1.0)
        call hit(ui, x - pitch / 2.0, cy - d / 2.0, pitch, d + px(u, 8.0, 5) + label_h, [p[0], 0])
        x = x + pitch
    end
    return 0
end

function power_paint(cr, a):
    kind = a[0][0]
    x = a[1]
    cy = a[2]
    d = a[3]
    u = a[6]
    call circle(cr, x, cy, d / 2.0)
    call rgba(cr, L["power_tint"][kind], 1.25 if a[5] else 1.0)
    call cairo.fill(cr)
    call circle(cr, x, cy, d / 2.0 - 0.5)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.30)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.97)
    g = px(u, L["power_glyph"], 14)
    if kind == "suspend":
        call icon_sleep(cr, x, cy, g)
    elif kind == "reboot":
        call icon_restart(cr, x, cy, g)
    else:
        call icon_power(cr, x, cy, g)
    end
    call centered(cr, a[0][1], a[4], x, cy + d / 2.0 + px(u, 8.0, 5), 0.85, u)
    return 0
end

# Volba relace vlevo dole: pilulka "Relace: LuxOS" se sipkou, po kliknuti nabidka nad ni
function session_pill(cr, w, h, ui, u):
    if len(ui["sessions"]) < 2:
        return 0
    end
    ph = px(u, L["session_h"], 26)
    x = px(u, L["session_inset"], 20)
    y = bottom_row(h, u) - ph / 2.0
    desc = font(ui, "Medium", px(u, L["message"], 11))
    layout = text_layout(cr, ui["session"], desc)
    size = pango.layout_get_pixel_size(layout)
    icon = px(u, 14.0, 11)
    pad = px(u, 12.0, 9)
    pw = pad + icon + px(u, 8.0, 6) + Float(size[0]) + px(u, 10.0, 7) + icon * 0.8 + pad
    call pill(cr, x, y, pw, ph)
    call rgba(cr, L["glass_hover"] if ui["hover"] == "session" or ui["menu"] else L["field_fill"], 1.0)
    call cairo.fill(cr)
    call pill(cr, x + 0.5, y + 0.5, pw - 1.0, ph - 1.0)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.30)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    call monitor_icon(cr, x + pad + icon / 2.0, y + ph / 2.0, icon)
    tx = x + pad + icon + px(u, 8.0, 6)
    call cairo.move_to(cr, tx, y + (ph - Float(size[1])) / 2.0)
    call pango.cairo_show_layout(cr, layout)
    call chevron(cr, tx + Float(size[0]) + px(u, 10.0, 7) + icon * 0.4, y + ph / 2.0, icon * 0.7, ui["menu"])
    call hit(ui, x, y, pw, ph, ["session", 0])
    if ui["menu"]:
        call session_menu(cr, x, y, ui, u)
    end
    return 0
end

function session_menu(cr, x, bottom, ui, u):
    row = px(u, L["menu_row"], 24)
    pad = px(u, 5.0, 4)
    desc = font(ui, "Regular", px(u, L["message"], 11))
    mark = px(u, 22.0, 16)
    width = 0.0
    for name in ui["sessions"]:
        width = max(width, text_width(cr, name, desc))
    end
    mw = max(px(u, 180.0, 140), width + mark + px(u, 26.0, 20))
    mh = Float(len(ui["sessions"])) * row + 2.0 * pad
    my = bottom - px(u, 6.0, 4) - mh
    # stin a tmave sklo nabidky
    for i in range(4):
        k = Float(i + 1) * px(u, 3.0, 2)
        call material.rounded_path(cr, x - k / 2.0, my - k / 4.0 + k / 2.0, mw + k, mh + k, px(u, L["radius_m"], 9) + k / 2.0)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.05)
        call cairo.fill(cr)
    end
    call material.rounded_path(cr, x, my, mw, mh, px(u, L["radius_m"], 9))
    call cairo.set_source_rgba(cr, 0.12, 0.13, 0.18, 0.86)
    call cairo.fill(cr)
    call material.rounded_path(cr, x + 0.5, my + 0.5, mw - 1.0, mh - 1.0, px(u, L["radius_m"], 9))
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.16)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    y = my + pad
    for i in range(len(ui["sessions"])):
        if ui["hover"] == "menu" + String(i):
            call material.rounded_path(cr, x + pad, y, mw - 2.0 * pad, row, px(u, L["radius_xs"], 4))
            call rgba(cr, tokens.COLORS["accent"], 1.0)
            call cairo.fill(cr)
        end
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
        if i == ui["session_sel"]:
            call check_icon(cr, x + pad + mark / 2.0 + px(u, 2.0, 1), y + row / 2.0, px(u, 12.0, 9))
        end
        layout = text_layout(cr, ui["sessions"][i], desc)
        size = pango.layout_get_pixel_size(layout)
        call cairo.move_to(cr, x + pad + mark + px(u, 4.0, 3), y + (row - Float(size[1])) / 2.0)
        call pango.cairo_show_layout(cr, layout)
        call hit(ui, x, y, mw, row, ["menu", i])
        y = y + row
    end
    return 0
end

# ---- cela plocha ------------------------------------------------------------------------------------

# Kreslit pres skupinu omezenou na obdelnik (pruhlednost pri prolnuti), jinak primo
function begin_fade(cr, x, y, w, h, t):
    if t >= 1.0:
        return False
    end
    call cairo.save(cr)
    call cairo.rectangle(cr, x, y, w, h)
    call cairo.clip(cr)
    call material.push_group(cr)
    return True
end

function end_fade(cr, faded, t):
    if faded:
        call material.pop_group_to_source(cr)
        call cairo.paint_with_alpha(cr, t)
        call cairo.restore(cr)
    end
    return 0
end

function prompt_cluster(cr, w, h, ui, t):
    m = metrics(w, h)
    u = m["u"]
    rise = (1.0 - t) * px(u, L["rise"], 8)
    cx = Float(w) / 2.0
    layout = text_layout(cr, ui["name"], font(ui, "Semi-Bold", px(u, L["name"], 13)))
    call pango.layout_set_width(layout, Int(Float(w) * 0.6 * 1024.0))
    call pango.layout_set_ellipsize(layout, 3)
    size = pango.layout_get_pixel_size(layout)
    # prolnuti pres skupinu jen v obdelniku avatar..pole (s uzivateli), hlasky maji alfu samy
    bw = max(m["fw"], Float(size[0])) + px(u, 24.0, 16)
    if ui["mode"] == "greeter" and len(ui["users"]) > 1:
        bw = Float(w)
    end
    top = m["ay"] - m["d"] / 2.0 - px(u, 12.0, 8)
    faded = begin_fade(cr, cx - bw / 2.0, top + rise, bw, m["fy"] + m["fh"] + 4.0 - top, t)
    call cairo.save(cr)
    call cairo.translate(cr, 0.0, rise)
    call avatar(cr, cx, m["ay"], m["d"], ui["face"], ui["initial"] if ui["initial"] != "" else ui["name"], ui["font"], u, ui["scale"], 1.0)
    if ui["mode"] == "greeter":
        call users_row(cr, w, ui, m)
    end
    call show(cr, layout, cx - Float(size[0]) / 2.0, m["name_y"], 1.0, u)
    call field(cr, ui, m, m["fy"])
    call cairo.restore(cr)
    call end_fade(cr, faded, t)
    call messages(cr, w, m["my"] + rise, ui, u, t)
    if ui["mode"] == "greeter":
        top = bottom_row(h, u) - px(u, L["power"], 34) / 2.0 - px(u, 8.0, 6)
        faded = begin_fade(cr, 0.0, top, Float(w), Float(h) - top, t)
        call power_buttons(cr, w, h, ui, u)
        call session_pill(cr, w, h, ui, u)
        call end_fade(cr, faded, t)
    end
    return 0
end

function frame(cr, w, h, ui, bd):
    ui["hits"] = []
    u = unit(h)
    t = ui["reveal"]
    call background(cr, bd, t)
    if ui["leaving"]:
        return 0
    end
    call clock(cr, w, h, ui, u)
    call status(cr, w, ui, u)
    if t > 0.0:
        call prompt_cluster(cr, w, h, ui, t)
    end
    return 0
end

# ---- animace ------------------------------------------------------------------------------------------

function prompt(ui, on):
    target = 1.0 if on else 0.0
    if ui["rev_to"] == target:
        return False
    end
    ui["rev_from"] = ui["reveal"]
    ui["rev_to"] = target
    ui["rev_start"] = glib.monotonic_time()
    return True
end

function shake(ui):
    now = glib.monotonic_time()
    ui["shake_start"] = now
    ui["rim_start"] = now
    return 0
end

function step(ui):
    now = glib.monotonic_time()
    more = False
    if ui["reveal"] != ui["rev_to"]:
        span = tokens.MOTION["lock_enter"] if ui["rev_to"] > ui["rev_from"] else tokens.MOTION["lock_leave"]
        p = Float(now - ui["rev_start"]) / (Float(span) * 1000.0)
        if p >= 1.0:
            ui["reveal"] = ui["rev_to"]
        else:
            ui["reveal"] = ui["rev_from"] + (ui["rev_to"] - ui["rev_from"]) * tokens.cubic_bezier(tokens.LOCK_CURVE, p)
            more = True
        end
    end
    ui["shake"] = 0.0
    if ui["shake_start"] != 0:
        p = Float(now - ui["shake_start"]) / (Float(tokens.MOTION["shake"]) * 1000.0)
        if p >= 1.0:
            ui["shake_start"] = 0
        else:
            ui["shake"] = Float(Int(math.sin(p * 2.0 * PI * Float(L["shake_cycles"])) * (1.0 - p) * Float(L["shake_px"]) + 0.5))
            more = True
        end
    end
    ui["rim"] = 0.0
    if ui["rim_start"] != 0:
        ms = Float(now - ui["rim_start"]) / 1000.0
        hold = Float(L["error_rim"])
        if ms >= hold:
            ui["rim_start"] = 0
        else:
            ui["rim"] = min(1.0, (hold - ms) / 200.0)
            more = True
        end
    end
    if ui["busy"]:
        if ui["spin_start"] == 0:
            ui["spin_start"] = now
        end
        more = True
    else:
        ui["spin_start"] = 0
    end
    return more
end
