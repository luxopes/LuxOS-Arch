# LuxOS Snimek obrazovky - plovouci lista jako v macOS (Shift+Super+5, Print); prepis luxos-screenshot
# z Pythonu do LSL. Okna bezi primo v luxos-hub (pripravena predem, lista je videt hned po zkratce),
# bez hubu v samostatnem procesu luxos-screenshot-ui. Maly klient luxos-screenshot jen preda prepinace
# pres abstraktni socket UNIX (viz luxos_shot_base: protokol, cista logika).
#
#   call shot.prebuild()             skryta okna (hub po startu relace)
#   shot.start_server(samostatne)    naslouchani na socketu; False kdyz uz posloucha nekdo jiny
#   call shot.handle_request(argv, None)   pozadavek primo (samostatny proces; vystup na stdout)
#   shot.exit_code()                 kod ukonceni samostatneho procesu
#
# Staticke snimky bere GDK primo z korenoveho okna X; vyrez a okno se bez listy (zkratka) vybiraji nad
# zmrazenym snimkem obrazovky, s listou nad zivou obrazovkou (pruhledny prekryv, mys mimo vyber jde do
# aplikaci). Popisek nad listou ukazuje rezim pod mysi / vybrany rezim a zkratku. Drzeny Ctrl pri zachyceni
# = do schranky misto souboru (obrazek drzi xclip i po skonceni). Nahled po snimku ma akce Kopirovat,
# Zobrazit v Souborech, Ulozit jako, Smazat (do Kose), Zavrit; i pres prave tlacitko.
#
# Okna jsou mimo spravce oken (override-redirect): kdyz xfwm4 zvedne jine okno (aktivace aplikace, navrat
# fokusu po dialogu), filtr korenoveho okna je hned vrati nahoru ve spravnem poradi
# (prekryv < lista < popisek/odpocet/nahled, nase nabidka vzdy navrchu; behem dialogu nic).
# Esc (a Enter u listy) jsou globalni klavesy (XGrabKey jen na tyto klavesy, ostatni jdou dal do aplikaci),
# jen dokud je nastroj videt; pri nahravani se Esc nezabira (nahravana aplikace ho dostane), zastavi se
# tlacitkem Zastavit nebo dalsim spustenim.
load env
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load cairo
load luxos_x11 as x11
load luxos_sys
load luxos_i18n as i18n
load luxos_text as text
load luxos_shot_base as base

HANDLE = 9
SIGINT = 2
SIGKILL = 9
KEY_ESCAPE = 65307
KEY_RETURN = 65293
KEY_KP_ENTER = 65421
KEY_CONTROL_L = 65507
KEY_CONTROL_R = 65508
KEY_SPACE = 32
ACCENT = [0.24, 0.48, 1.0]

CSS = ("window.lx-shot { background: transparent; }\n"
    + "window.lx-shot .bar { background-color: @sb_bg; border-radius: 18px; border: 1px solid @sb_border; padding: 8px 10px; color: @sb_fg; }\n"
    + "window.lx-shot .bar button, window.lx-shot .pill button, window.lx-shot .thumb button { background: none; background-image: none; border: none; box-shadow: none; outline: none; text-shadow: none; -gtk-icon-shadow: none; color: @sb_fg; border-radius: 8px; padding: 7px 11px; min-height: 0; min-width: 0; }\n"
    + "window.lx-shot .bar button:hover, window.lx-shot .pill button:hover, window.lx-shot .thumb button:hover { background-color: @sb_hover; }\n"
    + "window.lx-shot .bar button.active { background-color: @sb_active; border-radius: 10px; }\n"
    + "window.lx-shot .bar button.active:hover { background-color: @sb_active; }\n"
    + "window.lx-shot .bar button.close { padding: 6px 7px; }\n"
    + "window.lx-shot .bar button.capture { font-weight: 600; font-size: 15px; padding: 9px 20px; border-radius: 12px; background-color: #3d7bff; color: white; margin-left: 4px; }\n"
    + "window.lx-shot .bar button.capture:hover { background-color: #5a8fff; }\n"
    + "window.lx-shot .bar button.capture label { color: white; font-size: 15px; }\n"
    + "window.lx-shot .bar button:disabled { opacity: 0.4; }\n"
    + "window.lx-shot .bar label { color: @sb_fg; font-size: 15px; }\n"
    + "window.lx-shot .sep { background-color: @sb_sep; min-width: 1px; margin: 8px 8px; }\n"
    + "window.lx-shot .pill { background-color: @sb_bg; border-radius: 999px; border: 1px solid @sb_border; padding: 3px 4px 3px 12px; color: @sb_fg; }\n"
    + "window.lx-shot .pill label { font-feature-settings: \"tnum\"; font-weight: 600; font-size: 13px; color: @sb_fg; }\n"
    + "window.lx-shot .pill button { border-radius: 999px; padding: 4px 10px; }\n"
    + "window.lx-shot .count { background-color: @sb_bg; border-radius: 22px; border: 1px solid @sb_border; padding: 6px 26px; }\n"
    + "window.lx-shot .count label { font-size: 46px; font-weight: 700; color: @sb_fg; font-feature-settings: \"tnum\"; }\n"
    + "window.lx-shot .caption { background-color: @sb_bg; border-radius: 9px; border: 1px solid @sb_border; padding: 4px 10px; }\n"
    + "window.lx-shot .caption label { color: @sb_fg; font-size: 13px; }\n"
    + "window.lx-shot .caption label.name { font-weight: 600; }\n"
    + "window.lx-shot .caption label.key { border: 1px solid @sb_sep; border-radius: 5px; padding: 0 5px; font-size: 12px; }\n"
    + "window.lx-shot .caption label.hint, window.lx-shot .thumb label.status { opacity: 0.72; font-size: 12px; }\n"
    + "window.lx-shot .thumb { background-color: @sb_bg; border-radius: 12px; border: 1px solid @sb_border; padding: 6px; color: @sb_fg; }\n"
    + "window.lx-shot .thumb button { padding: 4px 10px 4px 7px; border-radius: 7px; }\n"
    + "window.lx-shot .thumb button label, window.lx-shot .thumb label { color: @sb_fg; font-size: 13px; }\n"
    + "window.lx-shot .thumb image { color: @sb_fg; }\n")

# Stejne barvy jako Ovladaci centrum; bez kompozitoru neprusvitne pozadi
function colors(dark, opaque):
    if dark:
        bg = "rgba(32, 33, 52, 0.86)"
        if opaque:
            bg = "rgb(32, 33, 52)"
        end
        return ("@define-color sb_bg " + bg + "; @define-color sb_border rgba(255, 255, 255, 0.14);\n"
            + "@define-color sb_fg #f4f4fa; @define-color sb_hover rgba(255, 255, 255, 0.10);\n"
            + "@define-color sb_active rgba(255, 255, 255, 0.20); @define-color sb_sep rgba(255, 255, 255, 0.16);\n")
    end
    bg = "rgba(246, 247, 252, 0.88)"
    if opaque:
        bg = "rgb(246, 247, 252)"
    end
    return ("@define-color sb_bg " + bg + "; @define-color sb_border rgba(0, 0, 0, 0.10);\n"
        + "@define-color sb_fg #1d1d2b; @define-color sb_hover rgba(0, 0, 0, 0.06);\n"
        + "@define-color sb_active rgba(0, 0, 0, 0.13); @define-color sb_sep rgba(0, 0, 0, 0.13);\n")
end

S = {"built": False, "composited": False, "provider": 0, "token": 1, "active": False, "state": "", "sink": None,
     "opts": {}, "args": {}, "mode": "portion", "busy": False, "to_clip": False, "toolbar_session": False,
     "frozen_pb": 0, "frozen_cursor": [], "surface": 0, "scale": 1, "rec": None, "dialog": 0, "menu": 0,
     "keys": {}, "shortcuts": {}, "holding_clip": False, "clip_owner": 0, "clip_watch": False,
     "standalone": False, "listening": False, "exit_code": 0, "restack_pending": False, "watching": False,
     "encoder": None, "grab_tries": 0, "seq": 0, "after_dialog": ""}
W = {}
OV = {"sel": None, "drag": None, "hover": None, "windows": None, "mode": "portion", "quick": False, "live": False, "sw": 0, "sh": 0, "open": False}
TB = {"mode": "portion", "hovered": "", "ctrl": False, "anchor": None, "caption": []}
TH = {"path": "", "full": 0, "small": 0, "copied": False, "video": False, "dragging": False, "menu": False, "timer": 0, "open": False}

function T(value):
    return i18n.T(value)
end

function log(message):
    call eprint("luxos-screenshot: " + message)
    return 0
end

function notify(message):
    call log(message)
    call glib.spawn_quiet(["notify-send", "-a", T("Screenshot"), "-i", "dialog-warning", T("Screenshot"), message])
    return 0
end

function is_live_token(token):
    return S["active"] and token == S["token"]
end

# ---- slozky ----------------------------------------------------------------------------------------------------

# Plocha / Obrazky / Videa podle xdg-user-dirs, jinak ~/Desktop, ~/Pictures, ~/Videos
function user_dir(kind):
    codes = {"desktop": 0, "pictures": 4, "videos": 7}
    names = {"desktop": "Desktop", "pictures": "Pictures", "videos": "Videos"}
    d = glib.user_special_dir(codes[kind])
    home = glib.home_dir()
    if d == "" or glib.realpath(d) == glib.realpath(home):
        d = home + "/" + names[kind]
    end
    return d
end

# Obrazky/Snimky obrazovky - nazev podslozky podle jazyka (cs: Snimky obrazovky)
function screenshots_dir():
    name = T("Screenshots").replace("/", "-").strip()
    if name == "":
        name = "Screenshots"
    end
    return user_dir("pictures") + "/" + name
end

# Kam ulozit soubor; None = schranka (jen u snimku, video do schranky nejde)
function save_dir(opts, video, override):
    if override != None and override != "":
        return override
    end
    to = opts["save_to"]
    if to == "clipboard":
        if video:
            return screenshots_dir()
        end
        return None
    end
    if to == "other" and opts["other_dir"] != "" and glib.is_dir(opts["other_dir"]):
        return opts["other_dir"]
    end
    if to == "desktop" or to == "pictures":
        return user_dir(to)
    end
    return screenshots_dir()
end

function now_fields():
    t = glib.localtime(glib.now())
    return [t[0], t[1], t[2], t[3], t[4], t[5]]
end

function save_options():
    return base.save_options(S["opts"], base.options_path())
end

# ---- vzhled --------------------------------------------------------------------------------------------------

function is_dark():
    return gtk.settings_theme_name().lower().find("dark") >= 0 or gtk.settings_prefer_dark()
end

function css_text():
    return colors(is_dark(), not S["composited"]) + CSS
end

function on_theme_changed(bound, pspec, settings):
    if S["provider"] != 0:
        call gtk.css_set(S["provider"], css_text())
    end
    return 0
end

# Okno bez dekorace mimo spravce oken: vzdy navrchu, bez animaci; bez kompozitoru zaoblene oriznutim
function popup_new(radius):
    win = gtk.window_new_popup()
    call gtk.widget_add_class(win, "lx-shot")
    call gtk.widget_set_app_paintable(win, True)
    if S["composited"]:
        call gtk.widget_set_rgba_visual(win)
    elif radius > 0:
        call gtk.connect_data(win, "size-allocate", 1, on_shape_alloc, radius)
    end
    return win
