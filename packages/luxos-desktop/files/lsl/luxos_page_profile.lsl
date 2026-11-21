# LuxOS - Nastaveni > Profilova fotka (drive luxos-profile-picture): fotka uctu z obrazku nebo z kamery, orez do kruhu.
#
#   luxos-profile-picture            stranka s aktualni fotkou (Vybrat fotku, Vyfotit, Odebrat)
#   luxos-profile-picture SOUBOR     rovnou orez obrazku
#   luxos-profile-picture --camera   rovnou kamera
#
# Fotka se ukaze na prihlasovaci a zamykaci obrazovce, v nabidce LuxOS a v Ovladacim centru (ulozeni:
# luxos_avatar - ~/.face a AccountsService). Kamera jako aplikace Kamera (luxos_camera: v4l2src, MJPEG ->
# jpegdec, zrcadleny nahled; snimky vyzvedava casovac hlavni smycky a kresli cairo). Kamera bezi jen na strance:
# odchod ze stranky i zavreni okna ji zastavi.
load cairo, math, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_avatar as avatar
load luxos_camera as camera
load luxos_testctl as testctl
load luxos_settings_ui as ui

VIEW = 280            # prumer kruhu orezu a nahledu kamery (px)
CSS = ".profile-page .name { font-size: 20px; font-weight: 800; }\n.profile-page .dim { opacity: 0.65; }\n.profile-page .error { color: #ff453a; }\n.profile-page .pill { border-radius: 999px; padding: 6px 16px; }\n.profile-page .suggested-action { border-radius: 999px; padding: 6px 18px; font-weight: 700; }\n.profile-page .shutter, .profile-page .shutter:hover, .profile-page .shutter:active, .profile-page .shutter:disabled {\n    background-image: none; background-color: transparent; border: none; box-shadow: none;\n    padding: 0; min-width: 0; min-height: 0; }\n.profile-page .stage { background-color: #141418; }\n.profile-page .flash { background-color: white; }\n"

V = {"window": 0, "stack": 0, "current": 0, "camera_on": False, "poll": 0, "flash_start": 0, "active": False}
crop = {"pix": 0, "zoom": 1.0, "ox": 0.0, "oy": 0.0, "drag": None}

# ---- kresleni ------------------------------------------------------------------------------------------------

# Nahradni avatar: modrofialovy prechod s pocatecnim pismenem (jako prihlasovaci obrazovka)
function circle_initials(cr, cx, cy, d, letter):
    g = cairo.pattern_create_linear(cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2)
    call cairo.pattern_add_color_stop_rgba(g, 0.0, 0.30, 0.52, 1.0, 1.0)
    call cairo.pattern_add_color_stop_rgba(g, 1.0, 0.66, 0.42, 0.98, 1.0)
    call cairo.arc(cr, cx, cy, d / 2, 0.0, 2 * math.PI)
    call cairo.set_source(cr, g)
    call cairo.fill(cr)
    call cairo.pattern_destroy(g)
    call cairo.select_font_face(cr, "Inter", 0, 1)
    call cairo.set_font_size(cr, d * 0.42)
    ext = cairo.text_extents(cr, letter)
    call cairo.move_to(cr, cx - ext[2] / 2 - ext[0], cy - ext[3] / 2 - ext[1])
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.97)
    call cairo.show_text(cr, letter)
end

function circle_pixbuf(cr, cx, cy, d, pb):
    pw = avatar.width(pb)
    ph = avatar.height(pb)
    call cairo.save(cr)
    call cairo.arc(cr, cx, cy, d / 2, 0.0, 2 * math.PI)
    call cairo.clip(cr)
    s = d / min(pw, ph)
    call cairo.translate(cr, cx, cy)
    call cairo.scale(cr, s, s)
    call gtk.cairo_set_source_pixbuf(cr, pb, -pw / 2.0, -ph / 2.0)
    # CAIRO_FILTER_GOOD
    call gtk.cairo_source_filter(cr, 1)
    call cairo.paint(cr)
    call cairo.restore(cr)
end

