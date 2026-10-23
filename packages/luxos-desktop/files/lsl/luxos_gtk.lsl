# lsl: internal-abi
# lsl: link libgtk-3.so.0 libgdk-3.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - doplnky k modulu gtk LSL 0.10.6 pro Ovladaci centrum a Kalendar; programy nacitaji
# `load luxos_gtk, gtk as gtk` (co tu neni, bere se ze standardniho modulu). Nazvy = funkce GTK bez gtk_.
#   connect_data(widget, signal, nargs, f, data)   obsluha s vazanou hodnotou (luxos_glib)
#   bin_get_child, image_new, widget_set_no_show_all, widget_has_class, widget_set_class(widget, trida, zapnuto),
#   window_set_wmclass, widget_get_preferred_height/width -> [min, nat], scrolled_window_set_propagate_natural_height,
#   scrolled_window_get_max_content_height, widget_get_font_family, entry_set_width_chars,
#   dialog_new/dialog_add_button/dialog_get_content_area/dialog_set_default_response/dialog_run (agent Bluetooth),
#   css_set(provider, css) (novy obsah poskytovatele: prepnuti svetly/tmavy), settings_theme_name(), settings_prefer_dark(),
#   pointer_position() -> [x, y], screen_active_window() (GdkWindow aktivniho okna podle spravce oken, 0 kdyz neni;
#   nova reference -> glib.object_unref), window_set_rgba(okno) (RGBA visual + app paintable, jen s kompozitorem)
load glib, gtk
load luxos_glib

RESPONSE_OK = -5
RESPONSE_CANCEL = -6
# GtkIconSize
ICON_MENU = 1
ICON_LARGE_TOOLBAR = 3
ICON_DIALOG = 6

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

function data(bytes):
    unsafe:
        return __lsl_qbe_load64(__lsl_address(bytes) + 24)
    end
end

function flag(value):
    if value:
        return 1
    end
    return 0
end

function connect_data(widget, signal, nargs, handler, bound):
    return luxos_glib.connect_data(widget, signal, nargs, handler, bound)
end

function bin_get_child(bin):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_bin_get_child"), ptr(bin))
    end
end

function image_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_image_new"))
    end
end

function widget_set_no_show_all(widget, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_widget_set_no_show_all"), ptr(widget), flag(value))
    end
end

function widget_has_class(widget, name):
    unsafe:
        context = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_style_context"), ptr(widget))
        return __lsl_qbe_call2(__lsl_symbol("gtk_style_context_has_class"), context, cstr(name)) != 0
    end
end

function widget_set_class(widget, name, on):
    if on:
        return gtk.widget_add_class(widget, name)
    end
    return gtk.widget_remove_class(widget, name)
end

function window_set_wmclass(window, name, class_name):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_window_set_wmclass"), ptr(window), cstr(name), cstr(class_name))
    end
end

function widget_get_preferred_height(widget):
    unsafe:
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_call3(__lsl_symbol("gtk_widget_get_preferred_height"), ptr(widget), data(cell), data(cell) + 4)
        return [__lsl_qbe_s32(__lsl_qbe_load32(data(cell))), __lsl_qbe_s32(__lsl_qbe_load32(data(cell) + 4))]
    end
end

function widget_get_preferred_width(widget):
    unsafe:
        cell = __lsl_byte_zeros(8)
        call __lsl_qbe_call3(__lsl_symbol("gtk_widget_get_preferred_width"), ptr(widget), data(cell), data(cell) + 4)
        return [__lsl_qbe_s32(__lsl_qbe_load32(data(cell))), __lsl_qbe_s32(__lsl_qbe_load32(data(cell) + 4))]
    end
end

function scrolled_window_set_propagate_natural_height(window, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_scrolled_window_set_propagate_natural_height"), ptr(window), flag(value))
    end
end

function scrolled_window_get_max_content_height(window):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_scrolled_window_get_max_content_height"), ptr(window)))
    end
end

# Rodina pisma widgetu ("Inter"), "" kdyz neni
function widget_get_font_family(widget):
    unsafe:
        context = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_pango_context"), ptr(widget))
        description = __lsl_qbe_call1(__lsl_symbol("pango_context_get_font_description"), context)
        if description == 0:
            return ""
        end
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("pango_font_description_get_family"), description))
    end
end

function entry_set_width_chars(entry, chars):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_entry_set_width_chars"), ptr(entry), ptr(chars))
    end
end

# ---- dialog -----------------------------------------------------------------------------------------------

function dialog_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_dialog_new"))
    end
end

function dialog_add_button(dialog, text, response):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_dialog_add_button"), ptr(dialog), cstr(text), ptr(response))
    end
end

function dialog_get_content_area(dialog):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_dialog_get_content_area"), ptr(dialog))
    end
end

function dialog_set_default_response(dialog, response):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_dialog_set_default_response"), ptr(dialog), ptr(response))
    end
end

function dialog_run(dialog):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_dialog_run"), ptr(dialog)))
    end
end

# ---- styl a nastaveni --------------------------------------------------------------------------------------

function css_set(provider, css):
    unsafe:
        return __lsl_qbe_call4(__lsl_symbol("gtk_css_provider_load_from_data"), ptr(provider), cstr(css), -1, 0)
    end
end

function settings_theme_name():
    return gtk.object_get_string(gtk.settings_get_default(), "gtk-theme-name")
end

function settings_prefer_dark():
    return gtk.object_get_bool(gtk.settings_get_default(), "gtk-application-prefer-dark-theme")
end

# Pruhledne pozadi okna (jen kdyz bezi kompozitor)
function window_set_rgba(window):
    if gtk.screen_is_composited():
        call gtk.widget_set_rgba_visual(window)
    end
    return gtk.widget_set_app_paintable(window, True)
end

# ---- GDK: kurzor a aktivni okno ---------------------------------------------------------------------------------

function pointer_position():
    unsafe:
        display = __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
        seat = __lsl_qbe_call1(__lsl_symbol("gdk_display_get_default_seat"), display)
        pointer = __lsl_qbe_call1(__lsl_symbol("gdk_seat_get_pointer"), seat)
        cell = __lsl_byte_zeros(8)
        if pointer != 0:
            call __lsl_qbe_call4(__lsl_symbol("gdk_device_get_position"), pointer, 0, data(cell), data(cell) + 4)
        end
        return [__lsl_qbe_s32(__lsl_qbe_load32(data(cell))), __lsl_qbe_s32(__lsl_qbe_load32(data(cell) + 4))]
    end
end

function screen_active_window():
    unsafe:
        screen = __lsl_qbe_call0(__lsl_symbol("gdk_screen_get_default"))
        return __lsl_qbe_call1(__lsl_symbol("gdk_screen_get_active_window"), screen)
    end
end
