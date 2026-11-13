# LuxOS Emoji a symboly - vyber emoji jako Win+. ve Windows a Ctrl+Cmd+Mezernik v macOS (Super+. a
# Ctrl+Super+Mezernik). Okno bezi primo v luxos-hub (vznikne s daty pri prvnim pouziti a pak zustane
# pripravene, dalsi zkratka ho ukaze hned), bez hubu v samostatnem procesu luxos-emoji-ui. Maly klient
# luxos-emoji jen preda prepinace pres abstraktni socket UNIX (protokol a cista logika v luxos_emoji_base).
#
#   call emoji.prebuild()            skryte okno a data predem (luxos-emoji-ui s LUXOS_EMOJI_RESIDENT=1)
#   emoji.start_server(samostatne)   naslouchani na socketu; False kdyz uz posloucha nekdo jiny
#   call emoji.handle_request(argv, None)   pozadavek primo (samostatny proces)
#
# Okno: hledani nahore (nazvy a klicova slova CLDR v jazyce systemu i anglicky, bez ohledu na diakritiku),
# zalozky Naposledy pouzite + 9 skupin, mrizka kreslena primo (jen viditelne radky, zadne widgety pro
# ~1900 emoji), dole nazev emoji a vyber odstinu pleti (pamatuje se). Sipky, PageUp/PageDown, Tab =
# dalsi skupina, Enter/klik vlozi a zavre, Shift+Enter/Shift+klik vlozi a nechá okno otevrene, Esc zavre.
#
# Vlozeni: okno si pri otevreni zapamatuje aktivni okno aplikace. Po vyberu prectu puvodni obsah schranky
# (text nebo obrazek), do schranky dam emoji, aktivuji puvodni okno a poslu Ctrl+V (terminaly Ctrl+Shift+V,
# xterm/rxvt Shift+Insert s PRIMARY) pres XTEST; po 1 s vratim puvodni obsah schranky, pokud ji mezitim
# nikdo neprevzal. Kdyz vlozit nejde (zadne okno, okno zmizelo, nedostalo fokus), emoji zustane ve schrance
# a upozorneni to rekne.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo
load pango
load luxos_x11 as x11
load luxos_sys
load luxos_i18n as i18n
load luxos_emoji_base as base

KEY_ESCAPE = 65307
KEY_RETURN = 65293
KEY_KP_ENTER = 65421
KEY_LEFT = 65361
KEY_UP = 65362
KEY_RIGHT = 65363
KEY_DOWN = 65364
KEY_PAGE_UP = 65365
KEY_PAGE_DOWN = 65366
KEY_TAB = 65289
KEY_ISO_LEFT_TAB = 65056
KEY_SHIFT_L = 65505
KEY_CONTROL_L = 65507
KEY_INSERT = 65379
KEY_V = 118

CELL = 40
COLS = 9
GRID_W = 360
GRID_H = 296
HEADER_H = 28
SEARCH_LIMIT = 270
EMOJI_FONT = "Noto Color Emoji, emoji 23px"
RESTORE_MS = 1000
FOCUS_TRIES = 40           # x 15 ms: jak dlouho cekat, nez puvodni okno dostane fokus
TONE_HAND = "✋"

CSS = ("window.lx-emoji { background: transparent; }\n"
    + "window.lx-emoji .panel { background-color: @em_bg; border-radius: 14px; border: 1px solid @em_border; padding: 10px 10px 8px 10px; color: @em_fg; }\n"
    + "window.lx-emoji entry { background-color: @em_entry; background-image: none; border: 1px solid @em_border; border-radius: 8px; box-shadow: none; color: @em_fg; min-height: 30px; padding: 0 8px; font-size: 14px; }\n"
    + "window.lx-emoji entry:focus { border-color: @em_accent; box-shadow: 0 0 0 2px @em_ring; }\n"
    + "window.lx-emoji entry image { color: @em_dim; }\n"
    + "window.lx-emoji .tabs button, window.lx-emoji .tones button { background: none; background-image: none; border: none; box-shadow: none; outline: none; text-shadow: none; padding: 3px 0; min-height: 0; min-width: 0; border-radius: 7px; }\n"
    + "window.lx-emoji .tabs button:hover, window.lx-emoji .tones button:hover { background-color: @em_hover; }\n"
    + "window.lx-emoji .tabs button.active, window.lx-emoji .tones button.active { background-color: @em_active; }\n"
    + "window.lx-emoji .tabs label { font-size: 17px; }\n"
    + "window.lx-emoji .tones button { padding: 1px 3px; }\n"
    + "window.lx-emoji .tones label { font-size: 15px; }\n"
    + "window.lx-emoji .name { font-size: 12px; color: @em_dim; }\n"
    + "window.lx-emoji separator { background-color: @em_sep; min-height: 1px; }\n")

