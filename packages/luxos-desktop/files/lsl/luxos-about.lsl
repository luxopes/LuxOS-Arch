# LuxOS - "O tomto pocitaci": verze LuxOS, pocitac, procesor, pamet, grafika, uloziste, baterie a jadro
# v okne ve stylu ostatnich oken Nastaveni (zaoblena skupina, hodnoty zarovnane ve sloupci) a tlacitka
# Co je noveho / Prohlidka / Zpetna vazba / Aktualizace softwaru. Drive yad (bash): stary vzhled GTK, barevne
# ikony v tlacitkach, nezarovnane hodnoty a bez UTF-8 locale (LANG=C) se okno vubec neotevrelo
# ("Invalid byte sequence in conversion input" - yad prevadel argumenty podle locale).
# Testy: LUXOS_ABOUT_ROOT=<slozka> cte etc/os-release, proc/*, sys/class/* z ni misto ze systemu,
# LUXOS_ABOUT_LSPCI=<program> misto lspci, LUXOS_ABOUT_DF=<program> misto df.
load env, os
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys

CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.about-grid { padding: 12px 16px; }\n.about-name { font-size: 26px; font-weight: 800; }\n.dim { opacity: 0.6; }\n.about-key { font-weight: 600; }\n"

ui = {"window": 0}

function root():
    return env.get("LUXOS_ABOUT_ROOT", "")
end

function sys_path(path):
    return root() + path
end

function tool(name, var):
    value = env.get(var, "")
    if value == None or value == "":
        return name
    end
    return value
end

function unquote(value):
    v = value.strip()
    if len(v) >= 2 and (v.startswith("\"") or v.startswith("'")):
        v = v[1:len(v) - 1]
    end
    return v
end

function os_release():
    out = {}
    for line in glib.read_text(sys_path("/etc/os-release")).split("\n"):
        cut = line.find("=")
        if cut > 0 and not line.startswith("#"):
            out[line[0:cut].strip()] = unquote(line[cut + 1:])
        end
    end
    return out
end

function squeeze(text):
    out = ""
    prev = False
    for ch in text.strip():
        space = ch == " " or ch == "\t"
        if not (space and prev):
            if space:
                out = out + " "
            else:
                out = out + ch
            end
        end
        prev = space
    end
    return out
end

function cpu_name():
    for line in glib.read_text(sys_path("/proc/cpuinfo")).split("\n"):
        if line.startswith("model name"):
            cut = line.find(":")
            if cut >= 0:
                return squeeze(line[cut + 1:])
            end
        end
    end
    return "-"
end

# Nainstalovana pamet jako na krabici (16 GB): MemTotal je bez pameti grafiky a firmwaru (na 16GB notebooku
# 14,95 GiB) - nahoru na cele GB, od 4 GB na sude
function memory_gb(kb):
    if kb <= 0:
        return 0
    end
    n = 0
    while n * 1048576 < kb:
        n += 1
    end
    if n >= 4 and n % 2 == 1:
        n += 1
    end
    return n
end

function memory_text():
    for line in glib.read_text(sys_path("/proc/meminfo")).split("\n"):
        if line.startswith("MemTotal:"):
            digits = ""
            for ch in line:
                if ch in "0123456789":
                    digits = digits + ch
                end
            end
            if digits != "":
                return String(memory_gb(Int(digits))) + " GB"
            end
        end
    end
    return "-"
end

# Kratky nazev grafiky z radku lspci ("NVIDIA GeForce GTX 1650 Mobile / Max-Q" misto "NVIDIA Corporation
# TU117M [...] (rev a1)"): dlouhe nazvy roztahovaly okno pres pul obrazovky
function gpu_name(line):
    name = line.strip()
    cut = name.find(" (rev")
    if cut >= 0:
        name = name[0:cut]
    end
    for pair in [["Advanced Micro Devices, Inc. [AMD/ATI]", "AMD"], ["NVIDIA Corporation", "NVIDIA"], ["Intel Corporation", "Intel"]]:
        if name.startswith(pair[0]):
            name = pair[1] + name[len(pair[0]):]
        end
    end
    for brand in ["AMD ", "NVIDIA ", "Intel "]:
        if name.startswith(brand) and name.endswith("]"):
            open_at = name.find("[")
            if open_at > 0 and name.find("]") == len(name) - 1:
                return brand + name[open_at + 1:len(name) - 1]
            end
        end
    end
    return name
