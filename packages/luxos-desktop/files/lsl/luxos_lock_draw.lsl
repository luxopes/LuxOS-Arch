# LuxOS - kresba zamykaci obrazovky na Waylandu (luxos-lock): jedna plocha na monitor, vse cairem.
# Vzhled a rozmery jako luxos-lock-ui.c (xfce4-screensaver) a luxos-greeter: datum a velke tenke hodiny
# nahore, dole kulaty avatar, jmeno, matne pole pro heslo se sipkou, hlaska, Caps Lock a rozlozeni,
# vpravo nahore baterie. Pozadi je rozostrena tapeta z luxos_material (stejne sklo jako lista a Dock).
#
#   draw.frame(cr, w, h, ui, gl)   cela plocha; ui = stav (viz luxos-lock.lsl), gl = material.glass nebo None
#   draw.field_rect(w, h, dx)      [x, y, w, h] pole pro heslo (testy: kde hledat tecky)
load cairo, pango, gtk, glib
load luxos_material as material
load luxos_tokens as tokens
load luxos_lock_sys as sys

PI = cairo.PI

function px(u, v, lo):
    return max(Float(lo), Float(Int(v * u + 0.5)))
end

function unit(h):
    return max(0.55, Float(h) / 1080.0)
end

function font(ui, weight, size):
    return ui["font"] + ",Inter,Cantarell,Noto Sans " + weight + " " + String(Int(size + 0.5)) + "px"
end

function text_layout(cr, text, desc):
    layout = pango.cairo_create_layout(cr)
    call pango.layout_set_font(layout, desc)
    call pango.layout_set_text(layout, text)
    return layout
end

# Mekky stin jako shadow_text v luxos-lock-ui.c: posunute kopie s malou pruhlednosti, pak bily text
function shadow_text(cr, layout, x, y, alpha, blur):
    for off in [[0.0, 1.0], [0.0, 2.0], [-1.0, 1.5], [1.0, 1.5], [0.0, 3.0]]:
        call cairo.move_to(cr, x + off[0] * blur * 0.35, y + off[1] * blur * 0.45)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.055 * alpha)
        call pango.cairo_show_layout(cr, layout)
    end
    call cairo.move_to(cr, x, y)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alpha)
    call pango.cairo_show_layout(cr, layout)
    return 0
end

function centered_text(cr, text, desc, cx, y, alpha, blur):
    layout = text_layout(cr, text, desc)
    size = pango.layout_get_pixel_size(layout)
    call shadow_text(cr, layout, cx - Float(size[0]) / 2.0, y, alpha, blur)
    call pango.layout_unref(layout)
    return size
end

function pill(cr, x, y, w, h):
    call material.rounded_path(cr, x, y, w, h, h / 2.0)
    return 0
end

# ---- pozadi ----

function background(cr, w, h, gl):
    if gl == None:
        call cairo.set_source_rgb(cr, 0.10, 0.11, 0.25)
        call cairo.paint(cr)
    else:
        m = material.map_for(gl, w, h)
        call cairo.save(cr)
        call cairo.scale(cr, 1.0 / m[2], 1.0 / m[2])
        call cairo.set_source_surface(cr, gl[0], -m[3], -m[4])
        call sys.source_pad(cr)
        call cairo.paint(cr)
        call cairo.restore(cr)
    end
    # ztmaveni jako prihlasovaci stav luxos-lock-ui.c: bile pismo citelne i na svetle tapete
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.30)
    call cairo.paint(cr)
    return 0
end

function clock(cr, w, h, ui, u):
    cx = Float(w) / 2.0
    y = Float(h) * 0.06
    size = centered_text(cr, ui["date"], font(ui, "Semi-Bold", tokens.FONT["lock_date"] * u), cx, y, 0.81, 2.0 * u)
    big = tokens.FONT["lock_clock"] * u
    # horni okraj cislic tesne pod datum (logicka vyska ma nad cislicemi asi petinu velikosti)
    call centered_text(cr, ui["clock"], font(ui, "Ultra-Light", big), cx, y + Float(size[1]) + 14.0 * u - big * 0.2, 0.88, 4.0 * u)
    return 0
