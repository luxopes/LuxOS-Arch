# lsl: internal-abi
# LuxOS - material z matneho skla pro plochy layer-shell na Waylandu (lista, Dock, vyskakovaci okna, oznameni):
# vyrez rozostrene tapety pod plochou, mlecny podklad, zavoj podle jasu vyrezu a odlesk. Bez XShape a bez snimani
# obrazovky; programy nacitaji `load luxos_material as material`.
# Cisla jsou stejna jako luxos-widgets.lsl on_card_draw a luxos-glass.c glass_paint (gpt-features-1.1.1),
# test tests/test_luxos_material.py porovnava pixely s C (tests/glass-ref/luxos-glass-material.c).
#
#   material.wallpaper_path(vystup)      tapeta z ~/.config/luxos/appearance.conf: WALLPAPER_<VYSTUP>, pak WALLPAPER,
#                                        jinak vychozi tapeta LuxOS podle rezimu (~/.config/luxos/appearance); "" = neni
#   material.wallpaper_mode(vystup)      WALLPAPER_MODE_<VYSTUP>, pak WALLPAPER_MODE: fill (vychozi), fit, center, tile
#   material.wallpaper_color()           WALLPAPER_COLOR=#rrggbb (plocha bez tapety a okraje u fit/center) -> [r, g, b]
#   material.layer_position(anchor, okraje, w, h, plocha)
#                                        [x, y, w, h] plochy layer-shell na vystupu: anchor ANCHOR_* (jako zwlr_layer_surface_v1),
#                                        okraje [nahore, vpravo, dole, vlevo], w/h 0 = roztazeni mezi protilehle kotvy,
#                                        plocha = [x, y, w, h] pouzitelne casti vystupu (cely vystup nebo bez exkluzivnich zon)
#   material.strip(vystup, out_w, out_h, x, y, w, h, polomer, ink, scale)
#                                        hotovy kousek skla [povrch ARGB32, svetle] pro obdelnik na vystupu, nebo None bez tapety;
#                                        ink -1 = barva textu podle tapety, 0 = bily text (tmave sklo), 1 = tmavy text;
#                                        scale = HiDPI (povrch ma device scale). Povrch patri mezipameti - nenicit, jen kreslit.
#   material.paint(cr, x, y, w, h, polomer, screen_x, screen_y, ink, sklo, mapa)
#                                        totez primo do cr (pod uz nakreslene pixely, DEST_OVER); vraci svetle
#   material.glass(cesta), material.map_for(sklo, out_w, out_h)   rozostrena tapeta a jeji mapa na vystup (fill)
#   material.map_mode(sklo, out_w, out_h, rezim)                    mapa pro rezim zobrazeni tapety (jako luxos-backdrop)
#   material.reload()                    zmena tapety nebo appearance.conf: zahodit mezipamet
#   material.forget_output(vystup)       vystup odpojen
#
# Vykon (LSL: Float v lokalnich promennych bez alokaci, GC zastavi svet): kazdy pixel se pocita jen pri zmene tapety
# (zmensenina GLASS["size"] px, ~5 tisic pixelu); vyrez, zavoj a odlesk kresli cairo v C jednou pro vystup, obdelnik
# a tapetu. Pri kresleni snimku se jen vykresli hotovy povrch.
load cairo, gtk, glib
load luxos_glib as lglib
load luxos_text as text
load luxos_tokens as tokens

ANCHOR_TOP = 1
ANCHOR_BOTTOM = 2
ANCHOR_LEFT = 4
ANCHOR_RIGHT = 8
DEFAULT_WALLPAPERS = "/usr/share/backgrounds/luxos"
STRIP_CACHE = 16
GLASS_CACHE = 4
OPERATOR_DEST_OVER = 7

MODES = ["fill", "fit", "center", "tile"]

