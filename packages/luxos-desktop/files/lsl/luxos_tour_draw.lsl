# LuxOS - kresleni ilustraci Prohlidky LuxOS (luxos-tour.lsl) v cairo, bez obrazku: virtualni plocha 640 x 300,
# barvy podle svetleho/tmaveho vzhledu, text pres Pango, ikony aplikaci z motivu (jinak barevna dlazdice).
#
#   p = painter(cr, widget, dark)     kontext jedne ilustrace (barvy, pismo widgetu)
#   draw_page(p, index, mode)         stranka 0-8; mode = vybrany vzhled na strance Svetly/Tmavy/Auto
load env, math
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo, pango
load luxos_i18n as i18n

VW = 640.0
VH = 300.0
PI = 3.141592653589793
ACCENT = [0.24, 0.48, 1.0]
VIOLET = [0.55, 0.36, 1.0]
# Logo LuxOS (luxos-branding/files/logo/luxos-logo.svg, viewBox 256)
LOGO_PATH = "M246.27 209.91C188.18 163.23 147.07 104.71 133.55 30.45C116.12 140.58 158.36 161.65 246.27 209.91ZM8.09 211.18C89.02 173.90 133.08 136.86 126.09 40.64C105.95 110.22 62.88 165.17 8.09 211.18ZM248.64 226.09C158.26 151.17 105.77 146.57 13.73 222.82C95.86 182.21 167.60 183.49 248.64 226.09Z"
WHITE = [1.0, 1.0, 1.0, 1.0]

icons = {}
logo_ops = []

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

# ---- barvy a tvary ------------------------------------------------------------------------------------------

function rgba(c, a=1.0):
    return [c[0], c[1], c[2], a]
end

function hex_byte(pair):
    digits = "0123456789abcdef"
    return digits.find(pair[0:1].lower()) * 16 + digits.find(pair[1:2].lower())
end

function hexc(h, a=1.0):
    return [Float(hex_byte(h[1:3])) / 255.0, Float(hex_byte(h[3:5])) / 255.0, Float(hex_byte(h[5:7])) / 255.0, a]
end

function src(cr, c):
    a = 1.0
    if len(c) > 3:
        a = c[3]
    end
    return cairo.set_source_rgba(cr, c[0], c[1], c[2], a)
end

function rrect(cr, x, y, w, h, r):
    r = max(0.0, min(Float(r), w / 2.0, h / 2.0))
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("cairo_new_sub_path"), ptr(cr))
    end
    call cairo.arc(cr, x + w - r, y + r, r, -PI / 2.0, 0.0)
    call cairo.arc(cr, x + w - r, y + h - r, r, 0.0, PI / 2.0)
    call cairo.arc(cr, x + r, y + h - r, r, PI / 2.0, PI)
    call cairo.arc(cr, x + r, y + r, r, PI, 3.0 * PI / 2.0)
    return cairo.close_path(cr)
end

function fill(cr, color):
    call src(cr, color)
    return cairo.fill(cr)
end

function vgrad(y0, y1, c0, c1):
    g = cairo.pattern_create_linear(0.0, y0, 0.0, y1)
    call stop(g, 0.0, c0)
    call stop(g, 1.0, c1)
    return g
end

function stop(g, offset, c):
    a = 1.0
    if len(c) > 3:
        a = c[3]
    end
    return cairo.pattern_add_color_stop_rgba(g, offset, c[0], c[1], c[2], a)
end

# vypln vzorem (prechodem) a jeho uvolneni
function fill_pattern(cr, g, paint=False):
    call cairo.set_source(cr, g)
    if paint:
        call cairo.paint(cr)
    else:
        call cairo.fill(cr)
    end
    return cairo.pattern_destroy(g)
end

function set_operator(cr, op):
    return cairo.set_operator(cr, op)
end

# Mekky stin pod oknem (nekolik pruhlednych vrstev)
function shadow(cr, x, y, w, h, r, dark, depth=10):
    i = depth
    while i > 0:
        k = Float(i)
        call rrect(cr, x - k * 0.3, y + k * 0.5, w + k * 0.6, h + k * 0.4, r + k * 0.5)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.05 if dark else 0.025)
        call cairo.fill(cr)
        i -= 2
    end
    return 0
end

function parse_logo():
    out = []
    tokens = []
    word = ""
    for ch in LOGO_PATH:
        if ch == "M" or ch == "C" or ch == "Z" or ch == " " or ch == "-":
            if word != "":
                tokens.append(word)
            end
            word = ""
            if ch == "-":
                word = "-"
            elif ch != " ":
                tokens.append(ch)
            end
        else:
            word = word + ch
        end
    end
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "M":
            out.append(["M", Float(tokens[i + 1]), Float(tokens[i + 2])])
            i += 3
        elif t == "C":
            out.append(["C"] + [Float(v) for v in tokens[i + 1:i + 7]])
            i += 7
        else:
            out.append(["Z"])
            i += 1
        end
    end
    return out
end

# Logo LuxOS velikosti size (levy horni roh x, y) do cesty
function logo_path(cr, x, y, size):
    global logo_ops
    if len(logo_ops) == 0:
        logo_ops = parse_logo()
    end
    s = size / 256.0
    for op in logo_ops:
        if op[0] == "M":
            call cairo.move_to(cr, x + op[1] * s, y + op[2] * s)
        elif op[0] == "C":
            call cairo.curve_to(cr, x + op[1] * s, y + op[2] * s, x + op[3] * s, y + op[4] * s, x + op[5] * s, y + op[6] * s)
        else:
            call cairo.close_path(cr)
        end
    end
    return 0
end

function logo(cr, x, y, size, color=None):
    call logo_path(cr, x, y, size)
    if color != None:
        return fill(cr, color)
    end
    g = cairo.pattern_create_linear(x + size * 0.16, y + size * 0.12, x + size * 0.88, y + size * 0.9)
    call stop(g, 0.0, [0.48, 0.72, 1.0])
    call stop(g, 0.5, [0.36, 0.49, 1.0])
    call stop(g, 1.0, [0.63, 0.42, 1.0])
    return fill_pattern(cr, g)
end

# ---- painter ------------------------------------------------------------------------------------------------

function painter(cr, widget, dark):
    font = gtk.widget_get_font_family(widget)
    if font == "":
        font = "Sans"
    end
    p = {"cr": cr, "widget": widget, "dark": dark, "font": font}
    p["fg"] = hexc("#f2f3f7") if dark else hexc("#1d1d1f")
    p["dim"] = hexc("#f2f3f7", 0.6) if dark else hexc("#1d1d1f", 0.55)
    p["win"] = hexc("#262833") if dark else hexc("#ffffff")
    p["win2"] = hexc("#1e2029") if dark else hexc("#f3f4f8")
    p["line"] = [1.0, 1.0, 1.0, 0.10] if dark else [0.0, 0.0, 0.0, 0.10]
    return p
end

function layout_for(p, s, size, bold, mono):
    lay = pango.cairo_create_layout(p["cr"])
    family = p["font"]
    if mono:
        family = "Monospace"
    end
    if bold:
        family = family + " Bold"
    end
    call pango.layout_set_font(lay, family + " " + String(Float(size)) + "px")
    call pango.layout_set_text(lay, s)
    return lay
end

