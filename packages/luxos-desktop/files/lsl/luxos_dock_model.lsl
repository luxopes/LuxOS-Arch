# LuxOS - Dock bez GTK: nastaveni (~/.config/luxos/dock.conf), prevzeti polozek z Planku a rozlozeni ikon
# se zvetsenim. Oddelene od luxos-dock.lsl, aby slo testovat bez displeje (tests/lsl/luxos-dock-model-test.lsl).
#
#   parse_conf(text) -> {items, icon_size, zoom, hide}     chybejici klice = vychozi hodnoty LuxOS
#   conf_text(conf)                                         zpet do souboru (klic=hodnota jako appearance.conf)
#   dockitem_launcher(text) -> "file:///..", "docklet://trash" nebo ""
#   plank_order(dock_items, names)                          poradi souboru .dockitem podle dconf dock-items
#   item_for_launcher(uri)                                  polozka Docku: cesta .desktop, "trash" nebo ""
#   layout(n, size, gap, pad, zoom, progress, px, x0)       [leve okraje, velikosti, levy okraj panelu, sirka panelu]
#   panel_width(n, size, gap, pad), max_zoom_extra(n, size, gap, pad, zoom)
#   item_at(lay, gap, x)                                    index ikony pod x nebo -1
load math
load luxos_text as text

# Vychozi Dock LuxOS (dconf/10-luxos: dock-items, icon-size, zoom-percent, hide-mode)
DEFAULT_ITEMS = ["luxos-launchpad.desktop", "luxai.desktop", "luxos-store.desktop", "thunar.desktop",
    "firefox.desktop", "luxos-terminal.desktop", "luxos-text.desktop", "xfce-settings-manager.desktop", "trash"]
DEFAULTS = {"icon_size": 48, "zoom": 150, "hide": "dodge"}
HIDE_MODES = ["none", "dodge", "autohide"]
# Plank hide-mode -> nas rezim (intellihide/window-dodge/dodge-maximized/dodge-active = uhnout oknu)
PLANK_HIDE = {"none": "none", "auto": "autohide", "autohide": "autohide"}
# Dosah zvetseni v sirkach ikony (vcetne mezery): soused zvetsen na polovinu, ob jednu uz ne
REACH = 2.0

function unquote(value):
    v = value.strip()
    if len(v) >= 2 and (v[0] == "\"" or v[0] == "'") and v[-1] == v[0]:
        return v[1:-1]
    end
    return v
end

function number(value, fallback, lo, hi):
    v = unquote(value)
    if v == "" or not text.is_digits(v):
        return fallback
    end
    return max(lo, min(hi, Int(v)))
end

function parse_conf(content):
    kv = text.parse_kv(content)
    conf = {"items": List(DEFAULT_ITEMS), "icon_size": DEFAULTS["icon_size"], "zoom": DEFAULTS["zoom"],
        "hide": DEFAULTS["hide"]}
    if "ITEMS" in kv:
        conf["items"] = [item for item in unquote(kv["ITEMS"]).split(" ") if item != ""]
    end
    conf["icon_size"] = number(kv.get("ICON_SIZE", ""), DEFAULTS["icon_size"], 24, 128)
    # 100 = bez zvetseni; vic nez dvojnasobek se do plochy Docku nevejde
    conf["zoom"] = number(kv.get("ZOOM", ""), DEFAULTS["zoom"], 100, 200)
    hide = unquote(kv.get("HIDE", ""))
    if hide in HIDE_MODES:
        conf["hide"] = hide
    end
    return conf
end

function conf_text(conf):
    return ("# LuxOS - Dock (luxos-dock); ITEMS = id .desktop souboru nebo cesta, trash = Kos\n"
        + "ITEMS=\"" + text.join(conf["items"], " ") + "\"\n"
        + "ICON_SIZE=" + String(conf["icon_size"]) + "\n"
        + "ZOOM=" + String(conf["zoom"]) + "\n"
        + "HIDE=" + conf["hide"] + "\n")
end

# ---- prevzeti z Planku ----

function dockitem_launcher(content):
    for line in content.split("\n"):
        pair = text.partition(line.strip(), "=")
        if pair[0].strip() == "Launcher":
            return pair[1].strip()
        end
    end
    return ""
end

function item_for_launcher(uri):
    if uri == "docklet://trash":
        return "trash"
    end
    if uri.startswith("file://") and uri.endswith(".desktop"):
        return uri[7:]
    end
    return ""
end

# dock_items = vystup "dconf read" (['a.dockitem', 'b.dockitem']); soubory mimo seznam na konec podle abecedy
function plank_order(dock_items, names):
    order = []
    for part in dock_items.replace("[", "").replace("]", "").split(","):
        name = unquote(part)
        if name != "" and name in names and not (name in order):
            order.append(name)
        end
    end
    rest = [name for name in names if not (name in order)]
    call rest.sort()
    return order + rest
end

function plank_hide(mode):
    m = unquote(mode)
    if m == "":
        return DEFAULTS["hide"]
    end
    return PLANK_HIDE.get(m, "dodge")
end

# ---- rozlozeni ----

function panel_width(n, size, gap, pad):
    return 2 * pad + n * size + max(0, n - 1) * gap
end

# Mira zvetseni ikony ve vzdalenosti d od mysi (1 primo pod mysi, 0 od dosahu dal)
function falloff(d, reach):
    if d >= reach:
        return 0.0
    end
    return (math.cos(math.PI * d / reach) + 1.0) / 2.0
end

# Ikony zleva: leve okraje a velikosti (Float). Panel roste z mista pod mysi: relativni poloha mysi v panelu
# zustava stejna, takze okraje se hybou plynule a ikona pod mysi zustava pod ni.
function layout(n, size, gap, pad, zoom, progress, px, x0):
    s = Float(size)
    g = Float(gap)
    base_w = Float(panel_width(n, size, gap, pad))
    amount = (Float(zoom) / 100.0 - 1.0) * Float(progress)
    reach = REACH * (s + g)
    FloatArray(sizes) = FloatArray()
    total = 2.0 * Float(pad) + Float(max(0, n - 1)) * g
    for i in range(n):
        center = Float(x0) + Float(pad) + s / 2.0 + Float(i) * (s + g)
        z = s
        if amount > 0.0:
            z = s * (1.0 + amount * falloff(abs(Float(px) - center), reach))
        end
        sizes.append(z)
        total = total + z
    end
    anchor = max(Float(x0), min(Float(x0) + base_w, Float(px)))
    left = anchor - (anchor - Float(x0)) * total / base_w
    FloatArray(lefts) = FloatArray()
    x = left + Float(pad)
    for i in range(n):
        lefts.append(x)
        x = x + sizes[i] + g
    end
    return [lefts, sizes, left, total]
end

# Nejvetsi rozsireni panelu pres vsechny polohy mysi (sirka plochy Docku)
function max_zoom_extra(n, size, gap, pad, zoom):
    if n == 0 or zoom <= 100:
        return 0
    end
    base_w = panel_width(n, size, gap, pad)
    best = 0.0
    px = 0
    while px <= base_w:
        lay = layout(n, size, gap, pad, zoom, 1.0, px, 0)
        best = max(best, lay[3] - Float(base_w))
        px += 2
    end
    return Int(best) + 2
end

# Ikona pod x: polovina mezery patri kazde strane
function item_at(lay, gap, x):
    lefts = lay[0]
    sizes = lay[1]
    half = Float(gap) / 2.0
    for i in range(len(lefts)):
        if Float(x) >= lefts[i] - half and Float(x) < lefts[i] + sizes[i] + half:
            return i
        end
    end
    return -1
end
