# lsl: link libm.so.6
# LuxOS - jediny zdroj hodnot vzhledu pro desktop na Waylandu (1.1.0): barvy, material, vyska (stiny), zaobleni,
# mezery, pismo, animace a kontrast pisma. Programy nacitaji `load luxos_tokens as tokens`.
# Material, vyska, zaobleni, typograficka stupnice a mezery jsou z navrhu 1.1.0 (out/plan-1.1.0/design-review.md
# G1-G5); test tests/test_luxos_tokens.py hlida kontrast pisma na kazdem materialu a porovnava vystupy
# generatoru se snimky.
#
#   tokens.color(name, dark) -> [r, g, b, a]     r, g, b 0-255, a 0-1 (COLORS, LIGHT/DARK)
#   tokens.material(plocha, dark, blur)          tonovani plochy (SURFACE -> MATERIAL); blur = kompozitor pod ni
#                                                rozmazava (luxwm), jinak kryti BLUR["fallback_opacity"]
#   tokens.elevation(plocha, dark) -> [dosah, posun, alfa]   stin plochy kreslený kompozitorem (ELEVATION)
#   tokens.namespace(nazev, plocha)              jmenny prostor layer-shell s materialem ("luxos-cc@popup:16")
#   tokens.type_css(role), font(role)            pismo role TYPE pro CSS / pango
#   tokens.gtk3_css(dark, blur), menu_css(dark, blur)   CSS GTK 3 shellu / jen nabidek
#   tokens.css_color(c), hex8(c), rgb01(c)       zapis barvy pro CSS / labwc / cairo
#   tokens.gtk3_css(dark)                        CSS pro klienty shellu v LSL (GTK 3, tridy .lx-*)
#   tokens.labwc_themerc(dark), labwc_buttons(dark), labwc_rc(dark)
#                                                tema dekoraci pro luxwm (labwc): themerc, semafor v SVG,
#                                                cast <theme> do rc.xml
#   tokens.srgb_linear(v), luminance(r, g, b), contrast(l1, l2), white_contrast(lum)
#   tokens.want_dark_ink(contrast, current)      bile/tmave pismo listy s hysterezi (luxos-bar.c)
#   tokens.scrim_strength(lum), scrim_profile(t) zavoj pod listou na svetle tapete (luxos-bar.c)
#   tokens.ease_in_out_cubic(t), cubic_bezier(curve, t)

# ---- barvy ----------------------------------------------------------------------------------
# Spolecne: akcent a stav (luxos-themes/luxos-gtk3.css, luxos_bar_popups.lsl), semafor (luxos_glass.lsl),
# krizek oznameni (luxos-themes/notify/*.css)
COLORS = {
    "accent": [61, 123, 255, 1.0],
    "accent_hover": [47, 106, 230, 1.0],
    "accent_pressed": [40, 91, 204, 1.0],
    "accent_text": [255, 255, 255, 1.0],
    "error": [255, 69, 58, 1.0],
    "error_soft": [255, 180, 173, 1.0],
    "close_glyph": [255, 59, 48, 1.0],
    "close_glyph_hover": [215, 0, 21, 1.0],
    "light_close": [255, 95, 87, 1.0],
    "light_min": [254, 188, 46, 1.0],
    "light_max": [40, 200, 64, 1.0],
    "light_glyph": [60, 20, 10, 0.70],
    "light_border": [0, 0, 0, 0.12],
    "white": [255, 255, 255, 1.0],
    "on_glass": [255, 255, 255, 1.0],
    "on_glass_light": [25, 31, 43, 1.0],
    "card_edge": [255, 255, 255, 0.38],
    "card_edge_top": [255, 255, 255, 0.62],
    "card_edge_bottom": [255, 255, 255, 0.20],
    "card_inset": [255, 255, 255, 0.18],
    "menu_edge": [255, 255, 255, 0.30],
    "menu_inset": [255, 255, 255, 0.22],
    "desktop_hover": [0, 0, 0, 0.30]
}

# Svetly a tmavy rezim: obsah na materialu (luxos_bar_popups.lsl LIGHT/DARK), okna, odkazy; podklad ploch
# shellu je MATERIAL. Odkaz je stisknuty akcent (jeden modry ton, kontrast na bile 6,4:1). fg_soft = vedlejsi text
# v oknech; na materialu (pod nim muze byt cokoli) vedlejsi text fg_secondary, at ma i tam 4,5:1.
LIGHT = {
    "fg": [29, 29, 43, 1.0],
    "fg_soft": [29, 29, 43, 0.72],
    "fg_secondary": [29, 29, 43, 0.84],
    "dim": [29, 29, 43, 0.58],
    "window": [242, 242, 247, 1.0],
    "border": [0, 0, 0, 0.10],
    "tile": [0, 0, 0, 0.05],
    "tile_hover": [0, 0, 0, 0.09],
    "bubble": [0, 0, 0, 0.08],
    "trough": [0, 0, 0, 0.10],
    "fill": [255, 255, 255, 1.0],
    "field": [255, 255, 255, 0.55],
    "button": [0, 0, 0, 0.06],
    "button_hover": [0, 0, 0, 0.11],
    "link": [40, 91, 204, 1.0],
    "light_inactive": [0, 0, 0, 0.18]
}
DARK = {
    "fg": [244, 244, 250, 1.0],
    "fg_soft": [244, 244, 250, 0.72],
    "fg_secondary": [244, 244, 250, 0.84],
    "dim": [244, 244, 250, 0.60],
    "window": [33, 36, 43, 1.0],
    "border": [255, 255, 255, 0.14],
    "tile": [255, 255, 255, 0.08],
    "tile_hover": [255, 255, 255, 0.13],
    "bubble": [255, 255, 255, 0.14],
    "trough": [255, 255, 255, 0.14],
    "fill": [255, 255, 255, 0.85],
    "field": [0, 0, 0, 0.24],
    "button": [255, 255, 255, 0.10],
    "button_hover": [255, 255, 255, 0.16],
    "link": [122, 167, 255, 1.0],
    "light_inactive": [255, 255, 255, 0.22]
}

