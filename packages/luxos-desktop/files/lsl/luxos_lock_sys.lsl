# lsl: link libglib-2.0.so.0 libcairo.so.2 libpangocairo-1.0.so.0 libpango-1.0.so.0 libgobject-2.0.so.0
# LuxOS - volani C pro zamek obrazovky (luxos-lock, luxos-lock-session), at programy samy C nevolaji.
#
#   protect()                          proces nejde vypsat ani ladit jinym procesem uzivatele (PR_SET_DUMPABLE 0),
#                                      bez core dumpu: v pameti muze byt rozepsane heslo
#   spawn_lines(argv, envp, f, data)   program s rourou na stdin i stdout -> [pid, stdin] nebo [] pri chybe;
#                                      f(data, radek, 0) za kazdy radek stdout, po konci procesu jednou
#                                      f(data, "", status) (status jako waitpid); envp [] = prostredi tohoto procesu
#   real_name(), user_name()
#   source_pad(cr)                     zdroj cairo za okrajem opakuje krajni pixely (zvetsena tapeta bez tmaveho lemu)
#   battery(dir)                       prvni baterie z /sys/class/power_supply -> [procenta, nabiji] nebo None
#   network(dir, wireless)             sit z /sys/class/net a /proc/net/wireless -> ["wifi", 0-3], ["wired", 0], ["none", 0]
#
# Kresba stejna jako X11 (luxos-lock-ui.c a popisky GTK): pango s presnym popisem pisma a metrikami, maska A8 s
# rozmazanim jako stin textu GTK (gtkcairoblur.c), filtry a okraje vzoru cairo.
#   text_layout(cr, text, px, weight, family, spacing)   PangoLayout (uvolnit layout_unref); px absolutni velikost
#   extents(layout)                    [ink x, y, w, h, logical x, y, w, h] v jednotkach pango (1/1024 px)
#   char_pixels(layout), font_metrics(layout)   sirka znaku jako GtkLabel; [ascent, descent] pisma
#   cursor_x(layout, index)            vodorovna poloha kurzoru (jednotky pango)
#   layout_wrap(layout, width)         zalamovani slov na sirku (jednotky pango) se zarovnanim na stred
#   show_layout(cr, layout), layout_unref(layout)
#   mask_surface(w, h, scale, dx, dy), blur_a8(surface, radius), mask(cr, surface, x, y)
#   font_options(layout, hint_style, hint_metrics), filter(cr, f), extend(cr, e), fill_rule(cr, r), new_sub_path(cr)
#   device_scale(surface, scale), device_offset(surface, x, y), box_blur(surface, radius, passes, saturate), pixel_bgr(surface, x, y)
load glib
load luxos_glib as lglib
load luxos_text as ltext

PR_SET_DUMPABLE = 4
RLIMIT_CORE = 4
# G_SPAWN_DO_NOT_REAP_CHILD 2 | G_SPAWN_CLOEXEC_PIPES 256
SPAWN_FLAGS = 258

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function protect():
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("prctl"), PR_SET_DUMPABLE, 0)
        limit = __lsl_byte_zeros(16)
        call __lsl_qbe_call2(__lsl_symbol("setrlimit"), RLIMIT_CORE, lglib.data(limit))
    end
    return 0
end

# state = [handler, data, stdout, bezi, id zaznamu cteni, id zaznamu potomka, rozepsany radek, status]
function spawn_lines(argv, envp, handler, bound):
    unsafe:
        array = glib.cstr_array(argv)
        env_data = 0
        if len(envp) > 0:
            env_array = glib.cstr_array(envp)
            env_data = glib.array_data(env_array)
        end
        cells = __lsl_byte_zeros(32)
        base = lglib.data(cells)
        ok = __lsl_qbe_call11(__lsl_symbol("g_spawn_async_with_pipes"), 0, glib.array_data(array), env_data, SPAWN_FLAGS, 0, 0, base, base + 8, base + 16, 0, base + 24)
        if ok == 0:
            error = __lsl_qbe_load64(base + 24)
            if error != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            return []
        end
        pid = __lsl_qbe_s32(__lsl_qbe_load32(base))
        input = __lsl_qbe_s32(__lsl_qbe_load32(base + 8))
        out = __lsl_qbe_s32(__lsl_qbe_load32(base + 16))
        state = [handler, bound, out, True, 0, 0, "", 0]
        read_rec = lglib.track(lines_read, 2, state)
        child_rec = lglib.track(lines_exit, 2, state)
        state[4] = read_rec[1]
        state[5] = child_rec[1]
        # G_IO_IN 1 | G_IO_ERR 8 | G_IO_HUP 16
        call __lsl_qbe_call4(__lsl_symbol("g_unix_fd_add"), out, 25, __lsl_symbol("lsl_arch_callback_u3"), ptr(read_rec[0]))
        call __lsl_qbe_call5(__lsl_symbol("g_child_watch_add_full"), 0, pid, __lsl_symbol("lsl_arch_callback_u3"), ptr(child_rec[0]), 0)
        return [pid, input]
    end