# Ztmaveni mimo kruh a tenky bily okraj kruhu
function dim_outside(cr, w, h, cx, cy, d):
    # CAIRO_FILL_RULE_EVEN_ODD, pak WINDING
    call gtk.cairo_set_fill_rule(cr, 1)
    call cairo.rectangle(cr, 0.0, 0.0, w, h)
    call cairo.arc(cr, cx, cy, d / 2, 0.0, 2 * math.PI)
    call cairo.set_source_rgba(cr, 0.08, 0.08, 0.10, 0.62)
    call cairo.fill(cr)
    call gtk.cairo_set_fill_rule(cr, 0)
    call cairo.arc(cr, cx, cy, d / 2, 0.0, 2 * math.PI)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.85)
    call cairo.set_line_width(cr, 2.0)
    call cairo.stroke(cr)
end

function size_of(widget):
    return [Float(gtk.widget_get_allocated_width(widget)), Float(gtk.widget_get_allocated_height(widget))]
end

# ---- hlavni stranka ------------------------------------------------------------------------------------------

function label(text, css, chars):
    l = gtk.label_new(text)
    call gtk.widget_add_class(l, css)
    if chars > 0:
        call gtk.label_set_line_wrap(l, True)
        call gtk.label_set_justify(l, gtk.JUSTIFY_CENTER)
        call gtk.label_set_max_width_chars(l, chars)
    end
    return l
end

function button(text, css, handler):
    b = gtk.button_new(text)
    call gtk.widget_add_class(b, css)
    call gtk.connect_data(b, "clicked", 0, handler, 0)
    return b
end