# Text: vraci sirku; align l/c/r vuci x
function text(p, s, x, y, size=11.0, color=None, bold=False, align="l", mono=False, maxw=0.0, lines=1):
    cr = p["cr"]
    lay = layout_for(p, s, size, bold, mono)
    if maxw > 0.0:
        call pango.layout_set_width(lay, Int(maxw))
        # PANGO_ELLIPSIZE_END = 3
        call pango.layout_set_ellipsize(lay, 3)
        if lines > 1:
            # PANGO_WRAP_WORD_CHAR = 2
            call pango.layout_set_wrap(lay, 2)
            call pango.layout_set_height(lay, -lines)
        end
    end
    size_px = pango.layout_get_pixel_size(lay)
    w = Float(size_px[0])
    h = Float(size_px[1])
    if maxw > 0.0 and lines > 1 and align != "l":
        call pango.layout_set_alignment(lay, 1 if align == "c" else 2)
        w = maxw
    end
    dx = 0.0
    if align == "c":
        dx = -w / 2.0
    elif align == "r":
        dx = -w
    end
    call cairo.move_to(cr, x + dx, y - h / 2.0)
    call src(cr, color if color != None else p["fg"])
    call pango.cairo_show_layout(cr, lay)
    call pango.layout_unref(lay)
    return w
end

function text_width(p, s, size=11.0, bold=False):
    lay = layout_for(p, s, size, bold, False)
    w = Float(pango.layout_get_pixel_size(lay)[0])
    call pango.layout_unref(lay)
    return w
end

# GTK_ICON_LOOKUP_FORCE_SIZE = 16; 0 kdyz motiv ikonu nema
function load_icon(name, px):
    key = name + "@" + String(px)
    if key in icons:
        return icons[key]
    end
    unsafe:
        theme = __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_get_default"))
        pb = __lsl_qbe_call5(__lsl_symbol("gtk_icon_theme_load_icon"), theme, cstr(name), ptr(px), 16, 0)
    end
    icons[key] = pb
    return pb
end

# Ikona aplikace z motivu ikon (prvni existujici), jinak barevna dlazdice s glyfem
function icon(p, names, x, y, size, fallback=None, glyph=""):
    cr = p["cr"]
    if fallback == None:
        fallback = ACCENT
    end
    px = Int(size * 2.0)
    pb = 0
    for n in names:
        if pb == 0:
            pb = load_icon(n, px)
        end
    end
    if pb != 0:
        call cairo.save(cr)
        call cairo.translate(cr, x, y)
        call cairo.scale(cr, size / Float(gtk.pixbuf_get_width(pb)), size / Float(gtk.pixbuf_get_height(pb)))
        call gtk.cairo_set_source_pixbuf(cr, pb, 0.0, 0.0)
        call cairo.paint(cr)
        return cairo.restore(cr)
    end
    call rrect(cr, x + size * 0.06, y + size * 0.06, size * 0.88, size * 0.88, size * 0.22)
    light = [min(1.0, fallback[0] + 0.18), min(1.0, fallback[1] + 0.18), min(1.0, fallback[2] + 0.18)]
    call fill_pattern(cr, vgrad(y, y + size, rgba(light), rgba(fallback)))
    if glyph != "":
        call text(p, glyph, x + size / 2.0, y + size / 2.0, size * 0.42, WHITE, bold=True, align="c")
    end
    return 0
end

# Klavesa; vraci sirku
function keycap(p, label, x, y, h=26.0, size=11.0):
    cr = p["cr"]
    dark = p["dark"]
    w = max(h, text_width(p, label, size, True) + 18.0)
    call rrect(cr, x, y + 2.0, w, h, 6.0)
    call fill(cr, [0.0, 0.0, 0.0, 0.35 if dark else 0.12])
    call rrect(cr, x, y, w, h, 6.0)
    g = vgrad(y, y + h, hexc("#3a3d4a") if dark else hexc("#ffffff"), hexc("#30323d") if dark else hexc("#eef0f5"))
    call cairo.set_source(cr, g)
    call cairo.fill_preserve(cr)
    call cairo.pattern_destroy(g)
    call src(cr, p["line"])
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    call text(p, label, x + w / 2.0, y + h / 2.0, size, bold=True, align="c")
    return w
end

# Kombinace klaves "Super + A"; vraci sirku
function combo(p, keys, x, y, h=24.0, size=10.0, align="l"):
    widths = [max(h, text_width(p, k, size, True) + 18.0) for k in keys]
    total = 16.0 * Float(len(keys) - 1)
    for wk in widths:
        total = total + wk
    end
    kx = x - total / 2.0 if align == "c" else x
    for i in range(len(keys)):
        if i > 0:
            call text(p, "+", kx + 8.0, y + h / 2.0, size + 1.0, p["dim"], bold=True, align="c")
            kx = kx + 16.0
        end
        kx = kx + keycap(p, keys[i], kx, y, h, size)
    end
    return total
end

# Popisek v barevnem stitku (vysvetlivka v ilustraci); vraci [levy okraj, sirka]
function pill(p, s, x, y, size=10.5, color=None, align="c"):
    cr = p["cr"]
    if color == None:
        color = ACCENT
    end
    w = text_width(p, s, size, True) + 18.0
    h = size + 11.0
    x0 = x - w / 2.0
    if align == "l":
        x0 = x
    elif align == "r":
        x0 = x - w
    end
    call rrect(cr, x0, y - h / 2.0, w, h, h / 2.0)
    call fill(cr, rgba(color, 0.95))
    call text(p, s, x0 + w / 2.0, y, size, WHITE, bold=True, align="c")
    return [x0, w]
end

function leader(p, x0, y0, x1, y1):
    cr = p["cr"]
    call src(cr, rgba(ACCENT, 0.9))
    call cairo.set_line_width(cr, 1.5)
    call cairo.move_to(cr, x0, y0)
    call cairo.line_to(cr, x1, y1)
    call cairo.stroke(cr)
    call cairo.arc(cr, x0, y0, 3.0, 0.0, 2.0 * PI)
    return cairo.fill(cr)
end

# Zvyrazneni oblasti: zareni + ostra linka
function ring(p, x, y, w, h, r):
    cr = p["cr"]
    for item in [[12.0, 0.10], [7.0, 0.18], [2.5, 0.95]]:
        call rrect(cr, x, y, w, h, r)
        call src(cr, rgba(ACCENT, item[1]))
        call cairo.set_line_width(cr, item[0])
        call cairo.stroke(cr)
    end
    return 0
end

# Tapeta LuxOS v miniature: prechod modra -> fialova s vlnami
function wallpaper(p, x, y, w, h, r=10.0, dark=None):
    cr = p["cr"]
    if dark == None:
        dark = p["dark"]
    end
    call cairo.save(cr)
    call rrect(cr, x, y, w, h, r)
    call cairo.clip(cr)
    g = cairo.pattern_create_linear(x, y, x + w, y + h)
    if dark:
        call stop(g, 0.0, [0.06, 0.10, 0.26])
        call stop(g, 0.55, [0.17, 0.14, 0.45])
        call stop(g, 1.0, [0.33, 0.16, 0.52])
    else:
        call stop(g, 0.0, [0.62, 0.78, 1.0])
        call stop(g, 0.55, [0.70, 0.66, 1.0])
        call stop(g, 1.0, [0.86, 0.68, 1.0])
    end
    call fill_pattern(cr, g, True)
    alphas = [0.16, 0.11, 0.08]
    for i in range(3):
        yy = y + h * (0.45 + Float(i) * 0.16)
        call cairo.move_to(cr, x - 10.0, yy)
        call cairo.curve_to(cr, x + w * 0.3, yy - h * 0.35, x + w * 0.6, yy + h * 0.3, x + w + 10.0, yy - h * 0.15)
        call cairo.line_to(cr, x + w + 10.0, y + h + 10.0)
        call cairo.line_to(cr, x - 10.0, y + h + 10.0)
        call cairo.close_path(cr)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alphas[i])
        call cairo.fill(cr)
    end
    return cairo.restore(cr)