end

function lines_read(state, handle, condition):
    unsafe:
        buffer = __lsl_byte_zeros(4096)
        n = __lsl_qbe_call3(__lsl_symbol("read"), ptr(handle), lglib.data(buffer), 4096)
        if n < 0 and lglib.interrupted():
            return True
        end
        if n > 0:
            text = state[6] + __lsl_text_from_bytes(buffer, 0, n)
            cut = text.find("\n")
            while cut >= 0:
                handler = state[0]
                call handler(state[1], text[0:cut], 0)
                text = text[cut + 1:]
                cut = text.find("\n")
            end
            state[6] = text
            return True
        end
        call __lsl_qbe_call1(__lsl_symbol("close"), ptr(handle))
    end
    state[2] = -1
    call lglib.release(state[4])
    if not state[3]:
        call lines_finish(state)
    end
    return False
end

function lines_exit(state, pid, status):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_spawn_close_pid"), ptr(pid))
    end
    state[3] = False
    state[7] = status
    call lglib.release(state[5])
    if state[2] == -1:
        call lines_finish(state)
    end
    return False
end

function lines_finish(state):
    handler = state[0]
    call handler(state[1], "", state[7])
    return 0
end

function real_name():
    unsafe:
        return glib.from_c(__lsl_qbe_call0(__lsl_symbol("g_get_real_name")))
    end
end

function user_name():
    unsafe:
        return glib.from_c(__lsl_qbe_call0(__lsl_symbol("g_get_user_name")))
    end
end

function source_pad(cr):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("cairo_pattern_set_extend"), __lsl_qbe_call1(__lsl_symbol("cairo_get_source"), ptr(cr)), 3)
    end
    return 0
end

# Prvni baterie zarizeni (ne mys ani klavesnice: scope Device); blesk i kdyz nabijecka drzi plnou baterii
function battery(base):
    mains = False
    found = None
    for name in lglib.list_dir(base):
        dir = base + "/" + name
        kind = lglib.read_text(dir + "/type").strip()
        if (kind == "Mains" or kind == "USB") and lglib.read_text(dir + "/online").strip() == "1":
            mains = True
        end
        cap = lglib.read_text(dir + "/capacity").strip()
        if found == None and kind == "Battery" and lglib.read_text(dir + "/scope").strip() != "Device" and ltext.is_digits(cap) and cap != "":
            found = [min(100, Int(cap)), lglib.read_text(dir + "/status").strip()]
        end
    end
    if found == None:
        return None
    end
    return [found[0], found[1] == "Charging" or (found[1] != "Discharging" and mains)]
end

# Pripojena rozhrani: Wi-Fi ma prednost (sila z /proc/net/wireless, kvalita z 70), pak kabel; mosty, kontejnery
# a VPN (virtualni zarizeni) se nepocitaji
function network(base, wireless):
    wired = False
    for name in lglib.list_dir(base):
        dir = base + "/" + name
        if name == "lo" or lglib.read_text(dir + "/operstate").strip() != "up":
            continue
        end
        if lglib.realpath(dir).find("/virtual/") >= 0:
            continue
        end
        if lglib.is_dir(dir + "/wireless"):
            level = 3
            for raw in lglib.read_text(wireless).split("\n"):
                words = [w for w in raw.strip().split(" ") if w != ""]
                if len(words) > 2 and words[0] == name + ":":
                    q = ltext.to_int(words[2].strip("."), 70)
                    level = 3
                    if q < 25:
                        level = 1
                    elif q < 50:
                        level = 2
                    end
                end
            end
            return ["wifi", level]
        end
        if lglib.read_text(dir + "/type").strip() == "1":
            wired = True
        end
    end
    if wired:
        return ["wired", 0]
    end
    return ["none", 0]