# glasses: klic tapety -> [povrch RGB24, pixely IntArray, sirka, vyska, sirka tapety, vyska tapety]; strips: klic -> [povrch, svetle, vystup]
state = {"glasses": {}, "glass_order": [], "strips": {}, "strip_order": [], "conf": None}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function push_group(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_push_group"), ptr(cr))
    end
end

function pop_group_to_source(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_pop_group_to_source"), ptr(cr))
    end
end

function set_device_scale(surface, scale):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("cairo_surface_set_device_scale"), ptr(surface), Float(scale), Float(scale))
    end
end

function int_zeros(n):
    unsafe:
        return __lsl_int_zeros(n)
    end
end

function clamp(x, lo, hi):
    return max(lo, min(hi, x))
end

# ---- tapeta z nastaveni LuxOS -----------------------------------------------------------------

function config_dir():
    return glib.user_config_dir() + "/luxos"
end

function prefs():
    if state["conf"] == None:
        state["conf"] = text.parse_kv(lglib.read_text(config_dir() + "/appearance.conf"))
    end
    return state["conf"]
end

function unquote(value):
    v = value.strip()
    if len(v) >= 2 and (v[0] == "\"" or v[0] == "'") and v[-1] == v[0]:
        return v[1:-1]
    end
    return v
end

# Nazev vystupu jako cast klice: eDP-1 -> EDP_1, HDMI-A-1 -> HDMI_A_1
function output_key(name):
    out = ""
    for ch in String(name).upper():
        c = ord(ch)
        if (c >= 65 and c <= 90) or (c >= 48 and c <= 57):
            out = out + ch
        else:
            out = out + "_"
        end
    end
    return out
end

function wallpaper_path(output):
    p = prefs()
    for key in ["WALLPAPER_" + output_key(output), "WALLPAPER"]:
        value = unquote(p.get(key, ""))
        if value != "" and exists(value):
            return value
        end
    end
    mode = "light"
    if lglib.read_text(config_dir() + "/appearance").strip() == "dark":
        mode = "dark"
    end
    path = DEFAULT_WALLPAPERS + "/luxos-" + mode + ".jpg"
    if exists(path):
        return path
    end
    return ""
end

function wallpaper_mode(output):
    p = prefs()
    for key in ["WALLPAPER_MODE_" + output_key(output), "WALLPAPER_MODE"]:
        value = unquote(p.get(key, "")).lower()
        if value == "centre":
            value = "center"
        end
        if value in MODES:
            return value
        end
    end
    return "fill"
end

function hex_digit(ch):
    return "0123456789abcdef".find(ch.lower())
end

function wallpaper_color():
    value = unquote(prefs().get("WALLPAPER_COLOR", ""))
    if len(value) == 7 and value[0] == "#":
        rgb = []
        for i in [1, 3, 5]:
            hi = hex_digit(value[i])
            lo = hex_digit(value[i + 1])
            if hi < 0 or lo < 0:
                return tokens.GLASS["fallback"]
            end
            rgb.append(Float(hi * 16 + lo) / 255.0)
        end
        return rgb
    end
    return tokens.GLASS["fallback"]
end

# ---- rozostrena zmensenina ----------------------------------------------------------------------

# Dva pruchody filtru 1-4-6-4-1 (vodorovne, svisle), po druhem desaturace; pixely 0x..RRGGBB.
# Barva se uklada jako bajt stejne jako cairo_set_source_rgb + vyplneni v C (16 bitu se zaokrouhlenim,
# horni bajt). Typovana pole: pristup bez kontroly typu je v teto smycce asi 30x rychlejsi.
function blur(src, w, h):
    g = tokens.GLASS
    FloatArray(weights) = FloatArray()
    for v in g["weights"]:
        weights.append(Float(v))
    end
    norm = 0.0
    for k in range(5):
        norm = norm + weights[k]
    end
    norm = norm * 255.0
    floor = Float(g["floor"])
    keep = Float(g["keep"])
    luma = Float(g["luma"])
    IntArray(pix) = src
    for axis in range(2):
        IntArray(dst) = int_zeros(w * h)
        for y in range(h):
            row = y * w
            for x in range(w):
                r = 0.0
                gr = 0.0
                b = 0.0
                for k in range(5):
                    i = 0
                    if axis == 0:
                        i = x + k - 2
                        if i < 0:
                            i = 0
                        elif i > w - 1:
                            i = w - 1
                        end
                        i = row + i
                    else:
                        i = y + k - 2
                        if i < 0:
                            i = 0
                        elif i > h - 1:
                            i = h - 1
                        end
                        i = i * w + x
                    end
                    px = pix[i]
                    wk = weights[k]
                    r = r + Float((px >> 16) & 255) * wk / norm
                    gr = gr + Float((px >> 8) & 255) * wk / norm
                    b = b + Float(px & 255) * wk / norm
                end
                if axis == 1:
                    lum = 0.2126 * r + 0.7152 * gr + 0.0722 * b
                    r2 = floor + (r * keep + lum * luma) * keep
                    g2 = floor + (gr * keep + lum * luma) * keep
                    b2 = floor + (b * keep + lum * luma) * keep
                    r = r2
                    gr = g2
                    b = b2
                end
                dst[row + x] = (0xff000000 | ((Int(r * 65535.0 + 0.5) >> 8) << 16) | ((Int(gr * 65535.0 + 0.5) >> 8) << 8)
                                | (Int(b * 65535.0 + 0.5) >> 8))
            end
        end
        pix = dst
    end
    return pix
end

# Tapeta -> [povrch RGB24, pixely, sirka, vyska]; None kdyz nejde nacist
function load_glass(path):
    size = tokens.GLASS["size"]
    pb = gtk.pixbuf_new_from_file_at_scale(path, size, size, True)
    if pb == 0:
        return None
    end
    pw = gtk.pixbuf_get_width(pb)
    ph = gtk.pixbuf_get_height(pb)
    dims = image_size(path)
    fb = tokens.GLASS["fallback"]
    surface = cairo.image_surface_create(cairo.FORMAT_RGB24, pw, ph)
    cr = cairo.create(surface)
    call cairo.set_source_rgb(cr, fb[0], fb[1], fb[2])
    call cairo.paint(cr)
    call gtk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call glib.object_unref(pb)
    pixels = blur(cairo.surface_to_intarray(surface), pw, ph)
    call cairo.surface_destroy(surface)
    return [cairo.intarray_to_rgb_surface(pixels, pw, ph), pixels, pw, ph, max(1, dims[0]), max(1, dims[1])]
end

# Rozmery obrazku bez dekodovani pixelu
function image_size(path):
    unsafe:
        cell = __lsl_byte_zeros(8)
        base = __lsl_qbe_load64(__lsl_address(cell) + 24)
        format = __lsl_qbe_call3(__lsl_symbol("gdk_pixbuf_get_file_info"), __lsl_address(path) + 16, base, base + 4)
        if format == 0:
            return [0, 0]
        end
        return [__lsl_qbe_s32(__lsl_qbe_load32(base)), __lsl_qbe_s32(__lsl_qbe_load32(base + 4))]
    end
end

function glass(path):
    if path == "" or not exists(path):
        return None
    end
    key = path + "|" + String(lglib.stat(path))
    hit = state["glasses"].get(key)
    if hit != None:
        return hit
    end
    hit = load_glass(path)
    if hit == None:
        return None
    end
    while len(state["glass_order"]) >= GLASS_CACHE:
        old = state["glass_order"].pop(0)
        call cairo.surface_destroy(state["glasses"][old][0])
        call state["glasses"].pop(old)
    end
    state["glasses"][key] = hit
    state["glass_order"].append(key)
    return hit
end

# Mapa [sirka, vyska, meritko, posun x, posun y] zmenseniny na vystup out_w x out_h (styl "priblizit": vyplni
# vystup, prebytek orizne); souradnice jsou mistni na vystupu
function map_for(gl, out_w, out_h):
    pw = Float(gl[2])
    ph = Float(gl[3])
    mw = Float(max(1, out_w))
    mh = Float(max(1, out_h))
    sc = min(pw / mw, ph / mh)
    return [pw, ph, sc, (pw - mw * sc) / 2.0, (ph - mh * sc) / 2.0]
end

# Totez pro rezim zobrazeni tapety: fit = cela tapeta s okraji, center a tile = puvodni velikost
# (tile bez opakovani, sklo je rozostrene)
function map_mode(gl, out_w, out_h, mode):
    if mode == "fill":
        return map_for(gl, out_w, out_h)
    end
    pw = Float(gl[2])
    ph = Float(gl[3])
    mw = Float(max(1, out_w))
    mh = Float(max(1, out_h))
    sc = pw / Float(gl[4])
    if mode == "fit":
        sc = max(pw / mw, ph / mh)
    end
    if mode == "tile":
        return [pw, ph, sc, 0.0, 0.0]
    end
    return [pw, ph, sc, (pw - mw * sc) / 2.0, (ph - mh * sc) / 2.0]
end

# ---- volba skla a zavoj (glass_stats, glass_veil) -----------------------------------------------

# [nejtmavsi jas, nejvyssi RMS energie, prumerny jas] vyrezu sx, sy, sw, sh zmenseniny
function stats(gl, sx, sy, sw, sh):
    IntArray(pixels) = gl[1]
    pw = gl[2]
    ph = gl[3]
    lo = 1.0
    hi = 0.0
    total = 0.0
    count = 0
    y0 = Int(max(0.0, sy))
    y1 = Int(min(Float(ph - 1), sy + sh + 1.0))
    x0 = Int(max(0.0, sx))
    x1 = Int(min(Float(pw - 1), sx + sw + 1.0))
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px = pixels[y * pw + x]
            r = Float((px >> 16) & 255) / 255.0
            g = Float((px >> 8) & 255) / 255.0
            b = Float(px & 255) / 255.0
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            # RMS drzi rezervu i pro syte cervene/modre pozadi (prostemu prumeru by uniklo)
            energy = 0.2126 * r * r + 0.7152 * g * g + 0.0722 * b * b
            peak = 1.0
            for step in range(6):
                peak = (peak + energy / peak) / 2.0
            end
            lo = min(lo, lum)
            hi = max(hi, peak)
            total = total + lum
            count = count + 1
        end
    end
    return [lo, hi, total / Float(max(1, count))]
end

# Sila zavoje: svetle sklo (tmavy text) bily zavoj, tmave sklo (bily text) cerny
function veil(st, light):
    if light:
        return clamp((tokens.GLASS["veil_light"] - st[0]) / max(0.001, 1.0 - st[0]), 0.0, 1.0)
    end
    return clamp(1.0 - tokens.GLASS["veil_dark"] / max(0.001, st[1]), 0.0, 1.0)
end

# ---- kresleni ----------------------------------------------------------------------------------

function rounded_path(cr, x, y, w, h, radius):
    call cairo.new_path(cr)
    radius = min(radius, min(w, h) / 2.0)
    if radius > 0.0:
        pi = cairo.PI
        call cairo.arc(cr, x + w - radius, y + radius, radius, -pi / 2.0, 0.0)
        call cairo.arc(cr, x + w - radius, y + h - radius, radius, 0.0, pi / 2.0)
        call cairo.arc(cr, x + radius, y + h - radius, radius, pi / 2.0, pi)
        call cairo.arc(cr, x + radius, y + radius, radius, pi, 3.0 * pi / 2.0)
        call cairo.close_path(cr)
    else:
        call cairo.rectangle(cr, x, y, w, h)
    end
    return 0
end

# Karta skla (x, y, w, h v souradnicich cr; screen_x/y = jeji roh na vystupu) pod uz nakreslene pixely.
# Vrstvy se skladaji do skupiny a ta jde cela pod obsah (DEST_OVER), jako glass_paint v C.
function paint(cr, x, y, w, h, radius, screen_x, screen_y, ink, gl, m):
    x = Float(x)
    y = Float(y)
    w = Float(w)
    h = Float(h)
    sc = m[2]
    sx = clamp(m[3] + Float(screen_x) * sc, 0.5, m[0] - 0.5 - w * sc)
    sy = clamp(m[4] + Float(screen_y) * sc, 0.5, m[1] - 0.5 - h * sc)
    st = stats(gl, sx, sy, w * sc, h * sc)
    light = ink == 1
    if ink < 0:
        light = st[2] >= tokens.GLASS["light_mean"]
    end
    v = veil(st, light)
    base = tokens.GLASS["base"]
    sheen_alpha = tokens.GLASS["sheen"]
    call cairo.save(cr)
    call rounded_path(cr, x, y, w, h, Float(radius))
    call cairo.clip(cr)
    call push_group(cr)
    call cairo.set_source_rgba(cr, base[0], base[1], base[2], base[3])
    call cairo.paint(cr)
    call cairo.save(cr)
    call cairo.translate(cr, x, y)
    call cairo.scale(cr, 1.0 / sc, 1.0 / sc)
    call cairo.set_source_surface(cr, gl[0], -sx, -sy)
    call cairo.paint(cr)
    call cairo.restore(cr)
    tone = 0.0
    if light:
        tone = 1.0
    end
    call cairo.set_source_rgba(cr, tone, tone, tone, v)
    call cairo.paint(cr)
    sheen = cairo.pattern_create_linear(x, y, x + w * tokens.GLASS["sheen_reach"], y + h)
    call cairo.pattern_add_color_stop_rgba(sheen, 0.0, 1.0, 1.0, 1.0, sheen_alpha)
    call cairo.pattern_add_color_stop_rgba(sheen, 1.0, 1.0, 1.0, 1.0, 0.0)
    call cairo.set_source(cr, sheen)
    call cairo.paint(cr)
    call cairo.pattern_destroy(sheen)
    call pop_group_to_source(cr)
    call cairo.set_operator(cr, OPERATOR_DEST_OVER)
    call cairo.paint(cr)
    call cairo.restore(cr)
    return light
end

# ---- plochy layer-shell ------------------------------------------------------------------------

# Jedna osa: kotva na zacatek a/nebo konec, okraje, velikost (0 = roztazeni), pouzitelny usek [start, delka]
function place_axis(begin, finish, m0, m1, size, start, length):
    if size <= 0 and begin and finish:
        return [start + m0, max(0, length - m0 - m1)]
    end
    if begin and not finish:
        return [start + m0, size]
    end
    if finish and not begin:
        return [start + length - size - m1, size]
    end
    # bez kotvy nebo s obema kotvami a pevnou velikosti: na stred (okraje se neuplatni)
    return [start + (length - size) // 2, size]
end

function layer_position(anchor, margins, w, h, area):
    hx = place_axis((anchor & ANCHOR_LEFT) != 0, (anchor & ANCHOR_RIGHT) != 0, margins[3], margins[1], w, area[0], area[2])
    vy = place_axis((anchor & ANCHOR_TOP) != 0, (anchor & ANCHOR_BOTTOM) != 0, margins[0], margins[2], h, area[1], area[3])
    return [hx[0], vy[0], hx[1], vy[1]]
end

# ---- hotove kousky skla pro vystup ---------------------------------------------------------------

function strip(output, out_w, out_h, x, y, w, h, radius, ink, scale):
    path = wallpaper_path(output)
    gl = glass(path)
    if gl == None or w <= 0 or h <= 0:
        return None
    end
    mode = wallpaper_mode(output)
    key = (output + "|" + path + "|" + String(lglib.stat(path)) + "|" + mode + "|" + String([out_w, out_h, x, y, w, h, radius, ink, scale]))
    hit = state["strips"].get(key)
    if hit != None:
        return hit
    end
    s = max(1, Int(scale))
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, w * s, h * s)
    call set_device_scale(surface, s)
    cr = cairo.create(surface)
    light = paint(cr, 0, 0, w, h, radius, x, y, ink, gl, map_mode(gl, out_w, out_h, mode))
    call cairo.destroy(cr)
    call cairo.surface_flush(surface)
    while len(state["strip_order"]) >= STRIP_CACHE:
        call drop_strip(state["strip_order"][0])
    end
    hit = [surface, light, output]
    state["strips"][key] = hit
    state["strip_order"].append(key)
    return hit
end

function drop_strip(key):
    hit = state["strips"].pop(key)
    call state["strip_order"].remove(key)
    call cairo.surface_destroy(hit[0])
    return 0
end

function forget_output(output):
    for key in List(state["strip_order"]):
        if state["strips"][key][2] == output:
            call drop_strip(key)
        end
    end
    return 0
end

function reload():
    for key in List(state["strip_order"]):
        call drop_strip(key)
    end
    for key in state["glass_order"]:
        call cairo.surface_destroy(state["glasses"][key][0])
    end
    state["glasses"] = {}
    state["glass_order"] = []
    state["conf"] = None
    return 0
end
