# lsl: link libgdk_pixbuf-2.0.so.0 libgdk-3.so.0 libgtk-3.so.0 libcairo.so.2 libgobject-2.0.so.0
# LuxOS - ikona z kresby SVG v kodu do GtkImage (Ovladaci centrum podle prototypu vlastnika). Kresba 24x24
# s carami i vyplnemi v barve currentColor; symbolicke ikony GTK 3 prebarvuji jen vyplne, cary by zmizely.
#
#   svg_icon.set(image, body, size, color, scale)   body = vnitrek <svg> (24x24, cary 1,7 px), size v px,
#                                                    color "#rrggbb", scale = HiDPI obrazovky (1, 2)
load luxos_gtk, gtk as gtk

function document(body, color):
    return ("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" color=\"" + color
        + "\"><g stroke=\"currentColor\" fill=\"none\" stroke-width=\"1.7\" stroke-linecap=\"round\" stroke-linejoin=\"round\">"
        + body + "</g></svg>")
end

function set(image, body, size, color, scale):
    text = document(body, color)
    px = max(1, Int(Float(size) * Float(scale) + 0.5))
    unsafe:
        loader = __lsl_qbe_call2(__lsl_symbol("gdk_pixbuf_loader_new_with_type"), gtk.cstr("svg"), 0)
        if loader == 0:
            return False
        end
        call __lsl_qbe_call3(__lsl_symbol("gdk_pixbuf_loader_set_size"), loader, px, px)
        call __lsl_qbe_call4(__lsl_symbol("gdk_pixbuf_loader_write"), loader, gtk.cstr(text), len(text), 0)
        call __lsl_qbe_call2(__lsl_symbol("gdk_pixbuf_loader_close"), loader, 0)
        pixbuf = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_loader_get_pixbuf"), loader)
        if pixbuf != 0:
            surface = __lsl_qbe_call3(__lsl_symbol("gdk_cairo_surface_create_from_pixbuf"), pixbuf, gtk.ptr(scale), 0)
            call __lsl_qbe_call2(__lsl_symbol("gtk_image_set_from_surface"), gtk.ptr(image), surface)
            call __lsl_qbe_call1(__lsl_symbol("cairo_surface_destroy"), surface)
        end
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), loader)
        return pixbuf != 0
    end
end
