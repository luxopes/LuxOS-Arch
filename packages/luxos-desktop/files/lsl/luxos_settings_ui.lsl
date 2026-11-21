# lsl: link libgtk-3.so.0 libgdk-3.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - spolecne casti oken Nastaveni v LSL (luxos-settings, luxos-power, luxos-lock-settings): okno
# s HeaderBar velikosti podle pracovni plochy (jako luxos_winsize.py), skupiny radku ve stylu macOS,
# rozbalovaci seznamy s id, posuvnik s odlozenou zmenou, GSettings a soubory KLIC=hodnota.
#
#   ui.window(titulek, ikona, sirka, vyska, min_sirka, min_vyska) -> okno (vyska <= 0 = podle obsahu,
#                                     min_sirka <= 0 = nejmensi velikost podle obsahu)
#   ui.label(text, css), ui.group(page, titulek) -> {box, rows}, ui.row(g, titulek, napoveda, widget)
#   ui.combo(volby [[id, popisek]], aktivni, f, data)  f(data, id) po zmene; hodnota mimo volby se prida
#   ui.slider(od, do, hodnota, sirka, f, data)       f(data, cele cislo) 250 ms po posledni zmene
#   ui.switch(zapnuto, f, data)                      f(data, zapnuto) jen po zmene uzivatelem
#   ui.switch_set(sw, zapnuto)                       bez volani f
#   ui.wayland(), ui.read_kv(cesta), ui.write_kv(cesta, klic, hodnota), ui.touch(cesta), ui.sha1(text)
#   ui.gsettings(schema, cesta) -> objekt nebo 0, ui.gs_get_string/int/bool, ui.gs_set_string/int/bool
#   ui.run(argv) -> stdout bez mezer na koncich ("" pri chybe), ui.launch(argv) v nove relaci
#
# Testy: LUXOS_UI_TEST=soubor s prikazy (po radcich, po zobrazeni okna): dump (viditelne prvky do souboru.out),
# click POPISEK, switch RADEK on|off, combo RADEK ID, slider RADEK N, wait MS, quit. RADEK = titulek radku.
load env, process
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_text as text

TITLEBAR = 56
MARGIN = 16
MIN_WIDTH = 360
MIN_HEIGHT = 360

state = {"switches": {}, "combos": {}, "sliders": {}, "quiet": False, "rows": {}, "test": [], "window": 0}

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

function wayland():
    return env.get("WAYLAND_DISPLAY", "") != ""
end

# ---- okno -------------------------------------------------------------------------------------------------

function header_bar(window, title):
    unsafe:
        bar = __lsl_qbe_call0(__lsl_symbol("gtk_header_bar_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_show_close_button"), bar, 1)
        if title != "":
            call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_title"), bar, cstr(title))
        end
        call __lsl_qbe_call2(__lsl_symbol("gtk_window_set_titlebar"), ptr(window), bar)
        return bar
    end
end

function window_resize(window, width, height):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_window_resize"), ptr(window), ptr(width), ptr(height))
    end
end

# Vyska okna bez HeaderBar se vejde do pracovni plochy (bez listy a Docku), na 1366x768 i s tlacitky dole
function max_content_height():
    area = gtk.primary_monitor_workarea()
    return max(MIN_HEIGHT, area[3] - TITLEBAR - MARGIN)
end

function window(title, icon, width, height, min_width, min_height):
    w = gtk.window_new(title)
    call gtk.window_set_icon_list(w, icon)
    call header_bar(w, title)
    area = gtk.primary_monitor_workarea()
    width = min(width, max(MIN_WIDTH, area[2] - 2 * MARGIN))
    cap = max_content_height()
    if height > 0:
        height = min(height, cap)
    end
    call gtk.window_set_default_size(w, width, height)
    if min_width > 0:
        mh = min_height
        if height > 0:
            mh = min(mh, height)
        end
        call gtk.widget_set_size_request(w, min(min_width, width), min(mh, cap))
    end
    call gtk.connect(w, "map-event", on_map)
    state["window"] = w
    script = env.get("LUXOS_UI_TEST", "")
    if script != "":
        state["test"] = [line.strip() for line in glib.read_text(script).split("\n") if line.strip() != ""]
        call glib.timeout_add(800, test_step)
    end
    return w
end

# Po zobrazeni: skutecna vyska HeaderBar (s tlacitky vyssi nez odhad) - okno nesmi presahnout plochu
function on_map(event, w):
    area = gtk.primary_monitor_workarea()
    size = gtk.window_get_size(w)
    cap = area[3] - TITLEBAR - MARGIN
    if size[1] > cap and cap > 0:
        call window_resize(w, size[0], cap)
    end
    return False
end

