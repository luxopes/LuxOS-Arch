# lsl: link libgtk-3.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0 libcairo.so.2
# LuxOS - ikony plochy na Waylandu (luxos-backdrop): polozky, mrizka, ulozene polohy a kresba. Jako xfdesktop
# styl 2 (ikony souboru) podle kanalu xfce4-desktop: soubory z ~/Desktop, Domov/Souborovy system/Kos jen kdyz
# jsou zapnute (show-home, show-filesystem, show-trash; v LuxOS vypnute), pripojene vymenitelne disky
# (show-removable), velikost ikony a pisma (icon-size, font-size). Mrizka po sloupcich zleva nahore pod listou.
#
#   desk.settings()                 -> {"enabled", "icon", "font", "home", "filesystem", "trash", "removable"}
#   desk.scan(dir, conf, mounts)    -> polozky [{key, name, label, path, uri, kind, gicon..}]; kind "file", "dir",
#                                      "app" (spustitelny .desktop), "home", "filesystem", "trash", "mount"
#   desk.grid(conf, w, h)           -> {"cell_w", "cell_h", "x", "y", "cols", "rows", ...}
#   desk.place(items, g, saved)     sloupec a radek kazde polozky (ulozene polohy, jinak prvni volna bunka)
#   desk.load_positions() / save_positions(items)   ~/.config/luxos/desktop-icons ("sloupec radek klic")
#   desk.cell_rect(g, col, row), item_at(items, g, x, y), in_rect(items, g, rect)
#   desk.draw_item(cr, item, g, x, y, selected, dark, icon)   jedna ikona s popiskem v bunce x, y
#
# Polozky se ctou jednim g_file_enumerate_children (jmeno, ikona, typ, skryte soubory a .hidden), ikony
# se nacitaji az pri kresleni a sdileji se podle GIcon (luxos-backdrop.icon_for).
load glib, cairo, pango
load luxos_glib as lglib
load luxos_text as text
load luxos_apps as apps
load luxos_tokens as tokens
load luxos_xfconf as xfconf
load luxos_material as material

ATTRS = "standard::display-name,standard::icon,standard::type,standard::is-hidden,standard::is-backup,standard::name,access::can-execute"
BOTTOM = 88         # Dock (vyska + okraj), ikony pod nej nepatri
PAD = 6

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

function config_path():
    return glib.user_config_dir() + "/luxos/desktop-icons"
end

# ---- nastaveni ----

function flag(conf, key, default):
    value = conf.get(key, "")
    if value == "":
        return default
    end
    return value == "true"
end

function number(conf, key, default, lo, hi):
    value = conf.get(key, "").split(".")[0]
    if value == "" or not text.is_digits(value):
        return default
    end
    return max(lo, min(hi, Int(value)))
end

function settings():
    conf = xfconf.channel("xfce4-desktop")
    icons = "/desktop-icons/"
    files = icons + "file-icons/"
    return {"enabled": conf.get(icons + "style", "2") == "2", "icon": number(conf, icons + "icon-size", 56, 16, 256),
            "font": number(conf, icons + "font-size", 10, 6, 32),
            "home": flag(conf, files + "show-home", False), "filesystem": flag(conf, files + "show-filesystem", False),
            "trash": flag(conf, files + "show-trash", False), "removable": flag(conf, files + "show-removable", True)}
end

# ---- polozky ----

function special(key, label, uri, kind, icon_name):
    unsafe:
        gicon = __lsl_qbe_call1(__lsl_symbol("g_themed_icon_new"), cstr(icon_name))
    end
    return {"key": key, "name": key, "label": label, "path": "", "uri": uri, "kind": kind, "gicon": gicon}
end

function file_item(dir, info):
    unsafe:
        name = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_file_info_get_name"), ptr(info)))
        label = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_file_info_get_display_name"), ptr(info)))
        kind = __lsl_qbe_icall1(__lsl_symbol("g_file_info_get_file_type"), ptr(info))
        gicon = __lsl_qbe_call1(__lsl_symbol("g_file_info_get_icon"), ptr(info))
        if gicon != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_object_ref"), gicon)
        end
        exec = __lsl_qbe_icall2(__lsl_symbol("g_file_info_get_attribute_boolean"), ptr(info), cstr("access::can-execute")) & 255
        uri = glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_filename_to_uri"), cstr(dir + "/" + name), 0, 0))
    end
    item = {"key": name, "name": name, "label": label, "path": dir + "/" + name, "uri": uri, "kind": "file", "gicon": gicon}
    # G_FILE_TYPE_DIRECTORY 2
    if kind == 2:
        item["kind"] = "dir"
    elif name.endswith(".desktop") and exec != 0:
        # spoustec jen se spustitelnym bitem (jako xfdesktop/Nautilus): cizi .desktop se jen otevre
        app = apps.find(item["path"])
        if app != 0:
            item["kind"] = "app"
            item["app"] = app
            item["label"] = apps.name(app)
            unsafe:
                app_icon = __lsl_qbe_call1(__lsl_symbol("g_app_info_get_icon"), ptr(app))
                if app_icon != 0:
                    call __lsl_qbe_call1(__lsl_symbol("g_object_ref"), app_icon)
                    if gicon != 0:
                        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), gicon)
                    end
                    gicon = app_icon
                end
            end
            item["gicon"] = gicon
        end
    end
    return item