# ---- material -------------------------------------------------------------------------------
# Tonovani nad pozadim, ktere kompozitor rozmaze (luxcomp blur.c, design-review G1). Tri tloustky; kryti je
# nejmensi, pri kterem ma text na materialu 4,5:1 nad cernym, bilym i pestrym pozadim (se saturaci 1,6): fg vsude,
# vedlejsi fg_secondary na regular a thick (test_material_contrast); thin nese jen pismo listy (fg). border = 1 px vne obsahu,
# highlight = 1 px nahore uvnitr, shadow = vychozi uroven ELEVATION.
MATERIAL = {
    "thin": {
        "light": {"tint": [246, 247, 252], "opacity": 0.56, "blur": 32, "saturation": 1.6, "border": [0, 0, 0, 0.12], "highlight": [255, 255, 255, 0.55], "shadow": 1},
        "dark": {"tint": [28, 29, 38], "opacity": 0.66, "blur": 32, "saturation": 1.6, "border": [0, 0, 0, 0.45], "highlight": [255, 255, 255, 0.16], "shadow": 1}
    },
    "regular": {
        "light": {"tint": [246, 247, 252], "opacity": 0.72, "blur": 32, "saturation": 1.6, "border": [0, 0, 0, 0.12], "highlight": [255, 255, 255, 0.55], "shadow": 3},
        "dark": {"tint": [30, 31, 42], "opacity": 0.72, "blur": 32, "saturation": 1.6, "border": [0, 0, 0, 0.45], "highlight": [255, 255, 255, 0.16], "shadow": 3}
    },
    "thick": {
        "light": {"tint": [246, 247, 252], "opacity": 0.80, "blur": 32, "saturation": 1.6, "border": [0, 0, 0, 0.12], "highlight": [255, 255, 255, 0.55], "shadow": 2},
        "dark": {"tint": [30, 31, 42], "opacity": 0.76, "blur": 32, "saturation": 1.6, "border": [0, 0, 0, 0.45], "highlight": [255, 255, 255, 0.16], "shadow": 2}
    }
}
# Rozmazani v kompozitoru (dual Kawase, 4 pruchody); bez nej (labwc, X11) kryje material fallback_opacity
BLUR = {"radius": 32, "passes": 4, "saturation": 1.6, "fallback_opacity": 0.96}
# Karta skla vyskakovacich oken, Ovladaciho centra a Kalendare jako verze 1.1.1 (luxos_glass.panel(okno, box, 18))
CARD_RADIUS = 18
# Hrana matneho skla widgetu a Hodin.
WIDGET_RADIUS = 22
# Plochy shellu: [material, uroven vysky, polomer]; jmeno = material v kompozitoru (luxwm luxcomp_material_set).
# dim = zatemneni pod Launchpadem (rozmazana cela obrazovka, klient kresli cernou 0,28 a panel sheet).
SURFACE = {
    "bar": ["thin", 0, 0],
    "dock": ["thin", 1, 24],
    "menu": ["thick", 2, 12],
    "popup": ["regular", 3, CARD_RADIUS],
    "toast": ["thick", 3, 16],
    "sheet": ["regular", 4, 24],
    "dim": ["regular", 0, 0]
}
DIM = {"light": [0, 0, 0, 0.28], "dark": [0, 0, 0, 0.34], "fallback": [40, 42, 52]}

# Vyska: stin pod plochou, kresli ho kompozitor vne povrchu (dosah rozmazani, posun dolu, alfa); tmavy rezim
# alfa x 1,5. css = totez pro stin uvnitr povrchu klienta (panel Launchpadu).
ELEVATION = {
    "1": {"size": 24, "y": 8, "alpha": 0.18, "css": "0 8px 24px rgba(0, 0, 0, 0.18), 0 1px 2px rgba(0, 0, 0, 0.10)"},
    "2": {"size": 30, "y": 10, "alpha": 0.22, "css": "0 10px 30px rgba(0, 0, 0, 0.22), 0 2px 6px rgba(0, 0, 0, 0.12)"},
    "3": {"size": 44, "y": 16, "alpha": 0.24, "css": "0 16px 44px rgba(0, 0, 0, 0.24), 0 2px 8px rgba(0, 0, 0, 0.12)"},
    "4": {"size": 80, "y": 30, "alpha": 0.35, "css": "0 30px 80px rgba(0, 0, 0, 0.35)"}
}
DARK_SHADOW = 1.5

# ---- tvar -----------------------------------------------------------------------------------
# Sest polomeru, soustredne: vnitrni = vnejsi - odsazeni, nejmene 6. xs polozka nabidky a cip, s tlacitko a pole,
# m dlazdice, skupina radku, nabidka, okno; l vyskakovaci okno a oznameni; xl Dock, Launchpad, karta dialogu
RADIUS = {"xs": 6, "s": 8, "m": 12, "l": 16, "xl": 24, "pill": 999}

