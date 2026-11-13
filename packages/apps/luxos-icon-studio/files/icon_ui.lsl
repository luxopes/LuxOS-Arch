# lsl: internal-abi
load gtk
load glib
load cairo
load json
load env
load time
load math
load icon_native as native
load icon_style
load icon_model
load icon_render

language = "en"

function t(english, czech=""):
    if language == "cs" and czech:
        return czech
    end
    return english
end

function box(vertical=True, spacing=0, style=""):
    orientation = 0
    if vertical:
        orientation = 1
    end
    widget = gtk.box_new(orientation, spacing)
    if style:
        call gtk.widget_add_class(widget, style)
    end
    return widget
end

function pack(parent, child, expand=False):
    call gtk.box_pack_start(parent, child, expand, True, 0)
    return child
end

function label(text, style=""):
    widget = gtk.label_new(text)
    call native.left(widget)
    if style:
        call gtk.widget_add_class(widget, style)
    end
    return widget
end

function button(text, handler, bound, style=""):
    widget = gtk.button_new(text)
    if style:
        call gtk.widget_add_class(widget, style)
    end
    call native.connect(widget, "clicked", handler, bound)
    return widget
end

function icon_button(icon, tip, handler, bound, style="flat"):
    widget = gtk.button_new_from_icon_name(icon, 1)
    call gtk.widget_set_tooltip(widget, tip)
    if style:
        call gtk.widget_add_class(widget, style)
    end
    call native.connect(widget, "clicked", handler, bound)
    return widget
end

function scroll(child):
    widget = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(widget, 2, 1)
    call gtk.container_add(widget, child)
    return widget
end

function selected(state):
    return icon_model.find_layer(state["project"], state["selected"])
end

function checkpoint(state):
    value = json.encode(state["project"])
    if not state["undo"] or state["undo"][len(state["undo"]) - 1] != value:
        state["undo"].append(value)
        if len(state["undo"]) > 80:
            call state["undo"].pop(0)
        end
    end
    state["redo"] = []
    call trim_history(state)
end

function trim_history(state):
    total = 0
    for history in [state["undo"], state["redo"]]:
        for snapshot in history:
            total += __lsl_text_byte_length(snapshot)
        end
    end
    while total > 12582912:
        history = state["undo"]
        if not history:
            history = state["redo"]
        end
        removed = history.pop(0)
        total -= __lsl_text_byte_length(removed)
    end
end

function dirty(state):
    return json.encode(state["project"]) != state["saved"]
end

function status(state, text):
    call gtk.label_set_text(state["status"], text)
end

function error(state, detail):
    call status(state, detail)
    call native.message(state["window"], t("Something needs attention", "Je potřeba něco upravit"), detail)
end

function invalidate(state):
    if not state["render_pending"]:
        state["render_pending"] = True
        call native.defer(render_pending, state)
    end
    call gtk.widget_set_sensitive(state["undo_button"], len(state["undo"]) > 0)
    call gtk.widget_set_sensitive(state["redo_button"], len(state["redo"]) > 0)
    title = state["project"]["title"]
    suffix = ""
    if dirty(state):
        suffix = " •"
    end
    call gtk.window_set_title(state["window"], title + suffix + " — Icon Studio")
    call gtk.label_set_text(state["workspace_title"], title + suffix)
end

function render_pending(state):
    if not state["alive"]:
        return
    end
    state["render_pending"] = False
    state["render_key"] = ""
    call gtk.widget_queue_draw(state["canvas"])
    for item in state["previews"]:
        try:
            pixbuf = icon_render.pixbuf(state["project"], item[1], "transparent")
            call gtk.image_set_from_pixbuf(item[0], pixbuf)
            call native.unref(pixbuf)
        else:
            call status(state, String(last_error()))
        end
    end
end