end

function files(dir):
    out = []
    unsafe:
        file = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(dir))
        list = __lsl_qbe_call5(__lsl_symbol("g_file_enumerate_children"), file, cstr(ATTRS), 0, 0, 0)
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), file)
    end
    if list == 0:
        return out
    end
    while True:
        unsafe:
            info = __lsl_qbe_call3(__lsl_symbol("g_file_enumerator_next_file"), list, 0, 0)
        end
        if info == 0:
            break
        end
        unsafe:
            hidden = __lsl_qbe_icall1(__lsl_symbol("g_file_info_get_is_hidden"), info) & 255
            backup = __lsl_qbe_icall1(__lsl_symbol("g_file_info_get_is_backup"), info) & 255
        end
        if hidden == 0 and backup == 0:
            out.append(file_item(dir, info))
        end
        unsafe:
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), info)
        end
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), list)
    end
    return out
end

function sort_key(item):
    first = "1"
    if item["kind"] == "dir":
        first = "0"
    end
    return first + item["label"].lower()
end

# mounts: [[nazev, uri, gicon]..] od luxos-backdrop (GVolumeMonitor)
function scan(dir, conf, mounts):
    items = []
    if not conf["enabled"]:
        return items
    end
    if conf["home"]:
        items.append(special("@home", glib.getenv("USER"), glib.filename_to_uri(glib.home_dir()), "home", "user-home"))
    end
    if conf["filesystem"]:
        items.append(special("@filesystem", "File System", "file:///", "filesystem", "drive-harddisk"))
    end
    if conf["trash"]:
        items.append(special("@trash", "Trash", "trash:///", "trash", "user-trash"))
    end
    if conf["removable"]:
        for m in mounts:
            items.append({"key": "@mount:" + m[1], "name": m[0], "label": m[0], "path": "", "uri": m[1], "kind": "mount",
                          "gicon": m[2]})
            unsafe:
                call __lsl_qbe_call1(__lsl_symbol("g_object_ref"), ptr(m[2]))
            end
        end
    end
    found = files(dir)
    keys = {}
    for item in found:
        keys[sort_key(item) + "\t" + item["key"]] = item
    end
    for k in sorted(keys.keys()):
        items.append(keys[k])
    end
    return items
end

function free_items(items):
    for item in items:
        if item["gicon"] != 0:
            unsafe:
                call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(item["gicon"]))
            end
            item["gicon"] = 0
        end
    end
    return 0
end

# klic sdilene ikony: g_icon_to_string ("folder", "text-x-generic", cesta ikony aplikace)
function icon_key(item):
    if item["gicon"] == 0:
        return ""
    end
    unsafe:
        return glib.take_c(__lsl_qbe_call1(__lsl_symbol("g_icon_to_string"), ptr(item["gicon"])))
    end
end

# ---- mrizka ----

function font_px(conf):
    # body v pixelech pri 96 dpi
    return Float(conf["font"]) * 96.0 / 72.0
end