end

# ---- symbolicke ikony horni listy (stred cx, cy; velikost s) -------------------------------------------------

function g_wifi(p, cx, cy, s, c):
    cr = p["cr"]
    call src(cr, c)
    call cairo.set_line_width(cr, s * 0.13)
    call cairo.set_line_cap(cr, 1)
    by = cy + s * 0.38
    for k in [0.30, 0.56, 0.82]:
        call cairo.arc(cr, cx, by, s * k * 0.75, math.radians(-135.0), math.radians(-45.0))
        call cairo.stroke(cr)
    end
    call cairo.arc(cr, cx, by - s * 0.02, s * 0.08, 0.0, 2.0 * PI)
    return cairo.fill(cr)
end

function g_sound(p, cx, cy, s, c):
    cr = p["cr"]
    call src(cr, c)
    x = cx - s * 0.45
    call cairo.move_to(cr, x, cy - s * 0.14)
    call cairo.line_to(cr, x + s * 0.18, cy - s * 0.14)
    call cairo.line_to(cr, x + s * 0.42, cy - s * 0.36)
    call cairo.line_to(cr, x + s * 0.42, cy + s * 0.36)
    call cairo.line_to(cr, x + s * 0.18, cy + s * 0.14)
    call cairo.line_to(cr, x, cy + s * 0.14)
    call cairo.close_path(cr)
    call cairo.fill(cr)
    call cairo.set_line_width(cr, s * 0.1)
    call cairo.set_line_cap(cr, 1)
    for k in [0.2, 0.38]:
        call cairo.arc(cr, x + s * 0.42, cy, s * k, -0.9, 0.9)
        call cairo.stroke(cr)
    end
    return 0
end

function g_battery(p, cx, cy, s, c, level=0.82):
    cr = p["cr"]
    w = s * 1.15
    h = s * 0.58
    x = cx - w / 2.0
    y = cy - h / 2.0
    call rrect(cr, x, y, w, h, h * 0.28)
    call src(cr, c)
    call cairo.set_line_width(cr, s * 0.08)
    call cairo.stroke(cr)
    call rrect(cr, x + s * 0.1, y + s * 0.1, (w - s * 0.2) * level, h - s * 0.2, h * 0.14)
    call cairo.fill(cr)
    call rrect(cr, x + w + s * 0.04, cy - h * 0.2, s * 0.08, h * 0.4, s * 0.04)
    return cairo.fill(cr)
end

function g_cc(p, cx, cy, s, c):
    cr = p["cr"]
    call src(cr, c)
    call cairo.set_line_width(cr, s * 0.08)
    for item in [[-0.22, -0.2], [0.22, 0.2]]:
        call rrect(cr, cx - s * 0.42, cy + item[0] * s - s * 0.16, s * 0.84, s * 0.32, s * 0.16)
        call cairo.stroke(cr)
        call cairo.arc(cr, cx + item[1] * s, cy + item[0] * s, s * 0.1, 0.0, 2.0 * PI)
        call cairo.fill(cr)
    end
    return 0
end

function g_bell(p, cx, cy, s, c):
    cr = p["cr"]
    call src(cr, c)
    call cairo.move_to(cr, cx - s * 0.36, cy + s * 0.22)
    call cairo.curve_to(cr, cx - s * 0.26, cy + s * 0.08, cx - s * 0.3, cy - s * 0.38, cx, cy - s * 0.38)
    call cairo.curve_to(cr, cx + s * 0.3, cy - s * 0.38, cx + s * 0.26, cy + s * 0.08, cx + s * 0.36, cy + s * 0.22)
    call cairo.close_path(cr)
    call cairo.fill(cr)
    call cairo.arc(cr, cx, cy + s * 0.32, s * 0.09, 0.0, 2.0 * PI)
    return cairo.fill(cr)
end

function g_lock(p, cx, cy, s, c):
    cr = p["cr"]
    call src(cr, c)
    call cairo.set_line_width(cr, s * 0.12)
    call cairo.arc(cr, cx, cy - s * 0.08, s * 0.24, PI, 0.0)
    call cairo.line_to(cr, cx + s * 0.24, cy + s * 0.02)
    call cairo.move_to(cr, cx - s * 0.24, cy + s * 0.02)
    call cairo.line_to(cr, cx - s * 0.24, cy - s * 0.08)
    call cairo.stroke(cr)
    call rrect(cr, cx - s * 0.36, cy, s * 0.72, s * 0.5, s * 0.1)
    return cairo.fill(cr)
end

# Vlajka rozlozeni klavesnice (jako v liste: pruhy + kanton)
function g_flag(p, cx, cy, s, c):
    cr = p["cr"]
    w = s * 1.15
    h = s * 0.78
    x = cx - w / 2.0
    y = cy - h / 2.0
    call cairo.save(cr)
    call rrect(cr, x, y, w, h, s * 0.08)
    call cairo.clip(cr)
    for i in range(7):
        call cairo.rectangle(cr, x, y + Float(i) * h / 7.0, w, h / 7.0 + 0.3)
        call fill(cr, hexc("#d8323c") if i % 2 == 0 else hexc("#ffffff"))
    end
    call cairo.rectangle(cr, x, y, w * 0.45, h * 4.0 / 7.0)
    call fill(cr, hexc("#3b4a9c"))
    return cairo.restore(cr)
end

function glyph(p, name, cx, cy, s, c):
    if name == "bell":
        return g_bell(p, cx, cy, s, c)
    elif name == "cc":
        return g_cc(p, cx, cy, s, c)
    elif name == "battery":
        return g_battery(p, cx, cy, s, c)
    elif name == "sound":
        return g_sound(p, cx, cy, s, c)
    elif name == "wifi":
        return g_wifi(p, cx, cy, s, c)
    end
    return g_flag(p, cx, cy, s, c)
end

function pad2(n):
    if n < 10:
        return "0" + String(n)
    end
    return String(n)
end

# Horni lista jako ve skutecnosti: logo, nazev aktivni aplikace, ikony otevrenych oken; vpravo klavesnice, sit,
# zvuk, baterie, Ovladaci centrum, upozorneni, hodiny. windows = [[nazvy ikon, aktivni]]. Vraci polohy prvku.
function topbar(p, x, y, w, h, app, windows, big=False):
    cr = p["cr"]
    call rrect(cr, x, y, w, h, 10.0 if big else 0.0)
    call fill(cr, hexc("#1c1d24", 0.78) if p["dark"] else hexc("#ffffff", 0.82))
    fs = h * 0.42
    c = p["fg"]
    pos = {}
    lx = x + h * 0.45
    call logo(cr, lx, y + h * 0.2, h * 0.6, c)
    pos["logo"] = [lx + h * 0.3, y + h]
    # datum v jazyce plochy jako luxos-bar ("st 18. 11.  10:00", "Wed Nov 18  10:00")
    tm = glib.localtime(glib.now())
    clock = i18n.weekday_short(tm[6]) + " " + i18n.format_tm(tm, "short") + "  " + pad2(tm[3]) + ":" + pad2(tm[4])
    rx = x + w - h * 0.4
    cw = text(p, clock, rx, y + h / 2.0, fs, c, bold=True, align="r")
    pos["clock"] = [rx - cw / 2.0, y + h]
    rx = rx - cw - h * 0.75
    gs = h * 0.52
    for name in ["bell", "cc", "battery", "sound", "wifi", "keyboard"]:
        call glyph(p, name, rx, y + h / 2.0, gs, c)
        pos[name] = [rx, y + h]
        rx = rx - h * (1.05 if name == "battery" else 1.0)
    end
    # vlevo: nazev aktivni aplikace a ikony otevrenych oken (prepinani kliknutim)
    tx = lx + h * 0.95
    tw = text(p, app, tx, y + h / 2.0, fs, c, bold=True)
    ix = tx + tw + h * 0.35
    isz = h * 0.6
    w0 = ix
    for item in windows:
        if item[1]:
            call rrect(cr, ix - h * 0.12, y + h * 0.08, isz + h * 0.24, h * 0.84, h * 0.18)
            call fill(cr, hexc("#ffffff", 0.14) if p["dark"] else hexc("#000000", 0.07))
        end
        call icon(p, item[0], ix, y + (h - isz) / 2.0, isz)
        ix = ix + isz + h * 0.4
    end
    pos["windows"] = [(w0 + ix - h * 0.4) / 2.0 if ix > w0 else w0, y + h]
    return pos
