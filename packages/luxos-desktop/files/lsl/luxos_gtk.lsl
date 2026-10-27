# lsl: internal-abi
# lsl: link libgtk-3.so.0 libgdk-3.so.0 libgdk_pixbuf-2.0.so.0 libcairo.so.2 libatk-1.0.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# LuxOS - doplnky k modulu gtk LSL 0.10.6 pro Ovladaci centrum, Kalendar a Snimek obrazovky; programy nacitaji
# `load luxos_gtk, gtk as gtk` (co tu neni, bere se ze standardniho modulu). Nazvy = funkce GTK bez gtk_.
#   connect_data(widget, signal, nargs, f, data)   obsluha s vazanou hodnotou (luxos_glib)
#   bin_get_child, image_new, widget_set_no_show_all, widget_has_class, widget_set_class(widget, trida, zapnuto),
#   window_set_wmclass, widget_get_preferred_height/width -> [min, nat], scrolled_window_set_propagate_natural_height,
#   scrolled_window_get_max_content_height, widget_get_font_family, entry_set_width_chars,
#   dialog_new/dialog_add_button/dialog_get_content_area/dialog_set_default_response/dialog_run (agent Bluetooth),
#   css_set(provider, css) (novy obsah poskytovatele: prepnuti svetly/tmavy), settings_theme_name(), settings_prefer_dark(),
#   pointer_position() -> [x, y], screen_active_window() (GdkWindow aktivniho okna podle spravce oken, 0 kdyz neni;
#   nova reference -> glib.object_unref), window_set_rgba(okno) (RGBA visual + app paintable, jen s kompozitorem)
load glib, gtk, cairo
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

# ==== Snimek obrazovky (luxos_shot): okna mimo spravce oken, nabidky, dialogy, obrazky =========================
#   root_window(), root_size() -> [w, h], root_scale(), rgba_available(), monitor_at_pointer() -> [x, y, w, h]
#   gdk_window_raise(widget), widget_xid(widget), widget_shape_rounded(okno, w, h, r), widget_input_rect(okno, x, y, w, h)
#   (w < 0 = cela plocha), current_event_state(), event_crossing_detail(e), event_x_root/y_root(e)
#   seat_grab_keyboard(widget) / seat_ungrab(), accessible_name(widget, text)
#   menu_new, menu_item_new(text), menu_item_markup(markup), radio_menu_item_new(skupina, text), check_menu_item_new,
#   check_menu_item_get/set_active, separator_menu_item_new, menu_append, menu_attach, menu_popup_above(menu, widget),
#   menu_popup_at_pointer, menu_popdown, menu_item_set_label
#   file_chooser_new(titulek, akce), file_chooser_set_folder/set_name/get_filename/set_overwrite_confirm
#   drag_source_uri/drag_source_image(widget, pixbuf), selection_set_uri(data, uri), selection_set_pixbuf(data, pb)
#   clipboard_set_image(pb) -> vlastnik, clipboard_owner(), clipboard_object()
#   pixbuf_from_window(x, y, w, h), pixbuf_sub_copy, pixbuf_scale, pixbuf_save_png/jpeg(pb, cesta) -> chyba ("" = ok),
#   pixbuf_has_alpha, pixbuf_flatten, pixbuf_to_surface(pb, scale), surface_to_pixbuf(s, w, h), object_unref,
#   cairo_push_group/pop_group_to_source, cairo_set_fill_rule, surface_data/surface_stride/surface_flush/surface_mark_dirty

SEAT_KEYBOARD = 8
NOTIFY_INFERIOR = 2
FILE_CHOOSER_SAVE = 1
FILE_CHOOSER_SELECT_FOLDER = 2
RESPONSE_ACCEPT = -3

# Cele cislo se znamenkem z 32bitove hodnoty signalu (response dialogu)
function s32(value):
    unsafe:
        return __lsl_qbe_s32(ptr(value))
    end
end