function grid(conf, w, h):
    icon = conf["icon"]
    line = Int(font_px(conf) * 1.3 + 0.5)
    cell_w = max(icon + 44, Int(font_px(conf) * 7.0))
    cell_h = PAD + icon + 4 + 2 * line + 8
    top = tokens.BAR["height"] + 8
    cols = max(1, (w - 16) // cell_w)
    rows = max(1, (h - top - BOTTOM) // cell_h)
    return {"cell_w": cell_w, "cell_h": cell_h, "x": 8, "y": top, "cols": cols, "rows": rows, "icon": icon, "line": line,
            "font": tokens.FONT["family"] + ", Cantarell, sans-serif " + String(conf["font"])}
end

function cell_rect(g, col, row):
    return [g["x"] + col * g["cell_w"], g["y"] + row * g["cell_h"], g["cell_w"], g["cell_h"]]
end

function cell_at(g, x, y):
    col = (Int(x) - g["x"]) // g["cell_w"]
    row = (Int(y) - g["y"]) // g["cell_h"]
    return [max(0, min(g["cols"] - 1, col)), max(0, min(g["rows"] - 1, row))]
end

function load_positions():
    out = {}
    for line in text.lines(lglib.read_text(config_path())):
        col = text.partition(line, " ")
        row = text.partition(col[1], " ")
        if col[0] != "" and row[0] != "" and row[1] != "" and text.is_digits(col[0]) and text.is_digits(row[0]):
            out[row[1]] = [Int(col[0]), Int(row[0])]
        end
    end
    return out
end

# Ulozene zustanou i polohy polozek, ktere prave nejsou (odpojeny disk, soubor na chvili pryc)
function save_positions(items, saved):
    for item in items:
        saved[item["key"]] = [item["col"], item["row"]]
    end
    lines = []
    for key in sorted(saved.keys()):
        lines.append(String(saved[key][0]) + " " + String(saved[key][1]) + " " + key)
    end
    call lglib.mkdir_p(glib.user_config_dir() + "/luxos")
    call lglib.write_atomic(config_path(), "\n".join(lines) + "\n")
    return 0
end

function free_cell(g, used):
    for col in range(g["cols"]):
        for row in range(g["rows"]):
            if not ((String(col) + "," + String(row)) in used):
                return [col, row]
            end
        end
    end
    return [g["cols"] - 1, g["rows"] - 1]
end

function place(items, g, saved):
    used = {}
    for item in items:
        item["col"] = -1
        pos = saved.get(item["key"])
        if pos != None and pos[0] < g["cols"] and pos[1] < g["rows"] and not ((String(pos[0]) + "," + String(pos[1])) in used):
            item["col"] = pos[0]
            item["row"] = pos[1]
            used[String(pos[0]) + "," + String(pos[1])] = True
        end
    end
    for item in items:
        if item["col"] < 0:
            cell = free_cell(g, used)
            item["col"] = cell[0]
            item["row"] = cell[1]
            used[String(cell[0]) + "," + String(cell[1])] = True
        end
    end
    return items
end

# ---- zasah ----

# ikona a popisek bez okraju bunky (mezi ikonami se da zacit vyber tazenim)
function item_box(g, item, x, y):
    return [Float(x + 4), Float(y + PAD - 3), Float(g["cell_w"] - 8), Float(g["icon"] + 7 + 2 * g["line"])]
end

function item_at(items, g, x, y):
    for item in items:
        cell = cell_rect(g, item["col"], item["row"])
        box = item_box(g, item, cell[0], cell[1])
        if x >= box[0] and x < box[0] + box[2] and y >= box[1] and y < box[1] + box[3]:
            return item
        end
    end
    return None
end

function in_rect(items, g, r):
    out = []
    for item in items:
        cell = cell_rect(g, item["col"], item["row"])
        box = item_box(g, item, cell[0], cell[1])
        if box[0] < r[0] + r[2] and r[0] < box[0] + box[2] and box[1] < r[1] + r[3] and r[1] < box[1] + box[3]:
            out.append(item)
        end
    end
    return out
end

# ---- kresba ----

function label_layout(cr, g, item):
    layout = pango.cairo_create_layout(cr)
    call pango.layout_set_font(layout, g["font"])
    call pango.layout_set_width(layout, g["cell_w"] - 8)
    call pango.layout_set_height(layout, -2)
    call pango.layout_set_wrap(layout, pango.WRAP_WORD_CHAR)
    call pango.layout_set_ellipsize(layout, pango.ELLIPSIZE_END)
    call pango.layout_set_alignment(layout, pango.ALIGN_CENTER)
    call pango.layout_set_text(layout, item["label"])
    return layout
end

# Ikona a popisek: bily text se stinem jako na X11 (text_desktop), vybrana polozka ma matny podklad
# ikony a popisek na barve vyberu (jako Finder)
function draw_item(cr, item, g, x, y, selected, dark, icon):
    icon_size = Float(g["icon"])
    cx = Float(x) + Float(g["cell_w"]) / 2.0
    top = Float(y + PAD)
    if selected:
        shade = 0.0
        if dark:
            shade = 1.0
        end
        call cairo.set_source_rgba(cr, shade, shade, shade, 0.22)
        call material.rounded_path(cr, cx - icon_size / 2.0 - 4.0, top - 4.0, icon_size + 8.0, icon_size + 8.0, 6.0)
        call cairo.fill(cr)
    end
    if icon != 0:
        call cairo.save(cr)
        call cairo.translate(cr, cx - icon_size / 2.0, top)
        iw = Float(cairo.image_surface_get_width(icon))
        if iw > 0.0:
            # povrch ikony je v pixelech zarizeni
            call cairo.scale(cr, icon_size / iw, icon_size / iw)
        end
        call cairo.set_source_surface(cr, icon, 0.0, 0.0)
        call cairo.paint(cr)
        call cairo.restore(cr)
    end
    layout = label_layout(cr, g, item)
    size = pango.layout_get_pixel_size(layout)
    lx = Float(x + 4)
    ly = top + icon_size + 4.0
    if selected:
        sel = tokens.COLORS["selection"]
        w = Float(size[0]) + 8.0
        call cairo.set_source_rgba(cr, Float(sel[0]) / 255.0, Float(sel[1]) / 255.0, Float(sel[2]) / 255.0, 0.92)
        call material.rounded_path(cr, cx - w / 2.0, ly - 1.0, w, Float(size[1]) + 2.0, 4.0)
        call cairo.fill(cr)
    else:
        for off in [[0.0, 1.0], [0.0, 2.0], [1.0, 1.0], [-1.0, 1.0]]:
            call cairo.move_to(cr, lx + off[0], ly + off[1])
            call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.28)
            call pango.cairo_show_layout(cr, layout)
        end
    end
    call cairo.move_to(cr, lx, ly)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
    call pango.cairo_show_layout(cr, layout)
    call pango.layout_unref(layout)
    return 0
end