end

# Okno aplikace s titulkem a semafory; vraci y obsahu
function window(p, x, y, w, h, title="", r=10.0):
    cr = p["cr"]
    call shadow(cr, x, y, w, h, r, p["dark"])
    call rrect(cr, x, y, w, h, r)
    call fill(cr, p["win"])
    call rrect(cr, x, y, w, h, r)
    call src(cr, p["line"])
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    call traffic_lights(cr, x, y)
    if title != "":
        call text(p, title, x + w / 2.0, y + 13.0, 10.0, p["dim"], bold=True, align="c")
    end
    return y + 26.0
end

function traffic_lights(cr, x, y):
    colors = ["#ff5f57", "#febc2e", "#28c840"]
    for i in range(3):
        call cairo.arc(cr, x + 14.0 + Float(i) * 13.0, y + 13.0, 4.2, 0.0, 2.0 * PI)
        call fill(cr, hexc(colors[i]))
    end
    return 0
end

# Dock s ikonami; vraci [x, y, w, h] panelu
function dock(p, cx, y, size, items, running):
    cr = p["cr"]
    gap = size * 0.22
    n = Float(len(items))
    w = n * size + (n - 1.0) * gap + size * 0.5
    h = size * 1.32
    x = cx - w / 2.0
    call rrect(cr, x, y, w, h, size * 0.32)
    call fill(cr, hexc("#2b2c36", 0.72) if p["dark"] else hexc("#ffffff", 0.55))
    call rrect(cr, x, y, w, h, size * 0.32)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.22 if p["dark"] else 0.7)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    ix = x + size * 0.25
    for i in range(len(items)):
        it = items[i]
        call icon(p, it[0], ix, y + size * 0.14, size, it[1], it[2])
        if i in running:
            call cairo.arc(cr, ix + size / 2.0, y + h - size * 0.09, size * 0.045, 0.0, 2.0 * PI)
            call fill(cr, p["fg"])
        end
        ix = ix + size + gap
    end
    return [x, y, w, h]
end

# ---- ilustrace jednotlivych stranek ---------------------------------------------------------------------------

DOCK_ITEMS = [[["luxos-launchpad"], [0.35, 0.45, 1.0], "⋮⋮"], [["luxai", "luxos-app"], [0.30, 0.42, 1.0], "✦"],
    [["luxos-store"], [0.20, 0.55, 1.0], "S"], [["luxos-files", "org.xfce.thunar", "system-file-manager"], [0.25, 0.6, 1.0], "▤"],
    [["firefox", "luxos-web-browser", "web-browser"], [1.0, 0.5, 0.2], "◉"], [["utilities-terminal", "org.xfce.terminal"], [0.2, 0.22, 0.26], ">_"],
    [["luxos-notes", "accessories-text-editor", "org.xfce.mousepad"], [0.4, 0.4, 0.95], "✎"],
    [["luxos-settings", "preferences-system", "org.xfce.settings.manager"], [0.45, 0.5, 0.6], "⚙"], [["user-trash"], [0.7, 0.72, 0.76], "◌"]]
GRID_ITEMS = DOCK_ITEMS[2:8] + [[["luxos-calculator", "accessories-calculator"], [1.0, 0.6, 0.1], "±"],
    [["luxos-camera", "camera-app", "cheese"], [0.3, 0.3, 0.35], "◎"], [["luxdrop"], [0.2, 0.7, 0.9], "⇄"],
    [["luxos-feedback"], [0.5, 0.4, 0.95], "!"], [["luxos-safe"], [0.25, 0.3, 0.45], "🔒"], [["printer"], [0.5, 0.55, 0.6], "⎙"],
    [["luxos-videos", "multimedia-video-player"], [0.9, 0.3, 0.3], "▶"], [["luxos-image-viewer", "image-viewer"], [0.3, 0.7, 0.4], "▣"]]
FILES_ICONS = ["luxos-files", "org.xfce.thunar", "system-file-manager"]
T = i18n.T

function draw_welcome(p):
    cr = p["cr"]
    call wallpaper(p, 0.0, 0.0, VW, VH, 18.0)
    cx = VW / 2.0
    cy = VH / 2.0 - 6.0
    s = 150.0
    # mekka zare za logem
    g = cairo.pattern_create_radial(cx, cy + 10.0, 10.0, cx, cy + 10.0, 170.0)
    call stop(g, 0.0, [1.0, 1.0, 1.0, 0.22 if p["dark"] else 0.55])
    call stop(g, 1.0, [1.0, 1.0, 1.0, 0.0])
    call fill_pattern(cr, g, True)
    for item in [[1.0, 0.18], [1.35, 0.10], [1.75, 0.06]]:
        call cairo.arc(cr, cx, cy + 12.0, s * 0.55 * item[0], 0.0, 2.0 * PI)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, item[1])
        call cairo.set_line_width(cr, 1.2)
        call cairo.stroke(cr)
    end
    call logo(cr, cx - s / 2.0, cy - s / 2.0 - 4.0, s, [1.0, 1.0, 1.0, 0.95] if p["dark"] else None)
    return text(p, "LuxOS", cx, VH - 34.0, 22.0, [1.0, 1.0, 1.0, 0.95] if p["dark"] else hexc("#1d1d1f", 0.85), bold=True, align="c")
end

function dnd_glyph(cr, cx, cy, ic):
    # preskrtnuty zvonek (obrys) jako ve skutecnem Ovladacim centru
    call src(cr, ic)
    call cairo.set_line_width(cr, 0.9)
    call cairo.set_line_cap(cr, 1)
    call cairo.set_line_join(cr, 1)
    call cairo.move_to(cr, cx - 3.4, cy + 2.2)
    call cairo.curve_to(cr, cx - 2.5, cy + 1.0, cx - 2.9, cy - 3.6, cx, cy - 3.6)
    call cairo.curve_to(cr, cx + 2.9, cy - 3.6, cx + 2.5, cy + 1.0, cx + 3.4, cy + 2.2)
    call cairo.close_path(cr)
    call cairo.stroke(cr)
    call cairo.arc(cr, cx, cy + 3.3, 0.9, 0.0, 2.0 * PI)
    call cairo.fill(cr)
    call cairo.move_to(cr, cx - 3.6, cy - 3.8)
    call cairo.line_to(cr, cx + 3.6, cy + 3.8)
    return cairo.stroke(cr)
end

