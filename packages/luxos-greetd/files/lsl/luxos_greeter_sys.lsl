# lsl: link libgdk-3.so.0
# lsl: link libcairo.so.2
# LuxOS - volani C pro prihlasovaci obrazovku (luxos-greeter), systemovy binding LSL (lslc --system-bindings).
#
#   caps_lock()          Caps Lock je zapnuty (GdkKeymap, funguje na Waylandu i X11)
#   key_group(udalost)   skupina xkb (rozlozeni) stisknute klavesy z GdkEventKey
#   epoch()              sekundy od 1970 (stav mezi spustenimi)
#   write_frame(cesta, povrch)  obraz cairo do souboru "LUXFRAME1 <w> <h>\n" + w*h*4 bajtu BGRx; True = ok

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

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

# Argumenty z jine funkce jsou hodnoty LSL: do C az po ptr()
function write_all(fd, at, n):
    unsafe:
        f = ptr(fd)
        p = ptr(at)
        left = ptr(n)
        while left > 0:
            done = __lsl_qbe_call3(__lsl_symbol("write"), f, p, left)
            if done <= 0 or done > left:
                return False
            end
            p = p + done
            left = left - done
        end
    end
    return True
end

# Docasny soubor + prejmenovani: relace nikdy nenacte pulku snimku. Slozka patri greeteru (nikdo jiny do ni
# nezapise), soubor 0644 - cte ho uzivatel relace. O_EXCL | O_NOFOLLOW: nikdy pres cizi soubor nebo odkaz.
function write_frame(path, surface):
    tmp = path + ".tmp"
    ok = False
    unsafe:
        s = ptr(surface)
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_flush"), s)
        w = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_width"), s))
        h = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_height"), s))
        stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), s))
        data = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), s)
        if data == 0 or w <= 0 or h <= 0:
            return False
        end
        call __lsl_qbe_call1(__lsl_symbol("unlink"), cstr(tmp))
        # O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC
        fd = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("open"), cstr(tmp), 1 + 64 + 128 + 131072 + 524288, 420))
        if fd < 0:
            return False
        end
        call __lsl_qbe_call2(__lsl_symbol("fchmod"), fd, 420)
        header = "LUXFRAME1 " + String(w) + " " + String(h) + chr(10)
        ok = write_all(fd, cstr(header), len(header))
        if ok and stride == w * 4:
            ok = write_all(fd, data, stride * h)
        else:
            row = 0
            while ok and row < h:
                ok = write_all(fd, data + row * stride, w * 4)
                row = row + 1
            end
        end
        if __lsl_qbe_call1(__lsl_symbol("close"), fd) != 0:
            ok = False
        end
        if ok:
            ok = __lsl_qbe_call2(__lsl_symbol("rename"), cstr(tmp), cstr(path)) == 0
        end
        if not ok:
            call __lsl_qbe_call1(__lsl_symbol("unlink"), cstr(tmp))
        end
    end
    return ok
end
