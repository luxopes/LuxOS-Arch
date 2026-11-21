# LuxOS - Zpetna vazba: hlaseni chyb a napadu primo autorovi LuxOS (drive Python).
#
#   luxos-feedback               okno (chyba / napad / neco jineho)
#   luxos-feedback --send-outbox odesle ulozena hlaseni bez okna (napr. po pripojeni), vypise pocet
#
# Odeslani, systemove udaje a fronta: luxos_feedback.lsl. Okno je nespousti samo (sit a journalctl by ho
# zdrzely), ale jako vlastni podproces: --collect (systemove udaje jako JSON), --send SOUBOR (hlaseni ze
# souboru 0600, ktery se hned smaze; vysledek jako JSON). Text hlaseni tak neni v argumentech procesu.
# Testy: LUXAI_ORIGIN (mistni falesny server), LUXOS_TEST_CONTROL=1 (luxos_testctl).
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_regex as re
load luxos_settings_ui as ui
load luxos_testctl as testctl
load luxos_feedback as fb

CSS = ".page-title { font-size: 20px; font-weight: 800; }\n.dim { opacity: 0.65; }\n.kind { border-radius: 14px; padding: 12px 8px; background-image: none; box-shadow: none;\n        border: 2px solid alpha(currentColor, 0.10); background-color: alpha(currentColor, 0.04); }\n.kind:hover { background-color: alpha(currentColor, 0.08); }\n.kind:checked { border-color: #3d7bff; background-color: alpha(#3d7bff, 0.14); color: inherit; }\n.kind:checked image { color: #3d7bff; }\n.kind-title { font-weight: 700; }\n.kind-sub { font-size: 11px; opacity: 0.65; }\n.editor, .editor > border { border-radius: 12px; border: 1px solid alpha(currentColor, 0.15); }\n.editor scrolledwindow, .editor textview, .editor text { border-radius: 12px; }\n.editor textview, .editor text { background-color: transparent; }\n.placeholder { opacity: 0.45; }\n.shot { border-radius: 8px; border: 1px solid alpha(currentColor, 0.15); }\n.sysinfo, .sysinfo text { font-family: monospace; font-size: 10px; background-color: alpha(currentColor, 0.04); }\n.primary { border-radius: 999px; padding: 6px 22px; font-weight: 700; background-image: none;\n           background-color: #2563eb; color: white; border: none; box-shadow: none; text-shadow: none; }\n.primary:hover { background-color: #1d4fd8; }\n.primary:disabled { background-color: alpha(@theme_fg_color, 0.10); color: alpha(@theme_fg_color, 0.6); }\n.primary:disabled label { color: alpha(@theme_fg_color, 0.6); }\n.group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.row { padding: 10px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.65; }\n.error { color: #ff453a; }\n.ok-icon { color: #30d158; }\n.done-title { font-size: 22px; font-weight: 800; }\n.info { border-radius: 10px; padding: 8px 12px; background-color: alpha(#30d158, 0.15); }\nentry { border-radius: 10px; padding: 6px 10px; min-height: 30px; }\n"

ui_ = {"window": 0, "kind": "bug", "shot": "", "system": None, "kind_buttons": {}, "busy": False}

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

function self_exe():
    path = glib.readlink("/proc/self/exe")
    if path == None or path == "" or path.endswith(" (deleted)"):
        return "luxos-feedback"
    end
    return path
end

# ---- widgety, ktere modul gtk nema ---------------------------------------------------------------------------

function text_view_new(wrap, left, right, top, bottom):
    unsafe:
        view = __lsl_qbe_call0(__lsl_symbol("gtk_text_view_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_wrap_mode"), view, ptr(wrap))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_left_margin"), view, ptr(left))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_right_margin"), view, ptr(right))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_top_margin"), view, ptr(top))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_bottom_margin"), view, ptr(bottom))
        return view
    end
end

function text_view_set(view, name, value):
    unsafe:
        if name == "accepts_tab":
            call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_accepts_tab"), ptr(view), 1 if value else 0)
        elif name == "editable":
            call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_editable"), ptr(view), 1 if value else 0)
        elif name == "cursor_visible":
            call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_cursor_visible"), ptr(view), 1 if value else 0)
        end
    end