end

function gpu_text():
    names = []
    out = ""
    safe:
        out = os.capture([tool("lspci", "LUXOS_ABOUT_LSPCI")])
    end
    for line in out.split("\n"):
        if "VGA" in line or "3D" in line or "Display" in line:
            cut = line.find(": ")
            if cut >= 0 and len(names) < 2:
                names.append(gpu_name(line[cut + 2:]))
            end
        end
    end
    if len(names) == 0:
        return "-"
    end
    return ", ".join(names)
end

function storage_text():
    out = ""
    safe:
        out = os.capture([tool("df", "LUXOS_ABOUT_DF"), "-h", "--output=avail,size", "/"])
    end
    lines = out.strip().split("\n")
    if len(lines) < 2:
        return "-"
    end
    parts = []
    for p in lines[1].strip().split(" "):
        if p != "":
            parts.append(p)
        end
    end
    if len(parts) < 2:
        return "-"
    end
    return i18n.TF("%s available of %s", [parts[0], parts[1]])
end

function battery_text():
    base = sys_path("/sys/class/power_supply")
    for name in glib.list_dir(base):
        if name.startswith("BAT"):
            value = glib.read_text(base + "/" + name + "/capacity").strip()
            if value != "":
                return value + " %"
            end
        end
    end
    return ""
end

function computer_text():
    vendor = glib.read_text(sys_path("/sys/class/dmi/id/sys_vendor")).strip()
    model = glib.read_text(sys_path("/sys/class/dmi/id/product_name")).strip()
    text = (vendor + " " + model).strip()
    if text == "":
        return "-"
    end
    return text
end

function kernel_text():
    value = glib.read_text(sys_path("/proc/sys/kernel/osrelease")).strip()
    if value == "":
        return "-"
    end
    return value
end

function info_rows():
    rows = [[i18n.T("Computer"), computer_text()], [i18n.T("Processor"), cpu_name()],
            [i18n.T("Memory"), memory_text()], [i18n.T("Graphics"), gpu_text()], [i18n.T("Storage"), storage_text()]]
    battery = battery_text()
    if battery != "":
        rows.append([i18n.T("Battery"), battery])
    end
    rows.append([i18n.T("Linux kernel"), kernel_text()])
    return rows
end

# ---- okno -------------------------------------------------------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function launch(argv):
    call glib.spawn_quiet(argv)
    call gtk.main_quit()
    return 0
end

function on_whats_new(button):
    return launch(["luxos-whats-new"])
end

function on_tour(button):
    return launch(["luxos-tour"])
end

function on_feedback(button):
    return launch(["luxos-feedback"])
end

function on_update(button):
    if glib.find_program_in_path("luxos-update") != None and glib.find_program_in_path("luxos-update") != "":
        return launch(["luxos-update"])
    end
    return launch(["luxos-terminal", "--title=" + i18n.T("Update"), "-x", "lsh", "-c",
                   "lux update; echo; read -rp '" + i18n.T("Press Enter to close").replace("'", "") + "'"])
end

function on_close(button):
    call gtk.main_quit()
    return 0
end

function on_delete(event, window):
    call gtk.main_quit()
    return False
end

function button(text, handler):
    b = gtk.button_new(text)
    call gtk.connect(b, "clicked", handler)
    return b
end