function draw(state, cr, area):
    width = gtk.widget_get_allocated_width(area)
    height = gtk.widget_get_allocated_height(area)
    background = state["background"]
    if background == "light":
        call cairo.set_source_rgb(cr, 0.91, 0.94, 0.98)
        call cairo.paint(cr)
    else:
        gradient = cairo.pattern_create_linear(0.0, 0.0, Float(width), Float(height))
        call cairo.pattern_add_color_stop_rgba(gradient, 0.0, 0.055, 0.096, 0.18, 1.0)
        call cairo.pattern_add_color_stop_rgba(gradient, 0.6, 0.10, 0.20, 0.30, 1.0)
        call cairo.pattern_add_color_stop_rgba(gradient, 1.0, 0.16, 0.18, 0.34, 1.0)
        call cairo.set_source(cr, gradient)
        call cairo.paint(cr)
        call cairo.pattern_destroy(gradient)
        glow = cairo.pattern_create_radial(width * 0.28, height * 0.38, 0.0, width * 0.28, height * 0.38, max(width, height) * 0.65)
        call cairo.pattern_add_color_stop_rgba(glow, 0.0, 0.18, 0.68, 0.68, 0.18)
        call cairo.pattern_add_color_stop_rgba(glow, 1.0, 0.18, 0.68, 0.68, 0.0)
        call cairo.set_source(cr, glow)
        call cairo.paint(cr)
        call cairo.pattern_destroy(glow)
    end
    # A quiet precision grid belongs to the workbench, never to the export.
    call cairo.set_source_rgba(cr, 0.65, 0.77, 0.9, 0.075)
    if background == "light":
        call cairo.set_source_rgba(cr, 0.18, 0.3, 0.5, 0.07)
    end
    for x in rang(24, width, 24):
        for y in rang(24, height, 24):
            call cairo.rectangle(cr, x, y, 1.0, 1.0)
        end
    end
    call cairo.fill(cr)
    fit = min(width - 70, height - 70)
    size = max(64, Int(fit * state["zoom"]))
    size = min(size, 1536)
    ox = (width - size) / 2.0
    oy = (height - size) / 2.0
    state["canvas_rect"] = [ox, oy, size]
    if background == "transparent":
        call cairo.save(cr)
        call cairo.rectangle(cr, ox, oy, size, size)
        call cairo.clip(cr)
        call cairo.set_source_rgb(cr, 0.89, 0.92, 0.96)
        call cairo.paint(cr)
        call cairo.set_source_rgb(cr, 0.80, 0.84, 0.9)
        for x in rang(0, size, 16):
            for y in rang(0, size, 16):
                if (x // 16 + y // 16) % 2 == 0:
                    call cairo.rectangle(cr, ox + x, oy + y, 16.0, 16.0)
                end
            end
        end
        call cairo.fill(cr)
        call cairo.restore(cr)
    end
    key = String(size) + "|" + json.encode(state["project"])
    if state["render_key"] != key:
        try:
            pixbuf = icon_render.pixbuf(state["project"], size, "transparent")
            call native.unref(state["pixbuf"])
            state["pixbuf"] = pixbuf
            state["render_key"] = key
        else:
            call status(state, String(last_error()))
        end
    end
    if state["pixbuf"]:
        call gtk.cairo_set_source_pixbuf(cr, state["pixbuf"], ox, oy)
        call cairo.paint(cr)
    end
    return False
end

function select_layer(state, identity):
    state["selected"] = identity
    call rebuild_layers(state)
    call sync_inspector(state)
end

function layer_clicked(bound, widget):
    call select_layer(bound["app"], bound["id"])
end

function visibility_changed(bound, widget):
    state = bound["app"]
    layer = icon_model.find_layer(state["project"], bound["id"])
    if layer == None or state["syncing"]:
        return
    end
    call checkpoint(state)
    layer["visible"] = gtk.toggle_button_get_active(widget)
    call invalidate(state)
end

function layer_symbol(kind):
    if kind == "circle" or kind == "ellipse":
        return "○"
    elif kind == "text":
        return "T"
    elif kind == "glyph":
        return "✦"
    elif kind == "image":
        return "▧"
    end
    return "▢"
end

function rebuild_layers(state):
    state["syncing"] = True
    call native.clear(state["layers"])
    state["layer_labels"] = {}
    layers = state["project"]["layers"]
    index = len(layers) - 1
    while index >= 0:
        layer = layers[index]
        bound = {"app": state, "id": layer["id"]}
        row = button("", layer_clicked, bound, "layer-row")
        call native.clear(row)
        if layer["id"] == state["selected"]:
            call gtk.widget_add_class(row, "selected")
        end
        content = box(False, 10)
        mark = label(layer_symbol(layer["kind"]), "layer-glyph")
        call native.align(mark, 0.5)
        call gtk.widget_set_halign(mark, 3)
        call pack(content, mark)
        names = box(True, 3)
        name = label(layer["name"], "layer-name")
        call gtk.label_set_ellipsize(name, 3)
        call gtk.label_set_max_width_chars(name, 16)
        state["layer_labels"][layer["id"]] = name
        call pack(names, name)
        call pack(names, label(layer["kind"], "layer-kind"))
        call pack(content, names, True)
        visible = gtk.check_button_new("")
        call gtk.toggle_button_set_active(visible, layer.get("visible", True))
        call gtk.widget_set_tooltip(visible, t("Show layer", "Zobrazit vrstvu"))
        call native.connect(visible, "toggled", visibility_changed, bound)
        call pack(content, visible)
        call gtk.container_add(row, content)
        call pack(state["layers"], row)
        index -= 1
    end
    call gtk.widget_show_all(state["layers"])
    state["syncing"] = False
    call gtk.label_set_text(state["layer_count"], String(len(layers)) + " " + t("layers", "vrstvy"))
end

function sync_inspector(state):
    state["syncing"] = True
    layer = selected(state)
    call gtk.widget_set_sensitive(state["inspector"], layer != None)
    if layer == None:
        call gtk.label_set_text(state["selected_kind"], t("Select a layer to edit", "Vyberte vrstvu k úpravě"))
    end
    if layer != None:
        call gtk.entry_set_text(state["fields"]["name"], layer["name"])
        for field in ["x", "y", "width", "height", "rotation", "radius"]:
            call gtk.spin_button_set_value(state["fields"][field], layer.get(field, 0))
        end
        call gtk.spin_button_set_value(state["fields"]["font_size"], layer.get("font_size", 300))
        call gtk.range_set_value(state["fields"]["opacity"], layer.get("opacity", 1.0) * 100.0)
        call gtk.range_set_value(state["fields"]["gloss"], layer.get("gloss", 0.0) * 100.0)
        call gtk.toggle_button_set_active(state["fields"]["shadow"], layer.get("shadow", False))
        call gtk.entry_set_text(state["fields"]["text"], layer.get("text", ""))
        call gtk.label_set_text(state["selected_kind"], layer["kind"].upper())
        for field in ["color", "color2"]:
            call set_color(state["fields"][field], layer.get(field, "#ffffff"))
        end
        call gtk.widget_set_visible(state["text_row"], layer["kind"] == "text")
        call gtk.widget_set_visible(state["glyph_row"], layer["kind"] == "glyph")
        glyphs = ["orbit", "spark", "diamond", "leaf", "wave"]
        glyph_index = 0
        for index in rang(len(glyphs)):
            if glyphs[index] == layer.get("glyph", "orbit"):
                glyph_index = index
            end
        end
        call gtk.combo_box_set_active(state["fields"]["glyph"], glyph_index)
        call gtk.widget_set_sensitive(state["fields"]["radius"], layer["kind"] == "rect")
        call gtk.widget_set_sensitive(state["fields"]["gloss"], layer["kind"] in ["rect", "circle", "ellipse"])
        call gtk.widget_set_sensitive(state["fields"]["color"], layer["kind"] != "image")
        call gtk.widget_set_sensitive(state["fields"]["color2"], layer["kind"] != "image")
    end
    state["syncing"] = False
end

function glyph_changed(state, widget):
    if state["syncing"]:
        return
    end
    layer = selected(state)
    if layer != None:
        index = gtk.combo_box_get_active(widget)
        if index >= 0:
            call checkpoint(state)
            layer["glyph"] = ["orbit", "spark", "diamond", "leaf", "wave"][index]
            call invalidate(state)
        end
    end
end

function numeric_changed(bound, widget):
    state = bound["app"]
    if state["syncing"]:
        return
    end
    layer = selected(state)
    if layer == None:
        return
    end
    value = gtk.spin_button_get_value(widget)
    if layer.get(bound["field"], 0) == value:
        return
    end
    call checkpoint(state)
    layer[bound["field"]] = value
    call invalidate(state)
end

function range_changed(bound, widget):
    state = bound["app"]
    if state["syncing"]:
        return
    end
    layer = selected(state)
    if layer != None:
        call checkpoint(state)
        layer[bound["field"]] = gtk.range_get_value(widget) / 100.0
        call invalidate(state)
    end
end

function text_changed(bound, widget):
    state = bound["app"]
    if state["syncing"]:
        return
    end
    value = gtk.entry_get_text(widget)
    layer = selected(state)
    if layer == None:
        return
    end
    call checkpoint(state)
    layer[bound["field"]] = value
    if bound["field"] == "name" and layer["id"] in state["layer_labels"]:
        call gtk.label_set_text(state["layer_labels"][layer["id"]], value)
    end
    call invalidate(state)
end

function project_title_changed(state, widget):
    if state["syncing"]:
        return
    end
    text = gtk.entry_get_text(widget)
    if text:
        call checkpoint(state)
        state["project"]["title"] = text
        call invalidate(state)
    end
end

function shadow_changed(state, widget):
    if state["syncing"]:
        return
    end
    layer = selected(state)
    if layer != None:
        call checkpoint(state)
        layer["shadow"] = gtk.toggle_button_get_active(widget)
        call invalidate(state)
    end
end

function hex_digit(value):
    return "0123456789abcdef"[max(0, min(15, value))]
end

function color_hex(widget):
    rgba = native.buffer(32)
    call __lsl_qbe_call2(__lsl_symbol("gtk_color_chooser_get_rgba"), native.ptr(widget), native.data(rgba))
    result = "#"
    for index in rang(3):
        component = Int(__lsl_float_from_bits(__lsl_qbe_load64(native.data(rgba) + index * 8)) * 255.0 + 0.5)
        result += hex_digit(component // 16) + hex_digit(component % 16)
    end
    return result
end

function set_color(widget, value):
    rgba = native.buffer(32)
    ok = __lsl_qbe_call2(__lsl_symbol("gdk_rgba_parse"), native.data(rgba), native.cstr(value))
    if ok:
        call __lsl_qbe_call2(__lsl_symbol("gtk_color_chooser_set_rgba"), native.ptr(widget), native.data(rgba))
    end
end

function color_changed(bound, widget):
    state = bound["app"]
    if state["syncing"]:
        return
    end
    layer = selected(state)
    if layer != None:
        call checkpoint(state)
        layer[bound["field"]] = color_hex(widget)
        call invalidate(state)
    end
end

function background_changed(state, widget):
    index = gtk.combo_box_get_active(widget)
    state["background"] = ["studio", "light", "transparent"][max(0, min(2, index))]
    call gtk.widget_queue_draw(state["canvas"])
end

function zoom_action(bound, widget):
    state = bound["app"]
    value = bound["value"]
    if value == 0:
        state["zoom"] = 1.0
    else:
        state["zoom"] = max(0.25, min(2.0, state["zoom"] + value))
    end
    call gtk.label_set_text(state["zoom_label"], String(Int(state["zoom"] * 100)) + "%")
    call gtk.widget_queue_draw(state["canvas"])
end

function undo(state, widget):
    if not state["undo"]:
        return
    end
    state["redo"].append(json.encode(state["project"]))
    state["project"] = json.decode(state["undo"].pop())
    call trim_history(state)
    call restored(state)
end

function redo(state, widget):
    if not state["redo"]:
        return
    end
    state["undo"].append(json.encode(state["project"]))
    state["project"] = json.decode(state["redo"].pop())
    call trim_history(state)
    call restored(state)
end

function restored(state):
    if selected(state) == None and state["project"]["layers"]:
        state["selected"] = state["project"]["layers"][len(state["project"]["layers"]) - 1]["id"]
    end
    state["syncing"] = True
    call gtk.entry_set_text(state["title_entry"], state["project"]["title"])
    state["syncing"] = False
    call rebuild_layers(state)
    call sync_inspector(state)
    call invalidate(state)
end

function basename(state, extension):
    title = state["project"]["title"].replace("/", "-").replace("\\", "-").replace("\0", "")
    if not title or title == "." or title == "..":
        title = "icon"
    end
    return title + extension
end

function save_to(state, path):
    try:
        call icon_model.save(state["project"], path)
        state["path"] = path
        state["saved"] = json.encode(state["project"])
        call status(state, t("Saved to ", "Uloženo do ") + path)
        call invalidate(state)
        return True
    else:
        call error(state, String(last_error()))
        return False
    end
end

function save_as(state, widget):
    path = native.choose(state["window"], t("Save icon project", "Uložit projekt ikony"), 1, basename(state, ".luxicon"))
    if not path:
        return False
    end
    return save_to(state, path)
end

function save(state, widget):
    if state["path"]:
        return save_to(state, state["path"])
    end
    return save_as(state, 0)
end

function confirm_discard(state):
    if not dirty(state):
        return True
    end
    response = native.message(state["window"], t("Save your changes?", "Uložit změny?"), t("Your icon has unsaved changes. Save the project before continuing?", "Ikona obsahuje neuložené změny. Chcete projekt před pokračováním uložit?"), True)
    if response == -3:
        return save(state, 0)
    end
    return response == -2
end

function new_project(state, widget):
    if not confirm_discard(state):
        return
    end
    state["project"] = icon_model.new_project("blank")
    state["path"] = ""
    state["undo"] = []
    state["redo"] = []
    state["saved"] = json.encode(state["project"])
    state["selected"] = ""
    call restored(state)
    call status(state, t("New canvas. Add your first layer.", "Nové plátno. Přidejte první vrstvu."))
end

function open_path(state, path):
    try:
        project = icon_model.open_project(path)
        call icon_render.validate_assets(project)
        state["project"] = project
        state["path"] = path
        state["undo"] = []
        state["redo"] = []
        state["saved"] = json.encode(project)
        state["selected"] = ""
        call restored(state)
        call status(state, path)
        return True
    else:
        call error(state, String(last_error()))
        return False
    end
end

function open_project(state, widget):
    if not confirm_discard(state):
        return
    end
    path = native.choose(state["window"], t("Open icon project", "Otevřít projekt ikony"))
    if path:
        call open_path(state, path)
    end
end

function import_asset(state, widget):
    path = native.choose(state["window"], t("Import SVG or PNG", "Importovat SVG nebo PNG"))
    if path:
        try:
            draft = icon_model.clone(state["project"])
            layer = icon_render.import_asset(draft, path)
            call checkpoint(state)
            state["project"] = draft
            state["selected"] = layer["id"]
            call restored(state)
            call status(state, t("Artwork imported and embedded in the project", "Grafika byla importována a vložena do projektu"))
        else:
            call error(state, String(last_error()))
        end
    end
end

function add_layer(state, kind):
    try:
        draft = icon_model.clone(state["project"])
        layer = icon_model.add_layer(draft, kind)
        call checkpoint(state)
        state["project"] = draft
        state["selected"] = layer["id"]
        call restored(state)
    else:
        call error(state, String(last_error()))
    end
end

function duplicate(state, widget):
    if selected(state) != None:
        try:
            draft = icon_model.clone(state["project"])
            layer = icon_model.duplicate_layer(draft, state["selected"])
            call icon_render.validate_assets(draft)
            call checkpoint(state)
            state["project"] = draft
            state["selected"] = layer["id"]
            call restored(state)
        else:
            call error(state, String(last_error()))
        end
    end
end

function remove(state, widget):
    if selected(state) != None:
        call checkpoint(state)
        call icon_model.remove_layer(state["project"], state["selected"])
        call restored(state)
    end
end

function reorder(bound, widget):
    state = bound["app"]
    if selected(state) != None:
        call checkpoint(state)
        call icon_model.move_layer(state["project"], state["selected"], bound["delta"])
        call restored(state)
    end
end

function export_file(state, kind):
    path = native.choose(state["window"], t("Export icon", "Exportovat ikonu"), 1, basename(state, "." + kind))
    if path:
        try:
            if kind == "svg":
                call icon_model.atomic_text(path, icon_render.svg(state["project"], 1024, "transparent"))
            else:
                call icon_render.render_png(state["project"], path, 1024)
            end
            call status(state, t("Exported to ", "Exportováno do ") + path)
        else:
            call error(state, String(last_error()))
        end
    end
end

function export_sizes(state):
    folder = native.choose(state["window"], t("Export icon size set", "Exportovat sadu velikostí ikon"), 2)
    if folder:
        try:
            call icon_render.export_set(state["project"], folder, "icon")
            call status(state, t("Icon size set exported to ", "Sada ikon exportována do ") + folder)
        else:
            call error(state, String(last_error()))
        end
    end
end

function menu_action(bound, widget):
    action = bound["action"]
    state = bound["app"]
    call gtk.widget_destroy(bound["menu"])
    if action == "png" or action == "svg":
        call export_file(state, action)
    elif action == "sizes":
        call export_sizes(state)
    elif action == "save_as":
        call save_as(state, 0)
    elif action == "aurora" or action == "ember":
        if confirm_discard(state):
            state["project"] = icon_model.new_project(action)
            state["path"] = ""
            state["undo"] = []
            state["redo"] = []
            state["saved"] = json.encode(state["project"])
            state["selected"] = ""
            call restored(state)
        end
    else:
        call add_layer(state, action)
    end
end

function menu(state, widget, entries):
    popup = __lsl_qbe_call0(__lsl_symbol("gtk_menu_new"))
    call __lsl_qbe_call3(__lsl_symbol("gtk_menu_attach_to_widget"), native.ptr(popup), native.ptr(widget), 0)
    call native.connect(popup, "selection-done", menu_dismissed, None)
    for item in entries:
        row = __lsl_qbe_call1(__lsl_symbol("gtk_menu_item_new_with_label"), native.cstr(item[0]))
        call __lsl_qbe_call2(__lsl_symbol("gtk_menu_shell_append"), native.ptr(popup), native.ptr(row))
        call native.connect(row, "activate", menu_action, {"app": state, "action": item[1], "menu": popup})
    end
    call gtk.widget_show_all(popup)
    call __lsl_qbe_call5(__lsl_symbol("gtk_menu_popup_at_widget"), native.ptr(popup), native.ptr(widget), 7, 1, 0)
end

function menu_dismissed(state, widget):
    call gtk.widget_destroy(widget)
end

function add_menu(state, widget):
    call menu(state, widget, [[t("Rounded rectangle", "Zaoblený obdélník"), "rect"], [t("Circle", "Kruh"), "circle"], [t("Ellipse", "Elipsa"), "ellipse"], [t("Orbit symbol", "Symbol oběžné dráhy"), "glyph"], [t("Text", "Text"), "text"]])
end

function export_menu(state, widget):
    call menu(state, widget, [[t("PNG · 1024 × 1024", "PNG · 1024 × 1024"), "png"], [t("SVG · scalable", "SVG · vektorová ikona"), "svg"], [t("All icon sizes", "Všechny velikosti ikon"), "sizes"]])
end

function project_menu(state, widget):
    call menu(state, widget, [[t("Save project as…", "Uložit projekt jako…"), "save_as"], [t("Aurora template", "Šablona Aurora"), "aurora"], [t("Ember template", "Šablona Ember"), "ember"]])
end

function close_requested(state, event, window):
    return not confirm_discard(state)
end

function destroyed(state, window):
    state["alive"] = False
    call native.unref(state["pixbuf"])
    state["pixbuf"] = 0
    if __lsl_qbe_call0(__lsl_symbol("gtk_main_level")) > 0:
        call gtk.main_quit()
    end
end

function key_pressed(state, event, window):
    key = gtk.event_key_keyval(event)
    mods = gtk.event_key_state(event)
    control = mods & 4 != 0
    shift = mods & 1 != 0
    if control and (key == 115 or key == 83):
        if shift:
            call save_as(state, 0)
        else:
            call save(state, 0)
        end
        return True
    elif control and (key == 111 or key == 79):
        call open_project(state, 0)
        return True
    elif control and (key == 110 or key == 78):
        call new_project(state, 0)
        return True
    elif control and (key == 122 or key == 90):
        if shift:
            call redo(state, 0)
        else:
            call undo(state, 0)
        end
        return True
    elif control and (key == 121 or key == 89):
        call redo(state, 0)
        return True
    elif control and (key == 100 or key == 68):
        call duplicate(state, 0)
        return True
    elif control and (key == 101 or key == 69):
        call export_file(state, "png")
        return True
    elif key == 65535 and __lsl_qbe_call1(__lsl_symbol("gtk_window_get_focus"), native.ptr(window)) == state["canvas"]:
        call remove(state, 0)
        return True
    end
    return False
end

function stage_clicked(state, event, area):
    if gtk.event_button(event) != 1:
        return False
    end
    call __lsl_qbe_call1(__lsl_symbol("gtk_widget_grab_focus"), native.ptr(area))
    rect = state["canvas_rect"]
    x = (gtk.event_x(event) - rect[0]) * 1024.0 / rect[2]
    y = (gtk.event_y(event) - rect[1]) * 1024.0 / rect[2]
    layers = state["project"]["layers"]
    index = len(layers) - 1
    while index >= 0:
        layer = layers[index]
        if layer.get("visible", True) and x >= layer["x"] and x <= layer["x"] + layer["width"] and y >= layer["y"] and y <= layer["y"] + layer["height"]:
            call select_layer(state, layer["id"])
            state["drag"] = {"id": layer["id"], "sx": x, "sy": y, "x": layer["x"], "y": layer["y"], "started": False}
            return True
        end
        index -= 1
    end
    return False
end

function stage_moved(state, event, area):
    drag = state.get("drag")
    if drag == None:
        return False
    end
    rect = state["canvas_rect"]
    dx = (gtk.event_x(event) - rect[0]) * 1024.0 / rect[2] - drag["sx"]
    dy = (gtk.event_y(event) - rect[1]) * 1024.0 / rect[2] - drag["sy"]
    if not drag["started"]:
        if abs(dx) + abs(dy) < 2:
            return True
        end
        drag["started"] = True
        call checkpoint(state)
    end
    layer = icon_model.find_layer(state["project"], drag["id"])
    if layer != None:
        layer["x"] = max(-4096.0, min(4096.0, drag["x"] + dx))
        layer["y"] = max(-4096.0, min(4096.0, drag["y"] + dy))
        state["syncing"] = True
        call gtk.spin_button_set_value(state["fields"]["x"], layer["x"])
        call gtk.spin_button_set_value(state["fields"]["y"], layer["y"])
        state["syncing"] = False
        call invalidate(state)
    end
    return True
end

function stage_released(state, event, area):
    state["drag"] = None
    return False
end

function numeric_field(state, parent, field, caption, minimum, maximum):
    column = box(True, 5)
    call pack(column, label(caption, "field-caption"))
    spin = gtk.spin_button_new_with_range(minimum, maximum, 1.0)
    call gtk.widget_set_hexpand(spin, True)
    call __lsl_qbe_call2(__lsl_symbol("gtk_entry_set_width_chars"), native.ptr(spin), 4)
    call __lsl_qbe_call2(__lsl_symbol("gtk_entry_set_max_width_chars"), native.ptr(spin), 6)
    call __lsl_qbe_call2(__lsl_symbol("gtk_spin_button_set_numeric"), native.ptr(spin), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_spin_button_set_digits"), native.ptr(spin), 0)
    state["fields"][field] = spin
    call native.connect(spin, "value-changed", numeric_changed, {"app": state, "field": field})
    call pack(column, spin)
    call pack(parent, column, True)
end

function section(parent, title):
    call pack(parent, label(title, "section-title"))
    card = box(True, 12, "property-card")
    call pack(parent, card)
    return card
end

function range_field(state, parent, field, caption):
    call pack(parent, label(caption, "property-label"))
    range = gtk.scale_new_with_range(0, 0.0, 100.0, 1.0)
    call gtk.scale_set_draw_value(range, True)
    call __lsl_qbe_call2(__lsl_symbol("gtk_scale_set_digits"), native.ptr(range), 0)
    state["fields"][field] = range
    call native.connect(range, "value-changed", range_changed, {"app": state, "field": field})
    call pack(parent, range)
end

function build_inspector(state):
    outer = box(True, 0, "pane")
    call gtk.widget_add_class(outer, "inspector-pane")
    call gtk.widget_set_size_request(outer, 272, -1)
    call gtk.widget_set_hexpand(outer, False)
    heading = box(True, 6)
    call gtk.widget_set_margin(heading, 20)
    state["properties_heading"] = label(t("Properties", "Vlastnosti"), "pane-title")
    call pack(heading, state["properties_heading"])
    state["selected_kind"] = label("", "pane-subtitle")
    call pack(heading, state["selected_kind"])
    call pack(outer, heading)
    content = box(True, 15)
    call gtk.widget_set_margins(content, 17, 17, 0, 20)
    state["inspector"] = content
    call pack(content, label(t("Layer", "Vrstva"), "section-title"))
    name = gtk.entry_new()
    call gtk.entry_set_max_length(name, 100)
    state["fields"]["name"] = name
    call native.connect(name, "changed", text_changed, {"app": state, "field": "name"})
    call pack(content, name)
    glyphrow = box(True, 7)
    state["glyph_row"] = glyphrow
    call pack(glyphrow, label(t("Symbol", "Symbol"), "section-title"))
    glyph = gtk.combo_box_text_new()
    for item in [["orbit", t("Orbit", "Oběžná dráha")], ["spark", t("Spark", "Jiskra")], ["diamond", t("Diamond", "Diamant")], ["leaf", t("Leaf", "List")], ["wave", t("Wave", "Vlna")]]:
        call gtk.combo_box_text_append(glyph, item[0], item[1])
    end
    state["fields"]["glyph"] = glyph
    call native.connect(glyph, "changed", glyph_changed, state)
    call pack(glyphrow, glyph)
    call pack(content, glyphrow)
    geometry = section(content, t("Transform", "Transformace"))
    row = box(False, 9)
    call numeric_field(state, row, "x", "X", -4096.0, 4096.0)
    call numeric_field(state, row, "y", "Y", -4096.0, 4096.0)
    call pack(geometry, row)
    row2 = box(False, 9)
    call numeric_field(state, row2, "width", t("Width", "Šířka"), 1.0, 4096.0)
    call numeric_field(state, row2, "height", t("Height", "Výška"), 1.0, 4096.0)
    call pack(geometry, row2)
    row3 = box(False, 9)
    call numeric_field(state, row3, "rotation", t("Rotation", "Otočení"), -180.0, 180.0)
    call numeric_field(state, row3, "radius", t("Radius", "Zaoblení"), 0.0, 512.0)
    call pack(geometry, row3)
    appearance = section(content, t("Appearance", "Vzhled"))
    colors = box(False, 9)
    for field in ["color", "color2"]:
        color_column = box(True, 6)
        caption = t("Primary", "Hlavní")
        if field == "color2":
            caption = t("Secondary", "Vedlejší")
        end
        call pack(color_column, label(caption, "field-caption"))
        chooser = __lsl_qbe_call0(__lsl_symbol("gtk_color_button_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_color_chooser_set_use_alpha"), native.ptr(chooser), 0)
        call gtk.widget_set_size_request(chooser, 92, 32)
        call gtk.widget_set_hexpand(chooser, True)
        state["fields"][field] = chooser
        call native.connect(chooser, "color-set", color_changed, {"app": state, "field": field})
        call pack(color_column, chooser)
        call pack(colors, color_column, True)
    end
    call pack(appearance, colors)
    call range_field(state, appearance, "opacity", t("Opacity", "Krytí"))
    call range_field(state, appearance, "gloss", t("Soft light", "Jemný lesk"))
    shadow = gtk.check_button_new(t("Soft shadow", "Jemný stín"))
    state["fields"]["shadow"] = shadow
    call native.connect(shadow, "toggled", shadow_changed, state)
    call pack(appearance, shadow)
    textrow = box(True, 7)
    state["text_row"] = textrow
    call pack(textrow, label(t("Text", "Text"), "section-title"))
    text = gtk.entry_new()
    call gtk.entry_set_max_length(text, 256)
    state["fields"]["text"] = text
    call native.connect(text, "changed", text_changed, {"app": state, "field": "text"})
    call pack(textrow, text)
    call numeric_field(state, textrow, "font_size", t("Font size", "Velikost písma"), 8.0, 1024.0)
    call pack(content, textrow)
    call pack(outer, scroll(content), True)
    return outer
end

function build_layers(state):
    outer = box(True, 0, "pane")
    call gtk.widget_add_class(outer, "layers-pane")
    call gtk.widget_set_size_request(outer, 222, -1)
    call gtk.widget_set_hexpand(outer, False)
    title = box(True, 9)
    call gtk.widget_set_margin(title, 19)
    call pack(title, label(t("Project", "Projekt"), "section-title"))
    state["title_entry"] = gtk.entry_new()
    call gtk.entry_set_max_length(state["title_entry"], 120)
    call native.connect(state["title_entry"], "changed", project_title_changed, state)
    call pack(title, state["title_entry"])
    call pack(title, label("1024 × 1024 · sRGB", "pane-subtitle"))
    call pack(outer, title)
    subhead = box(False, 6)
    call gtk.widget_set_margins(subhead, 20, 13, 7, 10)
    call pack(subhead, label(t("Layers", "Vrstvy"), "section-title"), True)
    call pack(subhead, icon_button("list-add-symbolic", t("Add a layer", "Přidat vrstvu"), add_menu, state))
    call pack(outer, subhead)
    state["layers"] = box(True, 3, "layer-list")
    call pack(outer, scroll(state["layers"]), True)
    footer = box(True, 11)
    call gtk.widget_set_margin(footer, 16)
    state["layer_count"] = label("", "muted")
    call pack(footer, state["layer_count"])
    call pack(footer, button(t("Import artwork…", "Importovat grafiku…"), import_asset, state))
    call pack(outer, footer)
    tools = box(False, 0, "tools")
    call pack(tools, icon_button("edit-copy-symbolic", t("Duplicate · Ctrl+D", "Duplikovat · Ctrl+D"), duplicate, state), True)
    call pack(tools, icon_button("go-up-symbolic", t("Move forward", "Posunout dopředu"), reorder, {"app": state, "delta": 1}), True)
    call pack(tools, icon_button("go-down-symbolic", t("Move backward", "Posunout dozadu"), reorder, {"app": state, "delta": -1}), True)
    call pack(tools, icon_button("user-trash-symbolic", t("Delete layer", "Smazat vrstvu"), remove, state), True)
    call pack(outer, tools)
    return outer
end

function build_canvas(state):
    outer = box(True, 0)
    call gtk.widget_set_hexpand(outer, True)
    toolbar = box(False, 7, "canvas-toolbar")
    state["workspace_title"] = label("Aurora", "workspace-title")
    call gtk.label_set_ellipsize(state["workspace_title"], 3)
    call pack(toolbar, state["workspace_title"], True)
    backdrop = gtk.combo_box_text_new()
    call gtk.combo_box_text_append(backdrop, "studio", t("Studio", "Studio"))
    call gtk.combo_box_text_append(backdrop, "light", t("Light", "Světlé"))
    call gtk.combo_box_text_append(backdrop, "transparent", t("Transparent", "Průhledné"))
    call gtk.combo_box_set_active(backdrop, 0)
    call native.connect(backdrop, "changed", background_changed, state)
    call pack(toolbar, backdrop)
    call pack(outer, toolbar)
    area = gtk.drawing_area_new()
    state["canvas"] = area
    call gtk.widget_set_vexpand(area, True)
    call gtk.widget_set_can_focus(area, True)
    call gtk.widget_set_hexpand(area, True)
    call gtk.widget_set_size_request(area, 250, 240)
    call __lsl_qbe_call2(__lsl_symbol("gtk_widget_add_events"), native.ptr(area), 772)
    call native.connect(area, "draw", draw, state, 1)
    call native.connect(area, "button-press-event", stage_clicked, state, 1)
    call native.connect(area, "motion-notify-event", stage_moved, state, 1)
    call native.connect(area, "button-release-event", stage_released, state, 1)
    call pack(outer, area, True)
    zoom = box(False, 7, "canvas-bottom")
    call pack(zoom, label(t("Canvas 1024 × 1024", "Plátno 1024 × 1024")), True)
    call pack(zoom, icon_button("zoom-out-symbolic", t("Zoom out", "Oddálit"), zoom_action, {"app": state, "value": -0.1}))
    state["zoom_label"] = label("100%")
    call pack(zoom, state["zoom_label"])
    call pack(zoom, icon_button("zoom-in-symbolic", t("Zoom in", "Přiblížit"), zoom_action, {"app": state, "value": 0.1}))
    call pack(zoom, button(t("Fit", "Přizpůsobit"), zoom_action, {"app": state, "value": 0}, "flat"))
    call pack(outer, zoom)
    strip = box(True, 9, "preview-strip")
    call pack(strip, label(t("Small sizes", "Malé velikosti"), "preview-title"))
    previews = box(False, 12)
    for size in [16, 32, 64]:
        column = box(True, 7, "preview-tile")
        image = gtk.image_new_from_icon_name("image-missing", 1)
        call gtk.widget_set_size_request(image, 66, 66)
        state["previews"].append([image, size])
        call pack(column, image)
        text = label(String(size) + " × " + String(size), "preview-caption")
        call gtk.widget_set_halign(text, 3)
        call pack(column, text)
        call pack(previews, column, True)
    end
    call pack(strip, previews)
    call pack(outer, strip)
    return outer
end

function new_window(path="", locale=""):
    global language
    language = locale
    if not language:
        lang = env.get("LANGUAGE", env.get("LC_ALL", env.get("LANG", "en")))
        language = "en"
        if lang.startswith("cs") or lang.startswith("sk"):
            language = "cs"
        end
    end
    call native.set_language(language)
    call gtk.css_load(icon_style.CSS)
    project = icon_model.new_project("aurora")
    state = {"project": project, "selected": "", "path": "", "saved": json.encode(project), "undo": [], "redo": [], "fields": {}, "previews": [], "layer_labels": {}, "syncing": False, "alive": True, "render_pending": False, "render_key": "", "pixbuf": 0, "zoom": 1.0, "background": "studio", "canvas_rect": [0.0, 0.0, 1]}
    window = gtk.window_new("Icon Studio")
    state["window"] = window
    call gtk.widget_add_class(window, "icon-studio")
    call gtk.window_set_icon_name(window, "luxos-icon-studio")
    call gtk.window_set_default_size(window, 1230, 820)
    header = __lsl_qbe_call0(__lsl_symbol("gtk_header_bar_new"))
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_show_close_button"), native.ptr(header), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_window_set_titlebar"), native.ptr(window), native.ptr(header))
    # Hlavicka jako ostatni aplikace LuxOS: tlacitka okna podle motivu, nazev dokumentu uprostred
    files = box(False, 4)
    call pack(files, icon_button("document-new-symbolic", t("New · Ctrl+N", "Nový · Ctrl+N"), new_project, state))
    call pack(files, icon_button("document-open-symbolic", t("Open · Ctrl+O", "Otevřít · Ctrl+O"), open_project, state))
    state["save_button"] = button(t("Save", "Uložit"), save, state)
    call pack(files, state["save_button"])
    call pack(files, icon_button("view-more-symbolic", t("Project menu", "Nabídka projektu"), project_menu, state))
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_pack_start"), native.ptr(header), native.ptr(files))
    actions = box(False, 4)
    state["undo_button"] = icon_button("edit-undo-symbolic", t("Undo · Ctrl+Z", "Zpět · Ctrl+Z"), undo, state)
    state["redo_button"] = icon_button("edit-redo-symbolic", t("Redo · Ctrl+Shift+Z", "Znovu · Ctrl+Shift+Z"), redo, state)
    call pack(actions, state["undo_button"])
    call pack(actions, state["redo_button"])
    state["export_button"] = button(t("Export…", "Exportovat…"), export_menu, state, "suggested-action")
    call pack(actions, state["export_button"])
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_pack_end"), native.ptr(header), native.ptr(actions))
    root = box(True, 0)
    body = box(False, 0)
    call pack(body, build_layers(state))
    call pack(body, build_canvas(state), True)
    call pack(body, build_inspector(state))
    call pack(root, body, True)
    bottom = box(False, 8, "statusbar")
    state["status"] = label(t("Ready", "Připraveno"))
    call pack(bottom, state["status"], True)
    call pack(root, bottom)
    call gtk.container_add(window, root)
    call native.connect(window, "delete-event", close_requested, state, 1)
    call native.connect(window, "destroy", destroyed, state)
    call native.connect(window, "key-press-event", key_pressed, state, 1)
    call restored(state)
    call gtk.widget_show_all(window)
    call sync_inspector(state)
    # fokus na platno, ne do pole s nazvem projektu (jinak je nazev po otevreni oznaceny)
    call __lsl_qbe_call1(__lsl_symbol("gtk_widget_grab_focus"), native.ptr(state["canvas"]))
    call __lsl_qbe_call3(__lsl_symbol("gtk_editable_select_region"), native.ptr(state["title_entry"]), 0, 0)
    if path:
        call open_path(state, path)
    end
    return state
end