end

# ---- pango a cairo pro kresbu zamku ----

function text_layout(cr, text, px, weight, family, spacing):
    unsafe:
        layout = __lsl_qbe_call1(__lsl_symbol("pango_cairo_create_layout"), ptr(cr))
        desc = __lsl_qbe_call0(__lsl_symbol("pango_font_description_new"))
        call __lsl_qbe_call2(__lsl_symbol("pango_font_description_set_family"), desc, glib.cstr(family))
        call __lsl_qbe_call2(__lsl_symbol("pango_font_description_set_weight"), desc, ptr(weight))
        call __lsl_qbe_call2(__lsl_symbol("pango_font_description_set_absolute_size"), desc, Float(px) * 1024.0)
        call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_font_description"), layout, desc)
        call __lsl_qbe_call1(__lsl_symbol("pango_font_description_free"), desc)
        if spacing != 0:
            attrs = __lsl_qbe_call0(__lsl_symbol("pango_attr_list_new"))
            call __lsl_qbe_call2(__lsl_symbol("pango_attr_list_insert"), attrs, __lsl_qbe_call1(__lsl_symbol("pango_attr_letter_spacing_new"), ptr(spacing)))
            call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_attributes"), layout, attrs)
            call __lsl_qbe_call1(__lsl_symbol("pango_attr_list_unref"), attrs)
        end
        call __lsl_qbe_call3(__lsl_symbol("pango_layout_set_text"), layout, glib.cstr(text), -1)
        return layout
    end
end

function layout_unref(layout):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(layout))
    end
end

function rect_at(base):
    unsafe:
        return [__lsl_qbe_s32(__lsl_qbe_load32(base)), __lsl_qbe_s32(__lsl_qbe_load32(base + 4)),
                __lsl_qbe_s32(__lsl_qbe_load32(base + 8)), __lsl_qbe_s32(__lsl_qbe_load32(base + 12))]
    end
end

function extents(layout):
    unsafe:
        cells = __lsl_byte_zeros(32)
        base = lglib.data(cells)
        call __lsl_qbe_call3(__lsl_symbol("pango_layout_get_extents"), ptr(layout), base, base + 16)
        return rect_at(base) + rect_at(base + 16)
    end
end

function metrics_of(layout):
    unsafe:
        context = __lsl_qbe_call1(__lsl_symbol("pango_layout_get_context"), ptr(layout))
        desc = __lsl_qbe_call1(__lsl_symbol("pango_layout_get_font_description"), ptr(layout))
        return __lsl_qbe_call3(__lsl_symbol("pango_context_get_metrics"), context, desc, __lsl_qbe_call1(__lsl_symbol("pango_context_get_language"), context))
    end
end

# Jako get_char_pixels v gtklabel.c: vetsi z prumerne sirky znaku a cislice
function char_pixels(layout):
    unsafe:
        m = metrics_of(layout)
        a = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_font_metrics_get_approximate_char_width"), m))
        b = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_font_metrics_get_approximate_digit_width"), m))
        call __lsl_qbe_call1(__lsl_symbol("pango_font_metrics_unref"), m)
        return max(a, b)
    end
end

function font_metrics(layout):
    unsafe:
        m = metrics_of(layout)
        a = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_font_metrics_get_ascent"), m))
        d = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_font_metrics_get_descent"), m))
        call __lsl_qbe_call1(__lsl_symbol("pango_font_metrics_unref"), m)
        return [a, d]
    end
end

function cursor_x(layout, index):
    unsafe:
        cells = __lsl_byte_zeros(32)
        base = lglib.data(cells)
        call __lsl_qbe_call4(__lsl_symbol("pango_layout_get_cursor_pos"), ptr(layout), ptr(index), base, base + 16)
        return rect_at(base)
    end
end

function layout_wrap(layout, width):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_wrap"), ptr(layout), 0)
        call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_alignment"), ptr(layout), 1)
        return __lsl_qbe_call2(__lsl_symbol("pango_layout_set_width"), ptr(layout), ptr(width))
    end
end

function layout_ellipsize(layout, width):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_ellipsize"), ptr(layout), 3)
        return __lsl_qbe_call2(__lsl_symbol("pango_layout_set_width"), ptr(layout), ptr(width))
    end