# Stejne barvy jako Ovladaci centrum a Snimek obrazovky; bez kompozitoru neprusvitne pozadi
function colors(dark, opaque):
    if dark:
        bg = "rgba(32, 33, 52, 0.90)"
        if opaque:
            bg = "rgb(32, 33, 52)"
        end
        return ("@define-color em_bg " + bg + "; @define-color em_border rgba(255, 255, 255, 0.14);\n"
            + "@define-color em_fg #f4f4fa; @define-color em_dim rgba(244, 244, 250, 0.68); @define-color em_hover rgba(255, 255, 255, 0.10);\n"
            + "@define-color em_active rgba(255, 255, 255, 0.20); @define-color em_sep rgba(255, 255, 255, 0.12);\n"
            + "@define-color em_entry rgba(255, 255, 255, 0.08); @define-color em_accent #5a8fff; @define-color em_ring rgba(90, 143, 255, 0.35);\n")
    end
    bg = "rgba(246, 247, 252, 0.92)"
    if opaque:
        bg = "rgb(246, 247, 252)"
    end
    return ("@define-color em_bg " + bg + "; @define-color em_border rgba(0, 0, 0, 0.10);\n"
        + "@define-color em_fg #1d1d2b; @define-color em_dim rgba(29, 29, 43, 0.62); @define-color em_hover rgba(0, 0, 0, 0.06);\n"
        + "@define-color em_active rgba(0, 0, 0, 0.12); @define-color em_sep rgba(0, 0, 0, 0.10);\n"
        + "@define-color em_entry rgba(255, 255, 255, 0.85); @define-color em_accent #3d7bff; @define-color em_ring rgba(61, 123, 255, 0.28);\n")
end

S = {"built": False, "data": None, "provider": 0, "composited": False, "visible": False, "had_focus": False,
     "standalone": False, "listening": False, "resident": False, "exit_code": 0, "target": 0, "target_class": ["", ""],
     "cfg": None, "boost": None, "query": "", "sel": 0, "hover": -1, "scroll": 0, "nav": False, "inserting": False,
     "token": 0, "pending": None, "job": None, "tab": -1, "quit_check": False, "dark": False}
W = {}
V = {"rows": [], "items": [], "pos": [], "sections": [], "height": 0, "search": False}

function T(value):
    return i18n.T(value)
end

function log(message):
    call eprint("luxos-emoji: " + message)
    return 0
end

# LUXOS_EMOJI_TEST_LOG: radky o stavu okna a vlozeni pro testy (s casem CLOCK_MONOTONIC)
function tlog(message):
    path = env.get("LUXOS_EMOJI_TEST_LOG", "")
    if path != None and path != "":
        call appendfile(path, message + " @" + String(monotonic()) + "\n")
    end
    return 0
end

function notify(message):
    call tlog("notify " + message)
    call glib.spawn_quiet(["notify-send", "-a", T("Emoji & Symbols"), "-i", "luxos-emoji", T("Emoji & Symbols"), message])
    return 0
end

# ---- data a vzhled -----------------------------------------------------------------------------------------------

function ensure_data():
    if S["data"] == None:
        S["data"] = base.load_data(base.data_dir(), base.lang())
        if not S["data"]["ok"]:
            call log("no emoji data in " + base.data_dir())
        end
    end
    if S["cfg"] == None:
        S["cfg"] = base.load_config(base.config_path())
    end
    return S["data"]
end

function is_dark():
    forced = env.get("GTK_THEME", "")
    if forced != None and forced != "":
        return forced.lower().find("dark") >= 0
    end
    return gtk.settings_theme_name().lower().find("dark") >= 0 or gtk.settings_prefer_dark()
end

function css_text():
    return colors(is_dark(), not S["composited"]) + CSS
end

function on_theme_changed(bound, pspec, settings):
    if S["provider"] != 0:
        S["dark"] = is_dark()
        call gtk.css_set(S["provider"], css_text())
    end
    return 0
end

# ---- okno ---------------------------------------------------------------------------------------------------------

function prebuild():
    call ensure_data()
    call ensure_built()
    return 0
end

