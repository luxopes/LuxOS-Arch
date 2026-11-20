# lsl: internal-abi
# lsl: link libluxcomp.so.0
# LuxOS - vazba na libluxcomp (jadro kompozitoru v C, packages/luxcomp) pro luxwm. Nazvy = funkce
# luxcomp_ bez predpony, konstanty = enumy z luxcomp.h bez LUXCOMP_. Popis API: docs/developers/luxcomp-api.md
#
#   init(handler)          handler(event, id, a, b, c) pro vsechny udalosti; chyba v obsluze se jen
#                          vypise ("LSL callback error"), kompozitor bezi dal (glib.dispatch)
#   view_title(v), view_app_id(v), output_name(o), socket()   kopie retezce ("" kdyz neni)
# Ostatni funkce jen predavaji cisla, neplatne id je v jadru tichy no-op.
load glib

API_VERSION = 1

EV_OUTPUT_ADD = 1
EV_OUTPUT_REMOVE = 2
EV_OUTPUT_USABLE = 3
EV_VIEW_NEW = 4
EV_VIEW_MAP = 5
EV_VIEW_UNMAP = 6
EV_VIEW_DESTROY = 7
EV_VIEW_TITLE = 8
EV_VIEW_APP_ID = 9
EV_VIEW_REQUEST = 10
EV_BUTTON = 11
EV_KEYBIND = 12
EV_SLIDE_DONE = 13
EV_MODS_RELEASED = 14

REQ_MOVE = 1
REQ_RESIZE = 2
REQ_MAXIMIZE = 3
REQ_FULLSCREEN = 4
REQ_MINIMIZE = 5
REQ_ACTIVATE = 6
REQ_DECORATION = 7

PART_NONE = 0
PART_CLIENT = 1
PART_TITLE = 2
PART_CLOSE = 3
PART_MINIMIZE = 4
PART_MAXIMIZE = 5
PART_LAYER = 6

EDGE_TOP = 1
EDGE_BOTTOM = 2
EDGE_LEFT = 4
EDGE_RIGHT = 8

MOD_SHIFT = 1
MOD_CTRL = 4
MOD_ALT = 8
MOD_SUPER = 64

OUT_X = 1
OUT_Y = 2
OUT_W = 3
OUT_H = 4
OUT_USABLE_X = 5
OUT_USABLE_Y = 6
OUT_USABLE_W = 7
OUT_USABLE_H = 8
OUT_REFRESH_MHZ = 9
OUT_SCALE_PCT = 10

VIEW_X = 1
VIEW_Y = 2
VIEW_W = 3
VIEW_H = 4
VIEW_DECO_TOP = 5
VIEW_OUTPUT = 6
VIEW_WORKSPACE = 7
VIEW_PARENT = 8
VIEW_MAPPED = 9
VIEW_VISIBLE = 10
VIEW_FOCUSED = 11
VIEW_FULLSCREEN = 12
VIEW_MAXIMIZED = 13
VIEW_LAYER = 14
VIEW_MIN_W = 15
VIEW_MIN_H = 16
VIEW_MAX_W = 17
VIEW_MAX_H = 18
VIEW_PID = 19

LAYER_NORMAL = 0
LAYER_ABOVE = 1
LAYER_FULLSCREEN = 2

STATE_FULLSCREEN = 1
STATE_MAXIMIZED = 2
STATE_TILED = 3

THEME_TITLE_HEIGHT = 1
THEME_CORNER_RADIUS = 2
THEME_BUTTON_SIZE = 3
THEME_BUTTON_SPACING = 4
THEME_BG_ACTIVE = 5
THEME_BG_INACTIVE = 6
THEME_TEXT_ACTIVE = 7
THEME_TEXT_INACTIVE = 8
THEME_CLOSE = 9
THEME_MINIMIZE = 10
THEME_MAXIMIZE = 11
THEME_BUTTON_INACTIVE = 12
THEME_SEPARATOR = 13

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

# ---- zivotni cyklus -------------------------------------------------------------------------

