# lsl: link libluxcomp.so.0
# LuxOS - vazba na libluxcomp (jadro kompozitoru v C, packages/luxcomp) pro luxwm. Nazvy = funkce
# luxcomp_ bez predpony, konstanty = enumy z luxcomp.h bez LUXCOMP_. Popis API: docs/developers/luxcomp-api.md
#
#   init(handler)          handler(event, id, a, b, c) pro vsechny udalosti; chyba v obsluze se jen
#                          vypise ("LSL callback error"), kompozitor bezi dal (glib.dispatch)
#   view_title(v), view_app_id(v), view_sandbox_app_id(v), view_sandbox_instance(v), output_name(o),
#   socket(), layout_name(i), ipc_line(k), input_name(d)
#                          kopie retezce ("" kdyz neni)
# Ostatni funkce jen predavaji cisla, neplatne id je v jadru tichy no-op.
load glib

API_VERSION = 13

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
EV_LOCK = 15
EV_LAYOUT = 16
EV_IPC_CONNECT = 17
EV_IPC_LINE = 18
EV_IPC_CLOSE = 19
EV_VIEW_SIZE = 20
EV_HOLD_END = 21
EV_LAYER_MAP = 22
EV_VIEW_CONTENT_TYPE = 23

REQ_MOVE = 1
REQ_RESIZE = 2
REQ_MAXIMIZE = 3
REQ_FULLSCREEN = 4
REQ_MINIMIZE = 5
REQ_ACTIVATE = 6
REQ_DECORATION = 7
REQ_CLOSE = 8

ORIGIN_CLIENT = 0
ORIGIN_VIEW = 1
ORIGIN_SHELL = 2
ORIGIN_TASKBAR = 3

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
OUT_VRR = 11
OUT_TEARING = 12
OUT_VRR_SUPPORTED = 13
OUT_VRR_ACTIVE = 14
OUT_FULLSCREEN = 15
OUT_SCANOUT = 16
OUT_TORN = 17

VRR_OFF = 0
VRR_FULLSCREEN = 1
VRR_ALWAYS = 2

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
VIEW_X11 = 20
VIEW_SANDBOXED = 21
VIEW_CONTENT_TYPE = 22
VIEW_TEARING = 23

CONTENT_NONE = 0
CONTENT_PHOTO = 1
CONTENT_VIDEO = 2
CONTENT_GAME = 3

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
THEME_GLYPH = 14
THEME_SHADOW_ACTIVE = 15
THEME_SHADOW_INACTIVE = 16
THEME_SHADOW_ACTIVE_SIZE = 17
THEME_SHADOW_INACTIVE_SIZE = 18
THEME_TITLE_HEIGHT_COMPACT = 19
THEME_BUTTON_INSET = 20
THEME_BUTTON_INSET_COMPACT = 21
THEME_BUTTON_RING = 22
THEME_BG_LIGHT = 23
THEME_BG_DARK = 24
THEME_DARK_TEXT_ACTIVE = 25
THEME_DARK_TEXT_INACTIVE = 26
THEME_DARK_BUTTON_INACTIVE = 27
THEME_DARK_BUTTON_RING = 28
THEME_ACCENT = 29
THEME_BORDER = 30
THEME_SHADOW_ACTIVE_OFFSET = 31
THEME_SHADOW_INACTIVE_OFFSET = 32

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

# Promenna prostredi pro programy, ktere luxwm spusti (LUXWM_SOCK)
function setenv(name, value):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("setenv"), cstr(name), cstr(value), 1)
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

# Pred start(): rozsvicene vystupy (splash) zustanou beze zmeny do prvniho snimku klienta (EV_HOLD_END)
function hold(timeout_ms):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_hold"), ptr(timeout_ms))
    end
end

function software_rendering():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_software_rendering"))
    end
end

# Material ploch layer-shell s priponou jmenneho prostoru "nazev@material[:polomer]" (luxcomp-api.md)
function material_set(name, radius, fallback, shadow, size, dy):
    unsafe:
        call __lsl_qbe_call6(__lsl_symbol("luxcomp_material_set"), cstr(name), ptr(radius), ptr(fallback), ptr(shadow), ptr(size), ptr(dy))
    end
end

function blur_set(radius, saturation_pct, mode):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_blur_set"), ptr(radius), ptr(saturation_pct), ptr(mode))
    end
end

function blur_tier():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_blur_tier"))
    end
end

# Material pod obdelnikem obsahu okna (souradnice geometrie okna); name "" nebo w/h <= 0 ho zrusi
function view_set_material(view, name, x, y, w, h):
    unsafe:
        call __lsl_qbe_call6(__lsl_symbol("luxcomp_view_set_material"), ptr(view), cstr(name), ptr(x), ptr(y), ptr(w), ptr(h))
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

function test_output_add(width, height):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_test_output_add"), ptr(width), ptr(height))
    end
end

function test_output_remove(output):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_test_output_remove"), ptr(output))
    end
    return 0
end

function output_at(x, y):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_output_at"), ptr(x), ptr(y))
    end
end

# OUT_VRR (VRR_*) a OUT_TEARING (0/1) vystupu
# Nocni svetlo a softwarovy jas vsech vystupu (luxcomp_set_night_light): kelviny (6500 = vypnuto), jas 10..100 %
function set_night_light(kelvin, brightness):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_set_night_light"), ptr(kelvin), ptr(brightness))
    end
    return 0