function ensure_built():
    if S["built"]:
        return 0
    end
    S["built"] = True
    call tlog("built")
    call ensure_data()
    S["composited"] = gtk.rgba_available()
    S["dark"] = is_dark()
    S["provider"] = gtk.css_load(css_text())
    call gtk.connect_data(gtk.settings_get_default(), "notify::gtk-theme-name", 1, on_theme_changed, 0)
    call gtk.connect_data(gtk.settings_get_default(), "notify::gtk-application-prefer-dark-theme", 1, on_theme_changed, 0)

    win = gtk.window_new(T("Emoji & Symbols"))
    W["win"] = win
    call gtk.widget_add_class(win, "lx-emoji")
    call gtk.window_set_decorated(win, False)
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_skip_taskbar_hint(win, True)
    call gtk.window_set_skip_pager_hint(win, True)
    call gtk.window_set_keep_above(win, True)
    call gtk.window_set_type_hint(win, gtk.TYPE_HINT_DIALOG)
    call gtk.window_set_rgba(win)
    if not S["composited"]:
        # bez kompozitoru by rohy byly cerne: tvar okna oriznout na zaobleny obdelnik
        call gtk.connect_data(win, "size-allocate", 1, on_shape_alloc, 14)
    end
    call gtk.window_set_wmclass(win, "luxos-emoji", "Luxos-emoji")
    call gtk.window_set_icon_list(win, "luxos-emoji")

    outer = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(outer, "panel")
    call gtk.container_add(win, outer)

    entry = gtk.search_entry_new()
    W["entry"] = entry
    call gtk.entry_set_placeholder_text(entry, T("Search emoji"))
    call gtk.connect_data(entry, "changed", 0, on_changed, 0)
    call gtk.box_pack_start(outer, entry, False, False, 0)

    tabs = gtk.box_new(gtk.HORIZONTAL, 2)
    call gtk.widget_add_class(tabs, "tabs")
    call gtk.box_set_homogeneous(tabs, True)
    W["tabs"] = []
    index = 0
    while index < len(base.TAB_ICONS):
        b = gtk.button_new(base.TAB_ICONS[index])
        call gtk.widget_set_can_focus(b, False)
        call gtk.widget_set_tooltip(b, tab_title(index))
        call gtk.connect_data(b, "clicked", 0, on_tab_clicked, index)
        call gtk.box_pack_start(tabs, b, True, True, 0)
        W["tabs"].append(b)
        index += 1
    end
    call gtk.box_pack_start(outer, tabs, False, False, 0)

    area = gtk.drawing_area_new()
    W["area"] = area
    call gtk.widget_set_size_request(area, GRID_W, GRID_H)
    call gtk.widget_add_events(area, gtk.POINTER_MOTION_MASK | gtk.BUTTON_PRESS_MASK | gtk.BUTTON_RELEASE_MASK | gtk.SCROLL_MASK | gtk.SMOOTH_SCROLL_MASK | gtk.LEAVE_NOTIFY_MASK)
    call gtk.connect_data(area, "draw", 1, on_draw, 0)
    call gtk.connect_data(area, "motion-notify-event", 1, on_motion, 0)
    call gtk.connect_data(area, "button-press-event", 1, on_press, 0)
    call gtk.connect_data(area, "scroll-event", 1, on_scroll, 0)
    call gtk.connect_data(area, "leave-notify-event", 1, on_leave, 0)
    call gtk.box_pack_start(outer, area, False, False, 0)

    call gtk.box_pack_start(outer, gtk.separator_new(gtk.HORIZONTAL), False, False, 0)
    footer = gtk.box_new(gtk.HORIZONTAL, 6)
    name = gtk.label_new("")
    W["name"] = name
    call gtk.widget_add_class(name, "name")
    call gtk.label_set_xalign(name, 0.0)
    call gtk.label_set_ellipsize(name, gtk.ELLIPSIZE_END)
    # dlouhy nazev nesmi okno rozsirit (ellipsize jen v pridelene sirce)
    call gtk.label_set_max_width_chars(name, 16)
    call gtk.widget_set_hexpand(name, True)
    call gtk.box_pack_start(footer, name, True, True, 2)
    tones = gtk.box_new(gtk.HORIZONTAL, 1)
    call gtk.widget_add_class(tones, "tones")
    W["tones"] = []
    index = 0
    while index < 6:
        label = TONE_HAND
        if index > 0:
            label = TONE_HAND + base.TONE_MODIFIERS[index - 1]
        end
        b = gtk.button_new(label)
        call gtk.widget_set_can_focus(b, False)
        call gtk.connect_data(b, "clicked", 0, on_tone_clicked, index)
        call gtk.box_pack_start(tones, b, False, False, 0)
        W["tones"].append(b)
        index += 1
    end
    call gtk.box_pack_end(footer, tones, False, False, 0)
    call gtk.box_pack_start(outer, footer, False, False, 0)

    call gtk.connect_data(win, "key-press-event", 1, on_key, 0)
    call gtk.connect_data(win, "focus-in-event", 1, on_focus_in, 0)
    call gtk.connect_data(win, "focus-out-event", 1, on_focus_out, 0)
    call gtk.connect_data(win, "delete-event", 1, on_delete, 0)
    call gtk.connect_data(win, "map-event", 1, on_map, 0)
    call update_tones()
    call rebuild()
    # obsah viditelny predem: velikost okna pro umisteni je znama uz pred prvnim zobrazenim
    call gtk.widget_show_all(outer)
    return 0
end

function on_shape_alloc(radius, allocation, win):
    call gtk.widget_shape_rounded(win, gtk.widget_get_allocated_width(win), gtk.widget_get_allocated_height(win), radius)
    return 0
end

function tab_title(index):
    if index == 0:
        if len(recent_items()) > 0 and len(S["cfg"]["recent"]) > 0:
            return T("Recently Used")
        end
        return T("Frequently Used")
    end
    return T(base.GROUPS[index - 1])
end

function tone_title(index):
    if index == 0:
        return T("Default skin tone")
    end
    name = S["data"]["tone_names"][index - 1]
    if name == "":
        return T("Skin tone")
    end
    return base.cap_first(name)
end

function update_tones():
    index = 0
    while index < 6:
        b = W["tones"][index]
        call gtk.widget_set_class(b, "active", index == S["cfg"]["tone"])
        call gtk.widget_set_tooltip(b, tone_title(index))
        index += 1
    end
    return 0
end

# ---- obsah mrizky -------------------------------------------------------------------------------------------------

function recent_items():
    data = S["data"]
    items = base.recent_indexes(data, S["cfg"]["recent"])
    if len(items) == 0:
        items = base.default_indexes(data)
    end
    return items
end

function add_header(title):
    V["rows"].append({"kind": "h", "y": V["height"], "title": title})
    V["height"] = V["height"] + HEADER_H
    return 0
end

function add_cells(items):
    index = 0
    while index < len(items):
        row = {"kind": "c", "y": V["height"], "first": len(V["items"]), "n": 0}
        n = 0
        while n < COLS and index < len(items):
            V["items"].append(items[index])
            V["pos"].append(len(V["rows"]))
            index += 1
            n += 1
        end
        row["n"] = n
        V["rows"].append(row)
        V["height"] = V["height"] + CELL
    end
    return 0