end

function on_shape_alloc(radius, allocation, win):
    call gtk.widget_shape_rounded(win, gtk.widget_get_allocated_width(win), gtk.widget_get_allocated_height(win), radius)
    return 0
end

function preferred_size(widget):
    return [gtk.widget_get_preferred_width(widget)[1], gtk.widget_get_preferred_height(widget)[1]]
end

# ---- ikony listy (vlastni kresba) --------------------------------------------------------------------------------

function dashed(cr, x, y, w, h):
    call cairo.set_dash(cr, [2.2, 1.8], 0.0)
    call cairo.rounded_rectangle(cr, x, y, w, h, 2.0)
    call cairo.stroke(cr)
    call cairo.set_dash(cr, [], 0.0)
    return 0
end

function rec_dot(cr, w, h, c):
    call cairo.set_operator(cr, cairo.OPERATOR_CLEAR)
    call cairo.arc(cr, w - 5.0, h - 4.5, 5.0, 0.0, 6.2832)
    call cairo.fill(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_OVER)
    call cairo.set_source_rgba(cr, c[0], c[1], c[2], 1.0)
    call cairo.arc(cr, w - 5.0, h - 4.5, 3.2, 0.0, 6.2832)
    call cairo.fill(cr)
    return 0
end

function paint_icon(key, cr, w, h, c):
    if key == "close":
        call cairo.set_source_rgba(cr, c[0], c[1], c[2], 0.22)
        call cairo.arc(cr, w / 2.0, h / 2.0, 8.0, 0.0, 6.2832)
        call cairo.fill(cr)
        call cairo.set_source_rgba(cr, c[0], c[1], c[2], 0.85)
        call cairo.set_line_width(cr, 1.5)
        call cairo.move_to(cr, w / 2.0 - 3.0, h / 2.0 - 3.0)
        call cairo.line_to(cr, w / 2.0 + 3.0, h / 2.0 + 3.0)
        call cairo.move_to(cr, w / 2.0 - 3.0, h / 2.0 + 3.0)
        call cairo.line_to(cr, w / 2.0 + 3.0, h / 2.0 - 3.0)
        call cairo.stroke(cr)
    elif key == "screen":
        call cairo.rounded_rectangle(cr, 2.5, 3.5, w - 5.0, h - 7.0, 2.5)
        call cairo.set_source_rgba(cr, c[0], c[1], c[2], 0.25)
        call cairo.fill_preserve(cr)
        call cairo.set_source_rgba(cr, c[0], c[1], c[2], 1.0)
        call cairo.stroke(cr)
    elif key == "window":
        call dashed(cr, 1.5, 1.5, w - 3.0, h - 3.0)
        call cairo.rounded_rectangle(cr, 5.5, 5.5, w - 11.0, h - 11.0, 1.5)
        call cairo.stroke(cr)
        call cairo.rectangle(cr, 5.5, 5.5, w - 11.0, 2.5)
        call cairo.fill(cr)
    elif key == "portion":
        call dashed(cr, 2.5, 3.5, w - 5.0, h - 7.0)
    elif key == "rec_screen" or key == "rec_portion":
        call gtk.cairo_push_group(cr)
        call cairo.set_source_rgba(cr, c[0], c[1], c[2], 1.0)
        call cairo.set_line_width(cr, 1.4)
        if key == "rec_screen":
            call cairo.rounded_rectangle(cr, 2.5, 3.5, w - 7.0, h - 8.0, 2.5)
            call cairo.stroke(cr)
        else:
            call dashed(cr, 2.5, 3.5, w - 7.0, h - 8.0)
        end
        call rec_dot(cr, w, h, c)
        call gtk.cairo_pop_group_to_source(cr)
        call cairo.paint(cr)
    elif key == "stop":
        call cairo.set_source_rgb(cr, 1.0, 0.23, 0.19)
        call cairo.rounded_rectangle(cr, w / 2.0 - 5.0, h / 2.0 - 5.0, 10.0, 10.0, 2.5)
        call cairo.fill(cr)
    elif key == "dot":
        call cairo.set_source_rgb(cr, 1.0, 0.23, 0.19)
        call cairo.arc(cr, w / 2.0, h / 2.0, 4.5, 0.0, 6.2832)
        call cairo.fill(cr)
    end
    return 0
end

function on_icon_draw(key, cr, area):
    c = gtk.widget_get_color(area, gtk.widget_get_state_flags(area))
    call cairo.set_source_rgba(cr, c[0], c[1], c[2], c[3])
    call cairo.set_line_width(cr, 1.7)
    call paint_icon(key, cr, Float(gtk.widget_get_allocated_width(area)), Float(gtk.widget_get_allocated_height(area)), c)
    return False
end

function icon_new(key, w, h):
    area = gtk.drawing_area_new()
    call gtk.widget_set_size_request(area, w, h)
    call gtk.connect_data(area, "draw", 1, on_icon_draw, key)
    return area
end

# ---- stavba oken (jednou za proces) ------------------------------------------------------------------------------

function mode_name(mode):
    names = {"screen": "Capture Entire Screen", "window": "Capture Selected Window", "portion": "Capture Selected Portion",
             "rec_screen": "Record Entire Screen", "rec_portion": "Record Selected Portion"}
    return T(names[mode])
end

function prebuild():
    if S["built"]:
        return 0
    end
    S["built"] = True
    S["composited"] = gtk.rgba_available()
    if S["provider"] == 0:
        S["provider"] = gtk.css_load(css_text())
        settings = gtk.settings_get_default()
        call gtk.connect_data(settings, "notify::gtk-theme-name", 1, on_theme_changed, 0)
        call gtk.connect_data(settings, "notify::gtk-application-prefer-dark-theme", 1, on_theme_changed, 0)
    else:
        call gtk.css_set(S["provider"], css_text())
    end
    call build_caption()
    call build_toolbar()
    call build_overlay()
    call build_thumb()
    call build_pill()
    call build_countdown()
    call build_options_menu()
    call x11.root_filter(on_root_event, 0)
    # okna X vytvorit hned (prvni zobrazeni pak nic nerealizuje)
    for key in ["caption", "toolbar", "overlay", "thumb", "pill", "countdown"]:
        call gtk.widget_realize(W[key])
    end
    call shortcuts_refresh()
    call mode_shortcut("screen")
    call mode_shortcut("portion")
    return 0
end

# Kompozitor se zapnul/vypnul od pripravy oken: okna s jinym visualem postavit znovu
function ensure_built():
    if S["built"] and S["composited"] != gtk.rgba_available():
        for key in ["toolbar", "caption", "overlay", "thumb", "pill", "countdown", "options_menu", "thumb_menu"]:
            if key in W:
                call gtk.widget_destroy(W[key])
            end
        end
        call W.clear()
        S["built"] = False
    end
    call prebuild()
    return 0
end

function build_caption():
    win = popup_new(9)
    box = gtk.box_new(gtk.HORIZONTAL, 7)
    call gtk.widget_add_class(box, "caption")
    for key in ["name", "key", "hint"]:
        lab = gtk.label_new("")
        call gtk.widget_add_class(lab, key)
        call gtk.box_pack_start(box, lab, False, False, 0)
        W["cap_" + key] = lab
    end
    call gtk.container_add(win, box)
    call gtk.widget_show_all(box)
    W["caption"] = win
    return 0
end

function build_toolbar():
    win = popup_new(18)
    bar = gtk.box_new(gtk.HORIZONTAL, 4)
    call gtk.widget_add_class(bar, "bar")
    call gtk.container_add(win, bar)
    W["bar"] = bar
    close = tool_new(bar, "close", 22, 22)
    call gtk.widget_add_class(close, "close")
    call sep_new(bar)
    W["modes"] = {}
    for mode in ["screen", "window", "portion", "", "rec_screen", "rec_portion"]:
        if mode == "":
            call sep_new(bar)
            continue
        end
        W["modes"][mode] = tool_new(bar, mode, 40, 26)
    end
    call sep_new(bar)
    opt = gtk.button_new_empty()
    call gtk.widget_set_can_focus(opt, False)
    ob = gtk.box_new(gtk.HORIZONTAL, 3)
    call gtk.box_pack_start(ob, gtk.label_new(T("Options")), False, False, 0)
    call gtk.box_pack_start(ob, gtk.image_new_from_icon_name("pan-down-symbolic", gtk.ICON_MENU), False, False, 0)
    call gtk.container_add(opt, ob)
    call gtk.connect_data(opt, "clicked", 0, on_tool_clicked, "options")
    call gtk.box_pack_start(bar, opt, False, False, 0)
    call hoverable(opt, "options")
    W["options"] = opt
    cap_button = gtk.button_new(T("Capture"))
    call gtk.widget_set_can_focus(cap_button, False)
    call gtk.widget_add_class(cap_button, "capture")
    call gtk.connect_data(cap_button, "clicked", 0, on_tool_clicked, "capture")
    call gtk.box_pack_start(bar, cap_button, False, False, 0)
    call hoverable(cap_button, "capture")
    W["capture"] = cap_button
    call gtk.widget_add_events(win, gtk.KEY_PRESS_MASK + gtk.KEY_RELEASE_MASK)
    call gtk.connect_data(win, "key-press-event", 1, on_window_key, 0)
    call gtk.connect_data(win, "key-release-event", 1, on_key_release, 0)
    call gtk.widget_show_all(bar)
    W["toolbar"] = win
    return 0
end

function tool_new(bar, key, w, h):
    button = gtk.button_new_empty()
    call gtk.widget_set_can_focus(button, False)
    call gtk.container_add(button, icon_new(key, w, h))
    call gtk.connect_data(button, "clicked", 0, on_tool_clicked, key)
    call gtk.box_pack_start(bar, button, False, False, 0)
    call hoverable(button, key)
    return button
end

function sep_new(bar):
    s = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(s, "sep")
    call gtk.box_pack_start(bar, s, False, False, 0)
    return s
end

# Pristupnost: tlacitka s ikonou maji jmeno i bez tooltipu; popisek nad listou hned pri najeti
function hoverable(button, key):
    names = {"close": "Close", "options": "Options", "capture": "Capture"}
    if key in names:
        call gtk.accessible_name(button, T(names[key]))
    else:
        call gtk.accessible_name(button, mode_name(key))
    end
    call gtk.connect_data(button, "enter-notify-event", 1, on_hover_enter, key)
    call gtk.connect_data(button, "leave-notify-event", 1, on_hover_leave, key)
    return 0
end

function on_hover_enter(key, event, button):
    TB["hovered"] = key
    call update_caption()
    return False
end

function on_hover_leave(key, event, button):
    TB["hovered"] = ""
    call update_caption()
    return False
end

function on_tool_clicked(key, button):
    if not S["active"]:
        return 0
    end
    if key == "close":
        call cancel()
    elif key == "options":
        call options_popup()
    elif key == "capture":
        call capture_now(None)
    else:
        call set_mode(key, False)
    end
    return 0
end

function build_overlay():
    win = popup_new(0)
    call gtk.widget_add_events(win, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK + gtk.KEY_PRESS_MASK + gtk.KEY_RELEASE_MASK)
    call gtk.connect_data(win, "draw", 1, on_ov_draw, 0)
    call gtk.connect_data(win, "button-press-event", 1, on_ov_press, 0)
    call gtk.connect_data(win, "button-release-event", 1, on_ov_release, 0)
    call gtk.connect_data(win, "motion-notify-event", 1, on_ov_motion, 0)
    call gtk.connect_data(win, "key-press-event", 1, on_ov_key, 0)
    call gtk.connect_data(win, "key-release-event", 1, on_key_release, 0)
    W["overlay"] = win
    return 0