end

# ---- avatar a jmeno ----

function avatar(cr, cx, cy, d, ui):
    r = d / 2.0
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy + d * 0.03, r + 1.0, 0.0, 2.0 * PI)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.18)
    call cairo.fill(cr)
    call cairo.save(cr)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r, 0.0, 2.0 * PI)
    call cairo.clip(cr)
    face = ui["face"]
    if face != None:
        fw = Float(gtk.pixbuf_get_width(face))
        fh = Float(gtk.pixbuf_get_height(face))
        sc = max(d / fw, d / fh)
        call cairo.translate(cr, cx - fw * sc / 2.0, cy - fh * sc / 2.0)
        call cairo.scale(cr, sc, sc)
        call gtk.cairo_set_source_pixbuf(cr, face, 0.0, 0.0)
        call cairo.paint(cr)
    else:
        g = cairo.pattern_create_linear(cx - r, cy - r, cx + r, cy + r)
        call cairo.pattern_add_color_stop_rgba(g, 0.0, 0.30, 0.52, 1.0, 1.0)
        call cairo.pattern_add_color_stop_rgba(g, 1.0, 0.66, 0.42, 0.98, 1.0)
        call cairo.set_source(cr, g)
        call cairo.paint(cr)
        call cairo.pattern_destroy(g)
        initial = ui["name"].strip()
        if initial == "":
            initial = "?"
        end
        layout = text_layout(cr, initial[0].upper(), font(ui, "Medium", d * 0.44))
        size = pango.layout_get_pixel_size(layout)
        call cairo.move_to(cr, cx - Float(size[0]) / 2.0, cy - Float(size[1]) / 2.0)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.97)
        call pango.cairo_show_layout(cr, layout)
        call pango.layout_unref(layout)
    end
    call cairo.restore(cr)
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, r - 0.5, 0.0, 2.0 * PI)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.22)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    return 0
end

# ---- pole pro heslo ----

function field_rect(w, h, dx):
    u = unit(h)
    fw = px(u, 250.0, 180)
    fh = px(u, 36.0, 28)
    bottom = Float(h) - px(u, 150.0, 110)
    y = bottom - px(u, 24.0, 18) - px(u, 14.0, 9) - px(u, 22.0, 16) - px(u, 14.0, 9) - fh
    return [(Float(w) - fw) / 2.0 + dx, y, fw, fh]
end

function arrow(cr, cx, cy, s):
    call cairo.set_line_width(cr, max(1.5, s * 0.11))
    call cairo.set_line_cap(cr, cairo.LINE_CAP_ROUND)
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.new_path(cr)
    call cairo.move_to(cr, cx - s * 0.3, cy)
    call cairo.line_to(cr, cx + s * 0.3, cy)
    call cairo.move_to(cr, cx + s * 0.05, cy - s * 0.25)
    call cairo.line_to(cr, cx + s * 0.3, cy)
    call cairo.line_to(cr, cx + s * 0.05, cy + s * 0.25)
    call cairo.stroke(cr)
    return 0
end