function build_main():
    box = gtk.box_new(gtk.VERTICAL, 14)
    call gtk.widget_set_margins(box, 0, 0, 12, 0)
    V["avatar"] = gtk.drawing_area_new()
    call gtk.widget_set_size_request(V["avatar"], 168, 168)
    call gtk.widget_set_halign(V["avatar"], gtk.ALIGN_CENTER)
    call gtk.connect_data(V["avatar"], "draw", 1, draw_avatar, 0)
    call gtk.box_pack_start(box, V["avatar"], False, False, 0)
    call gtk.box_pack_start(box, label(avatar.real_name(), "name", 0), False, False, 0)
    call gtk.box_pack_start(box, label(i18n.T("Shown on the login and lock screen, in the LuxOS menu and in Control Center."), "dim", 44), False, False, 0)
    buttons = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_set_halign(buttons, gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(buttons, 0, 0, 8, 0)
    V["remove_btn"] = button(i18n.T("Remove Picture"), "pill", on_remove)
    call gtk.box_pack_start(buttons, button(i18n.T("Choose Photo…"), "suggested-action", on_choose), False, False, 0)
    call gtk.box_pack_start(buttons, button(i18n.T("Take Photo"), "pill", on_take), False, False, 0)
    call gtk.box_pack_start(buttons, V["remove_btn"], False, False, 0)
    call gtk.box_pack_start(box, buttons, False, False, 0)
    V["hint"] = label("", "hint", 44)
    call gtk.widget_set_name(V["hint"], "hint")
    call gtk.box_pack_start(box, V["hint"], False, False, 0)
    return box
end

function load_current():
    if V["current"] != 0:
        call avatar.unref(V["current"])
        V["current"] = 0
    end
    path = avatar.current()
    if path != "":
        V["current"] = gtk.pixbuf_new_from_file_at_scale(path, 336, 336, True)
    end
    call gtk.widget_set_visible(V["remove_btn"], V["current"] != 0)
    call gtk.widget_set_no_show_all(V["remove_btn"], True)
    call gtk.widget_queue_draw(V["avatar"])
end

function draw_avatar(unused, cr, widget):
    size = size_of(widget)
    d = min(size[0], size[1]) - 4
    if V["current"] != 0:
        call circle_pixbuf(cr, size[0] / 2, size[1] / 2, d, V["current"])
    else:
        call circle_initials(cr, size[0] / 2, size[1] / 2, d, avatar.initials(avatar.real_name()))
    end
    return False
end

function say(text, error):
    call gtk.label_set_text(V["hint"], text)
    call gtk.widget_set_class(V["hint"], "error", error)
end

function on_choose(unused, b):
    # GTK_FILE_CHOOSER_ACTION_OPEN
    dialog = gtk.file_chooser_native_new(i18n.T("Choose Photo"), V["window"], 0, i18n.T("Open"), i18n.T("Cancel"))
    call gtk.file_chooser_add_image_filter(dialog, i18n.T("Images"))
    # G_USER_DIRECTORY_PICTURES
    pictures = glib.user_special_dir(4)
    if pictures != "" and glib.is_dir(pictures):
        call gtk.file_chooser_set_folder(dialog, pictures)
    end
    if gtk.native_dialog_run(dialog) == -3:
        call open_file(gtk.file_chooser_get_filename(dialog))
    end
    call gtk.object_unref(dialog)
    return 0
end

function open_file(path):
    pix = avatar.load(path)
    if pix == 0:
        call gtk.stack_set_visible_child_name(V["stack"], "main")
        call say(i18n.T("This file is not a picture LuxOS can open."), True)
        return False
    end
    call show_crop(pix)
    return True
end

function on_remove(unused, b):
    error = avatar.remove()
    call load_current()
    if error != "":
        call say(i18n.TF("The picture could not be removed: %s", [error]), True)
    else:
        call say(i18n.T("Picture removed."), False)
    end
    return 0
end

# ---- orez: obrazek pod kruhem, tazenim posunout, kolečkem nebo posuvnikem zvetsit ------------------------------

function build_crop():
    box = gtk.box_new(gtk.VERTICAL, 0)
    view = gtk.drawing_area_new()
    V["crop"] = view
    call gtk.widget_set_size_request(view, VIEW + 60, VIEW + 60)
    call gtk.widget_add_class(view, "stage")
    call gtk.widget_add_events(view, gtk.BUTTON_PRESS_MASK | gtk.BUTTON_RELEASE_MASK | gtk.POINTER_MOTION_MASK | gtk.SCROLL_MASK | gtk.SMOOTH_SCROLL_MASK)
    call gtk.widget_set_can_focus(view, True)
    call gtk.connect_data(view, "draw", 1, draw_crop, 0)
    call gtk.connect_data(view, "button-press-event", 1, on_press, 0)
    call gtk.connect_data(view, "button-release-event", 1, on_release, 0)
    call gtk.connect_data(view, "motion-notify-event", 1, on_motion, 0)
    call gtk.connect_data(view, "scroll-event", 1, on_scroll, 0)
    call gtk.connect_data(view, "key-press-event", 1, on_crop_key, 0)
    call gtk.box_pack_start(box, view, True, True, 0)
    tip = label(i18n.T("Drag to move the photo, scroll to zoom."), "dim", 0)
    call gtk.widget_set_margins(tip, 0, 0, 10, 0)
    call gtk.box_pack_start(box, tip, False, False, 0)
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(row, 40, 40, 6, 0)
    call gtk.box_pack_start(row, gtk.image_new_from_icon_name("zoom-out-symbolic", 4), False, False, 0)
    V["zoom"] = gtk.scale_new_with_range(gtk.HORIZONTAL, 1.0, avatar.MAX_ZOOM, 0.01)
    call gtk.scale_set_draw_value(V["zoom"], False)
    call gtk.widget_set_tooltip(V["zoom"], i18n.T("Zoom"))
    call gtk.connect_data(V["zoom"], "value-changed", 0, on_zoom_changed, 0)
    call gtk.box_pack_start(row, V["zoom"], True, True, 0)
    call gtk.box_pack_start(row, gtk.image_new_from_icon_name("zoom-in-symbolic", 4), False, False, 0)
    call gtk.box_pack_start(box, row, False, False, 0)
    bar = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margin(bar, 14)
    call gtk.box_pack_start(bar, button(i18n.T("Cancel"), "pill", on_back), False, False, 0)
    V["save_btn"] = button(i18n.T("Save"), "suggested-action", on_save)
    call gtk.box_pack_end(bar, V["save_btn"], False, False, 0)
    call gtk.box_pack_start(box, bar, False, False, 0)
    return box
end

function clamp():
    if crop["pix"] != 0:
        off = avatar.clamp_offset(avatar.width(crop["pix"]), avatar.height(crop["pix"]), VIEW, crop["zoom"], crop["ox"], crop["oy"])
        crop["ox"] = off[0]
        crop["oy"] = off[1]
    end
end

function crop_zoom(z):
    crop["zoom"] = max(1.0, min(avatar.MAX_ZOOM, Float(z)))
    call clamp()
    call gtk.widget_queue_draw(V["crop"])
end

function set_zoom(z):
    call gtk.range_set_value(V["zoom"], max(1.0, min(avatar.MAX_ZOOM, Float(z))))
end

function on_zoom_changed(unused, scale):
    call crop_zoom(gtk.range_get_value(scale))
    return 0
end

function draw_crop(unused, cr, widget):
    size = size_of(widget)
    call cairo.set_source_rgb(cr, 0.08, 0.08, 0.10)
    call cairo.paint(cr)
    pix = crop["pix"]
    if pix == 0:
        return False
    end
    cx = size[0] / 2
    cy = size[1] / 2
    pw = avatar.width(pix)
    ph = avatar.height(pix)
    s = avatar.base_scale(pw, ph, VIEW) * crop["zoom"]
    call cairo.save(cr)
    call cairo.translate(cr, cx + crop["ox"], cy + crop["oy"])
    call cairo.scale(cr, s, s)
    call gtk.cairo_set_source_pixbuf(cr, pix, -pw / 2.0, -ph / 2.0)
    call gtk.cairo_source_filter(cr, 1)
    call cairo.paint(cr)
    call cairo.restore(cr)
    call dim_outside(cr, size[0], size[1], cx, cy, Float(VIEW))
    return False
end

function on_press(unused, event, widget):
    call gtk.widget_grab_focus(widget)
    if gtk.event_button(event) == 1:
        crop["drag"] = [gtk.event_x(event), gtk.event_y(event), crop["ox"], crop["oy"]]
    end
    return True
end

function on_release(unused, event, widget):
    crop["drag"] = None
    return True
end

function on_motion(unused, event, widget):
    if crop["drag"] != None and crop["pix"] != 0:
        d = crop["drag"]
        crop["ox"] = d[2] + gtk.event_x(event) - d[0]
        crop["oy"] = d[3] + gtk.event_y(event) - d[1]
        call clamp()
        call gtk.widget_queue_draw(widget)
    end
    return True
end

function on_scroll(unused, event, widget):
    direction = gtk.event_scroll_direction(event)
    dy = 0.0
    if direction == gtk.SCROLL_UP:
        dy = -1.0
    elif direction == gtk.SCROLL_DOWN:
        dy = 1.0
    elif direction == gtk.SCROLL_SMOOTH:
        dy = gtk.event_scroll_deltas(event)[1]
    end
    if dy != 0:
        call set_zoom(crop["zoom"] * (0.9 ^ dy))
    end
    return True
end

function crop_key(keyval):
    step = 10.0
    moves = {gtk.KEY_Left: [step, 0.0], gtk.KEY_Right: [-step, 0.0], gtk.KEY_Up: [0.0, step], gtk.KEY_Down: [0.0, -step]}
    if keyval in moves:
        crop["ox"] = crop["ox"] + moves[keyval][0]
        crop["oy"] = crop["oy"] + moves[keyval][1]
        call clamp()
        call gtk.widget_queue_draw(V["crop"])
        return True
    end
    # plus, KP_Add, equal / minus, KP_Subtract
    if keyval == 43 or keyval == 65451 or keyval == 61:
        call set_zoom(crop["zoom"] * 1.1)
        return True
    end
    if keyval == 45 or keyval == 65453:
        call set_zoom(crop["zoom"] / 1.1)
        return True
    end
    return False
end

function on_crop_key(unused, event, widget):
    return crop_key(gtk.event_key_keyval(event))
end

function show_crop(pix):
    call stop_camera(False)
    if crop["pix"] != 0:
        call avatar.unref(crop["pix"])
    end
    crop["pix"] = pix
    crop["zoom"] = 1.0
    crop["ox"] = 0.0
    crop["oy"] = 0.0
    call gtk.widget_queue_draw(V["crop"])
    call gtk.range_set_value(V["zoom"], 1.0)
    call gtk.stack_set_visible_child_name(V["stack"], "crop")
    call gtk.widget_grab_focus(V["save_btn"])
end

function crop_rect():
    return avatar.crop_rect(avatar.width(crop["pix"]), avatar.height(crop["pix"]), VIEW, crop["zoom"], crop["ox"], crop["oy"])
end

function on_save(unused, b):
    if crop["pix"] == 0:
        return 0
    end
    out = avatar.render(crop["pix"], crop_rect(), avatar.SIZE)
    error = avatar.save(out)
    call avatar.unref(out)
    call load_current()
    call back()
    if error != "":
        call say(i18n.TF("The picture is saved, but the login screen could not be updated: %s", [error]), True)
    else:
        call say(i18n.T("Saved. The new picture appears on the login screen and in the menu."), False)
    end
    return 0
end

function back():
    call stop_camera(False)
    call gtk.stack_set_visible_child_name(V["stack"], "main")
end

function on_back(unused, b):
    call back()
    return 0
end

# ---- kamera ------------------------------------------------------------------------------------------------------

function build_camera():
    box = gtk.box_new(gtk.VERTICAL, 0)
    overlay = gtk.overlay_new()
    call gtk.box_pack_start(box, overlay, True, True, 0)
    V["cam_stack"] = gtk.stack_new(True)
    call gtk.container_add(overlay, V["cam_stack"])
    V["preview"] = gtk.drawing_area_new()
    call gtk.widget_set_size_request(V["preview"], VIEW + 60, VIEW + 60)
    call gtk.connect_data(V["preview"], "draw", 1, draw_preview, 0)
    call gtk.stack_add_named(V["cam_stack"], V["preview"], "preview")
    state = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_set_margin(state, 30)
    call gtk.widget_set_halign(state, gtk.ALIGN_CENTER)
    call gtk.widget_set_valign(state, gtk.ALIGN_CENTER)
    V["cam_icon"] = gtk.image_new()
    call gtk.image_set_pixel_size(V["cam_icon"], 64)
    call gtk.widget_add_class(V["cam_icon"], "dim")
    V["cam_spinner"] = gtk.spinner_new()
    call gtk.widget_set_size_request(V["cam_spinner"], 32, 32)
    V["cam_title"] = label("", "name", 40)
    call gtk.widget_set_name(V["cam_title"], "cam-title")
    V["cam_text"] = label("", "dim", 44)
    call gtk.widget_set_name(V["cam_text"], "cam-text")
    for key in ["cam_icon", "cam_spinner", "cam_title", "cam_text"]:
        call gtk.box_pack_start(state, V[key], False, False, 0)
    end
    call gtk.stack_add_named(V["cam_stack"], state, "state")
    V["flash"] = gtk.event_box_new()
    call gtk.widget_add_class(V["flash"], "flash")
    call gtk.widget_set_no_show_all(V["flash"], True)
    call gtk.overlay_add_overlay(overlay, V["flash"])
    call gtk.overlay_set_pass_through(overlay, V["flash"])

    bar = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margin(bar, 12)
    cancel = button(i18n.T("Cancel"), "pill", on_back)
    call gtk.widget_set_valign(cancel, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(bar, cancel, False, False, 0)
    V["shutter"] = gtk.button_new_empty()
    call gtk.button_set_relief(V["shutter"], gtk.RELIEF_NONE)
    call gtk.widget_set_tooltip(V["shutter"], i18n.T("Take Photo"))
    call gtk.widget_add_class(V["shutter"], "shutter")
    area = gtk.drawing_area_new()
    call gtk.widget_set_size_request(area, 60, 60)
    call gtk.connect_data(area, "draw", 1, draw_shutter, 0)
    call gtk.container_add(V["shutter"], area)
    call gtk.connect_data(V["shutter"], "clicked", 0, on_shutter, 0)
    call gtk.box_set_center_widget(bar, V["shutter"])
    call gtk.box_pack_start(box, bar, False, False, 0)
    return box
end

function cam_state(state, detail):
    texts = {"starting": ["camera-web-symbolic", i18n.T("Starting the camera…"), ""],
        "none": ["camera-disabled-symbolic", i18n.T("No camera found"), i18n.T("Connect a webcam, or check that the built-in camera is turned on. Some laptops have a camera switch, a privacy shutter or a key with a camera symbol.")],
        "busy": ["camera-web-symbolic", i18n.T("The camera is being used by another app"), i18n.T("Close the other app that uses the camera (a video call, a browser tab…) and try again.")],
        "denied": ["changes-prevent-symbolic", i18n.T("Camera access is not allowed"), ""],
        "error": ["dialog-warning-symbolic", i18n.T("The camera could not be started"), detail]}
    item = texts.get(state, texts["error"])
    call gtk.image_set_from_icon_name(V["cam_icon"], item[0], gtk.ICON_DIALOG)
    call gtk.widget_set_visible(V["cam_icon"], state != "starting")
    call gtk.widget_set_visible(V["cam_spinner"], state == "starting")
    call gtk.spinner_set(V["cam_spinner"], state == "starting")
    call gtk.label_set_text(V["cam_title"], item[1])
    call gtk.label_set_text(V["cam_text"], item[2])
    call gtk.widget_set_visible(V["cam_text"], item[2] != "")
    call gtk.stack_set_visible_child_name(V["cam_stack"], "state")
    call gtk.widget_set_sensitive(V["shutter"], False)
end

function open_camera():
    call say("", False)
    call gtk.stack_set_visible_child_name(V["stack"], "camera")
    V["camera_on"] = True
    call cam_state("starting", "")
    found = camera.scan_devices()
    devices = found[0]
    mode = camera.test_mode()
    if len(devices) == 0 or mode == "denied":
        call cam_state("denied" if found[1] > 0 or mode == "denied" else "none", "")
        return 0
    end
    if mode == "busy":
        call cam_state("busy", "")
        return 0
    end
    if devices[0]["path"].startswith("test:"):
        call build_pipeline(devices[0]["path"], "", False)
        return 0
    end
    # zjisteni formatu otevre kameru (desitky ms): az po vykresleni stavu "Spoustim kameru"
    call glib.timeout_add_data(50, probe, devices[0]["path"])
end

function probe(path):
    if not V["camera_on"]:
        return False
    end
    result = camera.probe_caps(path)
    if result[2] == "missing":
        call cam_state("error", i18n.T("The GStreamer plugin for cameras (gst-plugins-good) is missing."))
    elif result[2] == "open":
        call cam_state("busy" if accessible(path) else "denied", "")
    else:
        call build_pipeline(path, result[0], result[1])
    end
    return False
end

function accessible(path):
    unsafe:
        # access(R_OK | W_OK)
        return __lsl_qbe_call2(__lsl_symbol("access"), __lsl_address(path) + 16, 6) == 0
    end
end

function build_pipeline(path, caps, jpeg):
    error = camera.start(path, caps, jpeg)
    if error != "":
        call cam_state("error", error)
        return 0
    end
    # snimky z appsink vyzvedava hlavni smycka (zadna vlakna)
    V["poll"] = glib.timeout_add_data(15, poll_camera, 0)
end

function poll_camera(unused):
    if not camera.running():
        V["poll"] = 0
        return False
    end
    got = camera.poll()
    if got == "error":
        V["poll"] = 0
        call stop_camera(True)
        call cam_state("busy" if camera.error_busy() else "error", camera.error_text())
        return False
    end
    if got == "frame":
        if gtk.stack_get_visible_child_name(V["cam_stack"]) != "preview":
            call gtk.stack_set_visible_child_name(V["cam_stack"], "preview")
            call gtk.widget_set_sensitive(V["shutter"], True)
            call gtk.widget_grab_focus(V["shutter"])
        end
        call gtk.widget_queue_draw(V["preview"])
    end
    return True
end

function stop_camera(keep_page):
    if not keep_page:
        V["camera_on"] = False
    end
    if V["poll"] != 0:
        call glib.source_remove(V["poll"])
        V["poll"] = 0
    end
    call camera.stop()
end

function draw_preview(unused, cr, widget):
    size = size_of(widget)
    call cairo.set_source_rgb(cr, 0.08, 0.08, 0.10)
    call cairo.paint(cr)
    surf = camera.surface()
    if surf != 0:
        fw = Float(cairo.image_surface_get_width(surf))
        fh = Float(cairo.image_surface_get_height(surf))
        # kruh vyplni kratsi strana snimku
        s = max(VIEW / min(fw, fh), min(size[0] / fw, size[1] / fh))
        call cairo.save(cr)
        call cairo.translate(cr, size[0] / 2, size[1] / 2)
        call cairo.scale(cr, s, s)
        call cairo.set_source_surface(cr, surf, -fw / 2, -fh / 2)
        call gtk.cairo_source_filter(cr, 1)
        call cairo.paint(cr)
        call cairo.restore(cr)
    end
    call dim_outside(cr, size[0], size[1], size[0] / 2, size[1] / 2, Float(VIEW))
    return False
end

function draw_shutter(unused, cr, widget):
    size = size_of(widget)
    cx = size[0] / 2
    cy = size[1] / 2
    r = min(size[0], size[1]) / 2 - 3
    alpha = 1.0 if gtk.widget_get_sensitive(V["shutter"]) else 0.4
    fg = gtk.widget_get_color(widget, gtk.widget_get_state_flags(widget))
    call cairo.arc(cr, cx, cy, r, 0.0, 2 * math.PI)
    call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 0.85 * alpha)
    call cairo.set_line_width(cr, 4.0)
    call cairo.stroke(cr)
    call cairo.arc(cr, cx, cy, r - 6, 0.0, 2 * math.PI)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alpha)
    call cairo.fill_preserve(cr)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.15 * alpha)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    return False