function about():
    rel = os_release()
    version = rel.get("VERSION", "")
    if version == "":
        version = rel.get("VERSION_ID", "")
    end
    sub = i18n.TF("Version %s", [version])
    if rel.get("BUILD_ID", "") != "":
        sub = sub + " · " + i18n.TF("build %s", [rel["BUILD_ID"]])
    end

    call glib.set_prgname("luxos-about")
    call gtk.init()
    call gtk.css_load(CSS)
    window = gtk.window_new(i18n.T("About This Computer"))
    ui["window"] = window
    call gtk.window_set_wmclass(window, "luxos-about", "luxos-about")
    call gtk.window_set_icon_list(window, "luxos-app")
    call gtk.window_set_default_size(window, 540, -1)
    call gtk.window_set_resizable(window, False)
    call gtk.window_set_position(window, gtk.WIN_POS_CENTER)

    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 24, 24, 20, 20)

    head = gtk.box_new(gtk.HORIZONTAL, 18)
    logo = gtk.image_new_from_icon_name("luxos-app", gtk.ICON_DIALOG)
    call gtk.image_set_pixel_size(logo, 88)
    call gtk.widget_set_valign(logo, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(head, logo, False, False, 0)
    names = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_set_valign(names, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(names, label("LuxOS", "about-name"), False, False, 0)
    call gtk.box_pack_start(names, label(sub, "dim"), False, False, 0)
    call gtk.box_pack_start(names, label(i18n.T("Rolling release · based on Arch Linux"), "dim"), False, False, 0)
    call gtk.box_pack_start(head, names, True, True, 0)
    call gtk.box_pack_start(page, head, False, False, 0)

    # Hodnoty v jednom sloupci (mrizka): nazvy vlevo, hodnoty zarovnane pod sebou
    group = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(group, "group")
    call gtk.widget_set_margins(group, 0, 0, 18, 0)
    grid = gtk.grid_new()
    call gtk.widget_add_class(grid, "about-grid")
    call gtk.grid_set_column_spacing(grid, 18)
    call gtk.grid_set_row_spacing(grid, 8)
    top = 0
    for item in info_rows():
        key = label(item[0], "about-key")
        call gtk.widget_set_valign(key, gtk.ALIGN_START)
        value = label(item[1], "")
        call gtk.label_set_line_wrap(value, True)
        call gtk.label_set_max_width_chars(value, 42)
        call gtk.label_set_selectable(value, True)
        call gtk.widget_set_can_focus(value, False)
        call gtk.widget_set_hexpand(value, True)
        call gtk.grid_attach(grid, key, 0, top, 1, 1)
        call gtk.grid_attach(grid, value, 1, top, 1, 1)
        top += 1
    end
    call gtk.box_pack_start(group, grid, False, False, 0)
    call gtk.box_pack_start(page, group, False, False, 0)

    # Odkazy (stejne siroka tlacitka bez ikon) a dole Aktualizace softwaru + Zavrit
    links = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_set_homogeneous(links, True)
    call gtk.widget_set_margins(links, 0, 0, 18, 0)
    call gtk.box_pack_start(links, button(i18n.T("What's New"), on_whats_new), True, True, 0)
    call gtk.box_pack_start(links, button(i18n.T("LuxOS Tour"), on_tour), True, True, 0)
    call gtk.box_pack_start(links, button(i18n.T("Send Feedback…"), on_feedback), True, True, 0)
    call gtk.box_pack_start(page, links, False, False, 0)

    bottom = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(bottom, 0, 0, 12, 0)
    close = button(i18n.T("Close"), on_close)
    update = button(i18n.T("Software Update"), on_update)
    call gtk.widget_add_class(update, "suggested-action")
    call gtk.box_pack_end(bottom, close, False, False, 0)
    call gtk.box_pack_end(bottom, update, False, False, 0)
    call gtk.box_pack_start(page, bottom, False, False, 0)

    call gtk.container_add(window, page)
    call gtk.connect(window, "delete-event", on_delete)
    call gtk.widget_show_all(window)
    call gtk.widget_grab_focus(close)
    call gtk.main()
    return 0
end

# --print: udaje bez okna (testy, skripty)
function print_info():
    for item in info_rows():
        call sys.out(item[0] + "\t" + item[1] + "\n")
    end
    return 0
end

if arg(1) == "--print":
    call exit(print_info())
end
call exit(about())
