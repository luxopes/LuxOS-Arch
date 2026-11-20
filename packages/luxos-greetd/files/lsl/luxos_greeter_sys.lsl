# lsl: link libgdk-3.so.0
# LuxOS - volani C pro prihlasovaci obrazovku (luxos-greeter), systemovy binding LSL (lslc --system-bindings).
#
#   caps_lock()          Caps Lock je zapnuty (GdkKeymap, funguje na Waylandu i X11)
#   key_group(udalost)   skupina xkb (rozlozeni) stisknute klavesy z GdkEventKey
#   epoch()              sekundy od 1970 (stav mezi spustenimi)

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function caps_lock():
    unsafe:
        display = __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
        if display == 0:
            return False
        end
        keymap = __lsl_qbe_call1(__lsl_symbol("gdk_keymap_get_for_display"), display)
        return (__lsl_qbe_call1(__lsl_symbol("gdk_keymap_get_caps_lock_state"), keymap) & 255) != 0
    end
end

# GdkEventKey: ... hardware_keycode (guint16, +48), group (guint8, +50)
function key_group(event):
    unsafe:
        return __lsl_qbe_load8(ptr(event) + 50) & 255
    end
end

function epoch():
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("time"), 0)
    end
end
