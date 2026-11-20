# lsl: link libgtk-3.so.0 libgdk-3.so.0 libgdk_pixbuf-2.0.so.0 libpango-1.0.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - volani C pro luxos-notify (GVariant, GdkPixbuf, GTK, GLib), at program sam C nevola.
#
#   real_time()                         us od epochy (g_get_real_time)
#   write_private(path, text)           atomicky zapis s pravy 0600
#   local_tz()                          identifikator mistniho casoveho pasma
#   child(v, i), child_value(v, i), unref(v)
#   notify_hints(a{sv}, size) -> [slovnik hintu bez obrazku, GdkPixbuf z image-data nebo 0]
#   register_raw(bus, path, xml, f)     objekt D-Bus, f(sender, metoda, parametry GVariant, invocation)
#   add_timeout(ms, zaznam), add_idle(zaznam, priorita)     zaznam z glib.record_new (jeden na cely beh)
#   label_set_lines, label_set_wrap_mode, label_cut(label)  zkraceny text (...)
#   crossing_inferior(udalost)          prechod mysi na vnoreny widget
#   markup_ok(text), save_png(pixbuf, cesta)
load glib, gtk, gio

handlers = []

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function real_time():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("g_get_real_time"))
    end
end

function write_private(path, text):
    unsafe:
        # G_FILE_SET_CONTENTS_CONSISTENT, 0600
        return __lsl_qbe_call6(__lsl_symbol("g_file_set_contents_full"), glib.cstr(path), glib.cstr(text), __lsl_text_byte_length(text), 1, 384, 0) != 0
    end
end

function local_tz():
    unsafe:
        zone = __lsl_qbe_call0(__lsl_symbol("g_time_zone_new_local"))
        name = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_time_zone_get_identifier"), zone))
        call __lsl_qbe_call1(__lsl_symbol("g_time_zone_unref"), zone)
    end
    return name
end

# ---- GVariant ----

function child(variant, index):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("g_variant_get_child_value"), ptr(variant), ptr(index))
    end
end

function child_value(variant, index):
    c = child(variant, index)
    value = gio.variant_to_value(c)
    call gio.variant_unref(c)
    return value
end

function unref(variant):
    return gio.variant_unref(variant)
end

function type_string(variant):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_variant_get_type_string"), ptr(variant)))
    end
end