# ---- radky -------------------------------------------------------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    call gtk.label_set_line_wrap(l, True)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function group(page, title):
    call gtk.box_pack_start(page, label(title, "group-title"), False, False, 0)
    g = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(g, "group")
    call gtk.box_pack_start(page, g, False, False, 0)
    return {"box": g, "rows": 0}
end

function row(g, title, hint, widget):
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(box, "row")
    if g["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    texts = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(texts, label(title, ""), False, False, 0)
    if hint != "":
        h = label(hint, "hint")
        call gtk.label_set_max_width_chars(h, 48)
        call gtk.box_pack_start(texts, h, False, False, 0)
    end
    call gtk.box_pack_start(box, texts, True, True, 0)
    if widget != 0:
        call gtk.widget_set_valign(widget, gtk.ALIGN_CENTER)
        call gtk.box_pack_end(box, widget, False, False, 0)
    end
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    g["rows"] = g["rows"] + 1
    state["rows"][title] = widget
    return box
end

# ---- ovladaci prvky ----------------------------------------------------------------------------------------

function combo_set_active_id(combo, id):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_combo_box_set_active_id"), ptr(combo), cstr(id)) != 0
    end
end

function combo_active_id(combo):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_combo_box_get_active_id"), ptr(combo)))
    end
end

# Hodnota mimo nabidku (od spravce, rucni zmena) se ukaze jako "N min", ne prvni polozka - ta by
# lhala o skutecnem nastaveni; custom = sablona popisku s %s
function combo(options, active, custom, handler, bound):
    c = gtk.combo_box_text_new()
    for item in options:
        call gtk.combo_box_text_append(c, String(item[0]), item[1])
    end
    active = String(active)
    if active != "" and not combo_set_active_id(c, active):
        if text.is_digits(active) and Int(active) > 0 and custom != "":
            call gtk.combo_box_text_append(c, active, custom.replace("%s", active))
            call combo_set_active_id(c, active)
        else:
            call gtk.combo_box_set_active(c, 0)
        end
    elif active == "":
        call gtk.combo_box_set_active(c, 0)
    end
    state["combos"][c] = [handler, bound]
    call gtk.connect(c, "changed", on_combo)
    return c
end

function on_combo(c):
    if state["quiet"] or not (c in state["combos"]):
        return 0
    end
    h = state["combos"][c]
    call h[0](h[1], combo_active_id(c))
    return 0
end

function switch(active, handler, bound):
    sw = gtk.switch_new()
    call gtk.switch_set_active(sw, active)
    state["switches"][sw] = [handler, bound]
    call gtk.connect(sw, "state-set", on_switch)
    return sw
end

function switch_set(sw, active):
    if gtk.switch_get_active(sw) == active:
        return 0
    end
    state["quiet"] = True
    call gtk.switch_set_active(sw, active)
    state["quiet"] = False
    return 0
end

function on_switch(on, sw):
    if not state["quiet"] and sw in state["switches"]:
        h = state["switches"][sw]
        call h[0](h[1], on != 0)
    end
    return False
end

# Posuvnik posila mnoho udalosti: zmena se aplikuje az po kratke pauze
function slider(lo, hi, value, width, handler, bound):
    s = gtk.scale_new_with_range(gtk.HORIZONTAL, lo, hi, 1)
    call gtk.range_set_value(s, Float(value))
    call gtk.scale_set_draw_value(s, False)
    call gtk.widget_set_size_request(s, width, -1)
    state["sliders"][s] = [handler, bound, 0]
    call gtk.connect(s, "value-changed", on_slider)
    return s
end

function on_slider(s):
    entry = state["sliders"][s]
    if entry[2] != 0:
        call glib.source_remove(entry[2])
    end
    entry[2] = glib.timeout_add_data(250, fire_slider, s)
    return 0
end

function fire_slider(s):
    entry = state["sliders"][s]
    entry[2] = 0
    call entry[0](entry[1], Int(gtk.range_get_value(s) + 0.5))
    return False
end

# Prepinac rezimu jako tlacitko (GtkRadioButton bez kolecka); group = prvni tlacitko skupiny nebo 0
function radio_button(group):
    unsafe:
        b = __lsl_qbe_call1(__lsl_symbol("gtk_radio_button_new_from_widget"), ptr(group))
        call __lsl_qbe_call2(__lsl_symbol("gtk_toggle_button_set_mode"), b, 0)
        return b
    end
end

# Okno se otevre nahore: GTK by jinak dal fokus prvnimu ovladacimu prvku a posunul k nemu
function scroll_to_top(window, scroll):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_window_set_focus"), ptr(window), 0)
        adj = __lsl_qbe_call1(__lsl_symbol("gtk_scrolled_window_get_vadjustment"), ptr(scroll))
        return __lsl_qbe_call2(__lsl_symbol("gtk_adjustment_set_value"), adj, 0.0)
    end
end

function new_sub_path(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_new_sub_path"), ptr(cr))
    end
end

function scroll_position(scroll):
    unsafe:
        adj = __lsl_qbe_call1(__lsl_symbol("gtk_scrolled_window_get_vadjustment"), ptr(scroll))
        return __lsl_qbe_fcall1(__lsl_symbol("gtk_adjustment_get_value"), adj)
    end
end

function spinner_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_spinner_new"))
    end
end

function spinner_run(spinner, on):
    unsafe:
        if on:
            return __lsl_qbe_call1(__lsl_symbol("gtk_spinner_start"), ptr(spinner))
        end
        return __lsl_qbe_call1(__lsl_symbol("gtk_spinner_stop"), ptr(spinner))
    end
end

# Mrizka nahledu (GtkFlowBox bez vyberu, stejne siroke bunky)
function flow_box(per_line, spacing):
    unsafe:
        f = __lsl_qbe_call0(__lsl_symbol("gtk_flow_box_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_flow_box_set_selection_mode"), f, 0)
        call __lsl_qbe_call2(__lsl_symbol("gtk_flow_box_set_max_children_per_line"), f, ptr(per_line))
        call __lsl_qbe_call2(__lsl_symbol("gtk_flow_box_set_column_spacing"), f, ptr(spacing))
        call __lsl_qbe_call2(__lsl_symbol("gtk_flow_box_set_row_spacing"), f, ptr(spacing))
        call __lsl_qbe_call2(__lsl_symbol("gtk_flow_box_set_homogeneous"), f, 1)
        return f
    end
end

# Vyber obrazku pres portal / GTK (GtkFileChooserNative); "" = zruseno
function choose_picture(parent, title, filter_name):
    unsafe:
        dlg = __lsl_qbe_call5(__lsl_symbol("gtk_file_chooser_native_new"), cstr(title), ptr(parent), 0, 0, 0)
        call gtk.file_chooser_add_filter(dlg, filter_name, ["image/*"])
        path = ""
        if __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_native_dialog_run"), dlg)) == gtk.RESPONSE_ACCEPT:
            path = gtk.file_chooser_get_filename(dlg)
        end
        call glib.object_unref(dlg)
        return path
    end
end

# ---- GSettings (Plank) -------------------------------------------------------------------------------------

function gsettings(schema, path):
    unsafe:
        source = __lsl_qbe_call0(__lsl_symbol("g_settings_schema_source_get_default"))
        if source == 0:
            return 0
        end
        found = __lsl_qbe_call3(__lsl_symbol("g_settings_schema_source_lookup"), source, cstr(schema), 1)
        if found == 0:
            return 0
        end
        call __lsl_qbe_call1(__lsl_symbol("g_settings_schema_unref"), found)
        return __lsl_qbe_call2(__lsl_symbol("g_settings_new_with_path"), cstr(schema), cstr(path))
    end
end

function gs_get_string(settings, key):
    unsafe:
        return glib.take_c(__lsl_qbe_call2(__lsl_symbol("g_settings_get_string"), ptr(settings), cstr(key)))
    end
end

function gs_get_int(settings, key):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("g_settings_get_int"), ptr(settings), cstr(key)))
    end
