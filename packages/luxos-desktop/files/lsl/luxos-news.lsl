# LuxOS - Novinky: oznameni od vyvojaru LuxOS (nove vydani, udrzba, dulezite zmeny) v okne a v oznamenich.
#
#   luxos-news                okno s novinkami (z mezipameti, na pozadi zkontroluje nove); otevrene = prectene
#   luxos-news --check        stahne kanal a ohlasi nove novinky (luxos-hub po prihlaseni a kazdych 6 h);
#                             po ohlaseni ceka na klik na oznameni (otevre okno), nez se vsechna zavrou
#   luxos-news --fetch        jen stahne kanal (okno ho spousti na pozadi), vypise pocet platnych novinek
#   luxos-news --list         platne novinky jako JSON (ladeni, testy)
#
# Pro vyvojare (docs/developers/announcements.md):
#   luxos-news validate SOUBOR                          zkontroluje kanal, vypise chyby (navratovy kod 1)
#   luxos-news new SOUBOR --title TEXT [--title-cs TEXT] [--body TEXT] [--body-cs TEXT] [--url https://...]
#                         [--date YYYY-MM-DD] [--until YYYY-MM-DD] [--level important] [--id ID]
#                                                       prida novinku na zacatek kanalu (vytvori ho)
# Logika a format: luxos_news.lsl. Okno jako ostatni aplikace LuxOS v LSL (Hodiny, O tomto pocitaci):
# obycejne okno GTK, horni listu se semaforem kresli spravce oken, ostra ikona 16-256 px.
# Testy: LUXOS_NEWS_TEST_LOG=<soubor> - okno zapise zobrazene novinky a velikost okna.
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_text as txt
load luxos_news as news

KEY_ESCAPE = 65307
KEY_Q = 113
KEY_W = 119

LIGHT = ("@define-color n_bg #f6f6f9; @define-color n_fg #1d1d1f; @define-color n_dim rgba(29, 29, 31, 0.55);\n"
    + "@define-color n_group #ffffff; @define-color n_line rgba(0, 0, 0, 0.08); @define-color n_accent #3d7bff;\n"
    + "@define-color n_link #1f5fe0; @define-color n_important #ff9500; @define-color n_tint rgba(255, 149, 0, 0.09);\n")
DARK = ("@define-color n_bg #1c1c22; @define-color n_fg #f5f5f7; @define-color n_dim rgba(245, 245, 247, 0.55);\n"
    + "@define-color n_group #2a2a30; @define-color n_line rgba(255, 255, 255, 0.07); @define-color n_accent #4f8bff;\n"
    + "@define-color n_link #7aa7ff; @define-color n_important #ff9f0a; @define-color n_tint rgba(255, 159, 10, 0.12);\n")
CSS = ("window.news { background-color: @n_bg; color: @n_fg; }\n"
    + ".news label { color: @n_fg; }\n"
    + ".news .news-head { font-size: 24px; font-weight: 800; letter-spacing: -0.3px; }\n"
    + ".news .dim { color: @n_dim; }\n"
    + ".news .small { font-size: 12px; }\n"
    + ".news .section { font-size: 11px; font-weight: 700; letter-spacing: 0.6px; color: @n_dim; }\n"
    # karta: jemny okraj, dulezita s oranzovym nadechem
    + ".news .card { background-color: @n_group; border: 1px solid @n_line; border-radius: 14px; padding: 14px 16px 14px 14px; }\n"
    + ".news .card.important { background-image: linear-gradient(to bottom, @n_tint, @n_tint);"
    + " border-color: alpha(@n_important, 0.35); }\n"
    + ".news .tile { border-radius: 10px; color: white; min-width: 36px; min-height: 36px;"
    + " background-image: linear-gradient(to bottom, #6aa0ff, #3d6fe8); }\n"
    + ".news .tile image { -gtk-icon-shadow: 0 1px 1px alpha(black, 0.15); }\n"
    + ".news .tile.important { background-image: linear-gradient(to bottom, #ffb340, #ff8a00); }\n"
    + ".news .tile.read { background-image: linear-gradient(to bottom, #a4a9b4, #868b96); }\n"
    + ".news .dot { background-color: @n_accent; border-radius: 999px; min-width: 8px; min-height: 8px; }\n"
    + ".news .item-title { font-size: 15px; font-weight: 700; }\n"
    + ".news .card.read .item-title { font-weight: 600; }\n"
    + ".news .badge { font-size: 10px; font-weight: 800; letter-spacing: 0.3px; color: white; background-color: @n_important;"
    + " border-radius: 999px; padding: 1px 7px; }\n"
    + ".news button.link { background-image: none; border: none; box-shadow: none; border-radius: 999px;"
    + " background-color: alpha(@n_accent, 0.12); color: @n_link; padding: 3px 6px 3px 12px; min-height: 0; }\n"
    + ".news button.link:hover { background-color: alpha(@n_accent, 0.2); }\n"
    + ".news button.link label, .news button.link image { color: @n_link; font-weight: 600; }\n"
    + ".news button.plain { border-radius: 8px; padding: 4px 12px; background-image: none; border: none;"
    + " box-shadow: none; background-color: alpha(@n_fg, 0.08); color: @n_fg; }\n"
    + ".news button.plain:hover { background-color: alpha(@n_fg, 0.13); }\n"
    + ".news button.plain:disabled { opacity: 0.5; }\n"
    + ".news separator.foot { background-color: @n_line; min-height: 1px; }\n"
    + ".news .empty-icon { opacity: 0.55; }\n"
    + ".news scrolledwindow, .news viewport { background: transparent; border: none; }\n")