end

function build_thumb():
    win = popup_new(12)
    card = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(card, "thumb")
    img = gtk.drawing_area_new()
    call gtk.widget_set_valign(img, gtk.ALIGN_CENTER)
    call gtk.widget_add_events(img, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK)
    call gtk.connect_data(img, "draw", 1, on_thumb_draw, 0)
    call gtk.connect_data(img, "button-release-event", 1, on_thumb_click, 0)
    call gtk.connect_data(img, "drag-data-get", 4, on_drag_get, 0)
    call gtk.connect_data(img, "drag-begin", 1, on_drag_begin, 0)
    call gtk.connect_data(img, "drag-end", 1, on_drag_end, 0)
    call gtk.box_pack_start(card, img, False, False, 0)
    W["thumb_image"] = img
    col = gtk.box_new(gtk.VERTICAL, 1)
    call gtk.widget_set_valign(col, gtk.ALIGN_CENTER)
    st = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_set_margins(st, 7, 0, 0, 3)
    call gtk.box_pack_start(st, gtk.image_new_from_icon_name("object-select-symbolic", gtk.ICON_MENU), False, False, 0)
    lab = gtk.label_new(T("Copied to Clipboard"))
    call gtk.label_set_xalign(lab, 0)
    call gtk.widget_add_class(lab, "status")
    call gtk.box_pack_start(st, lab, False, False, 0)
    call gtk.box_pack_start(col, st, False, False, 0)
    W["thumb_status"] = st
    W["thumb_buttons"] = {}
    for item in [["copy", "edit-copy-symbolic", "Copy"], ["reveal", "folder-open-symbolic", "Show in Files"], ["save_as", "document-save-as-symbolic", "Save As…"], ["delete", "user-trash-symbolic", "Delete"], ["close", "window-close-symbolic", "Close"]]:
        b = gtk.button_new_empty()
        call gtk.widget_set_can_focus(b, False)
        bx = gtk.box_new(gtk.HORIZONTAL, 7)
        image = gtk.image_new_from_icon_name(item[1], gtk.ICON_MENU)
        blab = gtk.label_new(T(item[2]))
        call gtk.label_set_xalign(blab, 0)
        call gtk.box_pack_start(bx, image, False, False, 0)
        call gtk.box_pack_start(bx, blab, True, True, 0)
        call gtk.container_add(b, bx)
        call gtk.connect_data(b, "clicked", 0, on_thumb_button, item[0])
        call gtk.box_pack_start(col, b, False, False, 0)
        W["thumb_buttons"][item[0]] = [b, image, blab]
    end
    call gtk.box_pack_start(card, col, False, False, 0)
    call gtk.container_add(win, card)
    call gtk.widget_show_all(card)
    call gtk.widget_add_events(win, gtk.BUTTON_PRESS_MASK + gtk.ENTER_NOTIFY_MASK + gtk.LEAVE_NOTIFY_MASK)
    call gtk.connect_data(win, "button-press-event", 1, on_thumb_press, 0)
    call gtk.connect_data(win, "enter-notify-event", 1, on_thumb_enter, 0)
    call gtk.connect_data(win, "leave-notify-event", 1, on_thumb_leave, 0)
    W["thumb"] = win
    # Nabidka praveho tlacitka
    menu = gtk.menu_new()
    W["thumb_items"] = {}
    for item in [["open", "Open"], ["copy", "Copy"], ["reveal", "Show in Files"], ["save_as", "Save As…"], ["delete", "Delete"], ["sep", ""], ["close", "Close"]]:
        if item[0] == "sep":
            mi = gtk.separator_menu_item_new()
        else:
            mi = gtk.menu_item_new(T(item[1]))
            call gtk.connect_data(mi, "activate", 0, on_thumb_menu_item, item[0])
        end
        call gtk.menu_append(menu, mi)
        call gtk.widget_show(mi)
        W["thumb_items"][item[0]] = mi
    end
    call gtk.menu_attach(menu, win)
    call gtk.connect_data(menu, "hide", 0, on_thumb_menu_hidden, 0)
    W["thumb_menu"] = menu
    return 0
end

function build_pill():
    win = popup_new(16)
    box = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(box, "pill")
    call gtk.box_pack_start(box, icon_new("dot", 10, 18), False, False, 0)
    lab = gtk.label_new("0:00")
    call gtk.box_pack_start(box, lab, False, False, 0)
    W["pill_label"] = lab
    stop = gtk.button_new_empty()
    call gtk.widget_set_can_focus(stop, False)
    call gtk.widget_set_tooltip(stop, T("Stop Recording"))
    sb = gtk.box_new(gtk.HORIZONTAL, 5)
    call gtk.box_pack_start(sb, icon_new("stop", 14, 18), False, False, 0)
    call gtk.box_pack_start(sb, gtk.label_new(T("Stop")), False, False, 0)
    call gtk.container_add(stop, sb)
    call gtk.connect_data(stop, "clicked", 0, on_pill_stop, 0)
    call gtk.box_pack_start(box, stop, False, False, 0)
    call gtk.container_add(win, box)
    call gtk.widget_show_all(box)
    W["pill"] = win
    return 0
end

function build_countdown():
    win = popup_new(22)
    box = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(box, "count")
    lab = gtk.label_new("")
    call gtk.box_pack_start(box, lab, True, True, 0)
    call gtk.container_add(win, box)
    call gtk.widget_show_all(box)
    W["countdown"] = win
    W["count_label"] = lab
    return 0
end

function build_options_menu():
    menu = gtk.menu_new()
    W["opt_radio"] = []
    call menu_header(menu, T("Save to"))
    group = 0
    for pair in [["screenshots", "Screenshots"], ["desktop", "Desktop"], ["pictures", "Pictures"], ["clipboard", "Clipboard"]]:
        group = menu_radio(menu, group, T(pair[1]), "save_to", pair[0])
    end
    # Napoveda pod Schrankou: kopie jednoho snimku bez zmeny volby
    hint = gtk.menu_item_markup("<small>" + glib.markup_escape(T("Hold Ctrl to copy to the clipboard")) + "</small>")
    call gtk.widget_set_sensitive(hint, False)
    call gtk.menu_append(menu, hint)
    W["opt_other_radio"] = menu_radio(menu, group, "", "save_to", "other")
    other = gtk.menu_item_new(T("Other…"))
    call gtk.connect_data(other, "activate", 0, on_other_folder, 0)
    call gtk.menu_append(menu, other)
    call gtk.menu_append(menu, gtk.separator_menu_item_new())
    call menu_header(menu, T("Timer"))
    group = 0
    for pair in [[0, "None"], [5, "5 Seconds"], [10, "10 Seconds"]]:
        group = menu_radio(menu, group, T(pair[1]), "timer", pair[0])
    end
    call gtk.menu_append(menu, gtk.separator_menu_item_new())
    call menu_header(menu, T("Options"))
    W["opt_checks"] = []
    for pair in [["pointer", "Show Mouse Pointer"], ["remember", "Remember Last Selection"]]:
        item = gtk.check_menu_item_new(T(pair[1]))
        call gtk.connect_data(item, "toggled", 0, on_opt_check, pair[0])
        call gtk.menu_append(menu, item)
        W["opt_checks"].append([item, pair[0]])
    end
    call gtk.widget_show_all(menu)
    call gtk.menu_attach(menu, W["options"])
    call gtk.connect_data(menu, "hide", 0, on_options_hidden, 0)
    W["options_menu"] = menu
    return 0
end

function menu_header(menu, label):
    item = gtk.menu_item_new(label)
    call gtk.widget_set_sensitive(item, False)
    call gtk.menu_append(menu, item)
    return item
end

function menu_radio(menu, group, label, key, value):
    item = gtk.radio_menu_item_new(group, label)
    call gtk.connect_data(item, "toggled", 0, on_opt_radio, [key, value])
    call gtk.menu_append(menu, item)
    W["opt_radio"].append([item, key, value])
    return item
end

# ---- popisek nad listou ---------------------------------------------------------------------------------------

MODE_COMMANDS = {"screen": "luxos-screenshot --screen", "portion": "luxos-screenshot --portion"}

# Zkratky Xfce znovu jen po zmene souboru (cteni XML ~6 ms by zdrzelo listu)
function shortcuts_refresh():
    key = ""
    for path in base.shortcut_files():
        st = glib.stat(path)
        if len(st) > 0:
            key = key + path + ":" + String(st[1]) + ";"
        end
    end
    if key != S.get("shortcuts_key", "-"):
        S["shortcuts"] = {}
        S["shortcuts_key"] = key
    end
    return 0
end

function mode_shortcut(mode):
    if mode not in MODE_COMMANDS:
        return None
    end
    cmd = MODE_COMMANDS[mode]
    cache = S["shortcuts"]
    if cmd not in cache:
        found = base.global_shortcut(cmd, None)
        if found == None:
            cache[cmd] = ""
        else:
            cache[cmd] = found
        end
    end
    if cache[cmd] == "":
        return None
    end
    return cache[cmd]
end

# [nazev, klavesa, napoveda] pro popisek ("" = nic)
function describe(key):
    mode = TB["mode"]
    if key == "close":
        return [T("Close"), "Esc", ""]
    end
    if key == "options":
        names = {"screenshots": "Screenshots", "desktop": "Desktop", "pictures": "Pictures", "clipboard": "Clipboard"}
        to = S["opts"]["save_to"]
        dest = ""
        if to in names:
            dest = T(names[to])
        else:
            dest = base.basename(text.rstrip_chars(S["opts"]["other_dir"], "/"))
        end
        return [i18n.TF("Save to: %s", [dest]), "", ""]
    end
    if key == "capture":
        hint = ""
        if not mode.startswith("rec_") and mode != "window":
            hint = T("Hold Ctrl to copy to the clipboard")
        end
        return [mode_name(mode), "Enter", hint]
    end
    if key in base.MODES:
        hint = ""
        if key == "window":
            hint = T("Click a window to capture it")
        end
        shortcut = mode_shortcut(key)
        if shortcut == None:
            shortcut = ""
        end
        return [mode_name(key), shortcut, hint]
    end
    return ["", "", ""]
end

function update_caption():
    if not S["built"]:
        return 0
    end
    key = TB["hovered"]
    if key == "":
        key = TB["mode"]
    end
    values = describe(key)
    if values == TB["caption"]:
        return 0
    end
    TB["caption"] = values
    call gtk.label_set_text(W["cap_name"], values[0])
    call gtk.label_set_text(W["cap_key"], values[1])
    call gtk.widget_set_visible(W["cap_key"], values[1] != "")
    call gtk.label_set_text(W["cap_hint"], values[2])
    call gtk.widget_set_visible(W["cap_hint"], values[2] != "")
    call gtk.window_resize(W["caption"], 1, 1)        # i zmensit, kdyz je novy text kratsi
    call caption_place()
    return 0
end