function field(cr, w, h, ui, gl, u):
    r = field_rect(w, h, ui["shake"] * u)
    x = r[0]
    y = r[1]
    fw = r[2]
    fh = r[3]
    pad = px(u, 16.0, 11)
    # matne sklo pod polem (DEST_OVER: kreslit na prazdne misto), pak tmavy zavoj pro bily text
    call cairo.save(cr)
    call material.push_group(cr)
    if gl != None:
        call material.paint(cr, x, y, fw, fh, fh / 2.0, x, y, 0, gl, material.map_for(gl, w, h))
    end
    call pill(cr, x, y, fw, fh)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.34)
    call cairo.fill(cr)
    call pill(cr, x + 0.5, y + 0.5, fw - 1.0, fh - 1.0)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.18)
    call cairo.set_line_width(cr, 1.0)
    call cairo.stroke(cr)
    call material.pop_group_to_source(cr)
    call cairo.paint(cr)
    call cairo.restore(cr)

    length = ui["length"]
    dim = 1.0
    if ui["busy"]:
        dim = 0.5
    end
    if length == 0:
        layout = text_layout(cr, ui["placeholder"], font(ui, "Regular", px(u, 15.0, 12)))
        call pango.layout_set_width(layout, Int(fw - pad - fh))
        call pango.layout_set_ellipsize(layout, 3)
        size = pango.layout_get_pixel_size(layout)
        ty = y + (fh - Float(size[1])) / 2.0
        call cairo.move_to(cr, x + pad + 2.0, ty + 1.0)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.35 * dim)
        call pango.cairo_show_layout(cr, layout)
        call cairo.move_to(cr, x + pad + 2.0, ty)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.92 * dim)
        call pango.cairo_show_layout(cr, layout)
        call pango.layout_unref(layout)
    else:
        dot = max(2.5, 3.4 * u)
        step = max(8.0, 11.0 * u)
        room = Int((fw - pad - fh) / step)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95 * dim)
        for i in range(min(length, room)):
            call cairo.new_path(cr)
            call cairo.arc(cr, x + pad + dot + Float(i) * step, y + fh / 2.0, dot, 0.0, 2.0 * PI)
            call cairo.fill(cr)
        end
    end
    # sipka "odeslat" vpravo v poli
    d = fh - max(8.0, Float(Int(fh * 0.26 + 0.5)))
    cx = x + fw - fh / 2.0 - 2.0
    cy = y + fh / 2.0
    has = length > 0 and not ui["busy"]
    call cairo.new_path(cr)
    call cairo.arc(cr, cx, cy, d / 2.0, 0.0, 2.0 * PI)
    if has:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.30)
    else:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.12)
    end
    call cairo.fill(cr)
    if has:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    else:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.55)
    end
    call arrow(cr, cx, cy, d * 0.62)
    return r
end

# ---- hlaska, Caps Lock, rozlozeni ----

function hint(cr, w, y, ui, u):
    text = ui["hint"]
    if text == "":
        return 0
    end
    layout = text_layout(cr, text, font(ui, "Semi-Bold", px(u, 14.0, 11)))
    call pango.layout_set_width(layout, Int(Float(w) * 0.8))
    call pango.layout_set_ellipsize(layout, 3)
    size = pango.layout_get_pixel_size(layout)
    tw = Float(size[0])
    th = Float(size[1])
    x = (Float(w) - tw) / 2.0
    if ui["error"]:
        # chyba na tmavem podkladu: citelna i na svetle tapete (label.hint.error)
        call material.rounded_path(cr, x - 10.0, y, tw + 20.0, th + 2.0, 9.0)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
        call cairo.fill(cr)
        c = tokens.color("error_soft", False)
        call cairo.move_to(cr, x, y + 1.0)
        call cairo.set_source_rgba(cr, Float(c[0]) / 255.0, Float(c[1]) / 255.0, Float(c[2]) / 255.0, 1.0)
        call pango.cairo_show_layout(cr, layout)
    else:
        call shadow_text(cr, layout, x, y + 1.0, 0.88, 3.0 * u)
    end
    call pango.layout_unref(layout)
    return 0
end

# Caps Lock: obrys sipky nahoru s carkou pod ni (jako na klavese)
function caps_icon(cr, cx, cy, s):
    w = s * 0.80
    stem = s * 0.36
    top = cy - s * 0.46
    mid = cy - s * 0.02
    low = cy + s * 0.22
    call cairo.set_line_width(cr, max(1.3, s * 0.09))
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    call cairo.new_path(cr)
    call cairo.move_to(cr, cx, top)
    call cairo.line_to(cr, cx + w / 2.0, mid)
    call cairo.line_to(cr, cx + stem / 2.0, mid)
    call cairo.line_to(cr, cx + stem / 2.0, low)
    call cairo.line_to(cr, cx - stem / 2.0, low)
    call cairo.line_to(cr, cx - stem / 2.0, mid)
    call cairo.line_to(cr, cx - w / 2.0, mid)
    call cairo.close_path(cr)
    call cairo.stroke(cr)
    call cairo.rectangle(cr, cx - stem / 2.0, cy + s * 0.33, stem, max(1.3, s * 0.11))
    call cairo.fill(cr)
    return 0