end

# Radky mrizky podle hledani (vysledky) nebo vsech skupin (sekce pro zalozky)
function rebuild():
    data = S["data"]
    V["rows"] = []
    V["items"] = []
    V["pos"] = []
    V["sections"] = []
    V["height"] = 0
    V["search"] = S["query"].strip() != ""
    if V["search"]:
        if S["boost"] == None:
            S["boost"] = base.boost_set(data, S["cfg"]["recent"])
        end
        found = base.search(data, S["query"], SEARCH_LIMIT, S["boost"])
        V["height"] = 4
        call add_cells(found)
    else:
        V["sections"].append([0, 0, 0])
        call add_header(tab_title(0))
        call add_cells(recent_items())
        g = 0
        while g < len(base.GROUPS):
            items = data["groups"][g]
            if len(items) > 0:
                V["sections"].append([g + 1, V["height"], len(V["items"])])
                call add_header(T(base.GROUPS[g]))
                call add_cells(items)
            end
            g += 1
        end
    end
    V["height"] = V["height"] + 4
    S["sel"] = 0
    S["hover"] = -1
    S["scroll"] = 0
    S["nav"] = False
    call after_change()
    return 0
end

function after_change():
    call update_name()
    call update_tabs()
    if S["built"]:
        call gtk.widget_queue_draw(W["area"])
    end
    return 0
end

function display(k):
    return base.with_tone(S["data"], V["items"][k], S["cfg"]["tone"])
end

function update_name():
    k = S["hover"]
    if k < 0:
        k = S["sel"]
    end
    value = ""
    if k >= 0 and k < len(V["items"]):
        value = base.cap_first(S["data"]["name"][V["items"][k]])
    end
    call gtk.label_set_text(W["name"], value)
    return 0
end

# Zvyraznena zalozka podle polohy posuvu (pri hledani zadna)
function update_tabs():
    active = -1
    if not V["search"]:
        for sec in V["sections"]:
            if sec[1] <= S["scroll"] + 6:
                active = sec[0]
            end
        end
    end
    if active == S["tab"]:
        return 0
    end
    S["tab"] = active
    index = 0
    while index < len(W["tabs"]):
        call gtk.widget_set_class(W["tabs"][index], "active", index == active)
        index += 1
    end
    return 0
end

function max_scroll():
    return max(0, V["height"] - GRID_H)
end

function set_scroll(value):
    v = Int(value)
    if v < 0:
        v = 0
    end
    if v > max_scroll():
        v = max_scroll()
    end
    if v != S["scroll"]:
        S["scroll"] = v
        call update_tabs()
        call gtk.widget_queue_draw(W["area"])
    end
    return 0
end

function ensure_visible(k):
    if k < 0 or k >= len(V["items"]):
        return 0
    end
    r = V["pos"][k]
    y = V["rows"][r]["y"]
    top = y
    if r > 0 and V["rows"][r - 1]["kind"] == "h":
        top = V["rows"][r - 1]["y"]
    end
    if top < S["scroll"]:
        call set_scroll(top)
    elif y + CELL > S["scroll"] + GRID_H:
        call set_scroll(y + CELL - GRID_H)
    end
    return 0
end

# Index polozky pod bodem mrizky, -1 kdyz tam zadna neni
function item_at(x, y):
    if x < 0 or x >= COLS * CELL:
        return -1
    end
    yy = Int(y) + S["scroll"]
    col = Int(x) // CELL
    for row in V["rows"]:
        if row["kind"] == "c" and yy >= row["y"] and yy < row["y"] + CELL:
            if col < row["n"]:
                return row["first"] + col
            end
            return -1
        end
        if row["y"] > yy:
            break
        end
    end
    return -1
end

function select(k):
    if len(V["items"]) == 0:
        return 0
    end
    if k < 0:
        k = 0
    end
    if k >= len(V["items"]):
        k = len(V["items"]) - 1
    end
    S["sel"] = k
    S["hover"] = -1
    call ensure_visible(k)
    call update_name()
    call gtk.widget_queue_draw(W["area"])
    return 0
end

# Posun vyberu o radek (dy) se stejnym sloupcem; nadpisy sekci se preskoci
function move_rows(dy):
    if len(V["items"]) == 0:
        return 0
    end
    k = S["sel"]
    r = V["pos"][k]
    col = k - V["rows"][r]["first"]
    r2 = r + dy
    while r2 >= 0 and r2 < len(V["rows"]) and V["rows"][r2]["kind"] != "c":
        r2 += dy
    end
    if r2 < 0 or r2 >= len(V["rows"]):
        if dy < 0:
            call select(0)
        else:
            call select(len(V["items"]) - 1)
        end
        return 0
    end
    row = V["rows"][r2]
    call select(row["first"] + min(col, row["n"] - 1))
    return 0
end

# ---- kresleni -----------------------------------------------------------------------------------------------------

function on_map(bound, event, win):
    call tlog("drawn")
    return False
end