function caption_place():
    anchor = TB["anchor"]
    if anchor == None:
        return 0
    end
    size = preferred_size(W["caption"])
    call gtk.window_move(W["caption"], anchor[0] - size[0] // 2, anchor[1] - size[1] - 6)
    return 0
end

# ---- lista ---------------------------------------------------------------------------------------------------

function tb_set_mode(mode):
    TB["mode"] = mode
    for m in W["modes"].keys():
        call gtk.widget_set_class(W["modes"][m], "active", m == mode)
    end
    call tb_set_ctrl(TB["ctrl"])
    call gtk.widget_set_sensitive(W["capture"], mode != "window")      # okno se zachyti kliknutim na nej
    call update_caption()
    return 0
end

# Drzeny Ctrl: tlacitko ukaze Kopirovat (snimek pujde do schranky)
function tb_set_ctrl(held):
    TB["ctrl"] = held
    if TB["mode"].startswith("rec_"):
        call gtk.button_set_label(W["capture"], T("Record"))
    elif held:
        call gtk.button_set_label(W["capture"], T("Copy"))
    else:
        call gtk.button_set_label(W["capture"], T("Capture"))
    end
    return 0
end

# Dole uprostred monitoru s mysi, nad Dockem; popisek nad listou
function tb_place():
    g = gtk.monitor_at_pointer()
    size = preferred_size(W["toolbar"])
    x = g[0] + (g[2] - size[0]) // 2
    y = g[1] + g[3] - size[1] - max(90, g[3] // 10)
    call gtk.window_move(W["toolbar"], x, y)
    TB["anchor"] = [x + size[0] // 2, y]
    call caption_place()
    return 0
end

function toolbar_visible():
    return S["built"] and gtk.widget_get_visible(W["toolbar"])
end

function show_toolbar():
    call tb_place()
    call gtk.widget_show(W["toolbar"])
    call update_caption()
    call gtk.widget_show(W["caption"])
    call restack()
    # Celou klavesnici nezabirat (psani a zkratky v aplikacich funguji), jen Esc a Enter
    call keys_update()
    return 0
end

function hide_toolbar():
    call gtk.widget_hide(W["toolbar"])
    call gtk.widget_hide(W["caption"])
    return 0
end

# ---- globalni klavesy a poradi oken -------------------------------------------------------------------------------

function overlay_visible():
    return S["built"] and gtk.widget_get_visible(W["overlay"])
end

function visible(key):
    return S["built"] and gtk.widget_get_visible(W[key])
end

# Esc, dokud je nastroj videt (mimo nahravani a dialog); Enter jen s listou
function keys_update():
    want_esc = False
    want_enter = False
    if S["active"] and S["dialog"] == 0 and S["state"] != "recording" and S["built"]:
        want_esc = visible("toolbar") or visible("overlay") or visible("countdown") or visible("thumb")
        want_enter = visible("toolbar")
    end
    call key_set("esc", want_esc, [[KEY_ESCAPE, 0]])
    call key_set("enter", want_enter, [[KEY_RETURN, 0], [KEY_RETURN, x11.CONTROL_MASK], [KEY_KP_ENTER, 0], [KEY_KP_ENTER, x11.CONTROL_MASK]])
    call watch_update()
    return 0
end

function key_set(name, on, keys):
    current = S["keys"].get(name, False)
    if current == on:
        return 0
    end
    S["keys"][name] = on
    for pair in keys:
        if on:
            if not x11.grab_key(pair[0], pair[1]):
                call log("key " + String(pair[0]) + " is used by another program")
            end
        else:
            call x11.ungrab_key(pair[0], pair[1])
        end
    end
    return 0
end

# Sledovani korenoveho okna jen pri otevrenem nastroji
function watch_update():
    want = S["active"] and S["built"] and (visible("toolbar") or visible("overlay") or visible("countdown") or visible("thumb") or visible("pill"))
    if want != S["watching"]:
        S["watching"] = want
        call x11.root_watch(want)
    end
    return 0
end

function own_xids():
    out = []
    if not S["built"]:
        return out
    end
    for key in ["overlay", "toolbar", "caption", "countdown", "pill", "thumb"]:
        out.append(gtk.widget_xid(W[key]))
    end
    for key in ["options_menu", "thumb_menu"]:
        out.append(gtk.widget_get_toplevel_xid(W[key]))
    end
    return out
end

# Udalost korenoveho okna: globalni klavesa, nebo spravce oken zmenil poradi/aktivni okno
function on_root_event(bound, kind, window, detail, mods):
    if not S["active"]:
        return 0
    end
    if kind == x11.KEY_PRESS:
        call on_global_key(detail, mods)
        return 0
    end
    if kind == x11.PROPERTY_NOTIFY:
        if detail != x11.atom("_NET_ACTIVE_WINDOW") and detail != x11.atom("_NET_CLIENT_LIST_STACKING"):
            return 0
        end
    elif window in own_xids():
        return 0
    end
    if not S["restack_pending"]:
        S["restack_pending"] = True
        call glib.idle_add_data(restack_idle, 0)
    end
    return 0
end

function restack_idle(bound):
    S["restack_pending"] = False
    call restack()
    return False
end

# Nase okna navrch ve spravnem poradi; otevrena nabidka nad nimi; behem dialogu nic (dialog ma byt navrchu)
function restack():
    if not S["built"] or S["dialog"] != 0:
        return 0
    end
    for key in ["overlay", "toolbar", "caption", "countdown", "pill", "thumb"]:
        if gtk.widget_get_visible(W[key]):
            call gtk.gdk_window_raise(W[key])
        end
    end
    if S["menu"] != 0 and gtk.widget_get_visible(S["menu"]):
        call gtk.gdk_window_raise(gtk.widget_get_toplevel(S["menu"]))
    end
    return 0
end

function on_global_key(code, mods):
    if S["menu"] != 0 or S["dialog"] != 0:
        return 0
    end
    if code == x11.keycode(KEY_ESCAPE):
        call escape()
    elif code == x11.keycode(KEY_RETURN) or code == x11.keycode(KEY_KP_ENTER):
        if toolbar_visible():
            call capture_now(mods & x11.CONTROL_MASK != 0)
        end
    end
    return 0
end

# Esc: odpocet zrusi snimek, nahled zavre, lista/vyber zavre; nahravani ne (viz hlavicka)
function escape():
    if not S["active"] or S["state"] == "recording":
        return 0
    end
    if visible("thumb") and S["state"] == "idle":
        call thumb_finish()
        return 0
    end
    call cancel()
    return 0
end

# ---- klavesy v oknech (prekryv se zabranou klavesnici) -------------------------------------------------------------

function on_window_key(bound, event, win):
    return app_key(event)
end

function app_key(event):
    keyval = gtk.event_key_keyval(event)
    if keyval == KEY_ESCAPE:
        call escape()
        return True
    end
    if (keyval == KEY_RETURN or keyval == KEY_KP_ENTER) and toolbar_visible():
        call capture_now(gtk.event_key_state(event) & gtk.CONTROL_MASK != 0)
        return True
    end
    if (keyval == KEY_CONTROL_L or keyval == KEY_CONTROL_R) and S["toolbar_session"]:
        call tb_set_ctrl(True)
    end
    return False
end

function on_key_release(bound, event, win):
    keyval = gtk.event_key_keyval(event)
    if (keyval == KEY_CONTROL_L or keyval == KEY_CONTROL_R) and S["toolbar_session"]:
        call tb_set_ctrl(False)
    end
    return False
end

# Klavesnice pro prekryv bez listy (Esc, mezernik); po klavesove zkratce chvili opakovat
function grab_keyboard():
    S["grab_tries"] = 20
    if not try_grab(S["token"]):
        call glib.timeout_add_data(50, try_grab, S["token"])
    end
    return 0
end

function try_grab(token):
    if not is_live_token(token) or not overlay_visible() or S["menu"] != 0 or S["dialog"] != 0:
        return False
    end
    if gtk.seat_grab_keyboard(W["overlay"]):
        return False
    end
    S["grab_tries"] = S["grab_tries"] - 1
    return S["grab_tries"] > 0
end

# ---- prekryv: vyber vyrezu nebo okna ----------------------------------------------------------------------------

function ov_norm():
    if OV["sel"] == None:
        return None
    end
    return base.clamp_rect(OV["sel"], OV["sw"], OV["sh"])
end

function handles(sel):
    x = sel[0]
    y = sel[1]
    w = sel[2]
    h = sel[3]
    return [[x, y, "nw"], [x + w / 2.0, y, "n"], [x + w, y, "ne"], [x + w, y + h / 2.0, "e"],
            [x + w, y + h, "se"], [x + w / 2.0, y + h, "s"], [x, y + h, "sw"], [x, y + h / 2.0, "w"]]
end

function hit(px, py):
    sel = ov_norm()
    if sel == None or OV["quick"]:
        return ""
    end
    for hd in handles(sel):
        if abs(px - hd[0]) <= HANDLE and abs(py - hd[1]) <= HANDLE:
            return hd[2]
        end
    end
    if sel[0] <= px and px < sel[0] + sel[2] and sel[1] <= py and py < sel[1] + sel[3]:
        return "move"
    end
    return ""
end

function window_at(px, py):
    if OV["windows"] == None:
        return None
    end
    for r in OV["windows"]:
        if r[0] <= px and px < r[0] + r[2] and r[1] <= py and py < r[1] + r[3]:
            return r
        end
    end
    return None
end

function ov_open(mode, selection, quick, live):
    size = gtk.root_size()
    OV["sw"] = size[0]
    OV["sh"] = size[1]
    OV["quick"] = quick
    OV["live"] = live
    OV["sel"] = selection
    OV["drag"] = None
    OV["hover"] = None
    OV["windows"] = None
    OV["open"] = True
    call gtk.window_move(W["overlay"], 0, 0)
    call gtk.window_resize(W["overlay"], size[0], size[1])
    call gtk.widget_realize(W["overlay"])
    call ov_set_mode(mode)
    call gtk.widget_show(W["overlay"])
    call ov_set_cursor()
    return 0
end

function ov_close():
    OV["open"] = False
    OV["windows"] = None
    if S["built"]:
        call gtk.widget_hide(W["overlay"])
    end
    return 0
end

function ov_set_cursor():
    if OV["mode"] == "portion":
        call gtk.widget_set_cursor(W["overlay"], "crosshair")
    else:
        call gtk.widget_set_cursor(W["overlay"], "default")
    end
    return 0
end

function ov_set_mode(mode):
    if mode == "window":
        OV["mode"] = "window"
    else:
        OV["mode"] = "portion"
    end
    if OV["mode"] == "window" and OV["windows"] == None:
        OV["windows"] = x11.window_list(own_xids())
    end
    if OV["mode"] == "portion" and OV["sel"] == None and not OV["quick"]:
        w = OV["sw"] // 2
        h = OV["sh"] // 2
        OV["sel"] = [(OV["sw"] - w) // 2, (OV["sh"] - h) // 2, w, h]
    end
    OV["hover"] = None
    call ov_set_cursor()
    call ov_queue_draw()
    return 0
end

# Zivy prekryv: mys jen v ramecku vyberu (+uchyty); v rezimu okna cela plocha (klik vybere okno)
function ov_update_input():
    if not OV["live"]:
        return 0
    end
    sel = None
    if OV["mode"] == "portion":
        sel = ov_norm()
    end
    if sel != None and OV["drag"] == None:
        m = HANDLE + 2
        call gtk.widget_input_rect(W["overlay"], sel[0] - m, sel[1] - m, sel[2] + 2 * m, sel[3] + 2 * m)
    else:
        call gtk.widget_input_rect(W["overlay"], 0, 0, -1, -1)
    end
    return 0
end

function ov_queue_draw():
    call gtk.widget_queue_draw(W["overlay"])
    call ov_update_input()
    return 0
end

function on_ov_draw(bound, cr, win):
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    if OV["live"] or S["surface"] == 0:
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.0)
    else:
        call cairo.set_source_surface(cr, S["surface"], 0, 0)
    end
    call cairo.paint(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_OVER)
    if OV["mode"] == "window":
        hv = OV["hover"]
        if hv != None:
            call cairo.rectangle(cr, hv[0], hv[1], hv[2], hv[3])
            call cairo.set_source_rgba(cr, ACCENT[0], ACCENT[1], ACCENT[2], 0.28)
            call cairo.fill(cr)
        end
        return True
    end
    call gtk.cairo_set_fill_rule(cr, 1)
    call cairo.rectangle(cr, 0, 0, OV["sw"], OV["sh"])
    sel = ov_norm()
    if sel != None:
        call cairo.rectangle(cr, sel[0], sel[1], sel[2], sel[3])
    end
    shade = 0.38
    if OV["live"]:
        shade = 0.22
    end
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, shade)
    call cairo.fill(cr)
    if sel == None:
        return True
    end
    x = Float(sel[0])
    y = Float(sel[1])
    w = Float(sel[2])
    h = Float(sel[3])
    call cairo.set_line_width(cr, 1.0)
    call cairo.rectangle(cr, x - 0.5, y - 0.5, w + 1.0, h + 1.0)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.5)
    call cairo.stroke(cr)
    call cairo.rectangle(cr, x + 0.5, y + 0.5, max(0.0, w - 1.0), max(0.0, h - 1.0))
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    call cairo.stroke(cr)
    if not OV["quick"]:
        for hd in handles(sel):
            call cairo.new_path(cr)
            call cairo.arc(cr, hd[0], hd[1], 4.5, 0.0, 6.2832)
            call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
            call cairo.fill_preserve(cr)
            call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.35)
            call cairo.stroke(cr)
        end
    end
    # Popisek s rozmery pod vyberem
    label = String(sel[2]) + " × " + String(sel[3])
    call cairo.select_font_face(cr, "Inter", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    call cairo.set_font_size(cr, 12.0)
    ext = cairo.text_extents(cr, label)
    bw = ext[2] + 16.0
    bh = 22.0
    bx = min(max(4.0, x + (w - bw) / 2.0), OV["sw"] - bw - 4.0)
    by = y + h - bh - 10.0
    if y + h + 10.0 + bh < OV["sh"]:
        by = y + h + 10.0
    end
    if by < 4.0:
        by = 4.0
    end
    call cairo.rounded_rectangle(cr, bx, by, bw, bh, 6.0)
    call cairo.set_source_rgba(cr, 0.1, 0.1, 0.14, 0.82)
    call cairo.fill(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
    call cairo.move_to(cr, bx + 8.0 - ext[0], by + bh / 2.0 - ext[1] - ext[3] / 2.0)
    call cairo.show_text(cr, label)
    return True
end

function on_ov_press(bound, event, win):
    if not is_live_token(S["token"]):
        return True
    end
    button = gtk.event_button(event)
    px = gtk.event_x(event)
    py = gtk.event_y(event)
    if button != 1:
        if button == 3 and OV["quick"]:
            call cancel()
        end
        return True
    end
    if OV["mode"] == "window":
        r = window_at(gtk.event_x_root(event), gtk.event_y_root(event))
        if r != None:
            call selected(r, gtk.event_button_state(event) & gtk.CONTROL_MASK != 0)
        end
        return True
    end
    part = hit(px, py)
    if gtk.event_is_double_click(event) and part == "move":
        call capture_now(None)
        return True
    end
    if part != "":
        OV["drag"] = [part, px, py, ov_norm(), OV["sel"]]
    else:
        OV["drag"] = ["new", px, py, None, OV["sel"]]
        OV["sel"] = [Int(px), Int(py), 0, 0]
    end
    call ov_queue_draw()
    return True
end

CURSORS = {"move": "move", "n": "n-resize", "s": "s-resize", "e": "e-resize", "w": "w-resize", "ne": "ne-resize", "nw": "nw-resize", "se": "se-resize", "sw": "sw-resize"}

function on_ov_motion(bound, event, win):
    px = gtk.event_x(event)
    py = gtk.event_y(event)
    if OV["mode"] == "window":
        r = window_at(gtk.event_x_root(event), gtk.event_y_root(event))
        if r != OV["hover"]:
            OV["hover"] = r
            call ov_queue_draw()
        end
        return True
    end
    drag = OV["drag"]
    if drag == None:
        part = hit(px, py)
        call gtk.widget_set_cursor(W["overlay"], CURSORS.get(part, "crosshair"))
        return True
    end
    kind = drag[0]
    dx = px - drag[1]
    dy = py - drag[2]
    orig = drag[3]
    if kind == "new":
        OV["sel"] = [Int(drag[1]), Int(drag[2]), Int(dx), Int(dy)]
    elif kind == "move":
        x = min(max(0.0, orig[0] + dx), Float(OV["sw"] - orig[2]))
        y = min(max(0.0, orig[1] + dy), Float(OV["sh"] - orig[3]))
        OV["sel"] = [Int(x), Int(y), orig[2], orig[3]]
    else:
        x = Float(orig[0])
        y = Float(orig[1])
        x1 = x + orig[2]
        y1 = y + orig[3]
        if kind.find("w") >= 0:
            x = x + dx
        end
        if kind.find("e") >= 0:
            x1 = x1 + dx
        end
        if kind.find("n") >= 0:
            y = y + dy
        end
        if kind.find("s") >= 0:
            y1 = y1 + dy
        end
        OV["sel"] = [Int(x), Int(y), Int(x1 - x), Int(y1 - y)]
    end
    call ov_queue_draw()
    return True
end

function on_ov_release(bound, event, win):
    if gtk.event_button(event) != 1 or OV["drag"] == None:
        return True
    end
    prev = OV["drag"][4]
    OV["drag"] = None
    sel = ov_norm()
    if sel == None or sel[2] < 3 or sel[3] < 3:
        OV["sel"] = prev     # pouhy klik: puvodni vyber zustava
        call ov_queue_draw()
        return True
    end
    OV["sel"] = sel
    if OV["quick"]:
        call selected(sel, gtk.event_button_state(event) & gtk.CONTROL_MASK != 0)
    end
    call ov_queue_draw()           # zivy prekryv: zachytavani mysi zase jen v ramecku
    return True
end

function on_ov_key(bound, event, win):
    if gtk.event_key_keyval(event) == KEY_SPACE and OV["quick"] and OV["drag"] == None and S["mode"] != "rec_portion":
        if OV["mode"] == "window":
            call ov_set_mode("portion")
        else:
            call ov_set_mode("window")
        end
        return True
    end
    return app_key(event)
end

# ---- nahled po snimku -----------------------------------------------------------------------------------------

function thumb_actions():
    acts = []
    if not TH["video"] and not TH["copied"]:
        acts.append("copy")
    end
    if TH["path"] != "":
        acts.append("reveal")
    end
    acts.append("save_as")
    if TH["path"] != "":
        acts.append("delete")
    end
    acts.append("close")
    return acts
end

function thumb_open(path, pb, copied, video):
    TH["path"] = path
    TH["full"] = pb
    TH["copied"] = copied
    TH["video"] = video
    TH["dragging"] = False
    TH["menu"] = False
    TH["open"] = True
    w = gtk.pixbuf_get_width(pb)
    h = gtk.pixbuf_get_height(pb)
    s = min(200.0 / w, 140.0 / h, 1.0)
    TH["small"] = gtk.pixbuf_scale(pb, Int(w * s), Int(h * s))
    call gtk.widget_set_size_request(W["thumb_image"], gtk.pixbuf_get_width(TH["small"]), gtk.pixbuf_get_height(TH["small"]))
    call gtk.widget_set_visible(W["thumb_status"], copied)
    acts = thumb_actions()
    for key in W["thumb_buttons"].keys():
        call gtk.widget_set_visible(W["thumb_buttons"][key][0], key in acts)
    end
    copy = W["thumb_buttons"]["copy"]
    call gtk.image_set_from_icon_name(copy[1], "edit-copy-symbolic", gtk.ICON_MENU)
    call gtk.label_set_text(copy[2], T("Copy"))
    call gtk.drag_source_setup(W["thumb_image"], path != "", TH["small"])
    call gtk.window_resize(W["thumb"], 1, 1)
    g = gtk.monitor_at_pointer()
    size = preferred_size(W["thumb"])
    call gtk.window_move(W["thumb"], g[0] + g[2] - size[0] - 24, g[1] + g[3] - size[1] - 96)
    call gtk.widget_show(W["thumb"])
    call gtk.widget_queue_draw(W["thumb_image"])
    call restack()
    call keys_update()
    call thumb_start_timer()
    return 0
end

function thumb_start_timer():
    S["seq"] = S["seq"] + 1
    TH["timer"] = S["seq"]
    if TH["open"]:
        call glib.timeout_add_data(base.THUMB_TIME, thumb_timeout, [S["token"], TH["timer"]])
    end
    return 0
end

function thumb_stop_timer():
    TH["timer"] = 0
    return 0
end

function thumb_timeout(pair):
    if is_live_token(pair[0]) and TH["timer"] == pair[1] and TH["open"]:
        call thumb_finish()
    end
    return False
end

function on_thumb_enter(bound, event, win):
    call thumb_stop_timer()
    return False
end

function on_thumb_leave(bound, event, win):
    # presun na tlacitko neni odchod
    if gtk.event_crossing_detail(event) != gtk.NOTIFY_INFERIOR and not TH["menu"]:
        call thumb_start_timer()
    end
    return False
end

function on_thumb_draw(bound, cr, area):
    if TH["small"] == 0:
        return False
    end
    w = Float(gtk.widget_get_allocated_width(area))
    h = Float(gtk.widget_get_allocated_height(area))
    pw = gtk.pixbuf_get_width(TH["small"])
    ph = gtk.pixbuf_get_height(TH["small"])
    call cairo.rounded_rectangle(cr, 0.0, 0.0, w, h, 7.0)
    call cairo.clip(cr)
    call gtk.cairo_set_source_pixbuf(cr, TH["small"], (w - pw) / 2.0, (h - ph) / 2.0)
    call cairo.paint(cr)
    call cairo.reset_clip(cr)
    call cairo.rounded_rectangle(cr, 0.5, 0.5, w - 1.0, h - 1.0, 7.0)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.16)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    return False
end

function on_drag_get(bound, context, selection, info, time, widget):
    if TH["path"] != "":
        call gtk.selection_set_uri(selection, glib.filename_to_uri(TH["path"]))
    elif TH["full"] != 0:
        call gtk.selection_set_pixbuf(selection, TH["full"])
    end
    return 0
end

function on_drag_begin(bound, context, widget):
    TH["dragging"] = True
    call thumb_stop_timer()
    return 0
end

function on_drag_end(bound, context, widget):
    if TH["open"]:
        call thumb_finish()
    end
    return 0
end

function on_thumb_click(bound, event, area):
    if gtk.event_button(event) == 1 and not TH["dragging"] and TH["open"]:
        if TH["path"] != "":
            call open_uri(glib.filename_to_uri(TH["path"]))
            call thumb_finish()
        end
        return True
    end
    return False
end

function on_thumb_press(bound, event, win):
    if gtk.event_button(event) == 3 and TH["open"]:
        call thumb_menu_popup()
        return True
    end
    return False
end

function thumb_menu_popup():
    items = W["thumb_items"]
    acts = thumb_actions()
    call gtk.widget_set_visible(items["open"], TH["path"] != "")
    for key in ["copy", "reveal", "save_as", "delete", "close"]:
        call gtk.widget_set_visible(items[key], key in acts)
    end
    call thumb_stop_timer()
    TH["menu"] = True
    S["menu"] = W["thumb_menu"]
    call gtk.menu_popup_at_pointer(W["thumb_menu"])
    call keys_update()
    return 0
end

function on_thumb_menu_hidden(bound, menu):
    TH["menu"] = False
    if S["menu"] == W["thumb_menu"]:
        S["menu"] = 0
    end
    if TH["open"]:
        call thumb_start_timer()
    end
    return 0
end

function on_thumb_menu_item(key, item):
    # akce az po zavreni nabidky (dialog Ulozit jako nesmi bezet pod jejim zachycenim)
    call glib.idle_add_data(thumb_act_idle, [S["token"], key])
    return 0
end

function thumb_act_idle(pair):
    if is_live_token(pair[0]):
        call thumb_act(pair[1])
    end
    return False
end

function on_thumb_button(key, button):
    call thumb_act(key)
    return 0
end

function thumb_act(key):
    if not TH["open"]:
        return 0
    end
    if key == "copy":
        if copy_image(TH["full"]):
            copy = W["thumb_buttons"]["copy"]
            call gtk.image_set_from_icon_name(copy[1], "object-select-symbolic", gtk.ICON_MENU)
            call gtk.label_set_text(copy[2], T("Copied"))
        end
        call thumb_start_timer()
    elif key == "open":
        call open_uri(glib.filename_to_uri(TH["path"]))
        call thumb_finish()
    elif key == "reveal":
        call thumb_stop_timer()
        call gtk.widget_hide(W["thumb"])
        call reveal(TH["path"])
    elif key == "save_as":
        call thumb_stop_timer()
        call gtk.widget_hide(W["thumb"])          # dialog spravuje WM, nahled mimo WM by ho zakryl
        call save_as_dialog()
    elif key == "delete":
        if trash(TH["path"]):
            call thumb_finish()
        end
    elif key == "close":
        call thumb_finish()
    end
    return 0
end

function thumb_close():
    if not TH["open"]:
        return 0
    end
    TH["open"] = False
    call thumb_stop_timer()
    if S["built"]:
        if S["menu"] == W["thumb_menu"]:
            call gtk.menu_popdown(W["thumb_menu"])
        end
        call gtk.widget_hide(W["thumb"])
    end
    call gtk.object_unref(TH["small"])
    call gtk.object_unref(TH["full"])
    TH["small"] = 0
    TH["full"] = 0
    return 0
end

# Nahled zavreny (akce, cas, Esc): konec relace
function thumb_finish():
    if not TH["open"]:
        return 0
    end
    call thumb_close()
    call done()
    return 0
end

# ---- akce nahledu --------------------------------------------------------------------------------------------

function open_uri(uri):
    if not glib.launch_uri(uri):
        call glib.spawn_quiet(["xdg-open", uri])
    end
    return 0
end

# Obrazek do schranky pres xclip: drzi ho samostatny proces xclip, takze zustane ve schrance i po skonceni
# tohoto programu (do dalsiho kopirovani). Bez xclipu drzi obrazek tento proces.
function copy_image(pb):
    if pb == 0:
        return False
    end
    if glib.find_program_in_path("xclip") != "":
        tmp = base.runtime_dir() + "/.luxos-screenshot-clip-" + String(glib.getpid()) + ".png"
        if gtk.pixbuf_save_png(pb, tmp) == "":
            status = glib.spawn_sync_quiet(["xclip", "-selection", "clipboard", "-t", "image/png", "-i", tmp])
            call luxos_sys.unlink(tmp)
            if status == 0:
                return True
            end
        end
    end
    S["clip_owner"] = gtk.clipboard_set_image(pb)
    if not S["holding_clip"]:
        S["holding_clip"] = True
    end
    return True
end

function own_clipboard():
    owner = gtk.clipboard_owner()
    return owner != 0 and owner == S["clip_owner"]
end

# Zobrazit v Souborech: spravce souboru oznaci soubor (FileManager1), jinak otevre slozku
function reveal(path):
    ok = False
    try:
        bus = gio.session_bus()
        call gio.call_async(bus, "org.freedesktop.FileManager1", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1", "ShowItems", [[glib.filename_to_uri(path)], ""], "(ass)", 8000, on_reveal_reply, [S["token"], path])
        ok = True
    else:
        ok = False
    end
    if not ok:
        call open_uri(glib.filename_to_uri(base.dirname(path)))
        call thumb_finish()
    end
    return 0
end

function on_reveal_reply(pair, values, error):
    if error != "":
        call open_uri(glib.filename_to_uri(base.dirname(pair[1])))
    end
    if is_live_token(pair[0]):
        call thumb_finish()
    end
    return 0
end

# Smazat = do Kose; kdyz slozka Kos nepodporuje (napr. tmpfs), napevno - jde o snimek, ktery
# tento program prave vytvoril
function trash(path):
    result = glib.trash_file(path)
    if result == "trash":
        return True
    end
    if result == "unsupported":
        if luxos_sys.unlink(path):
            return True
        end
        result = "unlink failed"
    end
    call notify(T("The file could not be moved to the Trash.") + " " + result)
    return False
end

# Ulozit jako: video/soubor zkopiruje, obrazek ulozi podle pripony (.jpg = JPEG, jinak PNG); "" = ok
function write_copy(pb, src, dest, video):
    if video or pb == 0:
        if src != "" and glib.realpath(src) != glib.realpath(dest):
            if glib.spawn_sync_quiet(["cp", "--", src, dest]) != 0:
                return "copy failed"
            end
        end
        return ""
    end
    ext = base.splitext(dest)[1].lower()
    if ext == ".jpg" or ext == ".jpeg":
        flat = pb
        if gtk.pixbuf_has_alpha(pb):
            flat = gtk.pixbuf_flatten(pb)
        end
        err = gtk.pixbuf_save_jpeg(flat, dest)
        if flat != pb:
            call gtk.object_unref(flat)
        end
        return err
    end
    return gtk.pixbuf_save_png(pb, dest)
end

function save_as_dialog():
    video = TH["video"]
    title = T("Save Screenshot")
    if video:
        title = T("Save Recording")
    end
    dlg = gtk.file_chooser_new(title, gtk.FILE_CHOOSER_SAVE)
    call gtk.dialog_add_button(dlg, T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(dlg, T("Save"), gtk.RESPONSE_ACCEPT)
    call gtk.dialog_set_default_response(dlg, gtk.RESPONSE_ACCEPT)
    call gtk.file_chooser_set_overwrite_confirm(dlg, True)
    src = TH["path"]
    folder = user_dir("pictures")
    if src != "":
        folder = base.dirname(src)
    end
    if glib.is_dir(folder):
        call gtk.file_chooser_set_folder(dlg, folder)
    end
    if src != "":
        call gtk.file_chooser_set_name(dlg, base.basename(src))
    else:
        call gtk.file_chooser_set_name(dlg, base.file_name(now_fields(), False))
    end
    call open_dialog(dlg, on_save_response)
    return 0
end

function open_dialog(dlg, handler):
    call gtk.window_set_keep_above(dlg, True)
    S["dialog"] = dlg
    call gtk.connect_data(dlg, "response", 1, handler, S["token"])
    call keys_update()
    call gtk.widget_show(dlg)
    call gtk.window_present_with_time(dlg, gtk.get_current_event_time())
    return 0
end

function close_dialog():
    dlg = S["dialog"]
    if dlg == 0:
        return 0
    end
    S["dialog"] = 0
    call gtk.widget_destroy(dlg)
    call keys_update()
    return 0
end

function on_save_response(token, response, dlg):
    if dlg != S["dialog"]:
        return 0
    end
    path = ""
    if gtk.s32(response) == gtk.RESPONSE_ACCEPT:
        path = gtk.file_chooser_get_filename(dlg)
    end
    call close_dialog()
    if not is_live_token(token) or not TH["open"]:
        return 0
    end
    video = TH["video"]
    if path != "" and not video and base.splitext(path)[1] == "":
        path = base.unique_path(base.dirname(path), base.basename(path) + ".png")
    end
    if path != "":
        err = write_copy(TH["full"], TH["path"], path, video)
        if err == "":
            call thumb_finish()
            return 0
        end
        call notify(T("The screenshot could not be saved.") + " " + err)
    end
    call gtk.widget_show(W["thumb"])
    call restack()
    call keys_update()
    call thumb_start_timer()
    return 0
end

# ---- volby ---------------------------------------------------------------------------------------------------

function options_popup():
    o = S["opts"]
    S["menu_sync"] = True
    for entry in W["opt_radio"]:
        call gtk.check_menu_item_set_active(entry[0], o[entry[1]] == entry[2])
    end
    for entry in W["opt_checks"]:
        call gtk.check_menu_item_set_active(entry[0], o[entry[1]])
    end
    other = W["opt_other_radio"]
    if o["other_dir"] != "":
        name = base.basename(text.rstrip_chars(o["other_dir"], "/"))
        if name == "":
            name = o["other_dir"]
        end
        call gtk.menu_item_set_label(other, name)
        call gtk.widget_show(other)
    else:
        call gtk.widget_hide(other)
    end
    S["menu_sync"] = False
    S["menu"] = W["options_menu"]
    call gtk.menu_popup_above(W["options_menu"], W["options"])
    return 0
end

function on_options_hidden(bound, menu):
    if S["menu"] == W["options_menu"]:
        S["menu"] = 0
    end
    # Po zavreni nabidky GTK uvolni vsechna zachyceni: klavesnici prekryvu bez listy vzit zpet
    if S["active"] and OV["quick"] and overlay_visible():
        call grab_keyboard()
    end
    return 0
end

function on_opt_radio(pair, item):
    if S.get("menu_sync", False) or not S["active"]:
        return 0
    end
    if gtk.check_menu_item_get_active(item):
        call set_opt(pair[0], pair[1])
    end
    return 0
end

function on_opt_check(key, item):
    if S.get("menu_sync", False) or not S["active"]:
        return 0
    end
    call set_opt(key, gtk.check_menu_item_get_active(item))
    return 0
end

function set_opt(key, value):
    S["opts"][key] = value
    call save_options()
    if S["toolbar_session"]:
        TB["caption"] = []
        call update_caption()
    end
    if key == "pointer" and value and S["frozen_pb"] != 0 and len(S["frozen_cursor"]) == 0:
        S["frozen_cursor"] = x11.cursor_surface()
    end
    return 0
end

function on_other_folder(bound, item):
    call glib.idle_add_data(choose_folder, S["token"])
    return 0
end

# Dialog spravuje WM - lista a prekryv (mimo WM) by ho zakryly
function choose_folder(token):
    if not is_live_token(token):
        return False
    end
    S["after_dialog"] = ""
    if overlay_visible():
        S["after_dialog"] = "overlay"
    end
    call gtk.widget_hide(W["overlay"])
    call hide_toolbar()
    call gtk.seat_ungrab()
    dlg = gtk.file_chooser_new(T("Choose a Folder"), gtk.FILE_CHOOSER_SELECT_FOLDER)
    call gtk.dialog_add_button(dlg, T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.dialog_add_button(dlg, T("Choose"), gtk.RESPONSE_OK)
    if S["opts"]["other_dir"] != "":
        call gtk.file_chooser_set_folder(dlg, S["opts"]["other_dir"])
    end
    call open_dialog(dlg, on_folder_response)
    return False
end

function on_folder_response(token, response, dlg):
    if dlg != S["dialog"]:
        return 0
    end
    path = ""
    if gtk.s32(response) == gtk.RESPONSE_OK:
        path = gtk.file_chooser_get_filename(dlg)
    end
    call close_dialog()
    if not is_live_token(token):
        return 0
    end
    if path != "":
        S["opts"]["other_dir"] = path
        call set_opt("save_to", "other")
    end
    if S["after_dialog"] == "overlay" and OV["open"]:
        call gtk.widget_show(W["overlay"])
    end
    call show_toolbar()
    if OV["quick"] and overlay_visible():
        call grab_keyboard()
    end
    return 0
end

# ---- zachyceni -----------------------------------------------------------------------------------------------

function screen_rect():
    size = gtk.root_size()
    return [0, 0, size[0], size[1]]
end

# Obrazek korenoveho okna (pixely zarizeni) nebo jeho casti v logickych souradnicich; 0 pri chybe
function grab(rect):
    size = gtk.root_size()
    r = [0, 0, size[0], size[1]]
    if rect != None:
        r = base.clamp_rect(rect, size[0], size[1])
        if r == None:
            return 0
        end
    end
    return gtk.pixbuf_from_window(r[0], r[1], r[2], r[3])
end

# Vlozi kurzor do snimku, jehoz levy horni roh je na origin (logicky); vraci novy obrazek (stary uvolni)
function add_cursor(pb, origin, cursor, scale):
    if pb == 0 or len(cursor) == 0:
        return pb
    end
    w = gtk.pixbuf_get_width(pb)
    h = gtk.pixbuf_get_height(pb)
    surface = gtk.pixbuf_to_surface(pb, 1)
    cr = cairo.create(surface)
    call cairo.set_source_surface(cr, cursor[0], cursor[1] - origin[0] * scale, cursor[2] - origin[1] * scale)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    out = gtk.surface_to_pixbuf(surface, w, h)
    call cairo.surface_destroy(surface)
    if out == 0:
        return pb
    end
    call gtk.object_unref(pb)
    return out
end

function free_cursor(cursor):
    if len(cursor) > 0:
        call cairo.surface_destroy(cursor[0])
    end
    return 0
end

function unfreeze():
    if S["surface"] != 0:
        call cairo.surface_destroy(S["surface"])
        S["surface"] = 0
    end
    call gtk.object_unref(S["frozen_pb"])
    S["frozen_pb"] = 0
    call free_cursor(S["frozen_cursor"])
    S["frozen_cursor"] = []
    return 0
end

function freeze():
    call unfreeze()
    pb = grab(None)
    S["frozen_pb"] = pb
    if S["opts"]["pointer"]:
        S["frozen_cursor"] = x11.cursor_surface()
    end
    if pb != 0:
        S["surface"] = gtk.pixbuf_to_surface(pb, S["scale"])
    end
    return 0
end

# Tlacitko Zachytit / Nahrat nebo Enter; s Ctrl jde snimek do schranky
function capture_now(ctrl):
    if S["busy"] or not S["active"]:
        return 0
    end
    mode = S["mode"]
    if ctrl == None:
        S["to_clip"] = gtk.current_event_state() & gtk.CONTROL_MASK != 0
    else:
        S["to_clip"] = ctrl
    end
    if mode == "portion" or mode == "rec_portion":
        sel = None
        if OV["open"]:
            sel = ov_norm()
        end
        if sel == None or sel[2] < 3 or sel[3] < 3:
            return 0
        end
        call remember(sel)
        if mode == "portion":
            call capture_rect(sel, False)
        else:
            call start_recording(sel)
        end
    elif mode == "screen":
        call capture_rect(screen_rect(), True)
    elif mode == "rec_screen":
        call start_recording(screen_rect())
    end
    return 0
end

function remember(sel):
    if S["opts"]["remember"]:
        S["opts"]["selection"] = [sel[0], sel[1], sel[2], sel[3]]
        call save_options()
    end
    return 0
end

# Skryje listu a prekryv; vrati prodlevu (ms) pred snimkem
function hide_ui():
    shown = False
    for key in ["toolbar", "overlay"]:
        if visible(key):
            shown = True
        end
    end
    call hide_toolbar()
    call gtk.widget_hide(W["overlay"])
    call gtk.seat_ungrab()
    call keys_update()
    if shown:
        return base.HIDE_DELAY
    end
    return 0
end

# Pak f(arg); pripadne odpocet podle volby Casovac (jen s listou)
function after_timer(delay, handler, value):
    secs = 0
    if S["toolbar_session"]:
        secs = S["opts"]["timer"]
    end
    job = [S["token"], handler, value, secs]
    if secs == 0:
        if delay > 0:
            call glib.timeout_add_data(delay, run_job, job)
        else:
            call run_job(job)
        end
        return 0
    end
    call glib.timeout_add_data(max(delay, 1), countdown_tick, job)
    return 0
end

function run_job(job):
    if is_live_token(job[0]):
        handler = job[1]
        call handler(job[2])
    end
    return False
end

function countdown_tick(job):
    if not is_live_token(job[0]):
        return False
    end
    if job[3] <= 0:
        call gtk.widget_hide(W["countdown"])
        call keys_update()
        call glib.timeout_add_data(base.HIDE_DELAY, run_job, job)
        return False
    end
    call countdown_show(job[3])
    job[3] = job[3] - 1
    call glib.timeout_add_data(1000, countdown_tick, job)
    return False
end

function countdown_show(n):
    call gtk.label_set_text(W["count_label"], String(n))
    g = gtk.monitor_at_pointer()
    size = preferred_size(W["countdown"])
    call gtk.window_move(W["countdown"], g[0] + (g[2] - size[0]) // 2, g[1] + g[3] - size[1] - 120)
    call gtk.widget_show(W["countdown"])
    call restack()
    call keys_update()
    return 0
end

# Vyber v prekryvu hotov: vyrez pustenim mysi (bez listy) nebo klik na okno
function selected(rect, ctrl):
    if S["busy"]:
        return 0
    end
    S["to_clip"] = ctrl
    if S["mode"] == "rec_portion":
        call start_recording(rect)
    else:
        call capture_rect(rect, False)
    end
    return 0
end

function capture_rect(rect, live):
    S["busy"] = True
    delay = hide_ui()
    use_frozen = S["frozen_pb"] != 0 and not live and not (S["toolbar_session"] and S["opts"]["timer"] != 0)
    if use_frozen:
        delay = 0
    end
    call after_timer(delay, shoot, [rect, use_frozen])
    return 0
end

function shoot(job):
    rect = job[0]
    out = 0
    if job[1]:
        s = S["scale"]
        pb = S["frozen_pb"]
        r = base.clamp_rect([rect[0] * s, rect[1] * s, rect[2] * s, rect[3] * s], gtk.pixbuf_get_width(pb), gtk.pixbuf_get_height(pb))
        if r != None:
            out = gtk.pixbuf_sub_copy(pb, r[0], r[1], r[2], r[3])
        end
        if S["opts"]["pointer"]:
            out = add_cursor(out, rect, S["frozen_cursor"], s)
        end
    else:
        out = grab(rect)
        if out != 0 and S["opts"]["pointer"]:
            cursor = x11.cursor_surface()
            out = add_cursor(out, rect, cursor, S["scale"])
            call free_cursor(cursor)
        end
    end
    call deliver(out)
    return 0
end

function deliver(pb):
    call hide_toolbar()
    call ov_close()
    call unfreeze()
    if pb == 0:
        call notify(T("The screenshot could not be taken."))
        call end_session(0)
        return 0
    end
    args = S["args"]
    folder = None
    if args["clipboard"]:
        if args["output"] != "":
            folder = args["output"]          # --clipboard --output: soubor do slozky (jako drive)
        end
    else:
        folder = save_dir(S["opts"], False, args["output"])
    end
    if S["to_clip"] or folder == None:
        if not copy_image(pb):
            call notify(T("The screenshot could not be copied to the clipboard."))
        end
        call show_thumb("", pb, True, False)
        return 0
    end
    call luxos_sys.mkdir_p(folder)
    path = base.unique_path(folder, base.file_name(now_fields(), False))
    err = gtk.pixbuf_save_png(pb, path)
    if err != "":
        call gtk.object_unref(pb)
        call notify(T("The screenshot could not be saved.") + " " + err)
        call end_session(0)
        return 0
    end
    call emit_path(path)
    call show_thumb(path, pb, False, False)
    return 0
end

function show_thumb(path, pb, copied, video):
    if S["args"]["no_thumb"] or pb == 0:
        call gtk.object_unref(pb)
        call done()
        return 0
    end
    S["state"] = "idle"
    call thumb_open(path, pb, copied, video)
    return 0
end

# Konec po snimku: relace konci (obrazek ve schrance drzeny primo procesem pocka v samostatnem procesu)
function done():
    call end_session(0)
    return 0
end

# ---- nahravani ---------------------------------------------------------------------------------------------

function start_recording(rect):
    S["busy"] = True
    folder = save_dir(S["opts"], True, S["args"]["output"])
    S["rec"] = {"rect": rect, "folder": folder, "pid": 0, "running": False, "stopping": False, "started": 0, "part": "", "final": "", "err": ""}
    delay = hide_ui()
    call after_timer(delay, rec_go, rect)
    return 0
end

function rec_go(rect):
    call hide_toolbar()
    call ov_close()
    call unfreeze()
    if not rec_start():
        S["rec"] = None
        call end_session(0)
        return 0
    end
    S["state"] = "recording"
    full = rect == screen_rect()
    call pill_open(full, rect)
    call keys_update()
    return 0
end

function encoder_args():
    if S["encoder"] != None:
        return S["encoder"]
    end
    program = glib.find_program_in_path("ffmpeg")
    if program == "":
        return None
    end
    listing = ""
    safe:
        listing = capture(program, ["-hide_banner", "-encoders"])
    end
    enc = base.pick_encoder(listing)
    if enc != None:
        S["encoder"] = enc
    end
    return enc
end

function rec_start():
    rec = S["rec"]
    enc = encoder_args()
    if enc == None:
        call notify(T("Screen recording is not available: ffmpeg was not found."))
        return False
    end
    call luxos_sys.mkdir_p(rec["folder"])
    rec["final"] = base.unique_path(rec["folder"], base.file_name(now_fields(), True))
    rec["part"] = rec["folder"] + "/." + base.basename(rec["final"]) + ".part"
    s = S["scale"]
    r = rec["rect"]
    display = env.get("DISPLAY", "")
    if display == None or display == "":
        display = ":0"
    end
    cmd = base.ffmpeg_cmd(display, [r[0] * s, r[1] * s, r[2] * s, r[3] * s], rec["part"], enc, 30, True)
    S["seq"] = S["seq"] + 1
    rec["err"] = base.runtime_dir() + "/.luxos-screenshot-ffmpeg-" + String(glib.getpid()) + "-" + String(S["seq"]) + ".log"
    # ffmpeg skonci (a dopise soubor), i kdyby proces se Snimkem obrazovky nekdo zabil (PR_SET_PDEATHSIG)
    script = "exec \"$@\" 2>\"$0\""
    if glib.find_program_in_path("setpriv") != "":
        script = "exec setpriv --pdeathsig INT \"$@\" 2>\"$0\""
    end
    argv = ["sh", "-c", script, rec["err"]]
    argv.extend(cmd)
    pid = glib.spawn_watched_data(argv, on_rec_exit, S["token"])
    if pid == 0:
        call notify(T("Screen recording is not available: ffmpeg was not found."))
        return False
    end
    rec["pid"] = pid
    rec["running"] = True
    rec["started"] = glib.monotonic_time()
    call glib.timeout_add_data(250, rec_poll, S["token"])
    return True
end

function rec_poll(token):
    rec = S["rec"]
    if not is_live_token(token) or rec == None or not rec["running"]:
        return False
    end
    secs = (glib.monotonic_time() - rec["started"]) // 1000000
    call gtk.label_set_text(W["pill_label"], String(secs // 60) + ":" + text.pad(secs % 60, 2))
    return True
end

function rec_stop():
    rec = S["rec"]
    if rec == None or not rec["running"] or rec["stopping"]:
        return 0
    end
    rec["stopping"] = True
    call glib.kill(rec["pid"], SIGINT)        # ffmpeg dopise mp4 a skonci
    call glib.timeout_add_data(15000, rec_kill, rec)
    return 0
end

function rec_kill(rec):
    if rec["running"]:
        call glib.kill(rec["pid"], SIGKILL)
    end
    return False
end

function on_pill_stop(bound, button):
    call rec_stop()
    return 0
end

function on_rec_exit(token, pid, status):
    rec = S["rec"]
    if rec == None or rec["pid"] != pid:
        return 0
    end
    rec["running"] = False
    st = glib.stat(rec["part"])
    ok = len(st) > 0 and st[0] > 0
    if ok:
        ok = luxos_sys.rename(rec["part"], rec["final"])
    end
    if not ok:
        lines = text.lines(glib.read_text(rec["err"]).strip())
        msg = ""
        if len(lines) > 0:
            msg = " " + lines[-1]
        end
        call notify(T("The screen recording failed.") + msg)
        call luxos_sys.unlink(rec["part"])
    end
    call luxos_sys.unlink(rec["err"])
    if not is_live_token(token):
        return 0
    end
    path = ""
    if ok:
        path = rec["final"]
    end
    call rec_done(path)
    return 0
end

function rec_done(path):
    call gtk.widget_hide(W["pill"])
    S["rec"] = None
    S["state"] = "idle"
    if path == "":
        call end_session(0)
        return 0
    end
    call emit_path(path)
    if S["args"]["no_thumb"]:
        call done()
        return 0
    end
    # Prvni snimek videa jako nahled
    S["seq"] = S["seq"] + 1
    tmp = base.runtime_dir() + "/.luxos-screenshot-frame-" + String(glib.getpid()) + "-" + String(S["seq"]) + ".png"
    pid = glib.spawn_watched_data(["ffmpeg", "-v", "error", "-y", "-i", path, "-frames:v", "1", "-vf", "scale=440:-2", tmp], on_frame_done, [S["token"], path, tmp])
    if pid == 0:
        call done()
    end
    return 0
end

function on_frame_done(job, pid, status):
    pb = 0
    if exists(job[2]):
        pb = gtk.pixbuf_new_from_file(job[2])
        call luxos_sys.unlink(job[2])
    end
    if not is_live_token(job[0]):
        call gtk.object_unref(pb)
        return 0
    end
    call show_thumb(job[1], pb, False, True)
    return 0
end

# Plovouci tlacitko pri nahravani: cas a Zastavit; u vyrezu mimo nahravanou oblast
function pill_open(full, rect):
    call gtk.label_set_text(W["pill_label"], "0:00")
    g = gtk.monitor_at_pointer()
    size = preferred_size(W["pill"])
    w = size[0]
    h = size[1]
    x = g[0] + (g[2] - w) // 2
    y = g[1] + 40          # pod horni listou
    if not full:
        if rect[1] < y + h + 8 and y < rect[1] + rect[3]:
            if rect[1] + rect[3] + 10 + h < g[1] + g[3]:
                y = rect[1] + rect[3] + 10
            else:
                y = max(g[1], rect[1] - h - 10)
            end
            x = min(max(g[0], rect[0] + (rect[2] - w) // 2), g[0] + g[2] - w)
        end
    end
    call gtk.window_move(W["pill"], x, y)
    call gtk.widget_show(W["pill"])
    call restack()
    call watch_update()
    return 0
end

# ---- relace ---------------------------------------------------------------------------------------------------

function emit_path(path):
    call sink_send(S["sink"], "out " + path + "\n")
    return 0
end

function sink_send(sink, line):
    if sink == None:
        if line.startswith("out "):
            call luxos_sys.out(line[4:])
        elif line.startswith("err "):
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

function end_session(code):
    if not S["active"]:
        return 0
    end
    sink = S["sink"]
    S["active"] = False
    S["sink"] = None
    S["state"] = ""
    S["busy"] = False
    S["token"] = S["token"] + 1
    call close_dialog()
    if S["built"]:
        if S["menu"] != 0:
            call gtk.menu_popdown(S["menu"])
            S["menu"] = 0
        end
        call hide_toolbar()
        call ov_close()
        call gtk.widget_hide(W["countdown"])
        call gtk.widget_hide(W["pill"])
    end
    call thumb_close()
    call gtk.seat_ungrab()
    call unfreeze()
    call keys_update()
    call sink_finish(sink, code)
    if S["standalone"]:
        call glib.idle_add_data(standalone_check, 0)
    end
    return 0
end

# Samostatny proces skonci, jakmile nic nedela (obrazek ve schrance bez xclipu drzi, dokud ho nekdo neprevezme)
function standalone_check(bound):
    if S["active"] or S.get("resident", False):
        return False
    end
    if S["holding_clip"] and own_clipboard():
        if not S["clip_watch"]:
            S["clip_watch"] = True
            call glib.timeout_add_data(1500, clip_watch_start, 0)
        end
        return False
    end
    call gtk.main_quit()
    return False
end

function clip_watch_start(bound):
    call gtk.connect_data(gtk.clipboard_object(), "owner-change", 1, on_clip_owner_change, 0)
    call standalone_check(0)
    return False
end

function on_clip_owner_change(bound, event, clip):
    if not own_clipboard():
        S["holding_clip"] = False
        call standalone_check(0)
    end
    return 0
end

function cancel():
    if S["rec"] != None and S["rec"]["running"]:
        call rec_stop()
        return 0
    end
    call end_session(0)
    return 0
end

# Start podle prepinacu
function run_session(a):
    S["active"] = True
    S["token"] = S["token"] + 1
    S["args"] = a
    S["opts"] = base.load_options(base.options_path())
    call shortcuts_refresh()
    S["scale"] = gtk.root_scale()
    S["busy"] = False
    S["to_clip"] = False
    S["toolbar_session"] = False
    S["mode"] = S["opts"]["mode"]
    TB["hovered"] = ""
    TB["ctrl"] = False
    TB["caption"] = []
    OV["quick"] = False
    OV["sel"] = None
    S["state"] = "toolbar"
    action = a["action"]
    if action == "toolbar":
        S["toolbar_session"] = True
        mode = S["mode"]
        if mode not in base.MODES:
            mode = "portion"
        end
        call set_mode(mode, True)
    elif action == "screen" or action == "rec_screen" or a["region"] != None:
        rect = a["region"]
        if rect == None:
            rect = screen_rect()
        end
        if action.startswith("rec_"):
            call glib.idle_add_data(start_recording_job, [S["token"], rect])
        else:
            call glib.idle_add_data(capture_rect_job, [S["token"], rect])
        end
    else:           # --portion, --window, --record-portion: vyber mysi bez listy
        S["mode"] = action
        call freeze()
        call show_overlay(action, True)
    end
    return 0
end

function start_recording_job(job):
    if is_live_token(job[0]):
        call start_recording(job[1])
    end
    return False
end

function capture_rect_job(job):
    if is_live_token(job[0]):
        call capture_rect(job[1], True)
    end
    return False
end

function set_mode(mode, initial):
    S["mode"] = mode
    if S["opts"]["mode"] != mode:
        S["opts"]["mode"] = mode
        call save_options()
    end
    call tb_set_mode(mode)
    if mode == "screen" or mode == "rec_screen":
        call ov_close()
        call show_toolbar()
    elif OV["open"]:
        call ov_set_mode(mode)
        call show_toolbar()
    else:
        # S listou zivy prekryv bez zmrazeni: snimek se porizuje az pri Zachytit
        call show_overlay(mode, False)
    end
    return 0
end

function show_overlay(mode, quick):
    live = not quick and S["toolbar_session"] and S["composited"]
    if not live and S["surface"] == 0:
        call freeze()
    end
    if not live and S["surface"] == 0:
        call notify(T("The screenshot could not be taken."))
        call cancel()
        return 0
    end
    sel = None
    if not quick and S["opts"]["remember"] and S["opts"]["selection"] != None:
        size = gtk.root_size()
        sel = base.clamp_rect(S["opts"]["selection"], size[0], size[1])
    end
    call ov_open(mode, sel, quick, live)
    call restack()
    if S["toolbar_session"]:
        call show_toolbar()
    else:
        call keys_update()
        call grab_keyboard()
    end
    return 0
end

# Pozadavek klienta (nebo prepinace samostatneho procesu, sink None): jako dalsi spusteni v Pythonu -
# pri nahravani ho zastavi, otevrenou listu zavre (stejna zkratka) nebo nahradi, nahled predchoziho zavre
function handle_request(argv, sink):
    a = base.parse_args(argv, "/")
    if "error" in a:
        call sink_send(sink, "err " + a["error"] + "\n")
        call sink_finish(sink, 1)
        return 0
    end
    call ensure_built()
    if a["close"]:
        if S["active"] and S["state"] != "recording":
            call end_session(0)
        end
        call sink_finish(sink, 0)
        return 0
    end
    if a["stop"]:
        if S["state"] == "recording":
            call rec_stop()
        end
        call sink_finish(sink, 0)
        return 0
    end
    if S["active"]:
        if S["state"] == "recording":       # dalsi spusteni nahravani zastavi (jako v macOS)
            call rec_stop()
            call sink_finish(sink, 0)
            return 0
        end
        if S["state"] == "toolbar":
            call cancel()
            if a["action"] == "toolbar":     # znovu stejna zkratka listu zavre
                call sink_finish(sink, 0)
                return 0
            end
        else:                                 # nahled predchoziho snimku nesmi byt v novem
            call thumb_finish()
            call end_session(0)
        end
    end
    S["sink"] = sink
    call run_session(a)
    return 0
end

function exit_code():
    return S["exit_code"]
end

# ---- server (socket) -----------------------------------------------------------------------------------------

function start_server(standalone):
    S["standalone"] = standalone
    fd = luxos_sys.unix_listen(base.socket_name())
    if fd >= 0:
        S["listening"] = True
        call glib.fd_add_data(fd, 1, on_listen, fd)
        return True
    end
    if not standalone:
        # jmeno drzi samostatny proces (hub se restartoval behem nahravani): zkusit pozdeji
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
        if len(state["buf"]) > 65536:
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
        # potvrzeni az pred akci: kdyz klient mezitim odesel (vyprsel mu cas), pozadavek se zahodi
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