# Mezery (px): mrizka 4/8 bez 6
SPACE = {"xxs": 2, "xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
# Vyska ovladacich prvku (tlacitko, pole, rozbalovaci seznam, posuvnik)
CONTROL = {"height": 28}

# Pismo Inter. TYPE: role -> [velikost px, vyska radku px, vaha]; na radek nejvys jedna tucna, vedlejsi text fg_soft,
# nikdy pod 11 px. FONT: rodina a zobrazovaci velikosti zamku a widgetu (mimo stupnici).
TYPE = {
    "caption": [11, 14, 400],
    "footnote": [12, 16, 400],
    "body": [13, 18, 400],
    "body_strong": [13, 18, 600],
    "title": [15, 20, 600],
    "headline": [20, 26, 700],
    "large": [28, 34, 700]
}
FONT = {
    "family": "Inter",
    "fallback": "\"Inter\", \"Cantarell\", sans-serif",
    "light_glyph": 9,
    "lock_date": 27,
    "lock_clock": 180,
    "widget_time": 42,
    "widget_temp": 26
}
WEIGHT = {"ultralight": 200, "regular": 400, "medium": 500, "semibold": 600, "bold": 700, "heavy": 800}

# Stiny jako CSS (karty widgetu, prihlasovaci karta, jezdec prepinace, zamereni pole);
# okna luxwm: velikost a alfa stinu (nove, xfwm4 kreslilo stin motivem)
SHADOW = {
    "card": "0 8px 16px -8px rgba(8, 12, 24, 0.16)",
    "inset": "inset 0 1px rgba(255, 255, 255, 0.18)",
    "dialog": "0 18px 50px rgba(0, 0, 0, 0.35)",
    "knob": "0 1px 3px rgba(0, 0, 0, 0.25)",
    "knob_strong": "0 1px 3px rgba(0, 0, 0, 0.35)",
    "focus": "0 0 0 3px alpha(#3d7bff, 0.25)",
    "text_desktop": "0 1px 3px alpha(black, 0.75)"
}
# Lesk skla vyskakovacich oken a oznameni (luxos_glass.paint_panel: bila 8 % do 35 % sirky, sikmo dolu)
SHEEN = "linear-gradient(160deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0) 60%)"
# Stin okna (kompozitor): dosah, posun dolu, alfa; aktivni okno se zretelne oddeli od okna za nim
WINDOW_SHADOW = {"active_size": 48, "active_y": 16, "active_alpha": 0.32, "inactive_size": 28, "inactive_y": 8, "inactive_alpha": 0.18}

# ---- pohyb ----------------------------------------------------------------------------------
# ms: snimek 16, zatemneni relace 150 a prechod po prihlaseni 280 (luxos-session-cover.c), zamek
# klid->prihlaseni 380 a zpet 420, zatreseni pri spatnem hesle 480 (luxos-lock-ui.c), posun ploch 420
# (xfwm4 luxos-workspace-slide.patch), zmizeni zvetseni Docku nejpozdeji 450 (testy plank)
MOTION = {
    "frame": 16,
    "fade": 150,
    "login_fade": 280,
    "lock_enter": 380,
    "lock_leave": 420,
    "shake": 480,
    "workspace": 420,
    "dock_zoom_leave": 450
}
# Krivky jako cubic-bezier (x1, y1, x2, y2): posun ploch = CSS "ease" (luxos-workspace-slide.patch)
CURVES = {
    "ease": [0.25, 0.1, 0.25, 1.0],
    "ease_out": [0.0, 0.0, 0.58, 1.0]
}

# ---- sklo z tapety (luxos_material.strip: zamek a prihlaseni, dokud je neprekresli jejich navrh) -----------
# Material karet (luxos-widgets.lsl on_card_draw = luxos-glass.c glass_paint): tapeta zmensena na
# "size", dva pruchody filtru 1-4-6-4-1, desaturace (floor + (c * keep + lum * luma) * keep),
# podklad "base", zavoj podle jasu vyrezu, odlesk "sheen" do 35 % sirky
GLASS = {
    "size": 96,
    "weights": [1.0, 4.0, 6.0, 4.0, 1.0],
    "floor": 0.22,
    "keep": 0.72,
    "luma": 0.28,
    "fallback": [0.15, 0.17, 0.21],
    "base": [0.92, 0.94, 0.98, 0.86],
    "sheen": 0.08,
    "sheen_reach": 0.35,
    "light_mean": 0.56,
    "veil_light": 0.64,
    "veil_dark": 0.37
}
# ---- pismo listy na tapete (luxos-bar.c) ----------------------------------------------------
# Kontrast bileho pisma podle WCAG; tmave pod dark_below, zpet bile az nad white_above (hystereze).
# readable_*: jas pozadi pod textem (90. percentil), scrim_*: zavoj pod listou na velmi svetle tapete.
INK = {
    "dark_below": 2.0,
    "white_above": 2.3,
    "readable_light": 0.58,
    "readable_dark": 0.62,
    "readable_light_scrim": 0.45,
    "scrim_height": 128,
    "scrim_max": 0.38,
    "scrim_c_none": 2.0,
    "scrim_c_full": 1.3
}
BAR = {"height": 28}

# ---- LOCK/LOGIN: zamek a prihlasovaci obrazovka ------------------------------------------------
# Vzhled je kopie X11 (luxos-lock-ui.c, luxos-greeter) primo v luxos_lock_draw; tady jen chovani: po idle_after ms
# bez vstupu s prazdnym polem se vyzva vrati do klidu.
LOCK = {"idle_after": 8000}

# ---- barvy: zapis ---------------------------------------------------------------------------

function color(name, dark):
    mode = LIGHT
    if dark:
        mode = DARK
    end
    if name in mode:
        return mode[name]
    end
    return COLORS[name]
end

function surface_material(surface, dark):
    mode = "light"
    if dark:
        mode = "dark"
    end
    return MATERIAL[SURFACE[surface][0]][mode]
end

# Tonovani plochy [r, g, b, a]; bez rozmazani v kompozitoru vyssi kryti, at nic neprosvita
function material(surface, dark, blur):
    m = surface_material(surface, dark)
    a = m["opacity"]
    if not blur:
        a = max(a, BLUR["fallback_opacity"])
    end
    return [m["tint"][0], m["tint"][1], m["tint"][2], a]
end

function material_border(surface, dark):
    return surface_material(surface, dark)["border"]
end

function material_highlight(surface, dark):
    return surface_material(surface, dark)["highlight"]
end

# [dosah, posun, alfa] stinu plochy; uroven 0 = bez stinu
function elevation(surface, dark):
    level = String(SURFACE[surface][1])
    if level not in ELEVATION:
        return [0, 0, 0.0]
    end
    e = ELEVATION[level]
    a = e["alpha"]
    if dark:
        a = min(1.0, a * DARK_SHADOW)
    end
    return [e["size"], e["y"], a]
end

function radius_of(surface):
    return SURFACE[surface][2]
end

function namespace(name, surface):
    return name + "@" + surface + ":" + String(SURFACE[surface][2])
end

# CSS a pango pro roli TYPE
function type_css(role):
    t = TYPE[role]
    return "font-size: " + String(t[0]) + "px; font-weight: " + String(t[2]) + ";"
end

function font(role):
    t = TYPE[role]
    weight = ""
    if t[2] >= 700:
        weight = " Bold"
    elif t[2] >= 600:
        weight = " Semi-Bold"
    end
    # pango: velikost v bodech pri 96 dpi
    return FONT["family"] + weight + " " + String(Float(t[0]) * 0.75)
end

function hex2(v):
    digits = "0123456789abcdef"
    return digits[(v >> 4) & 15] + digits[v & 15]
end

function alpha_byte(a):
    return Int(Float(a) * 255.0 + 0.5)
end

function css_color(c):
    if c[3] >= 1.0:
        return "#" + hex2(c[0]) + hex2(c[1]) + hex2(c[2])
    end
    return "rgba(" + String(c[0]) + ", " + String(c[1]) + ", " + String(c[2]) + ", " + String(c[3]) + ")"
end

function hex8(c):
    return "#" + hex2(c[0]) + hex2(c[1]) + hex2(c[2]) + hex2(alpha_byte(c[3]))
end

function rgb01(c):
    return [Float(c[0]) / 255.0, Float(c[1]) / 255.0, Float(c[2]) / 255.0, Float(c[3])]
end

# ---- kontrast -------------------------------------------------------------------------------

function pow(x, y):
    unsafe:
        return __lsl_qbe_fcall2(__lsl_symbol("pow"), Float(x), Float(y))
    end
end

# Linearni slozka sRGB z bajtu 0-255 (luxos-bar.c srgb_linear)
function srgb_linear(v):
    c = Float(v) / 255.0
    if c <= 0.04045:
        return c / 12.92
    end
    return pow((c + 0.055) / 1.055, 2.4)
end

function luminance(r, g, b):
    return 0.2126 * srgb_linear(r) + 0.7152 * srgb_linear(g) + 0.0722 * srgb_linear(b)
end

function contrast(l1, l2):
    hi = max(l1, l2)
    lo = min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)