ui = {"window": 0, "list": 0, "status": 0, "provider": 0, "switch": 0, "lock": False, "read_before": [], "check": 0}

function label(text, classes, xalign):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, xalign)
    for c in classes:
        call gtk.widget_add_class(l, c)
    end
    return l
end

function clear(box):
    for child in gtk.container_get_children(box):
        call gtk.widget_destroy(child)
    end
    return 0
end

function test_log(line):
    path = env.get("LUXOS_NEWS_TEST_LOG", "")
    if path != None and path != "":
        safe:
            call appendfile(path, line + "\n")
        end
    end
    return 0
end

# Datum podle jazyka: cs/sk 18. 11. 2026, de/pl/hu/uk 18.11.2026, en Nov 18, 2026, jinak 2026-11-18
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function nice_date(day):
    y = day[0:4]
    m = Int(day[5:7])
    d = Int(day[8:10])
    lang = i18n.lang()
    if lang == "cs" or lang == "sk":
        return String(d) + ". " + String(m) + ". " + y
    end
    if lang == "de" or lang == "pl" or lang == "hu" or lang == "uk":
        return day[8:10] + "." + day[5:7] + "." + y
    end
    if lang == "en":
        return MONTHS[m - 1] + " " + String(d) + ", " + y
    end
    return day
end

# Dnes, Vcera, jinak datum
function when(day):
    diff = news.day_number(news.today()) - news.day_number(day)
    if diff == 0:
        return i18n.T("Today")
    end
    if diff == 1:
        return i18n.T("Yesterday")
    end
    return nice_date(day)
end

function icon(name, size):
    img = gtk.image_new_from_icon_name(name, 1)
    call gtk.image_set_pixel_size(img, size)
    return img
end