function widget_get_toplevel_xid(widget):
    unsafe:
        top = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_toplevel"), ptr(widget))
        window = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_window"), top)
        if window == 0:
            return 0
        end
        return __lsl_qbe_call1(__lsl_symbol("gdk_x11_window_get_xid"), window)
    end
end

function root_window():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gdk_get_default_root_window"))
    end
end

function root_size():
    unsafe:
        root = __lsl_qbe_call0(__lsl_symbol("gdk_get_default_root_window"))
        return [__lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_window_get_width"), root)), __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_window_get_height"), root))]
    end
end

function root_scale():
    unsafe:
        root = __lsl_qbe_call0(__lsl_symbol("gdk_get_default_root_window"))
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gdk_window_get_scale_factor"), root))
    end
end

function rgba_available():
    unsafe:
        screen = __lsl_qbe_call0(__lsl_symbol("gdk_screen_get_default"))
        return __lsl_qbe_call1(__lsl_symbol("gdk_screen_get_rgba_visual"), screen) != 0 and __lsl_qbe_call1(__lsl_symbol("gdk_screen_is_composited"), screen) != 0
    end
end

# Geometrie monitoru s mysi (cely monitor vcetne panelu)
function monitor_at_pointer():
    pointer = pointer_position()
    unsafe:
        display = __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
        monitor = __lsl_qbe_call3(__lsl_symbol("gdk_display_get_monitor_at_point"), display, ptr(pointer[0]), ptr(pointer[1]))
        if monitor == 0:
            monitor = __lsl_qbe_call1(__lsl_symbol("gdk_display_get_primary_monitor"), display)
        end
        if monitor == 0:
            monitor = __lsl_qbe_call2(__lsl_symbol("gdk_display_get_monitor"), display, 0)
        end
        return gtk.rectangle_of(monitor, False)
    end
end

function gdk_window_raise(widget):
    unsafe:
        window = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_window"), ptr(widget))
        if window != 0:
            call __lsl_qbe_call1(__lsl_symbol("gdk_window_raise"), window)
        end
        return 0
    end
end

# Identifikator okna X (0 kdyz okno jeste neni realizovane)
function widget_xid(widget):
    unsafe:
        window = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_window"), ptr(widget))
        if window == 0:
            return 0
        end
        return __lsl_qbe_call1(__lsl_symbol("gdk_x11_window_get_xid"), window)
    end
end

# Bez kompozitoru by rohy byly cerne: tvar okna oriznout na zaobleny obdelnik
function widget_shape_rounded(widget, width, height, radius):
    unsafe:
        w = max(1, ptr(width))
        h = max(1, ptr(height))
        surface = __lsl_qbe_call3(__lsl_symbol("cairo_image_surface_create"), 3, w, h)
        cr = __lsl_qbe_call1(__lsl_symbol("cairo_create"), surface)
        call cairo.rounded_rectangle(cr, 0, 0, w, h, radius)
        call __lsl_qbe_call1(__lsl_symbol("cairo_fill"), cr)
        call __lsl_qbe_call1(__lsl_symbol("cairo_destroy"), cr)
        region = __lsl_qbe_call1(__lsl_symbol("gdk_cairo_region_create_from_surface"), surface)
        call __lsl_qbe_call2(__lsl_symbol("gtk_widget_shape_combine_region"), ptr(widget), region)
        call __lsl_qbe_call1(__lsl_symbol("cairo_region_destroy"), region)
        call __lsl_qbe_call1(__lsl_symbol("cairo_surface_destroy"), surface)
        return 0
    end
end

# Oblast okna, ktera prijima mys; w < 0 = cele okno
function widget_input_rect(widget, x, y, width, height):
    unsafe:
        if ptr(width) < 0:
            call __lsl_qbe_call2(__lsl_symbol("gtk_widget_input_shape_combine_region"), ptr(widget), 0)
            return 0
        end
        rect = __lsl_byte_zeros(16)
        call __lsl_qbe_store32(data(rect), ptr(x))
        call __lsl_qbe_store32(data(rect) + 4, ptr(y))
        call __lsl_qbe_store32(data(rect) + 8, ptr(width))
        call __lsl_qbe_store32(data(rect) + 12, ptr(height))
        region = __lsl_qbe_call1(__lsl_symbol("cairo_region_create_rectangle"), data(rect))
        call __lsl_qbe_call2(__lsl_symbol("gtk_widget_input_shape_combine_region"), ptr(widget), region)
        call __lsl_qbe_call1(__lsl_symbol("cairo_region_destroy"), region)
        return 0
    end