end

# 0 vypnuto, 1 gamma tabulka vystupu, 2 zavoj (vystup bez gamma tabulky)
function night_light_mode(output):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("luxcomp_night_light_mode"), ptr(output))
    end
end

function output_set(output, prop, value):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_output_set"), ptr(output), ptr(prop), ptr(value))
    end
    return 0
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

function view_sandbox_app_id(view):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_view_sandbox_app_id"), ptr(view)))
    end
end

function view_sandbox_instance(view):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_view_sandbox_instance"), ptr(view)))
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

function view_set_compact(view, on):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_set_compact"), ptr(view), ptr(on))
    end
end

function view_set_badge(view, text):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_set_badge"), ptr(view), cstr(text))
    end
end

function view_set_names(view, app_id, title):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_view_set_names"), ptr(view), cstr(app_id), cstr(title))
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

function set_layout(index):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_set_layout"), ptr(index))
    end
end

function layout():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_layout"))
    end
end

function layout_count():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_layout_count"))
    end
end

function layout_name(index):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_layout_name"), ptr(index)))
    end
end

# ---- mys a touchpad (libinput) ---------------------------------------------------------------

INPUT_MOUSE = 1
INPUT_TOUCHPAD = 2

INPUT_KIND = 1
INPUT_SPEED = 2
INPUT_ACCEL_PROFILE = 3
INPUT_NATURAL_SCROLL = 4
INPUT_LEFT_HANDED = 5
INPUT_MIDDLE_EMULATION = 6
INPUT_TAP = 7
INPUT_TAP_DRAG = 8
INPUT_DISABLE_WHILE_TYPING = 9
INPUT_CLICK_METHOD = 10
INPUT_SCROLL_METHOD = 11

INPUT_DEFAULT = -1000
INPUT_NONE = -1001

function input_set(kind, prop, value):
    unsafe:
        call __lsl_qbe_call3(__lsl_symbol("luxcomp_input_set"), ptr(kind), ptr(prop), ptr(value))
    end
end

function input_next(device):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("luxcomp_input_next"), ptr(device))
    end
end

function input_name(device):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_input_name"), ptr(device)))
    end
end

function input_get(device, prop):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_input_get"), ptr(device), ptr(prop))
    end
end

# ---- IPC pro shell --------------------------------------------------------------------------

function ipc_listen(path):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("luxcomp_ipc_listen"), cstr(path))
    end
end

function ipc_line(client):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("luxcomp_ipc_line"), ptr(client)))
    end
end

function ipc_send(client, line):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_ipc_send"), ptr(client), cstr(line))
    end
end

function ipc_close(client):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_ipc_close"), ptr(client))
    end
end

# ---- allowlist, XWayland, zamek -------------------------------------------------------------

# "" vyprazdni allowlist privilegovanych protokolu
function privileged_allow(exe_path):
    unsafe:
        if exe_path == "":
            call __lsl_qbe_call1(__lsl_symbol("luxcomp_privileged_allow"), 0)
        else:
            call __lsl_qbe_call1(__lsl_symbol("luxcomp_privileged_allow"), cstr(exe_path))
        end
    end
end

function xwayland_start():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_xwayland_start"))
    end
end

function xwayland_display():
    unsafe:
        return glib.from_c(__lsl_qbe_call0(__lsl_symbol("luxcomp_xwayland_display")))
    end
end

function xwayland_running():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_xwayland_running"))
    end
end

function locked():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_locked"))
    end
end

# 0 nic, 1 zamceny ukazatel, 2 omezeny na oblast (pointer-constraints hry)
function pointer_constraint():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_pointer_constraint"))
    end
end

function idle_inhibit(on):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_idle_inhibit"), ptr(on))
    end
    return 0
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

function set_cursor(theme, size):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_set_cursor"), cstr(theme), ptr(size))
    end
end

# Zaneprazdneny ukazatel po vyzadani tokenu xdg-activation (spousteni z Docku), nejdele timeout_ms; 0 = vypnuto
function launch_feedback(timeout_ms):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_launch_feedback"), ptr(timeout_ms))
    end
end

function launch_start():
    unsafe:
        call __lsl_qbe_call0(__lsl_symbol("luxcomp_launch_start"))
    end
end

# ---- animace oken a zakryti po prihlaseni ---------------------------------------------------

ANIM_OPEN = 1
ANIM_CLOSE = 2
ANIM_MINIMIZE = 3
ANIM_RESTORE = 4

function anim_set(kind, ms):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_anim_set"), ptr(kind), ptr(ms))
    end
end

function view_animate(view, kind):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("luxcomp_view_animate"), ptr(view), ptr(kind))
    end
end

function cover(argb):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_cover"), ptr(argb))
    end
end

# Posledni snimek greeteru do zakryti (soubor LUXFRAME1, nejvys max_age_s stary); 1 = nacten
function cover_frame(path, max_age_s):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("luxcomp_cover_frame"), cstr(path), ptr(max_age_s))
    end
end

# Bar prubehu v zakryti: 0 ho ukaze, 1..4 faze relace (4 = hotovo)
function cover_stage(stage):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_cover_stage"), ptr(stage))
    end
end

function switch_vt(vt):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("luxcomp_switch_vt"), ptr(vt))
    end
end

function session_active():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("luxcomp_session_active"))
    end
end

function cover_fade(ms):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("luxcomp_cover_fade"), ptr(ms))
    end
end
