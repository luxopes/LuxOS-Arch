# lsl: internal-abi
# lsl: link libgtk-layer-shell.so.0 libgtk-3.so.0 libgdk-3.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - okna shellu na Waylandu (gtk-layer-shell 0.10, GTK 3): lista, Dock, plocha, oznameni a Launchpad
# jako vrstvy kompozitoru misto beznych oken. Modul je samostatny (nic z luxos_*), aby se dal presunout do
# adresare systemovych vazeb LSL. Nazvy = funkce gtk_layer_ bez predpony.
#
#   is_supported(), protocol_version(), version() -> [major, minor, micro]
#   init_for_window(okno)            pred prvnim zobrazenim okna
#   is_layer_window(okno)
#   set_namespace(okno, nazev)       "luxos-bar", "luxos-dock" (pravidla kompozitoru)
#   set_layer(okno, LAYER_*), set_monitor(okno, monitor) (0 = vybere kompozitor)
#   set_anchor(okno, EDGE_*, zap), set_anchors(okno, [EDGE_*..]) (ostatni okraje uvolni)
#   set_margin(okno, EDGE_*, px), set_exclusive_zone(okno, px), auto_exclusive_zone_enable(okno)
#   set_keyboard_mode(okno, KEYBOARD_*), set_respect_close(okno, zap), try_force_commit(okno)
#   get_layer, get_anchor(okno, hrana), get_margin(okno, hrana), get_exclusive_zone, get_keyboard_mode,
#   get_namespace, get_monitor, auto_exclusive_zone_is_enabled
# Monitory GDK: monitors() -> [monitor..], monitor_geometry(m) -> [x, y, w, h], monitor_model(m)
# Spojeni pro luxos_wl: is_wayland(), wl_display() -> wl_display GDK (0 mimo Wayland)
#
# Program musi mit libgtk-layer-shell v DT_NEEDED pred libwayland-client (knihovna podstrkuje vlastni
# xdg_surface); primo nactena knihovna programu to splnuje vzdy, libwayland-client prijde az s GDK.
load glib

LAYER_BACKGROUND = 0
LAYER_BOTTOM = 1
LAYER_TOP = 2
LAYER_OVERLAY = 3

EDGE_LEFT = 0
EDGE_RIGHT = 1
EDGE_TOP = 2
EDGE_BOTTOM = 3

KEYBOARD_NONE = 0
KEYBOARD_EXCLUSIVE = 1
KEYBOARD_ON_DEMAND = 2

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

function flag(value):
    if value:
        return 1
    end
    return 0
end

function is_supported():
    unsafe:
        return __lsl_qbe_icall0(__lsl_symbol("gtk_layer_is_supported")) != 0
    end
end

function protocol_version():
    unsafe:
        return __lsl_qbe_icall0(__lsl_symbol("gtk_layer_get_protocol_version"))
    end
end

function version():
    unsafe:
        return [__lsl_qbe_icall0(__lsl_symbol("gtk_layer_get_major_version")), __lsl_qbe_icall0(__lsl_symbol("gtk_layer_get_minor_version")), __lsl_qbe_icall0(__lsl_symbol("gtk_layer_get_micro_version"))]
    end
end

function init_for_window(window):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_layer_init_for_window"), ptr(window))
    end
end

function is_layer_window(window):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("gtk_layer_is_layer_window"), ptr(window)) != 0
    end
end

function set_namespace(window, name):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_layer_set_namespace"), ptr(window), cstr(name))
    end
end

function get_namespace(window):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_layer_get_namespace"), ptr(window)))
    end
end

function set_layer(window, layer):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_layer_set_layer"), ptr(window), ptr(layer))
    end
end

function get_layer(window):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("gtk_layer_get_layer"), ptr(window))
    end
end

function set_monitor(window, monitor):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_layer_set_monitor"), ptr(window), ptr(monitor))
    end
end

function get_monitor(window):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_layer_get_monitor"), ptr(window))
    end
end

function set_anchor(window, edge, on):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_layer_set_anchor"), ptr(window), ptr(edge), flag(on))
    end
end

function set_anchors(window, edges):
    for edge in [EDGE_LEFT, EDGE_RIGHT, EDGE_TOP, EDGE_BOTTOM]:
        call set_anchor(window, edge, edge in edges)
    end
    return 0
end

function get_anchor(window, edge):
    unsafe:
        return __lsl_qbe_icall2(__lsl_symbol("gtk_layer_get_anchor"), ptr(window), ptr(edge)) != 0
    end
end

function set_margin(window, edge, size):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_layer_set_margin"), ptr(window), ptr(edge), ptr(size))
    end
end

function get_margin(window, edge):
    unsafe:
        return __lsl_qbe_icall2(__lsl_symbol("gtk_layer_get_margin"), ptr(window), ptr(edge))
    end
end

function set_exclusive_zone(window, size):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_layer_set_exclusive_zone"), ptr(window), ptr(size))
    end
end

function get_exclusive_zone(window):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("gtk_layer_get_exclusive_zone"), ptr(window))
    end
end

function auto_exclusive_zone_enable(window):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_layer_auto_exclusive_zone_enable"), ptr(window))
    end
end

function auto_exclusive_zone_is_enabled(window):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("gtk_layer_auto_exclusive_zone_is_enabled"), ptr(window)) != 0
    end
end

function set_keyboard_mode(window, mode):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_layer_set_keyboard_mode"), ptr(window), ptr(mode))
    end
end

function get_keyboard_mode(window):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("gtk_layer_get_keyboard_mode"), ptr(window))
    end
end

# Zavreni okna kompozitorem (closed) jako delete-event GTK, ne okamzite skryti
function set_respect_close(window, on):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_layer_set_respect_close"), ptr(window), flag(on))
    end
end

function try_force_commit(window):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_layer_try_force_commit"), ptr(window))
    end
end

# ---- monitory a spojeni GDK ----

function default_display():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
    end
end

function monitors():
    display = default_display()
    result = []
    if display == 0:
        return result
    end
    unsafe:
        count = __lsl_qbe_icall1(__lsl_symbol("gdk_display_get_n_monitors"), ptr(display))
        index = 0
        while index < count:
            result.append(__lsl_qbe_call2(__lsl_symbol("gdk_display_get_monitor"), ptr(display), index))
            index += 1
        end
    end
    return result
end

function monitor_geometry(monitor):
    unsafe:
        rect = __lsl_byte_zeros(16)
        base = __lsl_qbe_load64(__lsl_address(rect) + 24)
        call __lsl_qbe_call2(__lsl_symbol("gdk_monitor_get_geometry"), ptr(monitor), base)
        return [__lsl_qbe_s32(__lsl_qbe_load32(base)), __lsl_qbe_s32(__lsl_qbe_load32(base + 4)), __lsl_qbe_s32(__lsl_qbe_load32(base + 8)), __lsl_qbe_s32(__lsl_qbe_load32(base + 12))]
    end
end

function monitor_model(monitor):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("gdk_monitor_get_model"), ptr(monitor)))
    end
end

function is_wayland():
    display = default_display()
    if display == 0:
        return False
    end
    unsafe:
        kind = __lsl_qbe_call0(__lsl_symbol("gdk_wayland_display_get_type"))
        return __lsl_qbe_icall2(__lsl_symbol("g_type_check_instance_is_a"), ptr(display), kind) != 0
    end
end

function wl_display():
    if not is_wayland():
        return 0
    end
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gdk_wayland_display_get_wl_display"), ptr(default_display()))
    end
end