end

# Stav modifikatoru prave zpracovavane udalosti (Ctrl pri kliknuti), 0 mimo udalost
function current_event_state():
    unsafe:
        cell = __lsl_byte_zeros(8)
        if __lsl_qbe_call1(__lsl_symbol("gtk_get_current_event_state"), data(cell)) == 0:
            return 0
        end
        return __lsl_qbe_load32(data(cell))
    end
end

# GdkEventCrossing.detail (GDK_NOTIFY_INFERIOR = presun na vnitrni widget)
function event_crossing_detail(event):
    unsafe:
        return __lsl_qbe_load32(ptr(event) + 76)
    end
end

# GdkEventButton/GdkEventMotion: souradnice v korenovem okne
function event_x_root(event):
    unsafe:
        return __lsl_float_from_bits(__lsl_qbe_load64(ptr(event) + 64))
    end
end

function event_y_root(event):
    unsafe:
        return __lsl_float_from_bits(__lsl_qbe_load64(ptr(event) + 72))
    end
end

# Klavesnice pro okno mimo spravce oken; True pri uspechu
function seat_grab_keyboard(widget):
    unsafe:
        window = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_window"), ptr(widget))
        if window == 0 or __lsl_qbe_call1(__lsl_symbol("gdk_window_is_visible"), window) == 0:
            return False
        end
        display = __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
        seat = __lsl_qbe_call1(__lsl_symbol("gdk_display_get_default_seat"), display)
        return __lsl_qbe_call8(__lsl_symbol("gdk_seat_grab"), seat, window, 8, 1, 0, 0, 0, 0) == 0
    end
end

function seat_ungrab():
    unsafe:
        display = __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
        seat = __lsl_qbe_call1(__lsl_symbol("gdk_display_get_default_seat"), display)
        call __lsl_qbe_call1(__lsl_symbol("gdk_seat_ungrab"), seat)
        return 0
    end
end

# Pristupnost: jmeno tlacitka s ikonou i bez tooltipu
function accessible_name(widget, name):
    unsafe:
        accessible = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_accessible"), ptr(widget))
        if accessible != 0:
            call __lsl_qbe_call2(__lsl_symbol("atk_object_set_name"), accessible, cstr(name))
        end
        return 0
    end
end

# ---- nabidky --------------------------------------------------------------------------------------------------

function menu_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_menu_new"))
    end
end

function menu_item_new(label):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_menu_item_new_with_label"), cstr(label))
    end
end

# Polozka s popiskem v markupu (napoveda <small>)
function menu_item_markup(markup):
    unsafe:
        item = __lsl_qbe_call0(__lsl_symbol("gtk_menu_item_new"))
        label = __lsl_qbe_call1(__lsl_symbol("gtk_label_new"), 0)
        call __lsl_qbe_call2(__lsl_symbol("gtk_label_set_markup"), label, cstr(markup))
        call __lsl_qbe_call2(__lsl_symbol("gtk_label_set_xalign"), label, __lsl_qbe_f32(0.0))
        call __lsl_qbe_call2(__lsl_symbol("gtk_container_add"), item, label)
        return item
    end
end

function radio_menu_item_new(group_item, label):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_radio_menu_item_new_with_label_from_widget"), ptr(group_item), cstr(label))
    end
end

function check_menu_item_new(label):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_check_menu_item_new_with_label"), cstr(label))
    end
end

function check_menu_item_get_active(item):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_check_menu_item_get_active"), ptr(item)) != 0
    end
end