function on_draw(bound, cr, area):
    t0 = monotonic()
    h = gtk.widget_get_allocated_height(area)
    w = gtk.widget_get_allocated_width(area)
    fg = gtk.widget_get_color(area, 0)
    scroll = S["scroll"]
    data = S["data"]
    layout = pango.cairo_create_layout(cr)
    call pango.layout_set_font(layout, EMOJI_FONT)
    head = pango.cairo_create_layout(cr)
    family = gtk.widget_get_font_family(area)
    if family == "":
        family = "Sans"
    end
    call pango.layout_set_font(head, family + " Bold 12px")
    x0 = (w - COLS * CELL) // 2
    for row in V["rows"]:
        if row["y"] + CELL < scroll:
            continue
        end
        if row["y"] > scroll + h:
            break
        end
        y = row["y"] - scroll
        if row["kind"] == "h":
            call pango.layout_set_text(head, row["title"])
            call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.55)
            call cairo.move_to(cr, x0 + 6, y + 9)
            call pango.cairo_show_layout(cr, head)
            continue
        end
        c = 0
        while c < row["n"]:
            k = row["first"] + c
            x = x0 + c * CELL
            if k == S["sel"]:
                call cairo.set_source_rgba(cr, 0.24, 0.48, 1.0, 0.30)
                call cairo.rounded_rectangle(cr, x + 1, y + 1, CELL - 2, CELL - 2, 8.0)
                call cairo.fill(cr)
            elif k == S["hover"]:
                call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.09)
                call cairo.rounded_rectangle(cr, x + 1, y + 1, CELL - 2, CELL - 2, 8.0)
                call cairo.fill(cr)
            end
            call pango.layout_set_text(layout, display(k))
            size = pango.layout_get_pixel_size(layout)
            call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 1.0)
            call cairo.move_to(cr, x + (CELL - size[0]) // 2, y + (CELL - size[1]) // 2)
            call pango.cairo_show_layout(cr, layout)
            c += 1
        end
    end
    if V["search"] and len(V["items"]) == 0:
        call pango.layout_set_font(head, family + " 13px")
        call pango.layout_set_text(head, T("No emoji found"))
        size = pango.layout_get_pixel_size(head)
        call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.55)
        call cairo.move_to(cr, (w - size[0]) // 2, (h - size[1]) // 2 - 10)
        call pango.cairo_show_layout(cr, head)
    end
    # tenky posuvnik jako v macOS
    if V["height"] > h:
        track = Float(h - 8)
        thumb = max(24.0, track * Float(h) / Float(V["height"]))
        top = 4.0 + (track - thumb) * Float(scroll) / Float(max(1, max_scroll()))
        call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.22)
        call cairo.rounded_rectangle(cr, Float(w) - 5.0, top, 3.0, thumb, 1.5)
        call cairo.fill(cr)
    end
    call pango.layout_unref(layout)
    call pango.layout_unref(head)
    call tlog("draw " + String(Int((monotonic() - t0) * 1000.0)) + "ms")
    return False
end

# ---- udalosti -----------------------------------------------------------------------------------------------------