end

function keyboard_row(cr, w, y, ui, u):
    row = px(u, 24.0, 18)
    gap = px(u, 14.0, 9)
    icon = px(u, 16.0, 12)
    desc = font(ui, "Semi-Bold", px(u, 14.0, 11))
    caps = None
    chip = None
    total = 0.0
    if ui["caps"]:
        caps = text_layout(cr, ui["caps_text"], desc)
        total = total + icon + px(u, 6.0, 4) + Float(pango.layout_get_pixel_size(caps)[0])
    end
    if ui["layout"] != "":
        chip = text_layout(cr, ui["layout"], font(ui, "Bold", px(u, 13.0, 11)))
        if caps != None:
            total = total + gap
        end
        total = total + Float(pango.layout_get_pixel_size(chip)[0]) + 2.0 * px(u, 10.0, 7)
    end
    x = (Float(w) - total) / 2.0
    cy = y + row / 2.0
    if caps != None:
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.30)
        call caps_icon(cr, x + icon / 2.0, cy + 1.0, icon)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
        call caps_icon(cr, x + icon / 2.0, cy, icon)
        x = x + icon + px(u, 6.0, 4)
        size = pango.layout_get_pixel_size(caps)
        call shadow_text(cr, caps, x, cy - Float(size[1]) / 2.0, 1.0, 3.0 * u)
        x = x + Float(size[0]) + gap
        call pango.layout_unref(caps)
    end
    if chip != None:
        size = pango.layout_get_pixel_size(chip)
        cw = Float(size[0]) + 2.0 * px(u, 10.0, 7)
        call pill(cr, x, y, cw, row)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.16)
        call cairo.fill(cr)
        call pill(cr, x + 0.5, y + 0.5, cw - 1.0, row - 1.0)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.18)
        call cairo.set_line_width(cr, 1.0)
        call cairo.stroke(cr)
        call cairo.move_to(cr, x + px(u, 10.0, 7), cy - Float(size[1]) / 2.0)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
        call pango.cairo_show_layout(cr, chip)
        call pango.layout_unref(chip)
    end
    return 0
end

# ---- baterie (luxos-lock-battery.c, stejna kresba jako luxos-greeter) ----

function bolt_path(cr, cx, cy, k):
    call cairo.new_path(cr)
    for p in [[0.14, -1.0], [-0.58, 0.14], [-0.07, 0.14], [-0.14, 1.0], [0.58, -0.14], [0.07, -0.14]]:
        call cairo.line_to(cr, cx + p[0] * k, cy + p[1] * k)
    end
    call cairo.close_path(cr)
    return 0
end