end

function buffer_of(view):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_text_view_get_buffer"), ptr(view))
    end
end

function buffer_set_text(buffer, text):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_set_text"), ptr(buffer), cstr(text), -1)
    end
end

function buffer_get_text(buffer):
    unsafe:
        iters = __lsl_byte_zeros(256)
        base = __lsl_qbe_load64(__lsl_address(iters) + 24)
        call __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_get_bounds"), ptr(buffer), base, base + 128)
        return glib.take_c(__lsl_qbe_call4(__lsl_symbol("gtk_text_buffer_get_text"), ptr(buffer), base, base + 128, 0))
    end
end

function buffer_char_count(buffer):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_text_buffer_get_char_count"), ptr(buffer)))
    end
end

# Prepinac karty (RadioButton bez kolecka, jako Gtk.RadioButton(draw_indicator=False))
function radio_new(group):
    unsafe:
        b = __lsl_qbe_call1(__lsl_symbol("gtk_radio_button_new_from_widget"), ptr(group))
        call __lsl_qbe_call2(__lsl_symbol("gtk_toggle_button_set_mode"), b, 0)
        return b
    end
end

function expander_new(text):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_expander_new"), cstr(text))
    end
end

# JPEG do pameti jako base64 ("" pri chybe)
function jpeg_base64(pixbuf, quality):
    unsafe:
        cells = __lsl_byte_zeros(24)
        base = __lsl_qbe_load64(__lsl_address(cells) + 24)
        keys = glib.cstr_array(["quality"])
        values = glib.cstr_array([quality])
        ok = __lsl_qbe_call7(__lsl_symbol("gdk_pixbuf_save_to_bufferv"), ptr(pixbuf), base, base + 8, cstr("jpeg"), glib.array_data(keys), glib.array_data(values), base + 16)
        if ok == 0:
            error = __lsl_qbe_load64(base + 16)
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return ""
        end
        raw = __lsl_qbe_load64(base)
        text = glib.take_c(__lsl_qbe_call2(__lsl_symbol("g_base64_encode"), raw, __lsl_qbe_load64(base + 8)))
        call __lsl_qbe_call1(__lsl_symbol("g_free"), raw)
        return text
    end
end

function pixbuf_size(pixbuf):
    unsafe:
        return [__lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_width"), ptr(pixbuf))), __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_height"), ptr(pixbuf)))]
    end
end

# ---- formular --------------------------------------------------------------------------------------------------

function label(text, css, xalign):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, xalign)
    call gtk.label_set_line_wrap(l, True)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function option_row(title, hint, widget, first):
    row = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(row, "row")
    if not first:
        call gtk.widget_add_class(row, "row-sep")
    end
    texts = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(texts, label(title, "", 0.0), False, False, 0)
    if hint != "":
        call gtk.box_pack_start(texts, label(hint, "hint", 0.0), False, False, 0)
    end
    call gtk.box_pack_start(row, texts, True, True, 0)
    call gtk.box_pack_end(row, widget, False, False, 0)
    return row
end

