"""LuxOS - kresleni grafu (cairo) pro Monitor systemu a Baterii.

Kruhovy ukazatel, plosny graf s historii a pomocne barvy. Vse kresli do
Gtk.DrawingArea, barvy textu bere z aktualniho tematu (svetly/tmavy rezim).
"""
import math

import cairo

COLORS = {
    "cpu": "#3d7bff",
    "memory": "#a35bff",
    "disk": "#ff9f0a",
    "net": "#30c48d",
    "net2": "#3d7bff",
    "battery": "#30c48d",
    "battery_low": "#ff453a",
}


def rgb(hexcolor, alpha=1.0):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (alpha,)


def fg_color(widget, alpha=1.0):
    c = widget.get_style_context().get_color(widget.get_state_flags())
    return (c.red, c.green, c.blue, alpha)


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def ring(cr, widget, cx, cy, radius, fraction, color, center_text="", sub_text="", width=11):
    """Kruhovy ukazatel: podklad, vyplneny oblouk a text uprostred."""
    fraction = max(0.0, min(1.0, fraction))
    cr.set_line_width(width)
    cr.set_line_cap(1)  # ROUND
    cr.set_source_rgba(*fg_color(widget, 0.10))
    cr.arc(cx, cy, radius, 0, 2 * math.pi)
    cr.stroke()
    if fraction > 0.003:
        cr.set_source_rgba(*rgb(color))
        start = -math.pi / 2
        cr.arc(cx, cy, radius, start, start + 2 * math.pi * fraction)
        cr.stroke()
    _center_text(cr, widget, cx, cy, center_text, sub_text, radius)


def _center_text(cr, widget, cx, cy, main, sub, radius):
    cr.select_font_face("Inter", 0, 1)
    size = max(12, radius * 0.42)
    cr.set_font_size(size)
    ext = cr.text_extents(main)
    cr.set_source_rgba(*fg_color(widget))
    cr.move_to(cx - ext.x_advance / 2, cy + (size * 0.35 if not sub else 0))
    cr.show_text(main)
    if sub:
        cr.select_font_face("Inter", 0, 0)
        cr.set_font_size(max(9, radius * 0.2))
        ext = cr.text_extents(sub)
        cr.set_source_rgba(*fg_color(widget, 0.6))
        cr.move_to(cx - ext.x_advance / 2, cy + size * 0.85)
        cr.show_text(sub)


def area_chart(cr, widget, x, y, w, h, series, maximum=None, grid=True, labels=None):
    """Plosny graf: series = [(hodnoty, barva), ...], hodnoty zleva (nejstarsi) doprava.

    maximum None = automaticky podle dat. labels = (vlevo dole, vpravo dole).
    """
    if grid:
        cr.set_line_width(1)
        cr.set_source_rgba(*fg_color(widget, 0.07))
        for i in range(1, 4):
            gy = y + h * i / 4
            cr.move_to(x, gy)
            cr.line_to(x + w, gy)
        cr.stroke()
    top = maximum or max([max(v) if v else 0 for v, _c in series] + [1e-9])
    for values, color in series:
        if len(values) < 2:
            continue
        n = len(values)
        step = w / (n - 1)
        pts = [(x + i * step, y + h - h * min(v / top, 1.0)) for i, v in enumerate(values)]
        # vypln s prechodem
        cr.move_to(pts[0][0], y + h)
        for px, py in pts:
            cr.line_to(px, py)
        cr.line_to(pts[-1][0], y + h)
        cr.close_path()
        grad = cairo.LinearGradient(0, y, 0, y + h)
        grad.add_color_stop_rgba(0, *rgb(color, 0.35)[:3], 0.35)
        grad.add_color_stop_rgba(1, *rgb(color, 0.0)[:3], 0.02)
        cr.set_source(grad)
        cr.fill()
        cr.set_line_width(2)
        cr.set_line_join(1)
        cr.set_source_rgba(*rgb(color))
        cr.move_to(*pts[0])
        for px, py in pts[1:]:
            cr.line_to(px, py)
        cr.stroke()
    if labels:
        cr.select_font_face("Inter", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgba(*fg_color(widget, 0.5))
        left, right = labels
        cr.move_to(x, y + h + 13)
        cr.show_text(left)
        ext = cr.text_extents(right)
        cr.move_to(x + w - ext.x_advance, y + h + 13)
        cr.show_text(right)


def human_bytes(n, per_second=False):
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1000 and i < len(units) - 1:
        v /= 1000
        i += 1
    text = f"{v:.0f} {units[i]}" if v >= 100 or i == 0 else f"{v:.1f} {units[i]}"
    return text + ("/s" if per_second else "")