function check_menu_item_set_active(item, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_check_menu_item_set_active"), ptr(item), flag(value))
    end
end

function separator_menu_item_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_separator_menu_item_new"))
    end
end

function menu_item_set_label(item, label):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_menu_item_set_label"), ptr(item), cstr(label))
    end
end

function menu_append(menu, item):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_menu_shell_append"), ptr(menu), ptr(item))
    end
end

function menu_attach(menu, widget):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_menu_attach_to_widget"), ptr(menu), ptr(widget), 0)
    end
end

# Nabidka nad widgetem (levy dolni roh nabidky na levem hornim rohu widgetu; GTK ji pripadne preklopi)
function menu_popup_above(menu, widget):
    unsafe:
        return __lsl_qbe_call5(__lsl_symbol("gtk_menu_popup_at_widget"), ptr(menu), ptr(widget), 1, 7, 0)
    end
end

function menu_popup_at_pointer(menu):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_menu_popup_at_pointer"), ptr(menu), 0)
    end
end

function menu_popdown(menu):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_menu_popdown"), ptr(menu))
    end
end

# ---- dialog vyberu souboru ------------------------------------------------------------------------------------

function file_chooser_new(title, action):
    unsafe:
        return __lsl_qbe_call4(__lsl_symbol("gtk_file_chooser_dialog_new"), cstr(title), 0, ptr(action), 0)
    end
end

function file_chooser_set_folder(chooser, path):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_current_folder"), ptr(chooser), cstr(path)) != 0
    end
end

function file_chooser_set_name(chooser, name):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_current_name"), ptr(chooser), cstr(name))
    end
end

function file_chooser_get_filename(chooser):
    unsafe:
        return glib.take_c(__lsl_qbe_call1(__lsl_symbol("gtk_file_chooser_get_filename"), ptr(chooser)))
    end
end

function file_chooser_set_overwrite_confirm(chooser, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_do_overwrite_confirmation"), ptr(chooser), flag(value))
    end
end

# ---- tazeni a schranka ----------------------------------------------------------------------------------------

# Tazeni levym tlacitkem (GDK_BUTTON1_MASK) s kopii (GDK_ACTION_COPY); cil URI souboru nebo obrazek
function drag_source_setup(widget, uris, pixbuf):
    unsafe:
        call __lsl_qbe_call5(__lsl_symbol("gtk_drag_source_set"), ptr(widget), 256, 0, 0, 2)
        if uris:
            call __lsl_qbe_call1(__lsl_symbol("gtk_drag_source_add_uri_targets"), ptr(widget))
        else:
            call __lsl_qbe_call1(__lsl_symbol("gtk_drag_source_add_image_targets"), ptr(widget))
        end
        if ptr(pixbuf) != 0:
            call __lsl_qbe_call2(__lsl_symbol("gtk_drag_source_set_icon_pixbuf"), ptr(widget), ptr(pixbuf))
        end
        return 0
    end
end

function selection_set_uri(selection, uri):
    unsafe:
        array = glib.cstr_array([uri])
        return __lsl_qbe_call2(__lsl_symbol("gtk_selection_data_set_uris"), ptr(selection), glib.array_data(array))
    end
end

function selection_set_pixbuf(selection, pixbuf):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_selection_data_set_pixbuf"), ptr(selection), ptr(pixbuf))
    end
end

# Schranka (GDK_SELECTION_CLIPBOARD = atom 69)
function clipboard_object():
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_clipboard_get"), 69)
    end
end

function clipboard_set_image(pixbuf):
    unsafe:
        clip = __lsl_qbe_call1(__lsl_symbol("gtk_clipboard_get"), 69)
        call __lsl_qbe_call2(__lsl_symbol("gtk_clipboard_set_image"), clip, ptr(pixbuf))
        call __lsl_qbe_call1(__lsl_symbol("gtk_clipboard_store"), clip)
        return __lsl_qbe_call1(__lsl_symbol("gdk_selection_owner_get"), 69)
    end
end

function clipboard_owner():
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gdk_selection_owner_get"), 69)
    end
end

# ---- obrazky (GdkPixbuf) -------------------------------------------------------------------------------------

function object_unref(object):
    unsafe:
        if ptr(object) != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(object))
        end
        return 0
    end
end

# Cast korenoveho okna (logicke souradnice) v pixelech zarizeni; 0 pri chybe
function pixbuf_from_window(x, y, width, height):
    unsafe:
        root = __lsl_qbe_call0(__lsl_symbol("gdk_get_default_root_window"))
        return __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_get_from_window"), root, ptr(x), ptr(y), ptr(width), ptr(height))
    end
end

# Samostatna kopie vyrezu obrazku
function pixbuf_sub_copy(pixbuf, x, y, width, height):
    unsafe:
        sub = __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_new_subpixbuf"), ptr(pixbuf), ptr(x), ptr(y), ptr(width), ptr(height))
        if sub == 0:
            return 0
        end
        out = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_copy"), sub)
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), sub)
        return out
    end