function grid_x(event):
    w = gtk.widget_get_allocated_width(W["area"])
    return gtk.event_x(event) - Float((w - COLS * CELL) // 2)
end

function on_motion(bound, event, area):
    k = item_at(grid_x(event), gtk.event_y(event))
    if k != S["hover"]:
        S["hover"] = k
        call update_name()
        call gtk.widget_queue_draw(area)
    end
    return False
end

function on_leave(bound, event, area):
    if S["hover"] != -1:
        S["hover"] = -1
        call update_name()
        call gtk.widget_queue_draw(area)
    end
    return False
end

function on_press(bound, event, area):
    if gtk.event_button(event) != 1:
        return False
    end
    k = item_at(grid_x(event), gtk.event_y(event))
    if k < 0:
        return True
    end
    keep = (gtk.event_button_state(event) & gtk.SHIFT_MASK) != 0
    S["sel"] = k
    call choose(k, keep)
    return True
end

function on_scroll(bound, event, area):
    direction = gtk.event_scroll_direction(event)
    delta = 0.0
    if direction == gtk.SCROLL_SMOOTH:
        delta = gtk.event_scroll_deltas(event)[1] * 60.0
    elif direction == gtk.SCROLL_UP:
        delta = -80.0
    elif direction == gtk.SCROLL_DOWN:
        delta = 80.0
    end
    call set_scroll(Float(S["scroll"]) + delta)
    return True
end

function on_changed(bound, entry):
    text = gtk.entry_get_text(entry)
    if text == S["query"]:
        return 0
    end
    S["query"] = text
    call rebuild()
    return 0
end

function on_tab_clicked(index, button):
    if S["query"] != "":
        call gtk.entry_set_text(W["entry"], "")
    end
    for sec in V["sections"]:
        if sec[0] == index:
            call set_scroll(sec[1])
            if sec[2] < len(V["items"]):
                S["sel"] = sec[2]
                call update_name()
            end
        end
    end
    call update_tabs()
    call gtk.widget_grab_focus(W["entry"])
    return 0
end

function on_tone_clicked(index, button):
    if S["cfg"]["tone"] != index:
        S["cfg"]["tone"] = index
        call base.save_config(S["cfg"], base.config_path())
        call update_tones()
        call gtk.widget_queue_draw(W["area"])
    end
    call gtk.widget_grab_focus(W["entry"])
    return 0
end

# Dalsi/predchozi skupina (Tab / Shift+Tab)
function next_tab(step):
    if V["search"] or len(V["sections"]) == 0:
        return 0
    end
    current = 0
    index = 0
    while index < len(V["sections"]):
        if V["sections"][index][0] == S["tab"]:
            current = index
        end
        index += 1
    end
    target = (current + step) % len(V["sections"])
    call on_tab_clicked(V["sections"][target][0], 0)
    return 0
end

function on_key(bound, event, win):
    key = gtk.event_key_keyval(event)
    state = gtk.event_key_state(event)
    shift = (state & gtk.SHIFT_MASK) != 0
    if key == KEY_ESCAPE:
        call close()
        return True
    end
    if key == KEY_RETURN or key == KEY_KP_ENTER:
        if len(V["items"]) > 0:
            call choose(S["sel"], shift)
        end
        return True
    end
    if key == KEY_DOWN or key == KEY_UP:
        S["nav"] = True
        if key == KEY_DOWN:
            call move_rows(1)
        else:
            call move_rows(-1)
        end
        return True
    end
    if key == KEY_PAGE_DOWN or key == KEY_PAGE_UP:
        S["nav"] = True
        step = GRID_H // CELL - 1
        while step > 0:
            if key == KEY_PAGE_DOWN:
                call move_rows(1)
            else:
                call move_rows(-1)
            end
            step -= 1
        end
        return True
    end
    if key == KEY_LEFT or key == KEY_RIGHT:
        # v poli hledani posouvaji kurzor, dokud se nezacne chodit po mrizce (nebo je pole prazdne)
        if S["nav"] or S["query"] == "":
            S["nav"] = True
            if key == KEY_RIGHT:
                call select(S["sel"] + 1)
            else:
                call select(S["sel"] - 1)
            end
            return True
        end
        return False
    end
    if key == KEY_TAB:
        call next_tab(1)
        return True
    end
    if key == KEY_ISO_LEFT_TAB:
        call next_tab(-1)
        return True
    end
    S["nav"] = False
    return False
end

function on_focus_in(bound, event, win):
    S["had_focus"] = True
    return False
end

function on_focus_out(bound, event, win):
    if S["visible"] and S["had_focus"] and not S["inserting"]:
        call glib.idle_add_data(focus_out_idle, S["token"])
    end
    return False
end

function focus_out_idle(token):
    if S["visible"] and not S["inserting"] and token == S["token"] and not gtk.window_is_active(W["win"]):
        call close()
    end
    return False
end

function on_delete(bound, event, win):
    call close()
    return True
end

# ---- otevreni a zavreni ------------------------------------------------------------------------------------------

function place():
    win = W["win"]
    p = gtk.pointer_position()
    wa = gtk.monitor_at_point_workarea(p[0], p[1])
    if wa[2] <= 0 or wa[3] <= 0:
        wa = [0, 0, gtk.root_size()[0], gtk.root_size()[1]]
    end
    ww = gtk.widget_get_preferred_width(win)[1]
    wh = gtk.widget_get_preferred_height(win)[1]
    x = p[0] - ww // 2
    y = p[1] + 18
    if y + wh > wa[1] + wa[3]:
        y = p[1] - wh - 18
    end
    x = max(wa[0] + 8, min(x, wa[0] + wa[2] - ww - 8))
    y = max(wa[1] + 8, min(y, wa[1] + wa[3] - wh - 8))
    call gtk.window_move(win, x, y)
    return 0
end

function open(search):
    call tlog("open")
    call ensure_built()
    S["token"] = S["token"] + 1
    own = gtk.widget_xid(W["win"])
    target = x11.active_window()
    if target == own and own != 0:
        target = S["target"]
    end
    S["target"] = target
    S["target_class"] = ["", ""]
    if target != 0:
        S["target_class"] = x11.wm_class(target)
    end
    call tlog("target " + String(target) + " " + S["target_class"][0] + "/" + S["target_class"][1])
    S["cfg"] = base.load_config(base.config_path())
    S["boost"] = None
    S["had_focus"] = False
    call update_tones()
    call gtk.widget_set_tooltip(W["tabs"][0], tab_title(0))
    value = ""
    if search != None:
        value = search
    end
    S["query"] = value
    call gtk.entry_set_text(W["entry"], value)
    call rebuild()
    call tlog("rebuilt")
    call place()
    call gtk.widget_show_all(W["win"])
    S["visible"] = True
    stamp = gtk.x11_server_time(W["win"])
    call gtk.window_present_with_time(W["win"], stamp)
    call gtk.entry_grab_focus_without_selecting(W["entry"])
    call tlog("shown")
    return 0
end

function close():
    if not S["built"]:
        return 0
    end
    S["token"] = S["token"] + 1
    if S["visible"]:
        call gtk.widget_hide(W["win"])
        S["visible"] = False
        call tlog("hidden")
    end
    if S["standalone"]:
        call schedule_quit_check()
    end
    return 0
end

function is_visible():
    return S["visible"]
end

# ---- vlozeni do aplikace -----------------------------------------------------------------------------------------

function choose(k, keep):
    if k < 0 or k >= len(V["items"]):
        return 0
    end
    e = display(k)
    S["cfg"]["recent"] = base.add_recent(S["cfg"]["recent"], e)
    call base.save_config(S["cfg"], base.config_path())
    S["boost"] = None
    call tlog("chose " + e)
    target = S["target"]
    method = base.paste_method(S["target_class"])
    S["token"] = S["token"] + 1
    job = {"e": e, "target": target, "method": method, "keep": keep, "token": S["token"], "text": None, "image": 0,
           "primary": None, "tries": 0, "time": gtk.x11_server_time(W["win"]), "cancelled": False}
    S["job"] = job
    # behem vkladani: okno se nezavre ztratou fokusu (Shift+Enter) a samostatny proces neskonci
    S["inserting"] = True
    if not keep:
        call close()
    end
    if target == 0 or not x11.window_alive(target):
        call copy_only(job)
        return 0
    end
    # Rozbehnute vraceni predchozi schranky: puvodni obsah prevezme nove vlozeni (jinak by se "vratilo" emoji)
    pending = S["pending"]
    if pending != None:
        pending["cancelled"] = True
        S["pending"] = None
        job["text"] = pending["text"]
        job["image"] = pending["image"]
        job["primary"] = pending["primary"]
        call paste_start(job)
        return 0
    end
    call gtk.selection_request_text(gtk.SELECTION_CLIPBOARD, on_saved_text, job)
    return 0
end

function on_saved_text(job, value):
    job["text"] = value
    if value == None:
        call gtk.selection_request_image(gtk.SELECTION_CLIPBOARD, on_saved_image, job)
        return 0
    end
    call saved_primary_step(job)
    return 0
end

function on_saved_image(job, pixbuf):
    job["image"] = pixbuf
    call saved_primary_step(job)
    return 0
end

function saved_primary_step(job):
    if job["method"] == "shift-insert":
        call gtk.selection_request_text(gtk.SELECTION_PRIMARY, on_saved_primary, job)
        return 0
    end
    call paste_start(job)
    return 0
end

function on_saved_primary(job, value):
    job["primary"] = value
    call paste_start(job)
    return 0
end

function paste_start(job):
    if job["token"] != S["token"] and S["job"] != job:
        return 0
    end
    call gtk.selection_set_text(gtk.SELECTION_CLIPBOARD, job["e"])
    if job["method"] == "shift-insert":
        call gtk.selection_set_text(gtk.SELECTION_PRIMARY, job["e"])
    end
    if not x11.activate(job["target"], job["time"]):
        call paste_failed(job)
        return 0
    end
    call glib.timeout_add_data(15, paste_wait, job)
    return 0
end

function paste_wait(job):
    if x11.active_window() == job["target"]:
        # chvile na zpracovani FocusIn v aplikaci
        call glib.timeout_add_data(40, paste_send, job)
        return False
    end
    job["tries"] = job["tries"] + 1
    if job["tries"] > FOCUS_TRIES or not x11.window_alive(job["target"]):
        call paste_failed(job)
        return False
    end
    return True
end

function paste_send(job):
    call x11.release_modifiers()
    ok = False
    if job["method"] == "ctrl-shift-v":
        ok = x11.send_keys([KEY_CONTROL_L, KEY_SHIFT_L], KEY_V)
    elif job["method"] == "shift-insert":
        ok = x11.send_keys([KEY_SHIFT_L], KEY_INSERT)
    else:
        ok = x11.send_keys([KEY_CONTROL_L], KEY_V)
    end
    if not ok:
        call paste_failed(job)
        return False
    end
    call tlog("pasted " + job["method"])
    S["pending"] = job
    call glib.timeout_add_data(RESTORE_MS, restore, job)
    if job["keep"]:
        call glib.timeout_add_data(150, reopen, job)
    else:
        S["inserting"] = False
    end
    return False
end

# Shift+Enter: zpet do okna vyberu (puvodni okno uz vlozene emoji ma)
function reopen(job):
    S["inserting"] = False
    if S["visible"]:
        S["had_focus"] = False
        stamp = gtk.x11_server_time(W["win"])
        call gtk.window_present_with_time(W["win"], stamp)
        call gtk.entry_grab_focus_without_selecting(W["entry"])
        call tlog("reopened")
    end
    return False
end

function paste_failed(job):
    call tlog("paste failed")
    call copy_only(job)
    return 0
end

# Vlozit nejde: emoji zustane ve schrance (puvodni obsah se nevraci) a upozorneni to rekne
function copy_only(job):
    call gtk.selection_set_text(gtk.SELECTION_CLIPBOARD, job["e"])
    if job["image"] != 0:
        call gtk.object_unref(job["image"])
        job["image"] = 0
    end
    call tlog("copied")
    call notify(T("The emoji was copied to the clipboard. Paste it with Ctrl+V."))
    if job["keep"]:
        call glib.timeout_add_data(150, reopen, job)
    else:
        S["inserting"] = False
    end
    if S["standalone"]:
        call schedule_quit_check()
    end
    return 0
end

# Po vlozeni puvodni obsah schranky (a PRIMARY u xterm), pokud ji mezitim nikdo jiny neprevzal
function restore(job):
    if job["cancelled"]:
        return False
    end
    if S["pending"] == job:
        S["pending"] = None
    end
    if gtk.selection_owned(gtk.SELECTION_CLIPBOARD):
        if job["text"] != None:
            call gtk.selection_set_text(gtk.SELECTION_CLIPBOARD, job["text"])
            call tlog("restored text")
        elif job["image"] != 0:
            call gtk.selection_set_image(gtk.SELECTION_CLIPBOARD, job["image"])
            call tlog("restored image")
        else:
            call tlog("restore nothing")
        end
    else:
        call tlog("restore skipped")
    end
    if job["image"] != 0:
        call gtk.object_unref(job["image"])
        job["image"] = 0
    end
    if job["method"] == "shift-insert" and job["primary"] != None and gtk.selection_owned(gtk.SELECTION_PRIMARY):
        call gtk.selection_set_text(gtk.SELECTION_PRIMARY, job["primary"])
    end
    if S["standalone"]:
        call schedule_quit_check()
    end
    return False
end

# ---- samostatny proces ---------------------------------------------------------------------------------------------

function schedule_quit_check():
    if not S["quit_check"]:
        S["quit_check"] = True
        call glib.timeout_add_data(300, quit_check, 0)
    end
    return 0
end

# Samostatny proces skonci, az nic nedela; drzi-li schranku (vlozene emoji, vraceny obsah), ceka, dokud ji
# neprevezme jiny program (jinak by obsah zmizel)
function quit_check(bound):
    if S["resident"]:
        S["quit_check"] = False
        return False
    end
    if S["visible"] or S["inserting"] or S["pending"] != None:
        return True
    end
    if gtk.selection_owned(gtk.SELECTION_CLIPBOARD) or gtk.selection_owned(gtk.SELECTION_PRIMARY):
        return True
    end
    S["quit_check"] = False
    call gtk.main_quit()
    return False
end

function exit_code():
    return S["exit_code"]
end

# ---- pozadavky -------------------------------------------------------------------------------------------------------

function sink_send(sink, line):
    if sink == None:
        if line.startswith("err "):
            call eprint(line[4:].strip())
        end
        return True
    end
    if sink["fd"] < 0:
        return False
    end
    if not luxos_sys.send_text(sink["fd"], line):
        call luxos_sys.close(sink["fd"])
        sink["fd"] = -1
        return False
    end
    return True
end

function sink_finish(sink, code):
    if sink == None:
        S["exit_code"] = code
        return 0
    end
    call sink_send(sink, "exit " + String(code) + "\n")
    if sink["fd"] >= 0:
        call luxos_sys.close(sink["fd"])
        sink["fd"] = -1
    end
    return 0
end

# Pozadavek klienta (nebo samostatneho procesu, sink None): otevrit / zavrit (stejna zkratka okno zavre)
function handle_request(argv, sink):
    a = base.parse_args(argv)
    if "error" in a:
        call sink_send(sink, "err " + a["error"] + "\n")
        call sink_finish(sink, 1)
        return 0
    end
    if a["help"]:
        call sink_finish(sink, 0)
        return 0
    end
    call ensure_built()
    if a["action"] == "close" or (a["action"] == "toggle" and S["visible"]):
        call close()
        call sink_finish(sink, 0)
        return 0
    end
    if not S["data"]["ok"]:
        call sink_send(sink, "err luxos-emoji: emoji data missing (" + base.data_dir() + ")\n")
    end
    call open(a["search"])
    call sink_finish(sink, 0)
    return 0
end

# ---- server (socket) ---------------------------------------------------------------------------------------------

function start_server(standalone):
    S["standalone"] = standalone
    fd = luxos_sys.unix_listen(base.socket_name())
    if fd >= 0:
        S["listening"] = True
        call glib.fd_add_data(fd, 1, on_listen, fd)
        return True
    end
    if not standalone:
        # jmeno drzi samostatny proces (hub se restartoval): zkusit pozdeji
        call glib.timeout_add_seconds_data(5, retry_listen, 0)
    end
    return False
end

function retry_listen(bound):
    fd = luxos_sys.unix_listen(base.socket_name())
    if fd < 0:
        return True
    end
    S["listening"] = True
    call glib.fd_add_data(fd, 1, on_listen, fd)
    return False
end

function on_listen(listen_fd, handle, condition):
    while True:
        conn = luxos_sys.unix_accept(listen_fd)
        if conn < 0:
            break
        end
        if luxos_sys.peer_uid(conn) != luxos_sys.getuid():
            call luxos_sys.close(conn)
            continue
        end
        state = {"fd": conn, "buf": "", "done": False}
        call glib.fd_add_data(conn, 1 + 8 + 16, on_conn_data, state)
        call glib.timeout_add_data(5000, conn_timeout, state)
    end
    return True
end

function conn_timeout(state):
    if not state["done"]:
        state["done"] = True
        call luxos_sys.close(state["fd"])
    end
    return False
end

function on_conn_data(state, handle, condition):
    if state["done"]:
        return False
    end
    r = luxos_sys.recv_text(state["fd"])
    if r[0] > 0:
        state["buf"] = state["buf"] + r[1]
        if len(state["buf"]) > 16384:
            state["done"] = True
            call luxos_sys.close(state["fd"])
            return False
        end
        argv = base.request_args(state["buf"])
        if argv == None:
            return True
        end
        state["done"] = True
        sink = {"fd": state["fd"]}
        if not sink_send(sink, "ok\n"):
            return False
        end
        try:
            call handle_request(argv, sink)
        else:
            call log("request: " + String(last_error()))
            call sink_finish(sink, 1)
        end
        return False
    end
    if r[0] == 0 or condition & 24 != 0:
        state["done"] = True
        call luxos_sys.close(state["fd"])
        return False
    end
    return True
end