end

function take_photo():
    surf = camera.surface()
    if surf == 0:
        return 0
    end
    pix = gtk.surface_to_pixbuf(surf, cairo.image_surface_get_width(surf), cairo.image_surface_get_height(surf))
    call gtk.widget_set_opacity(V["flash"], 1.0)
    call gtk.widget_show(V["flash"])
    V["flash_start"] = glib.monotonic_time()
    call glib.timeout_add_data(16, fade, pix)
end

function fade(pix):
    p = (glib.monotonic_time() - V["flash_start"]) / 250000.0
    if not V["active"]:
        # stranka mezitim opustena: snimek zahodit
        call gtk.widget_hide(V["flash"])
        call avatar.unref(pix)
        return False
    end
    if p >= 1:
        call gtk.widget_hide(V["flash"])
        call show_crop(pix)
        return False
    end
    call gtk.widget_set_opacity(V["flash"], 1 - p)
    return True
end

function on_shutter(unused, b):
    call take_photo()
    return 0
end

function on_take(unused, b):
    call open_camera()
    return 0
end

# Esc zpet; Enter ulozi orez, mezernik/Enter vyfoti - jen kdyz fokus neni na jinem tlacitku (Enter na Zrusit
# by jinak ulozil vyrez a prepsal ~/.face) a neni v poli (hledani v postrannim panelu)
function window_key(keyval):
    page = gtk.stack_get_visible_child_name(V["stack"])
    if keyval == gtk.KEY_Escape and (page == "crop" or page == "camera"):
        call back()
        return True
    end
    focus = gtk.window_get_focus(V["window"])
    if gtk.widget_is_button(focus) and focus != V["save_btn"] and focus != V["shutter"]:
        return False
    end
    if ui.is_a(focus, "GtkEditable"):
        return False
    end
    if page == "camera" and (keyval == gtk.KEY_space or keyval == gtk.KEY_Return or keyval == gtk.KEY_KP_Enter):
        if gtk.widget_get_sensitive(V["shutter"]):
            call take_photo()
        end
        return True
    end
    if page == "crop" and (keyval == gtk.KEY_Return or keyval == gtk.KEY_KP_Enter):
        call on_save(0, 0)
        return True
    end
    return False