function build():
    # vejde se na 1366x768 (drive 720 + HeaderBar = 765 px, tlacitko Odeslat pod okrajem obrazovky)
    window = ui.window(i18n.T("Feedback"), "luxos-feedback", 580, 720, 480, 460)
    ui_["window"] = window
    stack = gtk.stack_new(True)
    ui_["stack"] = stack
    call gtk.container_add(window, stack)

    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    box = gtk.box_new(gtk.VERTICAL, 12)
    call gtk.widget_set_margin(box, 22)
    call gtk.container_add(scroll, box)
    form = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.box_pack_start(form, scroll, True, True, 0)

    ui_["info"] = label("", "info", 0.0)
    call gtk.widget_set_name(ui_["info"], "info")
    call gtk.widget_set_no_show_all(ui_["info"], True)
    call gtk.box_pack_start(box, ui_["info"], False, False, 0)
    call gtk.box_pack_start(box, label(i18n.T("Help us improve LuxOS"), "page-title", 0.0), False, False, 0)
    call gtk.box_pack_start(box, label(i18n.T("Your report goes directly to the author of LuxOS."), "dim", 0.0), False, False, 0)

    cards = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.box_set_homogeneous(cards, True)
    call gtk.widget_set_margins(cards, 0, 0, 6, 0)
    group = 0
    for kind in fb.KINDS:
        b = radio_new(group)
        if group == 0:
            group = b
        end
        call gtk.widget_add_class(b, "kind")
        call gtk.widget_set_name(b, "kind-" + kind[0])
        inner = gtk.box_new(gtk.VERTICAL, 4)
        image = gtk.image_new_from_icon_name(kind[3], 4)
        call gtk.image_set_pixel_size(image, 26)
        call gtk.box_pack_start(inner, image, False, False, 2)
        for pair in [[kind[1], "kind-title"], [kind[2], "kind-sub"]]:
            l = label(i18n.T(pair[0]), pair[1], 0.5)
            call gtk.label_set_justify(l, gtk.JUSTIFY_CENTER)
            call gtk.box_pack_start(inner, l, False, False, 0)
        end
        call gtk.container_add(b, inner)
        call gtk.connect_data(b, "toggled", 0, on_kind, kind[0])
        ui_["kind_buttons"][kind[0]] = b
        call gtk.box_pack_start(cards, b, True, True, 0)
    end
    call gtk.box_pack_start(box, cards, False, False, 0)

    # Text s napovedou (GTK3 TextView nema placeholder - prekryvny popisek); GTK_WRAP_WORD_CHAR 3
    text = text_view_new(3, 10, 10, 8, 8)
    call text_view_set(text, "accepts_tab", False)
    ui_["text"] = text
    call gtk.connect_data(buffer_of(text), "changed", 0, on_changed, 0)
    tscroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(tscroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.scrolled_window_set_min_content_height(tscroll, 170)
    call gtk.container_add(tscroll, text)
    ui_["placeholder"] = label("", "placeholder", 0.0)
    call gtk.widget_set_name(ui_["placeholder"], "placeholder")
    call gtk.widget_set_valign(ui_["placeholder"], gtk.ALIGN_START)
    call gtk.widget_set_margins(ui_["placeholder"], 12, 12, 8, 0)
    overlay = gtk.overlay_new()
    call gtk.container_add(overlay, tscroll)
    call gtk.overlay_add_overlay(overlay, ui_["placeholder"])
    call gtk.overlay_set_pass_through(overlay, ui_["placeholder"])
    frame = gtk.frame_new("")
    call gtk.widget_add_class(frame, "editor")
    call gtk.container_add(frame, overlay)
    call gtk.box_pack_start(box, frame, False, False, 0)
    ui_["counter"] = label("", "dim", 1.0)
    call gtk.widget_set_name(ui_["counter"], "counter")
    call gtk.box_pack_start(box, ui_["counter"], False, False, 0)

    call gtk.box_pack_start(box, label(i18n.T("Your e-mail (optional, if you would like a reply)"), "dim", 0.0), False, False, 0)
    contact = gtk.entry_new()
    ui_["contact"] = contact
    call gtk.entry_set_placeholder_text(contact, "name@example.com")
    # GTK_INPUT_PURPOSE_EMAIL
    call gtk.object_set_int(contact, "input-purpose", 6)
    call gtk.entry_set_text(contact, fb.account_email())
    call gtk.connect_data(contact, "changed", 0, on_changed, 0)
    call gtk.box_pack_start(box, contact, False, False, 0)

    # Prilohy: radky s prepinaci jako v ostatnich oknech Nastaveni
    opts = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(opts, 0, 0, 4, 0)
    call gtk.widget_add_class(opts, "group")
    call gtk.box_pack_start(box, opts, False, False, 0)

    # Snimek obrazovky
    ui_["shot_check"] = gtk.switch_new()
    call gtk.widget_set_valign(ui_["shot_check"], gtk.ALIGN_CENTER)
    call gtk.connect_data(ui_["shot_check"], "notify::active", 1, on_shot_toggled, 0)
    call gtk.box_pack_start(opts, option_row(i18n.T("Attach a screenshot"), "", ui_["shot_check"], True), False, False, 0)
    shot_row = gtk.box_new(gtk.HORIZONTAL, 12)
    ui_["shot_row"] = shot_row
    call gtk.widget_set_margins(shot_row, 14, 14, 0, 10)
    ui_["shot_img"] = gtk.image_new()
    call gtk.widget_add_class(ui_["shot_img"], "shot")
    retake = gtk.button_new(i18n.T("Take Again"))
    call gtk.widget_set_valign(retake, gtk.ALIGN_CENTER)
    call gtk.connect_data(retake, "clicked", 0, on_retake, 0)
    call gtk.box_pack_start(shot_row, ui_["shot_img"], False, False, 0)
    call gtk.box_pack_start(shot_row, retake, False, False, 0)
    call gtk.widget_set_no_show_all(shot_row, True)
    call gtk.box_pack_start(opts, shot_row, False, False, 0)

    # Systemove udaje
    ui_["sys_check"] = gtk.switch_new()
    call gtk.switch_set_active(ui_["sys_check"], True)
    call gtk.widget_set_valign(ui_["sys_check"], gtk.ALIGN_CENTER)
    call gtk.box_pack_start(opts, option_row(i18n.T("Attach system information"), i18n.T("LuxOS and hardware versions and recent error messages. No personal files, passwords or e-mail addresses."), ui_["sys_check"], False), False, False, 0)
    exp = expander_new(i18n.T("Show what will be sent"))
    ui_["expander"] = exp
    call gtk.widget_set_margins(exp, 14, 14, 0, 10)
    view = text_view_new(1, 8, 0, 6, 6)
    call text_view_set(view, "editable", False)
    call text_view_set(view, "cursor_visible", False)
    call gtk.widget_add_class(view, "sysinfo")
    ui_["sys_view"] = view
    call buffer_set_text(buffer_of(view), i18n.T("Collecting…"))
    sscroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_min_content_height(sscroll, 200)
    call gtk.widget_set_margins(sscroll, 0, 0, 6, 0)
    call gtk.container_add(sscroll, view)
    call gtk.container_add(exp, sscroll)
    call gtk.box_pack_start(opts, exp, False, False, 0)

    # Spodni lista
    bar = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_set_margins(bar, 14, 14, 8, 14)
    ui_["status"] = label("", "error", 0.0)
    call gtk.widget_set_name(ui_["status"], "status")
    call gtk.label_set_max_width_chars(ui_["status"], 36)
    ui_["spinner"] = gtk.spinner_new()
    ui_["send_btn"] = gtk.button_new(i18n.T("Send"))
    call gtk.widget_set_name(ui_["send_btn"], "send")
    call gtk.widget_add_class(ui_["send_btn"], "primary")
    call gtk.connect_data(ui_["send_btn"], "clicked", 0, on_send, 0)
    cancel = gtk.button_new(i18n.T("Cancel"))
    call gtk.connect_data(cancel, "clicked", 0, on_close, 0)
    call gtk.box_pack_start(bar, ui_["status"], True, True, 0)
    call gtk.box_pack_end(bar, ui_["send_btn"], False, False, 0)
    call gtk.box_pack_end(bar, cancel, False, False, 0)
    call gtk.box_pack_end(bar, ui_["spinner"], False, False, 0)
    call gtk.box_pack_start(form, gtk.separator_new(gtk.HORIZONTAL), False, False, 0)
    call gtk.box_pack_start(form, bar, False, False, 0)
    call gtk.stack_add_named(stack, form, "form")
    call build_done()
    call kind_changed("bug")
    call gtk.connect_data(window, "destroy", 0, on_destroy, 0)
end

function build_done():
    box = gtk.box_new(gtk.VERTICAL, 12)
    call gtk.widget_set_margin(box, 40)
    call gtk.widget_set_valign(box, gtk.ALIGN_CENTER)
    ui_["done_icon"] = gtk.image_new_from_icon_name("emblem-ok-symbolic", 6)
    call gtk.image_set_pixel_size(ui_["done_icon"], 72)
    call gtk.widget_add_class(ui_["done_icon"], "ok-icon")
    call gtk.box_pack_start(box, ui_["done_icon"], False, False, 0)
    ui_["done_title"] = label("", "done-title", 0.5)
    call gtk.widget_set_name(ui_["done_title"], "done-title")
    ui_["done_text"] = label("", "dim", 0.5)
    call gtk.widget_set_name(ui_["done_text"], "done-text")
    call gtk.label_set_justify(ui_["done_text"], gtk.JUSTIFY_CENTER)
    ui_["done_id"] = label("", "dim", 0.5)
    call gtk.widget_set_name(ui_["done_id"], "done-id")
    call gtk.label_set_selectable(ui_["done_id"], True)
    call gtk.widget_set_no_show_all(ui_["done_id"], True)
    for key in ["done_title", "done_text", "done_id"]:
        call gtk.box_pack_start(box, ui_[key], False, False, 0)
    end
    row = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_set_halign(row, gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(row, 0, 0, 12, 0)
    another = gtk.button_new(i18n.T("Send Another"))
    call gtk.connect_data(another, "clicked", 0, on_reset, 0)
    close = gtk.button_new(i18n.T("Close"))
    call gtk.widget_add_class(close, "primary")
    call gtk.connect_data(close, "clicked", 0, on_close, 0)
    call gtk.box_pack_start(row, another, False, False, 0)
    call gtk.box_pack_start(row, close, False, False, 0)
    call gtk.box_pack_start(box, row, False, False, 0)
    ui_["done_box"] = box
    call gtk.stack_add_named(ui_["stack"], box, "done")
end

function kind_changed(key):
    ui_["kind"] = key
    for kind in fb.KINDS:
        if kind[0] == key:
            call gtk.label_set_text(ui_["placeholder"], i18n.T(kind[4]))
        end
    end
    call validate()
end

function on_kind(key, button):
    if gtk.toggle_button_get_active(button):
        call kind_changed(key)
    end
    return 0
end

function message():
    return buffer_get_text(buffer_of(ui_["text"])).strip()
end

function contact_text():
    return gtk.entry_get_text(ui_["contact"]).strip()
end

function validate():
    n = len(message())
    call gtk.widget_set_visible(ui_["placeholder"], buffer_char_count(buffer_of(ui_["text"])) == 0)
    if n < fb.MIN_LEN:
        call gtk.label_set_text(ui_["counter"], i18n.TF("At least %d characters", [fb.MIN_LEN]))
    else:
        call gtk.label_set_text(ui_["counter"], String(n) + " / " + String(fb.MAX_LEN))
    end
    contact = contact_text()
    ok_contact = contact == "" or re.search("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", contact, False) != None
    call gtk.widget_set_sensitive(ui_["send_btn"], n >= fb.MIN_LEN and n <= fb.MAX_LEN and ok_contact and not ui_["busy"])
end

function on_changed(unused, widget):
    call validate()
    return 0
end

# ---- snimek obrazovky (po skryti okna) ---------------------------------------------------------------------------

function on_shot_toggled(unused, pspec, check):
    if gtk.switch_get_active(check):
        call take_screenshot()
    else:
        ui_["shot"] = ""
        call gtk.widget_hide(ui_["shot_row"])
    end
    return 0
end

function on_retake(unused, b):
    call take_screenshot()
    return 0
end

function take_screenshot():
    call gtk.widget_hide(ui_["window"])
    call glib.timeout_add_data(600, capture, 0)
end

function capture(unused):
    size = gtk.root_size()
    pb = 0
    if size[0] > 0 and size[1] > 0:
        pb = gtk.pixbuf_from_window(0, 0, size[0], size[1])
    end
    shot = ""
    thumb = 0
    if pb != 0:
        dims = pixbuf_size(pb)
        for step in [[fb.SHOT_WIDTH, "75"], [1024, "60"], [800, "50"]]:
            scale = min(1.0, Float(step[0]) / Float(dims[0]))
            small = gtk.pixbuf_scale(pb, max(1, Int(dims[0] * scale)), max(1, Int(dims[1] * scale)))
            shot = jpeg_base64(small, step[1])
            call gtk.object_unref(small)
            if shot != "" and len(shot) < fb.SHOT_MAX:
                break
            end
        end
        if shot != "":
            thumb = gtk.pixbuf_scale(pb, 200, max(1, Int(200.0 * dims[1] / dims[0])))
        end
        call gtk.object_unref(pb)
    end
    ui_["shot"] = shot
    call gtk.widget_show(ui_["window"])
    call gtk.window_present(ui_["window"])
    if shot != "":
        call gtk.image_set_from_pixbuf(ui_["shot_img"], thumb)
        call gtk.object_unref(thumb)
        call gtk.widget_set_no_show_all(ui_["shot_row"], False)
        call gtk.widget_show_all(ui_["shot_row"])
    else:
        call gtk.switch_set_active(ui_["shot_check"], False)
        call gtk.label_set_text(ui_["status"], i18n.T("The screenshot could not be taken."))
    end
    return False
end

# ---- systemove udaje a fronta (podprocesy) ----------------------------------------------------------------------

function on_collected(unused, output, status):
    info = None
    safe:
        info = json.decode(output)
    end
    if info != None and type(info) == "Dictionary":
        ui_["system"] = info
        call buffer_set_text(buffer_of(ui_["sys_view"]), fb.pretty(info))
    end
    return 0
end

function on_flushed(unused, output, status):
    n = 0
    safe:
        n = Int(output.strip())
    end
    if n > 0:
        call gtk.label_set_text(ui_["info"], i18n.TF("%d saved report(s) from earlier have been sent. Thank you!", [n]))
        call gtk.widget_show(ui_["info"])
    end
    return 0
end

# ---- odeslani ----------------------------------------------------------------------------------------------------

function payload():
    p = {"kind": ui_["kind"], "message": message(), "app": fb.APP}
    if contact_text() != "":
        p["contact"] = contact_text()
    end
    if gtk.switch_get_active(ui_["sys_check"]):
        # None: udaje jeste nejsou - doplni je podproces pred odeslanim
        p["system"] = ui_["system"]
    end
    if ui_["shot"] != "":
        p["screenshot"] = "data:image/jpeg;base64," + ui_["shot"]
    end
    return p
end

function on_send(unused, b):
    ui_["busy"] = True
    call gtk.spinner_set(ui_["spinner"], True)
    call gtk.widget_set_sensitive(ui_["send_btn"], False)
    call gtk.label_set_text(ui_["status"], i18n.T("Sending…"))
    call gtk.widget_remove_class(ui_["status"], "error")
    dir = glib.user_runtime_dir()
    path = dir + "/luxos-feedback-" + String(glib.getpid()) + "-" + fb.hex8() + ".json"
    if not fb.write_new(path, json.encode(payload())):
        call sent({"error": "network", "status": 0, "saved": False})
        return 0
    end
    call glib.spawn_capture([self_exe(), "--send", path], on_sent, 0)
    return 0
end

function on_sent(unused, output, status):
    result = None
    safe:
        result = json.decode(output)
    end
    if result == None or type(result) != "Dictionary":
        result = {"error": "network", "status": 0, "saved": False}
    end
    call sent(result)
    return 0
end

function human(code):
    if code in fb.ERRORS:
        return i18n.T(fb.ERRORS[code])
    end
    if code == "network":
        return i18n.T("LuxOS could not reach the server. Check the internet connection.")
    end
    return i18n.TF("Sending failed (%s).", [code])
end

function sent(result):
    ui_["busy"] = False
    call gtk.spinner_set(ui_["spinner"], False)
    error = result.get("error", "")
    saved = result.get("saved", False) == True
    if error != "" and not saved:
        call gtk.widget_add_class(ui_["status"], "error")
        call gtk.label_set_text(ui_["status"], human(error))
        call gtk.widget_set_tooltip(ui_["status"], human(error))
        call gtk.button_set_label(ui_["send_btn"], i18n.T("Try Again"))
        call validate()
        return 0
    end
    rid = result.get("id", "")
    call show_done(rid if type(rid) == "String" else "", saved)
end

function show_done(rid, saved):
    call gtk.image_set_from_icon_name(ui_["done_icon"], "mail-send-symbolic" if saved else "emblem-ok-symbolic", 6)
    call gtk.image_set_pixel_size(ui_["done_icon"], 72)
    if saved:
        call gtk.label_set_text(ui_["done_title"], i18n.T("Saved for later"))
        call gtk.label_set_text(ui_["done_text"], i18n.T("You are offline. The report will be sent automatically the next time you open Feedback with an internet connection."))
    else:
        call gtk.label_set_text(ui_["done_title"], i18n.T("Thank you for your feedback!"))
        call gtk.label_set_text(ui_["done_text"], i18n.T("Your report has been delivered to the author of LuxOS. Every report helps make LuxOS better."))
    end
    call gtk.label_set_text(ui_["done_id"], i18n.TF("Report ID: %s", [rid]))
    call gtk.widget_show_all(ui_["done_box"])
    call gtk.widget_set_visible(ui_["done_id"], rid != "")
    call gtk.stack_set_visible_child_name(ui_["stack"], "done")
end

function on_reset(unused, b):
    call buffer_set_text(buffer_of(ui_["text"]), "")
    call gtk.switch_set_active(ui_["shot_check"], False)
    call gtk.label_set_text(ui_["status"], "")
    call gtk.button_set_label(ui_["send_btn"], i18n.T("Send"))
    call gtk.stack_set_visible_child_name(ui_["stack"], "form")
    call validate()
    return 0
end

function on_close(unused, b):
    call gtk.window_close(ui_["window"])
    return 0
end

function on_destroy(unused, window):
    call gtk.main_quit()
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1) ------------------------------------------------------------------------------

function on_test(command, rest):
    if command == "state":
        print "state " + json.encode({"page": gtk.stack_get_visible_child_name(ui_["stack"]), "kind": ui_["kind"],
            "send": gtk.widget_get_sensitive(ui_["send_btn"]), "system": ui_["system"] != None,
            "shot": len(ui_["shot"]), "sys_text": buffer_get_text(buffer_of(ui_["sys_view"])),
            "busy": ui_["busy"]})
    elif command == "type":
        call buffer_set_text(buffer_of(ui_["text"]), rest.replace("\\n", "\n"))
    elif command == "kind":
        call gtk.toggle_button_set_active(ui_["kind_buttons"][rest], True)
    elif command == "sysinfo":
        call gtk.switch_set_active(ui_["sys_check"], rest == "1")
    elif command == "expand":
        unsafe:
            call __lsl_qbe_call2(__lsl_symbol("gtk_expander_set_expanded"), ptr(ui_["expander"]), 1)
        end
    elif command == "size":
        print "size " + json.encode(gtk.window_get_size(ui_["window"]))
    elif command == "close":
        call gtk.window_close(ui_["window"])
    end
end

# ---- start -------------------------------------------------------------------------------------------------------

function send_file(path):
    p = None
    safe:
        p = json.decode(readfile(path))
    end
    call glib.unlink(path)
    if p == None or type(p) != "Dictionary":
        return {"error": "network", "status": 0, "saved": False}
    end
    p["version"] = fb.app_version()
    if "system" in p and p["system"] == None:
        p["system"] = fb.collect_system(fb.context())
    end
    r = fb.send(p)
    r["saved"] = False
    if r.get("error", None) != None and (r["error"] == "network" or r["status"] >= 500):
        r["saved"] = fb.save_outbox(p) != ""
    end
    return r
end

first = ""
if len(args) > 1:
    first = args[1]
end
if first == "--send-outbox":
    print String(fb.flush_outbox())
elif first == "--collect":
    print json.encode(fb.collect_system(fb.context()))
elif first == "--send" and len(args) > 2:
    print json.encode(send_file(args[2]))
else:
    call glib.set_prgname("luxos-feedback")
    call gtk.init()
    call gtk.css_load(CSS)
    call build()
    call gtk.widget_show_all(ui_["window"])
    call validate()
    call glib.spawn_capture([self_exe(), "--collect"], on_collected, 0)
    call glib.spawn_capture([self_exe(), "--send-outbox"], on_flushed, 0)
    call testctl.start(on_test)
    call gtk.main()
end
