# lsl: internal-abi
# SPDX-License-Identifier: MIT
# LuxOS SDK 1.0 - small optional GTK 3 helpers, copied into your own project.
# No service, interpreter, implicit worker or network dependency.
load gtk
load glib

VERSION = "1.0.0"

CSS = "\nwindow.lux-app { background: #f5f7fb; color: #1d2940; }\n.lux-app headerbar { background: #fcfdff; border-bottom: 1px solid #dfe5ef; box-shadow: none; padding: 8px 12px; }\n.lux-app .lux-title { font-size: 26px; font-weight: 800; color: #1d2940; }\n.lux-app .lux-subtitle { color: #66758c; font-size: 13px; }\n.lux-app .lux-section { font-size: 11px; font-weight: 700; color: #72819a; }\n.lux-app .lux-card { background: white; border: 1px solid #e0e6f0; border-radius: 16px; padding: 20px; }\n.lux-app button { background-image: none; background-color: #fff; color: #273650; border: 1px solid #dce3ee; border-radius: 9px; padding: 8px 14px; box-shadow: none; text-shadow: none; }\n.lux-app button:hover { background-color: #edf3fc; border-color: #b7c9e8; }\n.lux-app button.lux-primary { background-color: #4769e8; color: white; border-color: #4769e8; }\n.lux-app button.lux-primary:hover { background-color: #3859d4; }\n.lux-app button:focus { outline: 2px solid #8ca5f4; outline-offset: 2px; }\n.lux-app entry { border: 1px solid #dce3ee; border-radius: 9px; padding: 9px 11px; box-shadow: none; }\n.lux-app selection { background-color: #4769e8; color: white; }\n"

function style(widget, name):
    call gtk.widget_add_class(widget, name)
    return widget
end

function window(title, width=960, height=640):
    call glib.set_application_name(title)
    call gtk.css_load(CSS)
    result = style(gtk.window_new(title), "lux-app")
    call gtk.window_set_default_size(result, width, height)
    header = __lsl_qbe_call0(__lsl_symbol("gtk_header_bar_new"))
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_title"), glib.ptr(header), glib.cstr(title))
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_show_close_button"), glib.ptr(header), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_window_set_titlebar"), glib.ptr(result), glib.ptr(header))
    return result
end

function column(spacing=12):
    return gtk.box_new(gtk.VERTICAL, spacing)
end

function row(spacing=8):
    return gtk.box_new(gtk.HORIZONTAL, spacing)
end

function add(container, child, expand=False):
    call gtk.box_pack_start(container, child, expand, True, 0)
    return child
end

function label(text, appearance=""):
    result = gtk.label_new(text)
    call gtk.widget_set_halign(result, gtk.ALIGN_START)
    if appearance:
        call style(result, appearance)
    end
    return result
end

function heading(text):
    return label(text, "lux-title")
end

function subtitle(text):
    return label(text, "lux-subtitle")
end

function card():
    return style(column(12), "lux-card")
end

function button(text, handler=None, primary=False):
    result = gtk.button_new(text)
    if primary:
        call style(result, "lux-primary")
    end
    if handler != None:
        call gtk.connect(result, "clicked", handler)
    end
    return result
end