end

function on_key(unused, event, window):
    if not V["active"]:
        return False
    end
    return window_key(gtk.event_key_keyval(event))
end

# ---- testy (LUXOS_TEST_CONTROL=1, prikazy, ktere okno Nastaveni nezna) -----------------------------------------

function test(command, rest):
    if command == "open":
        print "open " + String(open_file(rest))
    elif command == "offset":
        parts = rest.split(" ")
        crop["ox"] = Float(parts[0])
        crop["oy"] = Float(parts[1])
        call clamp()
        call gtk.widget_queue_draw(V["crop"])
    elif command == "zoom":
        call set_zoom(Float(rest))
    elif command == "camera":
        call open_camera()
    elif command == "photo":
        call take_photo()
    elif command == "close":
        call gtk.window_close(V["window"])
    elif command == "key":
        print "key " + String(window_key(Int(rest)))
    elif command == "focus":
        call gtk.widget_grab_focus(testctl.find_button(rest))
    elif command == "crop":
        v = [Float(x) for x in rest.split(" ")]
        print "crop " + json.encode(avatar.crop_rect(Int(v[0]), Int(v[1]), Int(v[2]), v[3], v[4], v[5]))
    elif command == "clamp":
        v = [Float(x) for x in rest.split(" ")]
        print "clamp " + json.encode(avatar.clamp_offset(Int(v[0]), Int(v[1]), Int(v[2]), v[3], v[4], v[5]))
    elif command == "seticon":
        print "seticon " + avatar.set_icon_file(rest)
    elif command == "initials":
        print "initials " + avatar.initials(rest)
    elif command == "pick":
        print "pick " + json.encode(camera.pick_caps(rest))
    elif command == "scan":
        print "scan " + json.encode(camera.scan_devices())
    elif command == "page-state":
        size = [0, 0]
        if crop["pix"] != 0:
            size = [avatar.width(crop["pix"]), avatar.height(crop["pix"])]
        end
        print "page-state " + json.encode({"page": gtk.stack_get_visible_child_name(V["stack"]), "size": size,
            "cam": gtk.stack_get_visible_child_name(V["cam_stack"]), "camera": camera.running(),
            "shutter": gtk.widget_get_sensitive(V["shutter"]), "ox": crop["ox"], "oy": crop["oy"],
            "zoom": crop["zoom"], "hint_error": gtk.widget_has_class(V["hint"], "error")})
    else:
        return False
    end
    return True