end

function line_count(layout):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_layout_get_line_count"), ptr(layout)))
    end
end

function show_layout(cr, layout):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("pango_cairo_show_layout"), ptr(cr), ptr(layout))
    end
end

# Maska A8 v pixelech zarizeni (w, h logicky), pocatek posunuty o dx, dy (logicky)
function mask_surface(w, h, scale, dx, dy):
    unsafe:
        s = __lsl_qbe_call3(__lsl_symbol("cairo_image_surface_create"), 2, ptr(Int(Float(w) * scale)), ptr(Int(Float(h) * scale)))
        call __lsl_qbe_call3(__lsl_symbol("cairo_surface_set_device_scale"), s, Float(scale), Float(scale))
        call __lsl_qbe_call3(__lsl_symbol("cairo_surface_set_device_offset"), s, Float(dx) * scale, Float(dy) * scale)
        return s
    end
end

function mask(cr, surface, x, y):
    unsafe:
        return __lsl_qbe_call4(__lsl_symbol("cairo_mask_surface"), ptr(cr), ptr(surface), Float(x), Float(y))
    end
end

# Jeden pruchod krabicoveho rozmazani GTK (blur_xspan) nad n bajty po step: soucet v okne d, zaokrouhleni
# (soucet + d/2) / d, pro sude d posun shift
function gtk_span(start, step, n, d, shift, tmp):
    unsafe:
        offset = d // 2
        if d % 2 == 0:
            offset = (d - shift) // 2
        end
        total = 0
        half = d // 2
        i = offset - d
        stop = n + offset
        while i < stop:
            if i >= 0 and i < n:
                total = total + (__lsl_qbe_load8(start + i * step) & 255)
            end
            if i >= offset:
                if i >= d:
                    total = total - (__lsl_qbe_load8(start + (i - d) * step) & 255)
                end
                call __lsl_qbe_store8(tmp + i - offset, (total + half) // d)
            end
            i = i + 1
        end
        k = 0
        while k < n:
            call __lsl_qbe_store8(start + k * step, __lsl_qbe_load8(tmp + k) & 255)
            k = k + 1
        end
    end
    return 0
end

function gtk_line(start, step, n, d, tmp):
    if d % 2 == 1:
        call gtk_span(start, step, n, d, 0, tmp)
        call gtk_span(start, step, n, d, 0, tmp)
        call gtk_span(start, step, n, d, 0, tmp)
    else:
        call gtk_span(start, step, n, d, 1, tmp)
        call gtk_span(start, step, n, d, -1, tmp)
        call gtk_span(start, step, n, d + 1, 0, tmp)
    end
    return 0
end

# _gtk_cairo_blur_surface (GTK 3.24): jen pro polomer > 1, nejdriv sloupce, pak radky; sirka radku je stride
function blur_a8(surface, radius):
    r = Int(radius)
    if r <= 1:
        return 0
    end
    # GAUSSIAN_SCALE_FACTOR = 3 * sqrt(2 * pi) / 4
    d = Int(1.8799712059732503 * Float(r))
    unsafe:
        s = ptr(surface)
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_flush"), s)
        data = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), s)
        stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), s))
        h = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_height"), s))
        tmp = __lsl_qbe_call1(__lsl_symbol("malloc"), max(stride, h) + 1)
        x = 0
        while x < stride:
            call gtk_line(data + x, stride, h, d, tmp)
            x = x + 1
        end
        y = 0
        while y < h:
            call gtk_line(data + y * stride, 1, stride, d, tmp)
            y = y + 1
        end
        call __lsl_qbe_call1(__lsl_symbol("free"), tmp)
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_mark_dirty"), s)
    end
    return 0
end

function filter(cr, f):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("cairo_pattern_set_filter"), __lsl_qbe_call1(__lsl_symbol("cairo_get_source"), ptr(cr)), ptr(f))
    end
end

function extend(cr, e):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("cairo_pattern_set_extend"), __lsl_qbe_call1(__lsl_symbol("cairo_get_source"), ptr(cr)), ptr(e))
    end
end

function fill_rule(cr, r):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("cairo_set_fill_rule"), ptr(cr), ptr(r))
    end
end

function new_sub_path(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_new_sub_path"), ptr(cr))
    end
end

function device_scale(surface, scale):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("cairo_surface_set_device_scale"), ptr(surface), Float(scale), Float(scale))
    end