# image-data (iiibiiay) -> GdkPixbuf zmenseny na size px; 0 pri nesmyslnych rozmerech nebo kratkych datech
function image_pixbuf(variant, size):
    width = child_value(variant, 0)
    height = child_value(variant, 1)
    stride = child_value(variant, 2)
    alpha = child_value(variant, 3)
    bits = child_value(variant, 4)
    channels = child_value(variant, 5)
    need = 3
    if alpha:
        need = 4
    end
    if width < 1 or height < 1 or width > 4096 or height > 4096 or bits != 8 or channels != need or stride < width * channels:
        return 0
    end
    data = child(variant, 6)
    result = 0
    unsafe:
        if stride * (height - 1) + width * channels <= __lsl_qbe_call1(__lsl_symbol("g_variant_get_size"), data):
            bytes = __lsl_qbe_call1(__lsl_symbol("g_variant_get_data_as_bytes"), data)
            full = __lsl_qbe_call7(__lsl_symbol("gdk_pixbuf_new_from_bytes"), bytes, 0, ptr(Bool(alpha)), 8, ptr(width), ptr(height), ptr(stride))
            call __lsl_qbe_call1(__lsl_symbol("g_bytes_unref"), bytes)
            if full != 0:
                w = size
                h = size
                if width > height:
                    h = max(1, size * height // width)
                elif height > width:
                    w = max(1, size * width // height)
                end
                # GDK_INTERP_BILINEAR
                result = gtk.pixbuf_scale_simple(full, w, h, 2)
                call glib.object_unref(full)
            end
        end
    end
    call gio.variant_unref(data)
    return result
end

function notify_hints(dict, size):
    hints = {}
    image = 0
    unsafe:
        count = __lsl_qbe_call1(__lsl_symbol("g_variant_n_children"), ptr(dict))
        index = 0
        while index < count and index < 64:
            entry = child(dict, index)
            key = child_value(entry, 0)
            boxed = child(entry, 1)
            inner = __lsl_qbe_call1(__lsl_symbol("g_variant_get_variant"), boxed)
            if key == "image-data" or key == "image_data" or key == "icon_data":
                if image == 0 and type_string(inner) == "(iiibiiay)":
                    image = image_pixbuf(inner, size)
                end
            else:
                hints[key] = gio.variant_to_value(inner)
            end
            call gio.variant_unref(inner)
            call gio.variant_unref(boxed)
            call gio.variant_unref(entry)
            index += 1
        end
    end
    return [hints, image]
end

# ---- D-Bus objekt s parametry GVariant (Notify: image-data bez prevodu po bajtech) ----

function register_raw(bus, path, xml, handler):
    unsafe:
        cell = gio.error_cell()
        info = __lsl_qbe_call2(__lsl_symbol("g_dbus_node_info_new_for_xml"), glib.cstr(xml), glib.array_data(cell))
        call gio.take_error(cell)
        iface = __lsl_qbe_load64(__lsl_qbe_load64(info + 16))
        vtable = __lsl_byte_zeros(88)
        __lsl_qbe_store64(glib.array_data(vtable), ptr(glib.callback_eighth()))
        record = glib.record_bound(raw_trampoline, 6, handler)
        # vtable a introspekce musi zit po celou registraci
        handlers.append([vtable, info])
        id = __lsl_qbe_call7(__lsl_symbol("g_dbus_connection_register_object"), ptr(bus), glib.cstr(path), iface, glib.array_data(vtable), ptr(record), 0, glib.array_data(cell))
        call gio.take_error(cell)
        return id
    end
end

function raw_trampoline(handler, sender, path, interface, method, params, invocation):
    return handler(glib.from_c(sender), glib.from_c(method), params, invocation)
end

# ---- zdroje hlavni smycky se stalym zaznamem obsluhy ----

function add_timeout(ms, record):
    unsafe:
        return __lsl_qbe_call5(__lsl_symbol("g_timeout_add_full"), 0, ptr(ms), glib.callback_first(), ptr(record), 0)
    end
end

function add_idle(record, priority):
    unsafe:
        return __lsl_qbe_call4(__lsl_symbol("g_idle_add_full"), ptr(priority), glib.callback_first(), ptr(record), 0)
    end
end

# ---- GTK a Pango ----

function label_set_lines(label, lines):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_label_set_lines"), ptr(label), ptr(lines))
    end
end

function label_set_wrap_mode(label, mode):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_label_set_line_wrap_mode"), ptr(label), ptr(mode))
    end
end

function label_cut(label):
    unsafe:
        layout = __lsl_qbe_call1(__lsl_symbol("gtk_label_get_layout"), ptr(label))
        return __lsl_qbe_icall1(__lsl_symbol("pango_layout_is_ellipsized"), layout) != 0
    end
end

# GdkEventCrossing.detail == GDK_NOTIFY_INFERIOR
function crossing_inferior(event):
    unsafe:
        return __lsl_qbe_load32(ptr(event) + 76) == 2
    end
end

function markup_ok(text):
    unsafe:
        return __lsl_qbe_call7(__lsl_symbol("pango_parse_markup"), glib.cstr(text), -1, 0, 0, 0, 0, 0) != 0
    end
end

function save_png(pixbuf, path):
    unsafe:
        return __lsl_qbe_call6(__lsl_symbol("gdk_pixbuf_savev"), ptr(pixbuf), glib.cstr(path), glib.cstr("png"), 0, 0, 0) != 0
    end
end