function moon_glyph(cr, cx, cy, ic):
    # srpek mesice: kruh, z nej vyriznuty posunuty kruh
    call gtk.cairo_push_group(cr)
    call cairo.arc(cr, cx, cy, 3.8, 0.0, 2.0 * PI)
    call src(cr, ic)
    call cairo.fill(cr)
    call cairo.set_operator(cr, 0)
    call cairo.arc(cr, cx + 2.3, cy - 1.6, 3.3, 0.0, 2.0 * PI)
    call cairo.fill(cr)
    call gtk.cairo_pop_group_to_source(cr)
    return cairo.paint(cr)
end

function draw_menubar(p):
    cr = p["cr"]
    dark = p["dark"]
    call wallpaper(p, 0.0, 0.0, VW, VH, 18.0)
    by = 40.0
    bh = 30.0
    wins = [[FILES_ICONS, True], [["firefox", "luxos-web-browser", "web-browser"], False], [["org.xfce.terminal", "utilities-terminal"], False]]
    pos = topbar(p, 14.0, by, VW - 28.0, bh, T("Files"), wins, True)
    ccx = pos["cc"][0]
    bellx = pos["bell"][0]
    # Ovladaci centrum rozbalene pod ikonou (stejne casti jako skutecne)
    pw = 232.0
    ph = 206.0
    px = VW - 14.0 - pw
    py = by + bh + 8.0
    box = hexc("#ffffff", 0.07) if dark else hexc("#000000", 0.045)
    off = hexc("#ffffff", 0.15) if dark else hexc("#000000", 0.1)
    call shadow(cr, px, py, pw, ph, 14.0, dark)
    call rrect(cr, px, py, pw, ph, 14.0)
    call fill(cr, hexc("#22242e", 0.95) if dark else hexc("#f6f3f4", 0.96))
    # ucet LuxAI
    ax = px + 7.0
    ay = py + 7.0
    aw = pw - 14.0
    call rrect(cr, ax, ay, aw, 24.0, 8.0)
    call fill(cr, box)
    call cairo.arc(cr, ax + 13.0, ay + 12.0, 8.0, 0.0, 2.0 * PI)
    call fill(cr, hexc("#6d5cff"))
    call text(p, "✦", ax + 13.0, ay + 12.0, 7.0, WHITE, bold=True, align="c")
    call text(p, T("Sign in to LuxAI"), ax + 26.0, ay + 12.0, 8.5, bold=True, maxw=aw - 40.0)
    call text(p, "›", ax + aw - 8.0, ay + 12.0, 10.0, p["dim"], align="c")
    # dlazdice 2 x 3
    tiles = [[T("Wi-Fi"), T("Connected"), True, "wifi"], [T("Bluetooth"), T("Off"), False, "bt"],
             [T("Do Not Disturb"), T("Off"), False, "dnd"], [T("Dark Mode"), T("On") if dark else T("Off"), dark, "dark"],
             [T("Data Saver"), T("Off"), False, "data"], [T("Battery Saver"), T("Off"), False, "batt"]]
    tw = (aw - 5.0) / 2.0
    for i in range(6):
        t = tiles[i]
        tx = ax + Float(i % 2) * (tw + 5.0)
        ty = py + 36.0 + Float(i // 2) * 28.0
        call rrect(cr, tx, ty, tw, 24.0, 8.0)
        call fill(cr, box)
        cx = tx + 12.0
        cy = ty + 12.0
        call cairo.arc(cr, cx, cy, 8.0, 0.0, 2.0 * PI)
        call fill(cr, rgba(ACCENT) if t[2] else off)
        ic = WHITE if t[2] else p["fg"]
        if t[3] == "wifi":
            call g_wifi(p, cx, cy, 9.0, ic)
        elif t[3] == "bt":
            call text(p, "ᛒ", cx, cy, 8.0, ic, bold=True, align="c")
        elif t[3] == "dnd":
            call dnd_glyph(cr, cx, cy, ic)
        elif t[3] == "dark":
            call moon_glyph(cr, cx, cy, ic)
        elif t[3] == "data":
            for k in range(4):
                call cairo.rectangle(cr, cx - 4.0 + Float(k) * 2.2, cy + 3.5 - Float(k + 1) * 1.8, 1.4, Float(k + 1) * 1.8)
            end
            call fill(cr, ic)
        else:
            call g_battery(p, cx, cy, 8.0, ic, 0.4)
        end
        call text(p, t[0], tx + 24.0, cy - 4.0, 7.6, bold=True, maxw=tw - 27.0)
        call text(p, t[1], tx + 24.0, cy + 5.0, 6.8, p["dim"], maxw=tw - 27.0)
    end
    # jas a hlasitost v ramecku: popisek, ikona a posuvnik
    sliders = [[T("Display"), 0.97, "sun"], [T("Sound"), 0.42, "snd"]]
    for j in range(2):
        sy = py + 122.0 + Float(j) * 34.0
        call rrect(cr, ax, sy, aw, 30.0, 8.0)
        call fill(cr, box)
        call text(p, sliders[j][0], ax + 7.0, sy + 8.0, 7.6, bold=True)
        if sliders[j][2] == "sun":
            call cairo.arc(cr, ax + 12.0, sy + 20.0, 2.2, 0.0, 2.0 * PI)
            call fill(cr, p["fg"])
            call src(cr, p["fg"])
            call cairo.set_line_width(cr, 0.9)
            for k in range(8):
                an = Float(k) * PI / 4.0
                call cairo.move_to(cr, ax + 12.0 + math.cos(an) * 3.4, sy + 20.0 + math.sin(an) * 3.4)
                call cairo.line_to(cr, ax + 12.0 + math.cos(an) * 4.6, sy + 20.0 + math.sin(an) * 4.6)
            end
            call cairo.stroke(cr)
        else:
            call g_sound(p, ax + 12.0, sy + 20.0, 8.0, p["fg"])
        end
        sx0 = ax + 24.0
        sw = aw - 32.0
        val = sliders[j][1]
        call rrect(cr, sx0, sy + 17.0, sw, 6.0, 3.0)
        call fill(cr, hexc("#ffffff", 0.12) if dark else hexc("#000000", 0.08))
        call rrect(cr, sx0, sy + 17.0, sw * val, 6.0, 3.0)
        call fill(cr, hexc("#ffffff", 0.85) if dark else hexc("#ffffff", 1.0))
        call cairo.arc(cr, sx0 + sw * val, sy + 20.0, 4.5, 0.0, 2.0 * PI)
        call fill(cr, hexc("#ffffff"))
    end
    lx = ax + 3.0
    for link in [T("Desktop & Dock…"), T("Battery…"), T("All Settings…")]:
        lx = lx + text(p, link, lx, py + ph - 9.0, 7.4, p["fg"]) + 10.0
    end
    call ring(p, ccx - 12.0, by + 3.0, 24.0, bh - 6.0, 7.0)
    # vysvetlivky nad listou
    call pill(p, T("Control Center"), ccx + 10.0, 19.0, align="r")
    call pill(p, T("Notifications"), bellx - 10.0, 19.0, align="l")
    # vysvetlivky vlevo pod listou
    for item in [["logo", T("System menu"), 120.0], ["windows", T("Open windows"), 172.0], ["wifi", T("Keyboard, network, sound, battery"), 232.0]]:
        x0 = pos[item[0]][0]
        y0 = pos[item[0]][1]
        lx = min(max(x0, 80.0), px - 110.0)
        call leader(p, x0, y0 - 2.0, lx, item[2] - 10.0)
        call pill(p, item[1], lx, item[2])
    end
    return 0
end

function draw_dock(p):
    cr = p["cr"]
    dark = p["dark"]
    call wallpaper(p, 0.0, 0.0, VW, VH, 18.0)
    call rrect(cr, 0.0, 0.0, VW, 18.0, 0.0)
    call topbar(p, 0.0, 0.0, VW, 18.0, "LuxOS", [])
    top = window(p, 150.0, 40.0, 340.0, 150.0, T("Files"))
    call rrect(cr, 151.0, top, 90.0, 150.0 - (top - 40.0) - 1.0, 0.0)
    call fill(cr, p["win2"])
    for k in range(4):
        call rrect(cr, 162.0, top + 14.0 + Float(k) * 20.0, 58.0 - Float(k) * 6.0, 7.0, 3.5)
        call fill(cr, rgba(p["dim"], 0.3))
        call icon(p, ["folder"], 262.0 + Float(k) * 54.0, top + 22.0, 36.0, [0.35, 0.6, 1.0], "")
    end
    panel = dock(p, VW / 2.0, VH - 86.0, 48.0, DOCK_ITEMS, [3, 4])
    x = panel[0]
    y = panel[1]
    w = panel[2]
    h = panel[3]
    call ring(p, x - 4.0, y - 4.0, w + 8.0, h + 8.0, 20.0)
    # bublina s nazvem nad ikonou Soubory
    fx = x + 48.0 * 0.25 + 3.0 * (48.0 + 48.0 * 0.22) + 24.0
    bubble = [0.35, 0.37, 0.45] if dark else [0.15, 0.16, 0.2]
    call pill(p, T("Files"), fx, y - 22.0, 10.5, bubble)
    call cairo.move_to(cr, fx - 5.0, y - 13.0)
    call cairo.line_to(cr, fx + 5.0, y - 13.0)
    call cairo.line_to(cr, fx, y - 8.0)
    call cairo.close_path(cr)
    call fill(cr, rgba(bubble, 0.95))
    return text(p, T("● = app is running"), x + w - 6.0, y + h + 14.0, 10.0, p["fg"], bold=True, align="r")
end

function draw_launchpad(p):
    cr = p["cr"]
    dark = p["dark"]
    call wallpaper(p, 0.0, 0.0, VW, VH, 18.0)
    lx = 22.0
    ly = 22.0
    lw = 330.0
    lh = 256.0
    call shadow(cr, lx, ly, lw, lh, 18.0, dark)
    call rrect(cr, lx, ly, lw, lh, 18.0)
    call fill(cr, hexc("#1e1f27", 0.86) if dark else hexc("#ffffff", 0.8))
    call rrect(cr, lx + 16.0, ly + 14.0, lw - 32.0, 28.0, 14.0)
    call fill(cr, hexc("#ffffff", 0.08) if dark else hexc("#000000", 0.06))
    call text(p, "⌕  " + T("Search apps or ask LuxAI"), lx + 30.0, ly + 28.0, 10.5, p["dim"], maxw=lw - 60.0)
    for i in range(12):
        it = GRID_ITEMS[i]
        gx = lx + 26.0 + Float(i % 4) * 74.0
        gy = ly + 52.0 + Float(i // 4) * 58.0
        call icon(p, it[0], gx + 8.0, gy, 40.0, it[1], it[2])
    end
    # samotne tuknuti na Super
    call combo(p, ["Super"], lx + lw / 2.0, ly + lh - 34.0, 24.0, 10.0, "c")
    # Hledani + LuxAI
    sx = 372.0
    sy = 52.0
    sw = 248.0
    call shadow(cr, sx, sy, sw, 40.0, 14.0, dark)
    call rrect(cr, sx, sy, sw, 40.0, 14.0)
    call fill(cr, hexc("#262833", 0.95) if dark else hexc("#ffffff", 0.96))
    call text(p, "⌕", sx + 18.0, sy + 20.0, 15.0, p["dim"], align="c")
    call text(p, T("How do I connect a printer?"), sx + 34.0, sy + 20.0, 11.0, maxw=sw - 44.0)
    by = sy + 54.0
    call rrect(cr, sx, by, sw, 120.0, 14.0)
    call fill(cr, hexc("#262833", 0.92) if dark else hexc("#ffffff", 0.9))
    call cairo.save(cr)
    call cairo.translate(cr, sx + 14.0, by + 12.0)
    call rrect(cr, 0.0, 0.0, 24.0, 24.0, 7.0)
    call fill_pattern(cr, vgrad(0.0, 24.0, rgba(ACCENT), rgba(VIOLET)))
    call cairo.restore(cr)
    call text(p, "✦", sx + 26.0, by + 24.0, 12.0, WHITE, bold=True, align="c")
    call text(p, "LuxAI", sx + 46.0, by + 24.0, 11.0, bold=True)
    widths = [0.88, 0.95, 0.7, 0.5]
    for k in range(4):
        call rrect(cr, sx + 14.0, by + 48.0 + Float(k) * 16.0, (sw - 28.0) * widths[k], 7.0, 3.5)
        call fill(cr, rgba(p["dim"], 0.35))
    end
    return combo(p, ["Super", T("Space")], sx + sw / 2.0, sy + 190.0, 24.0, 10.0, "c")
end

function draw_files(p):
    cr = p["cr"]
    call wallpaper(p, 0.0, 0.0, VW, VH, 18.0)
    x = 60.0
    y = 24.0
    w = 440.0
    h = 252.0
    top = window(p, x, y, w, h, T("Home"))
    sb = 128.0
    call rrect(cr, x + 1.0, top, sb, h - (top - y) - 1.0, 0.0)
    call fill(cr, p["win2"])
    items = [T("Home"), T("Documents"), T("Downloads"), T("Pictures"), T("Music"), T("Safe")]
    for i in range(6):
        iy = top + 18.0 + Float(i) * 28.0
        if i == 5:
            call rrect(cr, x + 8.0, iy - 12.0, sb - 14.0, 24.0, 7.0)
            call fill(cr, rgba(ACCENT, 0.18))
            call g_lock(p, x + 22.0, iy, 13.0, rgba(ACCENT))
            call text(p, items[i], x + 36.0, iy, 10.5, bold=True, maxw=sb - 44.0)
            call ring(p, x + 6.0, iy - 14.0, sb - 10.0, 28.0, 8.0)
        else:
            call rrect(cr, x + 16.0, iy - 5.0, 12.0, 10.0, 2.0)
            call fill(cr, rgba(ACCENT, 0.75))
            call text(p, items[i], x + 36.0, iy, 10.5, maxw=sb - 40.0)
        end
    end
    folders = [T("Documents"), T("Downloads"), T("Pictures"), T("Music"), T("Videos"), T("Desktop")]
    for i in range(6):
        fx = x + sb + 26.0 + Float(i % 3) * 96.0
        fy = top + 22.0 + Float(i // 3) * 98.0
        call icon(p, ["folder"], fx + 14.0, fy, 54.0, [0.35, 0.6, 1.0], "")
        call text(p, folders[i], fx + 41.0, fy + 66.0, 10.0, align="c", maxw=90.0)
    end
    # velky zamek Trezoru
    lx = 552.0
    ly = 196.0
    call cairo.arc(cr, lx, ly, 52.0, 0.0, 2.0 * PI)
    call fill_pattern(cr, vgrad(ly - 52.0, ly + 52.0, rgba(ACCENT), rgba(VIOLET)))
    call g_lock(p, lx, ly + 2.0, 50.0, WHITE)
    return text(p, T("Encrypted"), lx, ly + 72.0, 11.0, [1.0, 1.0, 1.0, 0.95] if p["dark"] else p["fg"], bold=True, align="c")
end

function draw_store(p):
    cr = p["cr"]
    dark = p["dark"]
    call wallpaper(p, 0.0, 0.0, VW, VH, 18.0)
    x = 24.0
    y = 20.0
    w = 380.0
    h = 236.0
    top = window(p, x, y, w, h, "LuxOS Store")
    sb = 108.0
    call rrect(cr, x + 1.0, top, sb, h - (top - y) - 1.0, 0.0)
    call fill(cr, p["win2"])
    cats = [T("Discover"), T("Internet"), T("Office"), T("Graphics"), T("Games"), T("Updates")]
    for i in range(6):
        iy = top + 18.0 + Float(i) * 26.0
        if i == 0:
            call rrect(cr, x + 8.0, iy - 11.0, sb - 14.0, 22.0, 7.0)
            call fill(cr, rgba(ACCENT, 0.18))
        end
        call text(p, cats[i], x + 18.0, iy, 10.5, bold=(i == 0), maxw=sb - 24.0)
    end
    apps = [[["gimp"], [0.4, 0.4, 0.35], "G", "GIMP"], [["libreoffice-main", "libreoffice-startcenter"], [0.2, 0.6, 0.3], "L", "LibreOffice"],
            [["vlc"], [1.0, 0.5, 0.1], "▶", "VLC"], [["inkscape"], [0.2, 0.2, 0.2], "I", "Inkscape"]]
    for i in range(4):
        a = apps[i]
        cx = x + sb + 14.0 + Float(i % 2) * 130.0
        cy = top + 14.0 + Float(i // 2) * 96.0
        call rrect(cr, cx, cy, 120.0, 84.0, 12.0)
        call fill(cr, hexc("#ffffff", 0.05) if dark else hexc("#000000", 0.035))
        call icon(p, a[0], cx + 10.0, cy + 10.0, 38.0, a[1], a[2])
        call text(p, a[3], cx + 10.0, cy + 62.0, 10.5, bold=True, maxw=64.0)
        bw = max(40.0, text_width(p, T("Get"), 9.5, True) + 16.0)
        call rrect(cr, cx + 112.0 - bw, cy + 52.0, bw, 20.0, 10.0)
        call fill(cr, rgba(ACCENT, 0.16))
        call text(p, T("Get"), cx + 112.0 - bw / 2.0, cy + 62.0, 9.5, rgba(ACCENT), bold=True, align="c")
    end
    # Terminal s prikazem lux
    tx = 340.0
    ty = 128.0
    tw = 278.0
    th = 152.0
    call shadow(cr, tx, ty, tw, th, 10.0, True)
    call rrect(cr, tx, ty, tw, th, 10.0)
    call fill(cr, hexc("#16171d", 0.97))
    call traffic_lights(cr, tx, ty)
    lines = [["❯ ", "lux install gimp", "#8ab4ff"], ["", ":: " + T("Installing") + " gimp…", "#a9adbb"],
             ["", "✓ gimp " + T("installed"), "#5fd38d"], ["❯ ", "lux update", "#8ab4ff"], ["", "✓ " + T("System is up to date"), "#5fd38d"]]
    for i in range(5):
        l = lines[i]
        ly = ty + 38.0 + Float(i) * 21.0
        offset = 0.0
        if l[0] != "":
            offset = text(p, l[0], tx + 14.0, ly, 11.0, hexc("#b48cff"), mono=True)
        end
        call text(p, l[1], tx + 14.0 + offset, ly, 11.0, hexc(l[2]) if l[0] == "" else hexc("#f2f3f7"), mono=True, maxw=tw - 30.0)
    end
    return 0
end

function mini_desktop(p, x, y, w, h, dark):
    cr = p["cr"]
    call shadow(cr, x, y, w, h, 12.0, p["dark"])
    call wallpaper(p, x, y, w, h, 12.0, dark)
    call cairo.save(cr)
    call rrect(cr, x, y, w, h, 12.0)
    call cairo.clip(cr)
    call cairo.rectangle(cr, x, y, w, 12.0)
    call fill(cr, hexc("#1c1d24", 0.8) if dark else hexc("#ffffff", 0.8))
    wx = x + w * 0.16
    wy = y + h * 0.22
    ww = w * 0.62
    wh = h * 0.48
    call rrect(cr, wx, wy, ww, wh, 7.0)
    call fill(cr, hexc("#262833") if dark else hexc("#ffffff"))
    call rrect(cr, wx, wy, ww * 0.3, wh, 7.0)
    call fill(cr, hexc("#1e2029") if dark else hexc("#f0f1f5"))
    for k in range(3):
        call rrect(cr, wx + ww * 0.38, wy + 14.0 + Float(k) * 12.0, ww * (0.5 - Float(k) * 0.1), 5.0, 2.5)
        call fill(cr, hexc("#ffffff", 0.25) if dark else hexc("#000000", 0.15))
    end
    call rrect(cr, x + w * 0.3, y + h - 22.0, w * 0.4, 16.0, 6.0)
    call fill(cr, hexc("#2b2c36", 0.75) if dark else hexc("#ffffff", 0.6))
    return cairo.restore(cr)
end

APPEARANCE_MODES = ["light", "dark", "auto"]

# Rezim pod bodem virtualni plochy (nahled i popisek pod nim) nebo ""
function appearance_hit(vx, vy):
    for i in range(3):
        tx = 28.0 + Float(i) * 200.0
        if tx - 6.0 <= vx and vx <= tx + 190.0 and 34.0 <= vy and vy <= 252.0:
            return APPEARANCE_MODES[i]
        end
    end
    return ""
end

function triangle_clip(cr, ax, ay, bx, by, cx, cy):
    call cairo.move_to(cr, ax, ay)
    call cairo.line_to(cr, bx, by)
    call cairo.line_to(cr, cx, cy)
    call cairo.close_path(cr)
    return cairo.clip(cr)
end

function draw_appearance(p, mode):
    cr = p["cr"]
    call rrect(cr, 0.0, 0.0, VW, VH, 18.0)
    call fill(cr, hexc("#1a1c26") if p["dark"] else hexc("#eef0f8"))
    names = [T("Light"), T("Dark"), T("Auto")]
    for i in range(3):
        key = APPEARANCE_MODES[i]
        x = 28.0 + Float(i) * 200.0
        y = 40.0
        w = 184.0
        h = 170.0
        if key == "auto":
            call cairo.save(cr)
            call triangle_clip(cr, x - 20.0, y - 20.0, x + w + 20.0, y - 20.0, x - 20.0, y + h + 20.0)
            call mini_desktop(p, x, y, w, h, False)
            call cairo.restore(cr)
            call cairo.save(cr)
            call triangle_clip(cr, x + w + 20.0, y - 20.0, x + w + 20.0, y + h + 20.0, x - 20.0, y + h + 20.0)
            call mini_desktop(p, x, y, w, h, True)
            call cairo.restore(cr)
            # slunce a mesic
            call cairo.arc(cr, x + 22.0, y + 30.0, 8.0, 0.0, 2.0 * PI)
            call fill(cr, hexc("#ffb02e"))
            call cairo.arc(cr, x + w - 22.0, y + h - 40.0, 8.0, 0.0, 2.0 * PI)
            call fill(cr, hexc("#f4f4ff"))
            call cairo.arc(cr, x + w - 18.0, y + h - 44.0, 7.0, 0.0, 2.0 * PI)
            call fill(cr, hexc("#3b3170"))
        else:
            call mini_desktop(p, x, y, w, h, key == "dark")
        end
        if key == mode:
            call ring(p, x - 5.0, y - 5.0, w + 10.0, h + 10.0, 16.0)
        end
        call text(p, names[i], x + w / 2.0, y + h + 32.0, 13.0, bold=(key == mode), align="c")
    end
    return 0
end

function draw_share(p):
    cr = p["cr"]
    call wallpaper(p, 0.0, 0.0, VW, VH, 18.0)
    # notebook
    lx = 40.0
    ly = 86.0
    call rrect(cr, lx + 14.0, ly, 150.0, 96.0, 8.0)
    call fill(cr, hexc("#2a2c36"))
    call wallpaper(p, lx + 20.0, ly + 6.0, 138.0, 84.0, 4.0)
    call cairo.move_to(cr, lx, ly + 100.0)
    call cairo.line_to(cr, lx + 178.0, ly + 100.0)
    call cairo.line_to(cr, lx + 170.0, ly + 110.0)
    call cairo.line_to(cr, lx + 8.0, ly + 110.0)
    call cairo.close_path(cr)
    call fill(cr, hexc("#c9ccd6"))
    # telefon
    tx = 268.0
    ty = 70.0
    call rrect(cr, tx, ty, 58.0, 112.0, 12.0)
    call fill(cr, hexc("#2a2c36"))
    call wallpaper(p, tx + 4.0, ty + 4.0, 50.0, 104.0, 9.0)
    # vlny a letici soubor
    for k in [1, 2, 3]:
        call cairo.arc(cr, 225.0, 134.0, 14.0 * Float(k), math.radians(-50.0), math.radians(50.0))
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.8 - Float(k) * 0.18)
        call cairo.set_line_width(cr, 3.0)
        call cairo.stroke(cr)
    end
    call cairo.save(cr)
    call cairo.translate(cr, 210.0, 40.0)
    call cairo.rotate(cr, -0.12)
    call rrect(cr, 0.0, 0.0, 34.0, 42.0, 4.0)
    call fill(cr, hexc("#ffffff"))
    call rrect(cr, 4.0, 4.0, 26.0, 22.0, 2.0)
    call fill_pattern(cr, vgrad(4.0, 26.0, hexc("#7ab8ff"), hexc("#a06bff")))
    call cairo.move_to(cr, 4.0, 26.0)
    call cairo.line_to(cr, 13.0, 15.0)
    call cairo.line_to(cr, 20.0, 22.0)
    call cairo.line_to(cr, 24.0, 18.0)
    call cairo.line_to(cr, 30.0, 26.0)
    call cairo.close_path(cr)
    call fill(cr, hexc("#ffffff", 0.8))
    for k in range(2):
        call rrect(cr, 4.0, 30.0 + Float(k) * 5.0, 26.0 - Float(k) * 8.0, 2.5, 1.2)
        call fill(cr, hexc("#000000", 0.2))
    end
    call cairo.restore(cr)
    call pill(p, "LuxDrop", 186.0, 224.0)
    call text(p, T("works with LocalSend"), 186.0, 250.0, 10.5, p["fg"], bold=True, align="c")
    # tiskarna a skener
    px = 400.0
    py = 100.0
    call rrect(cr, px + 30.0, py - 30.0, 120.0, 50.0, 4.0)
    call fill(cr, hexc("#ffffff"))
    for k in range(3):
        call rrect(cr, px + 44.0, py - 20.0 + Float(k) * 10.0, 90.0 - Float(k) * 20.0, 4.0, 2.0)
        call fill(cr, hexc("#000000", 0.18))
    end
    call rrect(cr, px, py, 180.0, 80.0, 14.0)
    call fill_pattern(cr, vgrad(py, py + 80.0, hexc("#e9ebf1"), hexc("#b9bdc9")))
    call rrect(cr, px + 24.0, py + 48.0, 132.0, 10.0, 5.0)
    call fill(cr, hexc("#3a3c47"))
    call cairo.arc(cr, px + 156.0, py + 22.0, 5.0, 0.0, 2.0 * PI)
    call fill(cr, hexc("#28c840"))
    call rrect(cr, px + 40.0, py + 54.0, 100.0, 50.0, 3.0)
    call fill(cr, hexc("#ffffff"))
    call icon(p, ["luxos-logo"], px + 74.0, py + 62.0, 32.0, ACCENT, "")
    call pill(p, T("Printers & Scanners"), px + 90.0, 224.0)
    return text(p, T("plug in and print"), px + 90.0, 250.0, 10.5, p["fg"], bold=True, align="c")
end

function draw_help(p):
    cr = p["cr"]
    call rrect(cr, 0.0, 0.0, VW, VH, 18.0)
    call fill(cr, hexc("#1a1c26") if p["dark"] else hexc("#eef0f8"))
    rows = [[["Super", T("Space")], T("Search")], [["Super"], "Launchpad"], [["Super", "E"], T("Files")],
            [["Super", "T"], T("Terminal")], [["Super", "Q"], T("Close window")], [["Super", "Shift", "4"], T("Screenshot of region")],
            [["Super", "L"], T("Lock screen")], [["Super", ","], T("Settings")]]
    for i in range(8):
        x = 26.0 + Float(i % 2) * 196.0
        y = 26.0 + Float(i // 2) * 62.0
        call combo(p, rows[i][0], x, y, 26.0, 10.5)
        call text(p, rows[i][1], x, y + 42.0, 10.5, p["dim"], bold=True, maxw=186.0)
    end
    # Zpetna vazba
    fx = 430.0
    fy = 30.0
    fw = 186.0
    fh = 240.0
    call shadow(cr, fx, fy, fw, fh, 16.0, p["dark"])
    call rrect(cr, fx, fy, fw, fh, 16.0)
    call fill(cr, p["win"])
    call icon(p, ["luxos-feedback"], fx + fw / 2.0 - 32.0, fy + 22.0, 64.0, VIOLET, "!")
    call text(p, T("Feedback"), fx + fw / 2.0, fy + 108.0, 14.0, bold=True, align="c")
    kinds = [[T("Bug"), hexc("#ff453a")], [T("Idea"), hexc("#ffb02e")]]
    for i in range(2):
        bx = fx + 18.0 + Float(i) * 78.0
        c = kinds[i][1]
        call rrect(cr, bx, fy + 128.0, 72.0, 30.0, 10.0)
        call fill(cr, [c[0], c[1], c[2], 0.16])
        call text(p, kinds[i][0], bx + 36.0, fy + 143.0, 10.5, c, bold=True, align="c")
    end
    widths = [0.9, 0.75, 0.55]
    for k in range(3):
        call rrect(cr, fx + 18.0, fy + 174.0 + Float(k) * 14.0, (fw - 36.0) * widths[k], 7.0, 3.5)
        call fill(cr, rgba(p["dim"], 0.3))
    end
    call rrect(cr, fx + fw - 76.0, fy + fh - 34.0, 60.0, 22.0, 11.0)
    call fill(cr, rgba(ACCENT))
    return text(p, T("Send"), fx + fw - 46.0, fy + fh - 23.0, 10.0, WHITE, bold=True, align="c")
end

function draw_page(p, index, mode):
    if index == 0:
        return draw_welcome(p)
    elif index == 1:
        return draw_menubar(p)
    elif index == 2:
        return draw_dock(p)
    elif index == 3:
        return draw_launchpad(p)
    elif index == 4:
        return draw_files(p)
    elif index == 5:
        return draw_store(p)
    elif index == 6:
        return draw_appearance(p, mode)
    elif index == 7:
        return draw_share(p)
    end
    return draw_help(p)
end