end

function gs_get_bool(settings, key):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("g_settings_get_boolean"), ptr(settings), cstr(key)) != 0
    end
end

function gs_set_string(settings, key, value):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("g_settings_set_string"), ptr(settings), cstr(key), cstr(value))
    end
end

function gs_set_int(settings, key, value):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("g_settings_set_int"), ptr(settings), cstr(key), ptr(value))
    end
end

function gs_set_bool(settings, key, value):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("g_settings_set_boolean"), ptr(settings), cstr(key), gtk.flag(value))
    end
end

# Zapis do dconf je asynchronni: pred koncem programu dokoncit
function gs_sync():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("g_settings_sync"))
    end
end

# ---- soubory -----------------------------------------------------------------------------------------------

function read_kv(path):
    out = {}
    for raw in glib.read_text(path).split("\n"):
        line = raw.strip()
        cut = line.find("=")
        if cut > 0:
            out[line[0:cut]] = line[cut + 1:]
        end
    end
    return out
end

# KEY=hodnota v souboru (ostatni radky beze zmeny), atomicky
function write_kv(path, key, value):
    lines = []
    for line in glib.read_text(path).split("\n"):
        if line != "" and not line.startswith(key + "="):
            lines.append(line)
        end
    end
    lines.append(key + "=" + value)
    call glib.mkdir_p(dirname(path))
    return glib.write_atomic(path, "\n".join(lines) + "\n")
end

function dirname(path):
    cut = text.rfind(path, "/")
    if cut <= 0:
        return "/"
    end
    return path[0:cut]
end

function touch(path):
    call glib.mkdir_p(dirname(path))
    if not exists(path):
        call glib.write_atomic(path, "")
    end
    return 0
end