# Jediny zaznam obsluhy na cely beh (drzi ho glib.handlers), C ho dostane jako user_data
function init(handler):
    unsafe:
        record = glib.record_new(handler, 5)
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_init"), glib.callback_first(), ptr(record))
    end
end

function socket():
    unsafe:
        return glib.from_c(__lsl_qbe_call0(__lsl_symbol("luxcomp_socket")))
    end
end

function start():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_start"))
    end
end

function fd():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_fd"))
    end
end

function dispatch(timeout_ms):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("luxcomp_dispatch"), ptr(timeout_ms))
    end
end

function quit():
    unsafe:
        call __lsl_qbe_call0(__lsl_symbol("luxcomp_quit"))
    end
end

function destroy():
    unsafe:
        call __lsl_qbe_call0(__lsl_symbol("luxcomp_destroy"))
    end
end

function spawn(command):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("luxcomp_spawn"), cstr(command))
    end
end

function software_rendering():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_software_rendering"))
    end
end

function set_background(argb):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_set_background"), ptr(argb))
    end
end

# ---- vystupy --------------------------------------------------------------------------------

function output_get(output, prop):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_output_get"), ptr(output), ptr(prop))
    end
end

function output_name(output):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_output_name"), ptr(output)))
    end
end

function output_at(x, y):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_output_at"), ptr(x), ptr(y))
    end
end

function cursor_x():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_cursor_x"))
    end
end

function cursor_y():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_cursor_y"))
    end
end

# ---- okna -----------------------------------------------------------------------------------

function view_get(view, prop):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_view_get"), ptr(view), ptr(prop))
    end
end

function view_app_id(view):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_view_app_id"), ptr(view)))
    end
end

function view_title(view):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_view_title"), ptr(view)))
    end
end

function view_next(view):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("luxcomp_view_next"), ptr(view))
    end
end

function view_move(view, x, y):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_view_move"), ptr(view), ptr(x), ptr(y))
    end
end

function view_resize(view, w, h):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_view_resize"), ptr(view), ptr(w), ptr(h))
    end
end

function view_focus(view):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_view_focus"), ptr(view))
    end
end

function view_raise(view):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_view_raise"), ptr(view))
    end
end

function view_set_state(view, state, on):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_view_set_state"), ptr(view), ptr(state), ptr(on))
    end
end

function view_set_layer(view, layer):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_set_layer"), ptr(view), ptr(layer))
    end
end

function view_set_workspace(view, workspace):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_set_workspace"), ptr(view), ptr(workspace))
    end
end

function view_set_decorated(view, on):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_set_decorated"), ptr(view), ptr(on))
    end
end

function view_set_visible(view, on):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_set_visible"), ptr(view), ptr(on))
    end
end

function view_close(view):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_view_close"), ptr(view))
    end
end

function view_begin_move(view):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_view_begin_move"), ptr(view))
    end
end

function view_begin_resize(view, edges):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_begin_resize"), ptr(view), ptr(edges))
    end
end

# ---- plochy ---------------------------------------------------------------------------------

function workspace_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_workspace_new"))
    end
end

function workspace_show(workspace, on):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_workspace_show"), ptr(workspace), ptr(on))
    end
end

function workspace_slide(from, to, dir, ms):
    unsafe:
        call __lsl_qbe_call4(__lsl_symbol("luxcomp_workspace_slide"), ptr(from), ptr(to), ptr(dir), ptr(ms))
    end
end

# ---- vstup ----------------------------------------------------------------------------------

function set_keymap(layout, variant, options):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_set_keymap"), cstr(layout), cstr(variant), cstr(options))
    end
end

function set_repeat(rate, delay_ms):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_set_repeat"), ptr(rate), ptr(delay_ms))
    end
end

function bind_key(mods, key):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_bind_key"), ptr(mods), cstr(key))
    end
end

function unbind_key(binding):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_unbind_key"), ptr(binding))
    end
end

function modifiers():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_modifiers"))
    end
end

# ---- dekorace -------------------------------------------------------------------------------

function theme_set(prop, value):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_theme_set"), ptr(prop), ptr(value))
    end
end

function theme_set_font(font):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_theme_set_font"), cstr(font))
    end
end