end

# GDK_INTERP_BILINEAR = 2
function pixbuf_scale(pixbuf, width, height):
    unsafe:
        return __lsl_qbe_call4(__lsl_symbol("gdk_pixbuf_scale_simple"), ptr(pixbuf), max(1, ptr(width)), max(1, ptr(height)), 2)
    end
end

function pixbuf_has_alpha(pixbuf):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_has_alpha"), ptr(pixbuf)) != 0
    end
end

# Pruhlednost na bilem pozadi (JPEG); nova reference
function pixbuf_flatten(pixbuf):
    unsafe:
        w = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_width"), ptr(pixbuf))
        h = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_get_height"), ptr(pixbuf))
        return __lsl_qbe_call8(__lsl_symbol("gdk_pixbuf_composite_color_simple"), ptr(pixbuf), w, h, 0, 255, 8, 16777215, 16777215)
    end
end

# Ulozeni (savev); vraci "" pri uspechu, jinak zpravu chyby
function pixbuf_save(pixbuf, path, kind, keys, values):
    unsafe:
        key_array = glib.cstr_array(keys)
        value_array = glib.cstr_array(values)
        cell = __lsl_byte_zeros(8)
        ok = __lsl_qbe_call6(__lsl_symbol("gdk_pixbuf_savev"), ptr(pixbuf), cstr(path), cstr(kind), glib.array_data(key_array), glib.array_data(value_array), data(cell))
        if ok != 0:
            return ""
        end
        error = __lsl_qbe_load64(data(cell))
        message = "error"
        if error != 0:
            message = glib.from_c(__lsl_qbe_load64(error + 8))
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
        end
        return message
    end
end

function pixbuf_save_png(pixbuf, path):
    return pixbuf_save(pixbuf, path, "png", [], [])
end

function pixbuf_save_jpeg(pixbuf, path):
    return pixbuf_save(pixbuf, path, "jpeg", ["quality"], ["92"])
end

# cairo_surface_t z obrazku (scale = HiDPI); volajici ho znici cairo_surface_destroy
function pixbuf_to_surface(pixbuf, scale):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gdk_cairo_surface_create_from_pixbuf"), ptr(pixbuf), ptr(scale), 0)
    end
end

function surface_to_pixbuf(surface, width, height):
    unsafe:
        return __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_get_from_surface"), ptr(surface), 0, 0, ptr(width), ptr(height))
    end
end

# ---- cairo navic k modulu cairo -------------------------------------------------------------------------------

function cairo_push_group(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_push_group"), ptr(cr))
    end
end

function cairo_pop_group_to_source(cr):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_pop_group_to_source"), ptr(cr))
    end
end

# CAIRO_FILL_RULE_EVEN_ODD = 1
function cairo_set_fill_rule(cr, rule):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("cairo_set_fill_rule"), ptr(cr), ptr(rule))
    end
end

function surface_data(surface):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_data"), ptr(surface))
    end
end

function surface_stride(surface):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("cairo_image_surface_get_stride"), ptr(surface)))
    end
end

function surface_flush(surface):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_surface_flush"), ptr(surface))
    end
end

function surface_mark_dirty(surface):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("cairo_surface_mark_dirty"), ptr(surface))
    end
end