# Ikona aplikace; bez ni (chybi v motivu) modra dlazdice se zvonkem
function app_icon(size):
    if gtk.icon_theme_has_icon("luxos-news"):
        return icon("luxos-news", size)
    end
    tile = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(tile, "tile")
    call gtk.widget_set_size_request(tile, size, size)
    call gtk.widget_set_valign(tile, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(tile, icon("notifications-symbolic", Int(size / 2)), True, True, 0)
    return tile
end

function section(box, text):
    l = label(text.upper(), ["section"], 0.0)
    call gtk.widget_set_margins(l, 4, 0, 8, 0)
    call gtk.box_pack_start(box, l, False, False, 0)
    return 0
end

# Karta: barevna ikona (dulezite oranzova, nove modra, prectene seda), tecka neprecteneho, nazev, kdy, text, odkaz
function card_for(it, unread):
    important = it["level"] == "important"
    card = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(card, "card")
    tile = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(tile, "tile")
    name = "notifications-symbolic"
    if important:
        call gtk.widget_add_class(card, "important")
        call gtk.widget_add_class(tile, "important")
        name = "starred-symbolic"
    else:
        if not unread:
            call gtk.widget_add_class(tile, "read")
        end
    end
    if not unread:
        call gtk.widget_add_class(card, "read")
    end
    size = 18
    if not important:
        size = 22                          # zvonek ma v motivu vetsi okraje nez hvezda
    end
    glyph = icon(name, size)
    call gtk.widget_set_valign(glyph, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(tile, glyph, True, True, 0)
    call gtk.widget_set_valign(tile, gtk.ALIGN_START)
    call gtk.box_pack_start(card, tile, False, False, 0)
    col = gtk.box_new(gtk.VERTICAL, 4)
    top = gtk.box_new(gtk.HORIZONTAL, 8)
    title = label(news.localized(it["title"]), ["item-title"], 0.0)
    call gtk.label_set_line_wrap(title, True)
    call gtk.label_set_max_width_chars(title, 40)
    call gtk.box_pack_start(top, title, False, False, 0)
    if important:
        badge = label(i18n.T("Important").upper(), ["badge"], 0.5)
        call gtk.widget_set_valign(badge, gtk.ALIGN_CENTER)
        call gtk.box_pack_start(top, badge, False, False, 0)
    end
    side = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_set_valign(side, gtk.ALIGN_START)
    call gtk.box_pack_start(side, label(when(it["date"]), ["dim", "small"], 1.0), False, False, 0)
    if unread:
        dot = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_add_class(dot, "dot")
        call gtk.widget_set_valign(dot, gtk.ALIGN_CENTER)
        call gtk.box_pack_start(side, dot, False, False, 0)
    end
    call gtk.box_pack_end(top, side, False, False, 0)
    call gtk.box_pack_start(col, top, False, False, 0)
    body_text = news.localized(it["body"])
    if body_text != "":
        body = label(body_text, ["body"], 0.0)
        call gtk.label_set_line_wrap(body, True)
        call gtk.label_set_max_width_chars(body, 56)
        call gtk.label_set_selectable(body, True)
        call gtk.widget_set_can_focus(body, False)
        call gtk.box_pack_start(col, body, False, False, 0)
    end
    if it["url"] != "":
        more = gtk.button_new(i18n.T("More information"))
        call gtk.button_set_image(more, icon("go-next-symbolic", 12))
        call gtk.button_set_image_position(more, 1)
        call gtk.button_set_always_show_image(more, True)
        call gtk.widget_add_class(more, "link")
        call gtk.widget_set_halign(more, gtk.ALIGN_START)
        call gtk.widget_set_can_focus(more, False)
        call gtk.widget_set_tooltip(more, it["url"])
        call gtk.connect_data(more, "clicked", 0, on_link, it["url"])
        call gtk.widget_set_margins(more, 0, 0, 6, 0)
        call gtk.box_pack_start(col, more, False, False, 0)
    end
    call gtk.box_pack_start(card, col, True, True, 0)
    return card
end

function on_link(url, button):
    call glib.launch_uri(url)
    return 0
end

function render():
    box = ui["list"]
    call clear(box)
    items = news.active(news.cached_items(), news.today())
    if len(items) == 0:
        empty = gtk.box_new(gtk.VERTICAL, 10)
        call gtk.widget_set_margins(empty, 0, 0, 56, 40)
        big = app_icon(72)
        call gtk.widget_set_halign(big, gtk.ALIGN_CENTER)
        call gtk.widget_add_class(big, "empty-icon")
        call gtk.box_pack_start(empty, big, False, False, 0)
        call gtk.box_pack_start(empty, label(i18n.T("No news yet"), ["item-title"], 0.5), False, False, 0)
        call gtk.box_pack_start(box, empty, False, False, 0)
        call test_log("empty")
    end
    # neprectene podle stavu pri otevreni okna (zvyrazneni vydrzi i po kontrole na pozadi), nove nahore
    fresh = []
    older = []
    for it in items:
        if it["id"] not in ui["read_before"]:
            fresh.append(it)
        else:
            older.append(it)
        end
    end
    groups = [[i18n.T("Unread"), fresh, True], [i18n.T("Earlier"), older, False]]
    for g in groups:
        if len(g[1]) > 0:
            if len(fresh) > 0 and len(older) > 0:
                call section(box, g[0])
            end
            for it in g[1]:
                call gtk.box_pack_start(box, card_for(it, g[2]), False, False, 0)
                state = "read"
                if g[2]:
                    state = "unread"
                end
                call test_log("item " + it["id"] + " " + it["level"] + " " + state + " " + news.localized(it["title"]))
            end
        end
    end
    call gtk.widget_show_all(box)
    # otevrene okno = vse precteno (pristi otevreni uz bez zvyrazneni, kontrola je neohlasi)
    ids = []
    for it in items:
        ids.append(it["id"])
    end
    call news.mark_read(ids)
    return 0
end

# Tento program; po aktualizaci baliku za behu ukazuje /proc/self/exe na "... (deleted)" - pak novy z PATH
function self_exe():
    path = glib.readlink("/proc/self/exe")
    if path == None or path == "" or path.endswith(" (deleted)"):
        return "luxos-news"
    end
    return path
end

function on_fetched(unused, output, status):
    if ui["window"] == 0:
        return 0
    end
    if status != 0:
        call gtk.label_set_text(ui["status"], i18n.T("Could not check for news. Check your internet connection."))
    else:
        call gtk.label_set_text(ui["status"], "")
    end
    call gtk.widget_set_sensitive(ui["check"], True)
    call render()
    call test_log("fetched " + String(status))
    return 0
end

function on_check(button):
    call gtk.label_set_text(ui["status"], i18n.T("Checking…"))
    call gtk.widget_set_sensitive(ui["check"], False)
    call glib.spawn_capture([self_exe(), "--fetch"], on_fetched, 0)
    return 0
end

function on_switch(state, switch):
    if not ui["lock"]:
        call news.set_enabled(state != 0)
    end
    return False
end

function theme_is_dark():
    return gtk.settings_theme_name().lower().find("dark") >= 0 or gtk.settings_prefer_dark()
end

function apply_theme():
    css = LIGHT + CSS
    if theme_is_dark():
        css = DARK + CSS
    end
    if ui["provider"] == 0:
        ui["provider"] = gtk.css_load(css)
    else:
        call gtk.css_set(ui["provider"], css)
    end
    return 0
end

function on_theme(pspec, settings):
    return apply_theme()
end

function on_delete(event, window):
    call gtk.main_quit()
    return False
end

# Klavesy jako v ostatnich aplikacich: Esc, Ctrl+W a Ctrl+Q zavrou okno
function on_key(event, window):
    key = gtk.event_key_keyval(event)
    ctrl = (gtk.event_key_state(event) & gtk.CONTROL_MASK) != 0
    if key == KEY_ESCAPE or (ctrl and (key == KEY_W or key == KEY_Q or key == KEY_W - 32 or key == KEY_Q - 32)):
        call gtk.main_quit()
        return True
    end
    return False
end

# Velikost okna pro testy (vejde se na 1366x768)
function log_size():
    size = gtk.window_get_size(ui["window"])
    call test_log("size " + String(size[0]) + "x" + String(size[1]))
    return False
end

function window():
    call glib.set_prgname("luxos-news")
    call gtk.init()
    win = gtk.window_new(i18n.T("LuxOS News"))
    ui["window"] = win
    call gtk.widget_add_class(win, "news")
    call gtk.window_set_wmclass(win, "luxos-news", "luxos-news")
    call gtk.window_set_icon_list(win, "luxos-news")      # ostra ikona 16-256 px (Dock, Alt+Tab)
    # 580x600 + horni lista spravce oken se vejde i na 1366x768 s listou a Dockem
    call gtk.window_set_default_size(win, 580, 600)
    call gtk.widget_set_size_request(win, 420, 360)
    call gtk.window_set_position(win, gtk.WIN_POS_CENTER)
    call apply_theme()
    call gtk.connect(gtk.settings_get_default(), "notify::gtk-theme-name", on_theme)
    root = gtk.box_new(gtk.VERTICAL, 0)
    hero = gtk.box_new(gtk.HORIZONTAL, 14)
    call gtk.widget_set_margins(hero, 24, 24, 20, 18)
    call gtk.box_pack_start(hero, app_icon(56), False, False, 0)
    texts = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(texts, label(i18n.T("News from the LuxOS team"), ["news-head"], 0.0), False, False, 0)
    sub = label(i18n.T("New releases, planned maintenance and important changes."), ["dim"], 0.0)
    call gtk.label_set_line_wrap(sub, True)
    call gtk.box_pack_start(texts, sub, False, False, 0)
    call gtk.box_pack_start(hero, texts, True, True, 0)
    call gtk.box_pack_start(root, hero, False, False, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    ui["list"] = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_margins(ui["list"], 24, 24, 0, 16)
    call gtk.container_add(scroll, ui["list"])
    call gtk.box_pack_start(root, scroll, True, True, 0)
    line = gtk.separator_new(gtk.HORIZONTAL)
    call gtk.widget_add_class(line, "foot")
    call gtk.box_pack_start(root, line, False, False, 0)
    foot = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_set_margins(foot, 24, 24, 12, 14)
    sw = gtk.switch_new()
    ui["switch"] = sw
    ui["lock"] = True
    call gtk.switch_set_active(sw, news.load_state()["enabled"])
    ui["lock"] = False
    call gtk.widget_set_valign(sw, gtk.ALIGN_CENTER)
    call gtk.widget_set_can_focus(sw, False)
    call gtk.connect(sw, "state-set", on_switch)
    call gtk.box_pack_start(foot, sw, False, False, 0)
    call gtk.box_pack_start(foot, label(i18n.T("Notify me about news"), [], 0.0), False, False, 0)
    check = gtk.button_new(i18n.T("Check Now"))
    ui["check"] = check
    call gtk.button_set_image(check, icon("view-refresh-symbolic", 14))
    call gtk.button_set_always_show_image(check, True)
    call gtk.widget_add_class(check, "plain")
    call gtk.widget_set_can_focus(check, False)
    call gtk.connect(check, "clicked", on_check)
    call gtk.box_pack_end(foot, check, False, False, 0)
    ui["status"] = label("", ["dim", "small"], 1.0)
    call gtk.box_pack_end(foot, ui["status"], True, True, 6)
    call gtk.box_pack_start(root, foot, False, False, 0)
    call gtk.container_add(win, root)
    ui["read_before"] = news.load_state()["read"]
    call gtk.connect(win, "delete-event", on_delete)
    call gtk.connect(win, "key-press-event", on_key)
    call render()
    call gtk.widget_show_all(win)
    call test_log("shown")
    call log_size()
    # na pozadi zkontrolovat nove (okno je hned z mezipameti)
    call on_check(0)
    call gtk.main()
    return 0
end

# ---- nastroje pro vyvojare ------------------------------------------------------------------------

# Odsazeny JSON (kanal ctou a upravuji lide)
function pretty(value, indent):
    pad = " " * indent
    if type(value) == "Dictionary":
        if len(value) == 0:
            return "{}"
        end
        parts = []
        for key in value.keys():
            parts.append(pad + "  " + json.encode(key) + ": " + pretty(value[key], indent + 2))
        end
        return "{\n" + ",\n".join(parts) + "\n" + pad + "}"
    end
    if type(value) == "List":
        if len(value) == 0:
            return "[]"
        end
        parts = []
        for v in value:
            parts.append(pad + "  " + pretty(v, indent + 2))
        end
        return "[\n" + ",\n".join(parts) + "\n" + pad + "]"
    end
    return json.encode(value)
end

function read_feed(path):
    if not exists(path):
        return {"version": 1, "announcements": []}
    end
    data = None
    safe:
        data = json.decode(glib.read_text(path))
    end
    return data
end

function validate_cmd(path):
    if not exists(path):
        call eprint(path + ": file not found")
        return 1
    end
    if len(glib.read_text(path)) > news.MAX_FEED:
        call eprint(path + ": larger than " + String(news.MAX_FEED) + " bytes")
        return 1
    end
    data = read_feed(path)
    if data == None:
        call eprint(path + ": not valid JSON")
        return 1
    end
    checked = news.validate(data)
    for e in checked[1]:
        call eprint(path + ": " + e)
    end
    if len(checked[1]) > 0:
        return 1
    end
    live = news.active(checked[0], news.today())
    print String(len(checked[0])) + " announcements OK (" + String(len(live)) + " active today)"
    return 0
end

function slug(text):
    out = ""
    for ch in text.lower():
        if "abcdefghijklmnopqrstuvwxyz0123456789".find(ch) >= 0:
            out = out + ch
        elif not out.endswith("-") and out != "":
            out = out + "-"
        end
    end
    out = out.strip("-")
    return out[0:40].strip("-")
end

function new_cmd(path):
    opts = {}
    i = 3
    while i < arg_count():
        key = arg(i)
        if not key.startswith("--") or i + 1 >= arg_count():
            call eprint("luxos-news new: unexpected argument " + key)
            return 2
        end
        opts[key[2:]] = arg(i + 1)
        i += 2
    end
    if opts.get("title", "") == "":
        call eprint("luxos-news new: --title is required")
        return 2
    end
    day = opts.get("date", news.today())
    item = {"id": opts.get("id", day + "-" + slug(opts["title"])), "date": day}
    if opts.get("until", "") != "":
        item["until"] = opts["until"]
    end
    item["level"] = opts.get("level", "info")
    title = {"en": opts["title"]}
    body = {}
    if opts.get("body", "") != "":
        body["en"] = opts["body"]
    end
    for key in opts.keys():
        if key.startswith("title-"):
            title[key[6:]] = opts[key]
        elif key.startswith("body-"):
            body[key[5:]] = opts[key]
        end
    end
    item["title"] = title
    if len(body) > 0:
        item["body"] = body
    end
    if opts.get("url", "") != "":
        item["url"] = opts["url"]
    end
    data = read_feed(path)
    if type(data) != "Dictionary" or type(data.get("announcements")) != "List":
        call eprint(path + ": not a LuxOS news feed")
        return 1
    end
    data["announcements"].insert(0, item)
    checked = news.validate(data)
    if len(checked[1]) > 0:
        for e in checked[1]:
            call eprint(path + ": " + e)
        end
        return 1
    end
    call glib.write_atomic(path, pretty({"version": 1, "announcements": data["announcements"]}, 0) + "\n")
    print "added " + item["id"]
    return 0
end

function list_cmd():
    out = []
    for it in news.active(news.cached_items(), news.today()):
        out.append({"id": it["id"], "title": news.localized(it["title"]), "level": it["level"]})
    end
    print json.encode(out)
    return 0
end

# ---- klik na oznameni ------------------------------------------------------------------------------
# Kontrola po ohlaseni nekonci hned: klik na oznameni (akce "default", xfce4-notifyd ji vyvola i klikem
# na cele oznameni) otevre okno. Konci, az se vsechna jeji oznameni zavrou, nejpozdeji pred dalsi kontrolou.
# LUXOS_NEWS_WAIT = nejdelsi cekani v s (testy).
WAIT_MAX = 21000

waiting = {"ids": []}

function forget(id):
    kept = []
    for n in waiting["ids"]:
        if n != id:
            kept.append(n)
        end
    end
    waiting["ids"] = kept
    if len(kept) == 0:
        call glib.main_quit()
    end
    return 0
end

function on_action(sender, path, interface, signal, values):
    if len(values) < 2 or values[0] not in waiting["ids"]:
        return 0
    end
    if values[1] == "default":
        call test_log("open " + String(values[0]))
        call glib.spawn_quiet([self_exe()])
    end
    return 0
end

function on_closed(sender, path, interface, signal, values):
    if len(values) >= 1 and values[0] in waiting["ids"]:
        call forget(values[0])
    end
    return 0
end

function on_wait_over():
    call glib.main_quit()
    return False
end

function check_cmd():
    sent = news.check()
    if len(sent) == 0:
        return 0
    end
    bus = 0
    safe:
        bus = gio.session_bus()
    end
    if bus == 0:
        return 0
    end
    waiting["ids"] = sent
    call gio.subscribe_values(bus, "org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked", "/org/freedesktop/Notifications", on_action)
    call gio.subscribe_values(bus, "org.freedesktop.Notifications", "org.freedesktop.Notifications", "NotificationClosed", "/org/freedesktop/Notifications", on_closed)
    call glib.timeout_add_seconds(txt.to_int(env.get("LUXOS_NEWS_WAIT", ""), WAIT_MAX), on_wait_over)
    call glib.main()
    return 0
end

function main():
    if arg_count() < 2:
        return window()
    end
    first = arg(1)
    if first == "--check":
        return check_cmd()
    end
    if first == "--fetch":
        result = news.fetch()
        if not result["ok"]:
            call eprint("luxos-news: " + result["error"])
            return 1
        end
        print String(len(news.active(result["items"], news.today())))
        return 0
    end
    if first == "--list":
        return list_cmd()
    end
    if first == "validate" and arg_count() >= 3:
        return validate_cmd(arg(2))
    end
    if first == "new" and arg_count() >= 3:
        return new_cmd(arg(2))
    end
    call eprint("Usage: luxos-news [--check|--fetch|--list] | validate FILE | new FILE --title TEXT [options]")
    return 2
end

call exit(main())