end

# Krabicove rozmazani malé tapety RGB24 jako box_blur v luxos-lock-ui.c (kanaly ve Float, okraj opakuje krajni
# pixel, pak sytost); w x h je jen ~100 x 64 pixelu
function blur_line(src, dst, start, step, n, radius):
    win = Float(2 * radius + 1)
    acc = src[start] * Float(radius + 1)
    for i in range(radius):
        acc = acc + src[start + min(i, n - 1) * step]
    end
    for i in range(n):
        acc = acc + src[start + min(i + radius, n - 1) * step] - src[start + max(i - radius - 1, 0) * step]
        dst[start + i * step] = acc / win
    end
    return 0
end

function box_blur(surface, radius, passes, saturate):
    unsafe:
        s = ptr(surface)
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_flush"), s)
        data = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), s)
        stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), s))
        w = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_width"), s))
        h = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_height"), s))
    end
    n = w * h
    ch = [[0.0 for i in range(n)] for c in range(3)]
    tmp = [0.0 for i in range(n)]
    unsafe:
        for y in range(h):
            for x in range(w):
                for c in range(3):
                    ch[c][y * w + x] = Float(__lsl_qbe_load8(data + y * stride + 4 * x + c) & 255)
                end
            end
        end
    end
    for c in range(3):
        for p in range(passes):
            for y in range(h):
                call blur_line(ch[c], tmp, y * w, 1, w, radius)
            end
            for x in range(w):
                call blur_line(tmp, ch[c], x, w, h, radius)
            end
        end
    end
    unsafe:
        for y in range(h):
            for x in range(w):
                i = y * w + x
                o = data + y * stride + 4 * x
                b = ch[0][i]
                g = ch[1][i]
                r = ch[2][i]
                lum = 0.0722 * b + 0.7152 * g + 0.2126 * r
                call __lsl_qbe_store8(o, min(255, max(0, Int(lum + (b - lum) * saturate))))
                call __lsl_qbe_store8(o + 1, min(255, max(0, Int(lum + (g - lum) * saturate))))
                call __lsl_qbe_store8(o + 2, min(255, max(0, Int(lum + (r - lum) * saturate))))
            end
        end
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_mark_dirty"), s)
    end
    return 0
end

# Bajty pixelu RGB24 [B, G, R] (vzorkovani jasu pod polem)
function pixel_bgr(surface, x, y):
    unsafe:
        s = ptr(surface)
        data = __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), s)
        stride = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), s))
        o = data + ptr(y) * stride + ptr(x) * 4
        return [__lsl_qbe_load8(o) & 255, __lsl_qbe_load8(o + 1) & 255, __lsl_qbe_load8(o + 2) & 255]
    end
end

# Volby pisma rozvrzeni: hint_style 0 vychozi .. 4 plne, hint_metrics 0 vychozi, 1 vyp, 2 zap
function font_options(layout, hint_style, hint_metrics, antialias, order):
    unsafe:
        opts = __lsl_qbe_call0(__lsl_symbol("cairo_font_options_create"))
        call __lsl_qbe_call2(__lsl_symbol("cairo_font_options_set_antialias"), opts, ptr(antialias))
        call __lsl_qbe_call2(__lsl_symbol("cairo_font_options_set_subpixel_order"), opts, ptr(order))
        call __lsl_qbe_call2(__lsl_symbol("cairo_font_options_set_hint_style"), opts, ptr(hint_style))
        call __lsl_qbe_call2(__lsl_symbol("cairo_font_options_set_hint_metrics"), opts, ptr(hint_metrics))
        call __lsl_qbe_call2(__lsl_symbol("pango_cairo_context_set_font_options"), __lsl_qbe_call1(__lsl_symbol("pango_layout_get_context"), ptr(layout)), opts)
        call __lsl_qbe_call1(__lsl_symbol("cairo_font_options_destroy"), opts)
        return __lsl_qbe_call1(__lsl_symbol("pango_layout_context_changed"), ptr(layout))
    end
end

# Uciari prvniho radku od horniho okraje (jednotky pango)
function baseline(layout):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_layout_get_baseline"), ptr(layout)))
    end
end

function device_offset(surface, x, y):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("cairo_surface_set_device_offset"), ptr(surface), Float(x), Float(y))
    end
end