end

# Kontrast bileho pisma na pozadi s prumernym linearnim jasem lum
function white_contrast(lum):
    return 1.05 / (lum + 0.05)
end

# True = tmave pismo; current = dosavadni rozhodnuti (tapeta na hranici nerozblika listu)
function want_dark_ink(c, current):
    if current:
        return c < INK["white_above"]
    end
    return c < INK["dark_below"]
end

function smoothstep(t):
    t = max(0.0, min(1.0, Float(t)))
    return t * t * (3.0 - 2.0 * t)
end

# Sila zavoje 0-1 podle prumerneho linearniho jasu tapety v pasu pod listou
function scrim_strength(lum):
    c = white_contrast(lum)
    return smoothstep((INK["scrim_c_none"] - c) / (INK["scrim_c_none"] - INK["scrim_c_full"]))
end

# Prubeh zavoje: 1 nahore, 0 na scrim_height, bez hrany na koncich
function scrim_profile(t):
    return 1.0 - smoothstep(t)
end

# ---- krivky ---------------------------------------------------------------------------------

function ease_in_out_cubic(t):
    t = Float(t)
    if t < 0.5:
        return 4.0 * t * t * t
    end
    u = -2.0 * t + 2.0
    return 1.0 - u * u * u / 2.0
end

# Postup krivky cubic-bezier v case t (0-1): x(u) = t pulenim, pak y(u)
function cubic_bezier(curve, t):
    x1 = Float(curve[0])
    y1 = Float(curve[1])
    x2 = Float(curve[2])
    y2 = Float(curve[3])
    t = max(0.0, min(1.0, Float(t)))
    lo = 0.0
    hi = 1.0
    u = t
    for i in range(40):
        u = (lo + hi) / 2.0
        v = 1.0 - u
        x = 3.0 * v * v * u * x1 + 3.0 * v * u * u * x2 + u * u * u
        if x < t:
            lo = u
        else:
            hi = u
        end
    end
    v = 1.0 - u
    return 3.0 * v * v * u * y1 + 3.0 * v * u * u * y2 + u * u * u