end

# ---- stranka -------------------------------------------------------------------------------------------------

# Relativni cesta k obrazku: argumenty jdou dal do okna, pripadne pres D-Bus do bezici instance s jinym
# pracovnim adresarem
function cli(args):
    if len(args) > 0 and not args[0].startswith("-") and not args[0].startswith("/"):
        args[0] = cwd() + "/" + args[0]
    end
    return None
end

function build(host):
    V["window"] = host["window"]
    call gtk.css_load(CSS)
    page = ui.page_box()
    call gtk.widget_add_class(page, "profile-page")
    V["stack"] = gtk.stack_new(True)
    call gtk.stack_set_transition_duration(V["stack"], 150)
    call gtk.box_pack_start(page, V["stack"], True, True, 0)
    call gtk.stack_add_named(V["stack"], build_main(), "main")
    call gtk.stack_add_named(V["stack"], build_crop(), "crop")
    call gtk.stack_add_named(V["stack"], build_camera(), "camera")
    call gtk.connect_data(V["window"], "key-press-event", 1, on_key, 0)
    # Odebrat skryte jeste pred show_all okna (jinak by stranka byla o tlacitko vyssi), po zobrazeni znovu podle fotky
    call load_current()
    call gtk.widget_show_all(page)
    call load_current()
    return page
end

# Pri kazdem zobrazeni, i s argumenty z druheho spusteni (luxos-profile-picture --camera pri otevrenem okne)
function show(host):
    V["active"] = True
    args = host["args"]
    if "--camera" in args:
        call open_camera()
    elif len(args) > 0 and not args[0].startswith("-"):
        call open_file(args[0])
    end
    return 0
end

function leave(host):
    V["active"] = False
    call back()
    return 0
end