function battery(cr, x, y, h, level, charging):
    w = h * 2.05
    lw = max(1.0, h * 0.09)
    bx = x + lw / 2.0
    by = y + lw / 2.0
    bw = w - h * 0.22 - lw
    bh = h - lw
    br = h * 0.26
    ix = x + lw
    iy = y + lw
    iw = bw - lw
    ih = h - 2.0 * lw
    fx = ix + h * 0.08
    fy = iy + h * 0.08
    fw = max(h * 0.12, (iw - h * 0.16) * min(1.0, max(0.0, Float(level) / 100.0)))
    fh = ih - h * 0.16
    ring = max(1.0, h * 0.08)
    halo = max(0.75, h * 0.06)
    call cairo.save(cr)
    call cairo.set_line_join(cr, cairo.LINE_JOIN_ROUND)
    # tmavy stin obrysu a podklad: baterie je videt i na svetle tapete
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.38)
    call cairo.set_line_width(cr, lw + 2.0 * halo)
    call material.rounded_path(cr, bx, by, bw, bh, br)
    call cairo.stroke(cr)
    call material.rounded_path(cr, x + w - h * 0.2 - halo, y + h * 0.33 - halo, h * 0.14 + 2.0 * halo, h * 0.34 + 2.0 * halo, h * 0.06 + halo)
    call cairo.fill(cr)
    call material.rounded_path(cr, ix, iy, iw, ih, br - lw / 2.0)
    call cairo.fill(cr)
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.9)
    call cairo.set_line_width(cr, lw)
    call material.rounded_path(cr, bx, by, bw, bh, br)
    call cairo.stroke(cr)
    call material.rounded_path(cr, x + w - h * 0.2, y + h * 0.33, h * 0.14, h * 0.34, h * 0.06)
    call cairo.fill(cr)
    if level <= 15 and not charging:
        call cairo.set_source_rgba(cr, 1.0, 0.36, 0.33, 1.0)
    else:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
    end
    call material.rounded_path(cr, fx, fy, fw, fh, h * 0.14)
    call cairo.fill(cr)
    if charging:
        cx = bx + bw / 2.0
        cy = y + h / 2.0
        k = ih / 2.0 - ring * 0.75
        ex = fx + fw
        call cairo.set_line_width(cr, 2.0 * ring)
        # nad vyplni tmavy blesk s bilym lemem, nad prazdnou casti bily s tmavym
        for part in [[ix, ex - ix, 0.95, 0.10], [ex, ix + iw - ex, 0.0, 0.97]]:
            if part[1] > 0.0:
                call cairo.save(cr)
                call cairo.rectangle(cr, part[0], iy, part[1], ih)
                call cairo.clip(cr)
                call bolt_path(cr, cx, cy, k)
                if part[2] > 0.5:
                    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
                    call cairo.stroke_preserve(cr)
                    call cairo.set_source_rgba(cr, 0.10, 0.10, 0.12, 0.92)
                else:
                    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.60)
                    call cairo.stroke_preserve(cr)
                    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.97)
                end
                call cairo.fill(cr)
                call cairo.restore(cr)
            end
        end
    end
    call cairo.restore(cr)
    return 0
end

function status(cr, w, ui, u):
    bat = ui["battery"]
    if bat == None:
        return 0
    end
    pad = px(u, 18.0, 10)
    s = px(u, 16.0, 12)
    h = s * 0.9
    x = Float(w) - pad - h * 2.05
    call battery(cr, x, pad + (s - h) / 2.0, h, bat[0], bat[1])
    layout = text_layout(cr, String(bat[0]) + " %", font(ui, "Semi-Bold", px(u, 14.0, 11)))
    size = pango.layout_get_pixel_size(layout)
    call shadow_text(cr, layout, x - px(u, 6.0, 4) - Float(size[0]), pad + (s - Float(size[1])) / 2.0, 1.0, 3.0 * u)
    call pango.layout_unref(layout)
    return 0
end

# ---- cela plocha ----

function frame(cr, w, h, ui, gl):
    u = unit(h)
    call background(cr, w, h, gl)
    call clock(cr, w, h, ui, u)
    call status(cr, w, ui, u)
    r = field(cr, w, h, ui, gl, u)
    fy = r[1]
    gap = px(u, 14.0, 9)
    name_size = px(u, 17.0, 13)
    name_h = name_size * 1.3
    name_y = fy - gap - name_h
    d = px(u, 104.0, 64)
    call avatar(cr, Float(w) / 2.0, name_y - px(u, 8.0, 5) - d / 2.0, d, ui)
    call centered_text(cr, ui["name"], font(ui, "Semi-Bold", name_size), Float(w) / 2.0, name_y, 1.0, 3.0 * u)
    hint_y = fy + r[3] + gap
    call hint(cr, w, hint_y, ui, u)
    call keyboard_row(cr, w, hint_y + px(u, 22.0, 16) + gap, ui, u)
    return 0
end