end

# ---- generator: GTK 3 CSS pro klienty shellu -----------------------------------------------
# Barvy jako @define-color lx_*, pravidla jsou pro oba rezimy stejna. Podklad ploch je material (lx_mat_*):
# s rozmazanim v kompozitoru (blur) jen tonovani, jinak skoro nepruhledny. Ovladace maji vysku CONTROL.

function px(v):
    return String(v) + "px"
end

function css_defines(dark, blur):
    mode = LIGHT
    if dark:
        mode = DARK
    end
    out = ""
    for name in sorted(COLORS.keys()):
        out = out + "@define-color lx_" + name + " " + css_color(COLORS[name]) + ";\n"
    end
    for name in sorted(mode.keys()):
        out = out + "@define-color lx_" + name + " " + css_color(mode[name]) + ";\n"
    end
    for surface in sorted(SURFACE.keys()):
        out = out + "@define-color lx_mat_" + surface + " " + css_color(material(surface, dark, blur)) + ";\n"
    end
    out = out + "@define-color lx_mat_border " + css_color(material_border("popup", dark)) + ";\n"
    out = out + "@define-color lx_mat_highlight " + css_color(material_highlight("popup", dark)) + ";\n"
    return out
end

function css_rules():
    r = RADIUS
    s = SPACE
    w = WEIGHT
    h = CONTROL["height"]
    pill = px(r["pill"])
    plain = " background: none; background-image: none; border: none; box-shadow: none; outline: none;"
    # okraj karty skla jako widgety a vyskakovaci okna verze 1.1.1 (luxos_glass.panel): svetla hrana, nahore
    # jasnejsi, dole tlumena, odlesk uvnitr a sikmy lesk pres material
    edge = (" border: 1px solid @lx_card_edge; border-top-color: @lx_card_edge_top; border-bottom-color: @lx_card_edge_bottom;"
        + " box-shadow: inset 0 1px @lx_card_inset; background-image: " + SHEEN + ";")
    return ("* { font-family: " + FONT["fallback"] + "; }\n"
        + "window.lx { background: transparent; color: @lx_fg; }\n"
        + ".lx-popup { background-color: @lx_mat_popup; border-radius: " + px(radius_of("popup")) + ";" + edge
        + " padding: " + px(s["m"]) + "; color: @lx_fg; }\n"
        # sklo z tapety kresli pod kartu klient (luxos_hub_popup.paint_glass)
        + ".lx-popup.lx-wallglass { background-color: transparent; }\n"
        + ".lx-card { border-radius: " + px(r["xl"]) + "; padding: " + px(s["l"]) + "; box-shadow: " + SHADOW["card"] + ", " + SHADOW["inset"] + "; }\n"
        + ".lx-head { " + type_css("title") + " }\n"
        + ".lx-title { " + type_css("body_strong") + " }\n"
        + ".lx-caption { " + type_css("caption") + " color: @lx_fg_secondary; margin: " + px(s["s"]) + " " + px(s["xs"]) + " 0 " + px(s["xs"]) + "; }\n"
        + ".lx-dim { " + type_css("footnote") + " color: @lx_fg_secondary; }\n"
        + ".lx-error { color: @lx_error; " + type_css("footnote") + " }\n"
        + ".lx-section { background-color: @lx_tile; border-radius: " + px(r["m"]) + "; padding: " + px(s["s"]) + "; }\n"
        + "button.lx-row {" + plain + " border-radius: " + px(r["s"]) + "; padding: " + px(s["xs"]) + " " + px(s["s"]) + "; min-height: " + px(h - 2 * s["xs"]) + "; color: @lx_fg; }\n"
        + "button.lx-row:hover { background-color: @lx_tile_hover; }\n"
        + "button.lx-row label { " + type_css("body") + " }\n"
        + ".lx-bubble { background-color: @lx_bubble; border-radius: " + pill + "; min-width: " + px(h) + "; min-height: " + px(h) + "; }\n"
        + "button.lx-row.on .lx-bubble { background-color: @lx_accent; color: @lx_accent_text; }\n"
        + "button.lx-icon {" + plain + " border-radius: " + pill + "; min-width: " + px(h) + "; min-height: " + px(h) + "; padding: 0; color: @lx_fg; }\n"
        + "button.lx-icon:hover { background-color: @lx_tile_hover; }\n"
        + "button.lx-accent {" + plain + " border-radius: " + px(r["s"]) + "; padding: 0 " + px(s["m"]) + "; min-height: " + px(h) + "; background-color: @lx_accent; }\n"
        + "button.lx-accent:hover { background-color: @lx_accent_hover; }\n"
        + "button.lx-accent:active { background-color: @lx_accent_pressed; }\n"
        + "button.lx-accent label { color: @lx_accent_text; " + type_css("footnote") + " font-weight: " + String(w["medium"]) + "; }\n"
        + "button.lx-button {" + plain + " border-radius: " + px(r["s"]) + "; padding: 0 " + px(s["m"]) + "; min-height: " + px(h) + "; background-color: @lx_button; color: @lx_fg; }\n"
        + "button.lx-button:hover { background-color: @lx_button_hover; }\n"
        + "button.lx-button label { " + type_css("footnote") + " font-weight: " + String(w["medium"]) + "; }\n"
        + ".lx-popup entry { min-height: " + px(h) + "; border-radius: " + px(r["s"]) + "; border: none; background-image: none;"
        + " background-color: @lx_field; box-shadow: inset 0 0 0 1px @lx_border; color: @lx_fg; }\n"
        + ".lx-popup entry:focus { box-shadow: " + SHADOW["focus"] + "; }\n"
        + ".lx-popup switch { border-radius: " + pill + "; border: none; background-image: none; background-color: @lx_bubble; box-shadow: none; min-height: 24px; min-width: 40px; }\n"
        + ".lx-popup switch:checked { background-color: @lx_accent; }\n"
        + ".lx-popup switch slider { border-radius: " + pill + "; min-width: 22px; min-height: 22px; margin: 1px; border: none;"
        + " background-image: none; background-color: @lx_white; box-shadow: " + SHADOW["knob"] + "; }\n"
        + ".lx-popup scale trough { min-height: " + px(h) + "; border-radius: " + px(h // 2) + "; background-color: @lx_trough; border: none; }\n"
        + ".lx-popup scale highlight { min-height: " + px(h) + "; border-radius: " + px(h // 2) + "; background-color: @lx_fill; border: none; }\n"
        + ".lx-popup scale slider { min-width: " + px(h) + "; min-height: " + px(h) + "; margin: 0; border-radius: " + px(h // 2) + "; background-color: @lx_white;"
        + " border: none; box-shadow: " + SHADOW["knob_strong"] + "; }\n"
        + ".lx-popup progressbar trough { background-color: @lx_trough; border: none; border-radius: " + px(s["xs"]) + "; min-height: 6px; }\n"
        + ".lx-popup progressbar progress { border-radius: " + px(s["xs"]) + "; min-height: 6px; }\n"
        + ".lx-unread { background-color: @lx_accent; border-radius: " + pill + "; min-width: 8px; min-height: 8px; }\n"
        + ".lx-notification { background-color: @lx_mat_toast; border-radius: " + px(radius_of("toast")) + ";" + edge
        + " padding: " + px(s["m"]) + "; color: @lx_fg; }\n"
        + ".lx-notification .lx-summary { " + type_css("body_strong") + " }\n"
        + ".lx-notification .lx-body { " + type_css("body") + " color: @lx_fg_secondary; }\n"
        + ".lx-notification .lx-dim { color: @lx_fg_secondary; }\n"
        + "button.lx-close {" + plain + " min-width: 18px; min-height: 18px; padding: 0; }\n"
        + "button.lx-close label { color: @lx_close_glyph; " + type_css("title") + " font-weight: " + String(w["bold"]) + "; }\n"
        + "button.lx-close:hover label { color: @lx_close_glyph_hover; }\n"
        + "button.lx-light { min-width: 12px; min-height: 12px; padding: 0; margin: 0 " + px(s["xs"]) + " 0 0; border-radius: " + pill + ";"
        + " border: 1px solid @lx_light_border; background-image: none; box-shadow: none; outline: none; }\n"
        + "button.lx-light label { font-size: " + px(FONT["light_glyph"]) + "; font-weight: " + String(w["heavy"]) + "; color: transparent; margin-top: -1px; }\n"
        + "button.lx-light:hover label { color: @lx_light_glyph; }\n"
        + "button.lx-light-close { background-color: @lx_light_close; }\n"
        + "button.lx-light-min { background-color: @lx_light_min; }\n"
        + "button.lx-light-max { background-color: @lx_light_max; }\n"
        + ".lx-backdrop button.lx-light { background-color: @lx_light_inactive; }\n"
        + css_menu_rules())
end

# Nabidky GTK (xdg_popup ploch shellu): material menu, polozka 26 px, oddelovac s odsazenim 10 px
function css_menu_rules():
    r = RADIUS
    s = SPACE
    return (".csd.popup decoration { box-shadow: none; border-radius: " + px(radius_of("menu")) + "; }\n"
        + "menu, .menu { background-color: @lx_mat_menu; border-radius: " + px(radius_of("menu")) + "; padding: 5px; border: none;"
        + " box-shadow: inset 0 0 0 1px " + css_color(COLORS["menu_edge"]) + ", inset 0 1px " + css_color(COLORS["menu_inset"]) + "; }\n"
        + "menu > menuitem { border-radius: " + px(r["xs"]) + "; padding: " + px(s["xs"]) + " 10px; min-height: 18px; color: @lx_fg; " + type_css("body") + " }\n"
        + "menu > menuitem label { color: inherit; }\n"
        + "menu > menuitem:hover { background-color: @lx_accent; color: @lx_accent_text; }\n"
        + "menu > menuitem:disabled { color: alpha(@lx_fg, 0.35); }\n"
        + "menu > menuitem accelerator { color: @lx_fg_secondary; }\n"
        + "menu > menuitem:hover accelerator { color: alpha(@lx_accent_text, 0.8); }\n"
        + "menu > separator { margin: 5px 10px; min-height: 1px; background-color: @lx_border; }\n")
end

# blur: kompozitor pod plochy kresli rozmazane pozadi (luxwm); bez nej material skoro nepruhledny
function gtk3_css(dark, blur):
    return css_defines(dark, blur) + css_rules()
end

# Jen nabidky (Dock, plocha): barvy a pravidla menu
function menu_css(dark, blur):
    return css_defines(dark, blur) + css_menu_rules()
end

# ---- zahlavi oken ----------------------------------------------------------------------------
# Jedna mira pro zahlavi kompozitoru (luxwm, libluxcomp deco.c) i GTK s vlastnim zahlavim (luxos-themes
# luxos-gtk3.css, shodu hlida test_luxos_themes.py), aby nastaveni LuxOS nemela dva vzhledy (design review
# 1.1.0, cast 10): bezne 38 px, nizke 30 px (cizi aplikace, dialogy), svetla 12 px po 20 px, stred prvniho
# na x = 20 (nizke 14); nazev 13 px tucny 600, neaktivni na 45 %; neaktivni svetla inkoust 22 % s krouzkem
# 10 %; obrys okna svetly cerna 20 %, tmavy cerna 60 %.
# Zaobleni okna je RADIUS["m"] (12 px).
TITLEBAR = {"height": 38, "height_compact": 30, "light": 12, "pitch": 20, "inset": 20, "inset_compact": 14,
    "title_px": 13, "title_weight": 600, "inactive_title_alpha": 0.45, "light_inactive_alpha": 0.22,
    "light_ring_alpha": 0.10, "border_light": [0, 0, 0, 0.20], "border_dark": [0, 0, 0, 0.60]}

# ---- generator: tema luxwm (labwc 0.20) ---------------------------------------------------
# Dekorace oken jako okna z matneho skla: titulek v barve okna, semafor vlevo (layout v rc.xml),
# tlacitka 20 px s kruhem 12 px (luxos_glass.lsl), stin okna podle WINDOW_SHADOW.

LIGHT_SIZE = 20

function opaque(c):
    return [c[0], c[1], c[2], 1.0]
end

function with_alpha(c, a):
    return [c[0], c[1], c[2], a]
end

function labwc_themerc(dark):
    fg = color("fg", dark)
    dim = color("dim", dark)
    win = color("window", dark)
    border = color("border", dark)
    popup = material("menu", dark, False)
    accent = COLORS["accent"]
    lines = [
        "# LuxOS - tema dekoraci luxwm (labwc 0.20), generovano z luxos_tokens.lsl (luxos-tokens labwc)",
        "border.width: 1",
        "window.titlebar.padding.width: " + String(SPACE["s"]),
        "window.titlebar.padding.height: 6",
        "window.active.border.color: " + hex8(border),
        "window.inactive.border.color: " + hex8(border),
        "window.active.indicator.toggled-keybind.color: " + hex8(COLORS["error"]),
        "window.active.title.bg.color: " + hex8(win),
        "window.inactive.title.bg.color: " + hex8(win),
        "window.*.title.bg: Solid",
        "window.active.label.text.color: " + hex8(fg),
        "window.inactive.label.text.color: " + hex8(dim),
        "window.label.text.justify: center",
        "window.button.width: " + String(LIGHT_SIZE),
        "window.button.height: " + String(LIGHT_SIZE),
        "window.button.spacing: 0",
        "window.button.hover.bg.color: #00000000",
        "window.button.hover.bg.corner-radius: " + String(LIGHT_SIZE // 2),
        "window.active.button.unpressed.image.color: " + hex8(fg),
        "window.inactive.button.unpressed.image.color: " + hex8(dim),
        "window.active.shadow.size: " + String(WINDOW_SHADOW["active_size"]),
        "window.inactive.shadow.size: " + String(WINDOW_SHADOW["inactive_size"]),
        "window.active.shadow.color: " + hex8([0, 0, 0, WINDOW_SHADOW["active_alpha"]]),
        "window.inactive.shadow.color: " + hex8([0, 0, 0, WINDOW_SHADOW["inactive_alpha"]]),
        "menu.overlap.x: 0",
        "menu.overlap.y: 0",
        "menu.width.min: 160",
        "menu.width.max: 360",
        "menu.border.width: 1",
        "menu.border.color: " + hex8(border),
        "menu.items.bg.color: " + hex8(opaque(popup)),
        "menu.items.text.color: " + hex8(fg),
        "menu.items.active.bg.color: " + hex8(accent),
        "menu.items.active.text.color: " + hex8(COLORS["accent_text"]),
        "menu.items.padding.x: 10",
        "menu.items.padding.y: " + String(SPACE["xs"]),
        "menu.separator.width: 1",
        "menu.separator.padding.width: " + String(SPACE["s"]),
        "menu.separator.padding.height: " + String(SPACE["xs"]),
        "menu.separator.color: " + hex8(border),
        "menu.title.bg.color: " + hex8(opaque(popup)),
        "menu.title.text.color: " + hex8(dim),
        "menu.title.text.justify: Left",
        "osd.bg.color: " + hex8(opaque(popup)),
        "osd.border.color: " + hex8(border),
        "osd.border.width: 1",
        "osd.label.text.color: " + hex8(fg),
        "osd.window-switcher.style-classic.padding: " + String(SPACE["s"]),
        "osd.window-switcher.style-classic.item.padding.x: 10",
        "osd.window-switcher.style-classic.item.padding.y: " + String(SPACE["xs"]),
        "osd.window-switcher.style-classic.item.active.border.width: 0",
        "osd.window-switcher.style-classic.item.active.border.color: " + hex8(accent),
        "osd.window-switcher.style-classic.item.active.bg.color: " + hex8(color("tile_hover", dark)),
        "osd.window-switcher.style-thumbnail.padding: " + String(SPACE["s"]),
        "osd.window-switcher.style-thumbnail.item.padding: 10",
        "osd.window-switcher.style-thumbnail.item.active.border.width: 0",
        "osd.window-switcher.style-thumbnail.item.active.border.color: " + hex8(accent),
        "osd.window-switcher.style-thumbnail.item.active.bg.color: " + hex8(color("tile_hover", dark)),
        "osd.window-switcher.style-thumbnail.item.icon.size: 96",
        "snapping.overlay.region.bg.color: " + hex8(with_alpha(accent, 0.25)),
        "snapping.overlay.edge.bg.color: " + hex8(with_alpha(accent, 0.25)),
        "snapping.overlay.region.border.width: 1",
        "snapping.overlay.edge.border.width: 1",
        "snapping.overlay.region.border.color: " + hex8(accent),
        "snapping.overlay.edge.border.color: " + hex8(accent)
    ]
    return "\n".join(lines) + "\n"
end

# Kruh semaforu; glyph = "" (bez znaku), "close", "min", "max"
function light_svg(fill, glyph, dark):
    c = Float(LIGHT_SIZE) / 2.0
    out = ("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + String(LIGHT_SIZE) + "\" height=\"" + String(LIGHT_SIZE)
        + "\" viewBox=\"0 0 " + String(LIGHT_SIZE) + " " + String(LIGHT_SIZE) + "\">"
        + "<circle cx=\"" + String(c) + "\" cy=\"" + String(c) + "\" r=\"5.5\" fill=\"" + css_color(opaque(fill))
        + "\" fill-opacity=\"" + String(fill[3]) + "\" stroke=\"" + css_color(opaque(COLORS["light_border"]))
        + "\" stroke-opacity=\"" + String(COLORS["light_border"][3]) + "\" stroke-width=\"1\"/>")
    ink = COLORS["light_glyph"]
    pen = "\" stroke=\"" + css_color(opaque(ink)) + "\" stroke-opacity=\"" + String(ink[3]) + "\" stroke-width=\"1.4\" stroke-linecap=\"round\"/>"
    if glyph == "close":
        out = out + "<path d=\"M7.5 7.5 12.5 12.5M12.5 7.5 7.5 12.5" + pen
    elif glyph == "min":
        out = out + "<path d=\"M7 10H13" + pen
    elif glyph == "max":
        out = out + "<path d=\"M10 7V13M7 10H13" + pen
    end
    return out + "</svg>\n"
end

# Soubory tlacitek labwc (nazev -> SVG); neaktivni okno = sedy kruh, pri najeti barva i znak
function labwc_buttons(dark):
    out = {}
    inactive = color("light_inactive", dark)
    for pair in [["close", "light_close", "close"], ["iconify", "light_min", "min"], ["max", "light_max", "max"], ["max_toggled", "light_max", "max"]]:
        name = pair[0]
        fill = COLORS[pair[1]]
        out[name + "-active.svg"] = light_svg(fill, "", dark)
        out[name + "-inactive.svg"] = light_svg(inactive, "", dark)
        out[name + "_hover-active.svg"] = light_svg(fill, pair[2], dark)
        out[name + "_hover-inactive.svg"] = light_svg(fill, pair[2], dark)
    end
    return out
end

function theme_name(dark):
    if dark:
        return "LuxOS-Dark"
    end
    return "LuxOS"
end

# Cast <theme> pro rc.xml luxwm: semafor vlevo, zaobleni okna, pismo titulku (labwc velikost v bodech)
function labwc_rc(dark):
    title_pt = TYPE["body_strong"][0] * 3 // 4 + 1
    font = ""
    for place in ["ActiveWindow", "InactiveWindow", "MenuHeader", "MenuItem", "OnScreenDisplay"]:
        weight = "normal"
        if place == "ActiveWindow" or place == "InactiveWindow":
            weight = "bold"
        end
        font = (font + "  <font place=\"" + place + "\"><name>" + FONT["family"] + "</name><size>" + String(title_pt)
            + "</size><slant>normal</slant><weight>" + weight + "</weight></font>\n")
    end
    return ("<theme>\n"
        + "  <name>" + theme_name(dark) + "</name>\n"
        + "  <titlebar><layout>close,iconify,max:</layout><showTitle>yes</showTitle></titlebar>\n"
        + "  <cornerRadius>" + String(RADIUS["m"]) + "</cornerRadius>\n"
        + "  <keepBorder>yes</keepBorder>\n"
        + "  <maximizedDecoration>titlebar</maximizedDecoration>\n"
        + "  <dropShadows>yes</dropShadows>\n"
        + "  <dropShadowsOnTiled>no</dropShadowsOnTiled>\n"
        + font
        + "</theme>\n")
end