function remove(path):
    if exists(path):
        call glib.unlink(path)
    end
    return 0
end

# G_CHECKSUM_SHA1 = 1
function sha1(text):
    unsafe:
        return glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_compute_checksum_for_string"), 1, cstr(text), -1))
    end
end

# Spusteni v nove relaci (jako subprocess.Popen(start_new_session=True)); chybejici program nevadi
function launch(argv):
    safe:
        call glib.spawn_quiet(argv)
    end
    return 0
end

function run(argv):
    program = glib.find_program_in_path(argv[0])
    if program == "":
        return ""
    end
    result = None
    safe:
        result = process.capture_result(program, argv[1:])
    end
    if result == None or not result["ok"]:
        return ""
    end
    return result["stdout"].strip()
end

# ---- testy (LUXOS_UI_TEST) ---------------------------------------------------------------------------------

function type_name(widget):
    unsafe:
        klass = __lsl_qbe_load64(ptr(widget))
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_type_name"), __lsl_qbe_load64(klass)))
    end
end

function is_a(widget, name):
    unsafe:
        gtype = __lsl_qbe_call1(__lsl_symbol("g_type_from_name"), cstr(name))
        return gtype != 0 and __lsl_qbe_call2(__lsl_symbol("g_type_check_instance_is_a"), ptr(widget), gtype) != 0
    end
end

function widget_mapped(widget):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_mapped"), ptr(widget)) != 0
    end
end

function button_label(button):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_button_get_label"), ptr(button)))
    end
end

function sensitive(widget):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_widget_is_sensitive"), ptr(widget)) != 0
    end
end

function walk(widget, out):
    if not widget_mapped(widget):
        return out
    end
    out.append(widget)
    if is_a(widget, "GtkContainer"):
        for child in gtk.container_get_children(widget):
            call walk(child, out)
        end
    end
    return out
end

function describe(widget):
    kind = type_name(widget)
    line = kind
    if is_a(widget, "GtkLabel"):
        line = line + "\t" + gtk.label_get_text(widget)
    elif is_a(widget, "GtkSwitch"):
        line = line + "\t" + ("on" if gtk.switch_get_active(widget) else "off")
    elif is_a(widget, "GtkComboBox"):
        line = line + "\t" + combo_active_id(widget)
    elif is_a(widget, "GtkRange"):
        line = line + "\t" + String(Int(gtk.range_get_value(widget) + 0.5))
    elif is_a(widget, "GtkScrolledWindow"):
        line = line + "\t" + String(Int(scroll_position(widget)))
    elif is_a(widget, "GtkButton"):
        caption = button_label(widget)
        if caption == "":
            for inner in walk(widget, []):
                if caption == "" and is_a(inner, "GtkLabel"):
                    caption = gtk.label_get_text(inner)
                end
            end
        end
        line = line + "\t" + caption
        toggled = is_a(widget, "GtkToggleButton") and gtk.toggle_button_get_active(widget)
        if toggled or gtk.widget_has_class(widget, "current") or gtk.widget_has_class(widget, "active"):
            line = line + " [current]"
        end
    end
    if not sensitive(widget):
        line = line + "\t(insensitive)"
    end
    return line
end

function find_button(text):
    for w in walk(state["window"], []):
        if is_a(w, "GtkButton") and button_label(w) == text:
            return w
        end
    end
    for w in walk(state["window"], []):
        if is_a(w, "GtkButton") and is_a(w, "GtkContainer"):
            for inner in walk(w, []):
                if is_a(inner, "GtkLabel") and gtk.label_get_text(inner) == text:
                    return w
                end
            end
        end
    end
    return 0
end

function test_step():
    while len(state["test"]) > 0:
        line = state["test"].pop(0)
        parts = line.split(" ")
        cmd = parts[0]
        arg = " ".join(parts[1:])
        if cmd == "wait":
            call glib.timeout_add(Int(arg), test_step)
            return False
        elif cmd == "quit":
            call gtk.main_quit()
            return False
        elif cmd == "dump":
            lines = [describe(w) for w in walk(state["window"], [])]
            out = env.get("LUXOS_UI_TEST", "") + ".out"
            call glib.write_atomic(out, glib.read_text(out) + "\n".join(lines) + "\n----\n")
        elif cmd == "click":
            b = find_button(arg)
            if b != 0:
                call gtk.button_clicked(b)
            end
        else:
            title = " ".join(parts[1:len(parts) - 1])
            value = parts[len(parts) - 1]
            w = state["rows"].get(title, 0)
            if w != 0 and cmd == "switch":
                call gtk.switch_set_active(w, value == "on")
            elif w != 0 and cmd == "combo":
                call combo_set_active_id(w, value)
            elif w != 0 and cmd == "slider":
                call gtk.range_set_value(w, Float(Int(value)))
            end
        end
    end
    return False
end
