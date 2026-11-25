/*
 * libluxcomp - jadro kompozitoru LuxOS na wlroots 0.20.
 *
 * Jadro vlastni objekty wlroots (backend, renderer, vystupy, scenu, xdg-shell, layer-shell,
 * seat, kurzor) a kresli. O oknech nerozhoduje: umisteni, zamereni, plochy, klavesove zkratky
 * a dekorace ridi program nad knihovnou (luxwm v LSL) pres toto ploche API.
 *
 * Pravidla API (kvuli FFI LSL, internal-abi + trampolina s user_data na 1. miste):
 *  - jen cela cisla (int64_t), retezce (const char *) a jeden ukazatel user_data,
 *    zadne struktury pres hranici;
 *  - objekty jsou cisla (id > 0, nikdy znovu nepouzita); neplatne id je tichy no-op / vraci 0,
 *    takze zastarale id z LSL nemuze sahnout do uvolnene pameti;
 *  - udalosti chodi jednim callbackem luxcomp_event_fn (max 6 argumentu), vzdy v hlavnim vlakne
 *    z luxcomp_dispatch()/luxcomp_run();
 *  - vracene retezce plati do dalsiho volani luxcomp_dispatch() nebo do zniceni objektu.
 * Popis: docs/developers/luxcomp-api.md
 */
#ifndef LUXCOMP_H
#define LUXCOMP_H

#include <stdint.h>

#define LUXCOMP_API_VERSION 15

#pragma GCC visibility push(default)

typedef void (*luxcomp_event_fn)(void *user, int64_t event, int64_t id,
	int64_t a, int64_t b, int64_t c);

enum luxcomp_event {
	LUXCOMP_EV_OUTPUT_ADD = 1,	/* id=output a=w b=h */
	LUXCOMP_EV_OUTPUT_REMOVE,	/* id=output */
	LUXCOMP_EV_OUTPUT_USABLE,	/* id=output; usable area changed (layer-shell exclusive zones) */
	LUXCOMP_EV_VIEW_NEW,		/* id=view a=parent view or 0 */
	LUXCOMP_EV_VIEW_MAP,		/* id=view a=w b=h; first commit with content, policy places it */
	LUXCOMP_EV_VIEW_UNMAP,		/* id=view */
	LUXCOMP_EV_VIEW_DESTROY,	/* id=view; the id is dead after this */
	LUXCOMP_EV_VIEW_TITLE,		/* id=view; luxcomp_view_title() changed */
	LUXCOMP_EV_VIEW_APP_ID,		/* id=view; luxcomp_view_app_id() changed */
	LUXCOMP_EV_VIEW_REQUEST,	/* id=view a=LUXCOMP_REQ_* b=argument */
	LUXCOMP_EV_BUTTON,		/* id=view or 0 a=button (linux code) b=1 press/0 release c=LUXCOMP_PART_* */
	LUXCOMP_EV_KEYBIND,		/* id=binding from luxcomp_bind_key() */
	LUXCOMP_EV_SLIDE_DONE,		/* id=workspace now shown */
	LUXCOMP_EV_MODS_RELEASED,	/* all modifiers released after a key binding (ends Alt+Tab) */
	LUXCOMP_EV_LOCK,		/* a=1 locked, 0 unlocked; b=1 the locker died (stays locked) */
	LUXCOMP_EV_LAYOUT,		/* a=keyboard layout index; switched by an XKB grp: option, not sent
					 * for luxcomp_set_layout()/luxcomp_set_keymap() */
	LUXCOMP_EV_IPC_CONNECT,		/* id=IPC client a=pid b=1 privileged (allowlisted executable) */
	LUXCOMP_EV_IPC_LINE,		/* id=IPC client; luxcomp_ipc_line() is the received line */
	LUXCOMP_EV_IPC_CLOSE,		/* id=IPC client; the id is dead after this */
	LUXCOMP_EV_VIEW_SIZE,		/* id=view a=w b=h; the client changed its size (not sent during an
					 * interactive move/resize, the button release ends those) */
	LUXCOMP_EV_HOLD_END,		/* a=1 a client frame ended luxcomp_hold(), 0 the timeout; sent once
					 * that frame is on every output (the old picture may go away now) */
	LUXCOMP_EV_LAYER_MAP,		/* id=output a=layer (0 background .. 3 overlay) b=1 with an exclusive
					 * zone; a layer-shell surface (wallpaper, bar, Dock) shows its first frame */
	LUXCOMP_EV_VIEW_CONTENT_TYPE,	/* id=view a=LUXCOMP_CONTENT_* (wp-content-type-v1 changed) */
	LUXCOMP_EV_CAPS_LOCK,		/* a=1 Caps Lock on, 0 off (keyboard that typed last) */
	LUXCOMP_EV_SUPER_ALONE,		/* Super pressed and released without any other key */
	LUXCOMP_EV_MODIFIERS,		/* a=LUXCOMP_MOD_* held by the active keyboard */
};

enum luxcomp_request {
	LUXCOMP_REQ_MOVE = 1,		/* client asks for an interactive move (CSD title bar) */
	LUXCOMP_REQ_RESIZE,		/* b=edges (LUXCOMP_EDGE_*) */
	LUXCOMP_REQ_MAXIMIZE,		/* b=1 on, 0 off */
	LUXCOMP_REQ_FULLSCREEN,		/* b=1 on, 0 off */
	LUXCOMP_REQ_MINIMIZE,		/* b=1 minimise, 0 restore (Dock) */
	LUXCOMP_REQ_ACTIVATE,		/* b=LUXCOMP_ORIGIN_* c=view that made the xdg-activation token */
	LUXCOMP_REQ_DECORATION,		/* b=1 client wants server-side decoration, 0 client-side
					 * (also when it destroys its xdg-decoration object) */
	LUXCOMP_REQ_CLOSE,		/* foreign-toplevel (Dock) asks to close */
};

/* Who asks: c of VIEW_REQUEST for MAXIMIZE/FULLSCREEN/MINIMIZE/CLOSE, b of ACTIVATE */
enum luxcomp_origin {
	LUXCOMP_ORIGIN_CLIENT = 0,	/* the window itself; ACTIVATE: no valid token */
	LUXCOMP_ORIGIN_VIEW,		/* ACTIVATE: token made by a surface of view c */
	LUXCOMP_ORIGIN_SHELL,		/* ACTIVATE: token from a layer-shell surface or luxcomp_spawn() */
	LUXCOMP_ORIGIN_TASKBAR,		/* wlr-foreign-toplevel-management (Dock, privileged clients) */
};

enum luxcomp_part {
	LUXCOMP_PART_NONE = 0,		/* empty desktop */
	LUXCOMP_PART_CLIENT,
	LUXCOMP_PART_TITLE,
	LUXCOMP_PART_CLOSE,
	LUXCOMP_PART_MINIMIZE,
	LUXCOMP_PART_MAXIMIZE,
	LUXCOMP_PART_LAYER,		/* a layer-shell surface (bar, dock...) */
};

enum luxcomp_edge {
	LUXCOMP_EDGE_TOP = 1,
	LUXCOMP_EDGE_BOTTOM = 2,
	LUXCOMP_EDGE_LEFT = 4,
	LUXCOMP_EDGE_RIGHT = 8,
};

enum luxcomp_mod {
	LUXCOMP_MOD_SHIFT = 1,
	LUXCOMP_MOD_CTRL = 4,
	LUXCOMP_MOD_ALT = 8,
	LUXCOMP_MOD_SUPER = 64,
};

/* Properties for luxcomp_output_get() */
enum luxcomp_output_prop {
	LUXCOMP_OUT_X = 1, LUXCOMP_OUT_Y, LUXCOMP_OUT_W, LUXCOMP_OUT_H,
	LUXCOMP_OUT_USABLE_X, LUXCOMP_OUT_USABLE_Y, LUXCOMP_OUT_USABLE_W, LUXCOMP_OUT_USABLE_H,
	LUXCOMP_OUT_REFRESH_MHZ,
	LUXCOMP_OUT_SCALE_PCT,
	LUXCOMP_OUT_VRR,		/* adaptive sync LUXCOMP_VRR_*, default FULLSCREEN; luxcomp_output_set() */
	LUXCOMP_OUT_TEARING,		/* 1 (default) = a fullscreen client asking for async presentation
					 * (tearing-control-v1) gets tearing page flips; luxcomp_output_set() */
	LUXCOMP_OUT_VRR_SUPPORTED,	/* the display and driver can do adaptive sync */
	LUXCOMP_OUT_VRR_ACTIVE,		/* adaptive sync is on now */
	LUXCOMP_OUT_FULLSCREEN,		/* fullscreen view on top of this output or 0 */
	LUXCOMP_OUT_SCANOUT,		/* 1 = the last frame was a client buffer scanned out directly */
	LUXCOMP_OUT_TORN,		/* 1 = the last frame was an async (tearing) page flip */
};

enum luxcomp_vrr {
	LUXCOMP_VRR_OFF = 0,
	LUXCOMP_VRR_FULLSCREEN,		/* only under a fullscreen view (on the desktop VRR can flicker) */
	LUXCOMP_VRR_ALWAYS,
};

/* Properties for luxcomp_view_get() */
enum luxcomp_view_prop {
	LUXCOMP_VIEW_X = 1,		/* content (client geometry) in layout coordinates */
	LUXCOMP_VIEW_Y,
	LUXCOMP_VIEW_W,
	LUXCOMP_VIEW_H,
	LUXCOMP_VIEW_DECO_TOP,		/* height of the server-side title bar, 0 = none */
	LUXCOMP_VIEW_OUTPUT,		/* output under the view centre */
	LUXCOMP_VIEW_WORKSPACE,
	LUXCOMP_VIEW_PARENT,
	LUXCOMP_VIEW_MAPPED,
	LUXCOMP_VIEW_VISIBLE,
	LUXCOMP_VIEW_FOCUSED,
	LUXCOMP_VIEW_FULLSCREEN,
	LUXCOMP_VIEW_MAXIMIZED,
	LUXCOMP_VIEW_LAYER,
	LUXCOMP_VIEW_MIN_W, LUXCOMP_VIEW_MIN_H, LUXCOMP_VIEW_MAX_W, LUXCOMP_VIEW_MAX_H,
	LUXCOMP_VIEW_PID,
	LUXCOMP_VIEW_X11,		/* 1 = X11 window through XWayland */
	LUXCOMP_VIEW_SANDBOXED,		/* 1 = client of a wp-security-context socket (app sandbox) */
	LUXCOMP_VIEW_CONTENT_TYPE,	/* LUXCOMP_CONTENT_* (wp-content-type-v1) */
	LUXCOMP_VIEW_TEARING,		/* 1 = the client asks for async presentation (tearing-control-v1) */
};

enum luxcomp_content {
	LUXCOMP_CONTENT_NONE = 0,
	LUXCOMP_CONTENT_PHOTO,
	LUXCOMP_CONTENT_VIDEO,
	LUXCOMP_CONTENT_GAME,
};

/* View stacking layers, bottom to top: background, bottom, NORMAL, ABOVE, top (bar), FULLSCREEN, overlay */
enum luxcomp_layer {
	LUXCOMP_LAYER_NORMAL = 0,
	LUXCOMP_LAYER_ABOVE,
	LUXCOMP_LAYER_FULLSCREEN,
};

enum luxcomp_state {
	LUXCOMP_STATE_FULLSCREEN = 1,
	LUXCOMP_STATE_MAXIMIZED,
	LUXCOMP_STATE_TILED,
};

/* Theme of the server-side title bar; colours are 0xAARRGGBB */
enum luxcomp_theme_prop {
	LUXCOMP_THEME_TITLE_HEIGHT = 1,
	LUXCOMP_THEME_CORNER_RADIUS,
	LUXCOMP_THEME_BUTTON_SIZE,
	LUXCOMP_THEME_BUTTON_SPACING,
	LUXCOMP_THEME_BG_ACTIVE,
	LUXCOMP_THEME_BG_INACTIVE,
	LUXCOMP_THEME_TEXT_ACTIVE,
	LUXCOMP_THEME_TEXT_INACTIVE,
	LUXCOMP_THEME_CLOSE,
	LUXCOMP_THEME_MINIMIZE,
	LUXCOMP_THEME_MAXIMIZE,
	LUXCOMP_THEME_BUTTON_INACTIVE,
	LUXCOMP_THEME_SEPARATOR,	/* line under the title bar, 0 = none */
	LUXCOMP_THEME_GLYPH,		/* x - + on a hovered traffic light */
	LUXCOMP_THEME_SHADOW_ACTIVE,	/* shadow colour incl. alpha, 0 = no shadow */
	LUXCOMP_THEME_SHADOW_INACTIVE,
	LUXCOMP_THEME_SHADOW_ACTIVE_SIZE,	/* px the shadow reaches beyond the window */
	LUXCOMP_THEME_SHADOW_INACTIVE_SIZE,
	LUXCOMP_THEME_TITLE_HEIGHT_COMPACT,	/* luxcomp_view_set_compact() */
	LUXCOMP_THEME_BUTTON_INSET,		/* centre x of the first traffic light */
	LUXCOMP_THEME_BUTTON_INSET_COMPACT,
	LUXCOMP_THEME_BUTTON_RING,		/* 1 px ring of an inactive light */
	/* The bar takes the client's colour (uniform neutral top row of its content); a translucent or
	 * coloured client gets BG_LIGHT or BG_DARK, an unknown one BG_ACTIVE/BG_INACTIVE. TEXT_* and
	 * BUTTON_INACTIVE/RING are the ink on a light bar, DARK_* the ink on a dark bar. */
	LUXCOMP_THEME_BG_LIGHT,
	LUXCOMP_THEME_BG_DARK,
	LUXCOMP_THEME_DARK_TEXT_ACTIVE,
	LUXCOMP_THEME_DARK_TEXT_INACTIVE,
	LUXCOMP_THEME_DARK_BUTTON_INACTIVE,
	LUXCOMP_THEME_DARK_BUTTON_RING,
	LUXCOMP_THEME_ACCENT,			/* sandbox badge */
	LUXCOMP_THEME_BORDER,			/* 1 px line around the window, 0 = none */
	LUXCOMP_THEME_SHADOW_ACTIVE_OFFSET,	/* px the shadow is moved down, -1 = size / 4 */
	LUXCOMP_THEME_SHADOW_INACTIVE_OFFSET,
};

/* Lifecycle and event loop */
int64_t luxcomp_init(luxcomp_event_fn fn, void *user);	/* 0 = ok */
const char *luxcomp_socket(void);			/* WAYLAND_DISPLAY name after init */
/* Before luxcomp_start(): outputs already lit (the boot splash) keep their mode and picture, nothing
 * is committed until a client surface is visible or timeout_ms passed (no black modeset frame) */
void luxcomp_hold(int64_t timeout_ms);
int64_t luxcomp_start(void);				/* starts the backend, 0 = ok */
int64_t luxcomp_fd(void);				/* poll this, then luxcomp_dispatch(0) */
int64_t luxcomp_dispatch(int64_t timeout_ms);		/* <0 = quit requested or error */
void luxcomp_run(void);					/* dispatch until luxcomp_quit() */
void luxcomp_quit(void);
void luxcomp_destroy(void);
int64_t luxcomp_spawn(const char *command);		/* sh -c in the session with an activation token, returns pid */
int64_t luxcomp_software_rendering(void);		/* 1 = pixman (no 3D), animations should be cheap */
/* VT switch through the logind session (DRM backend only, else 0); luxcomp_session_active() turns 0 once the
 * switch took the session away (1 without a session). The greeter hands the screen over through an empty
 * graphics VT (docs/developers/wayland-session.md). */
int64_t luxcomp_switch_vt(int64_t vt);
int64_t luxcomp_session_active(void);
void luxcomp_set_background(int64_t argb);		/* solid colour below the wallpaper layer */

/* Outputs */
int64_t luxcomp_output_get(int64_t output, int64_t prop);
const char *luxcomp_output_name(int64_t output);
int64_t luxcomp_output_at(int64_t x, int64_t y);
void luxcomp_output_set(int64_t output, int64_t prop, int64_t value);	/* LUXCOMP_OUT_VRR, _TEARING */
/* Tests only: plug in a headless output of this size (returns its id, 0 without the headless
 * backend) and unplug it again. Real (DRM) outputs are never touched. */
int64_t luxcomp_test_output_add(int64_t width, int64_t height);
void luxcomp_test_output_remove(int64_t output);
int64_t luxcomp_cursor_x(void);
int64_t luxcomp_cursor_y(void);

/* Views (xdg toplevels) */
int64_t luxcomp_view_get(int64_t view, int64_t prop);
const char *luxcomp_view_app_id(int64_t view);
const char *luxcomp_view_title(int64_t view);
int64_t luxcomp_view_next(int64_t view);	/* stacking order top to bottom, 0 starts/ends */
void luxcomp_view_move(int64_t view, int64_t x, int64_t y);
void luxcomp_view_resize(int64_t view, int64_t w, int64_t h);
void luxcomp_view_focus(int64_t view);		/* keyboard focus + activated; 0 = nobody */
void luxcomp_view_raise(int64_t view);
void luxcomp_view_set_state(int64_t view, int64_t state, int64_t on);
void luxcomp_view_set_layer(int64_t view, int64_t layer);
void luxcomp_view_set_workspace(int64_t view, int64_t workspace);
void luxcomp_view_set_decorated(int64_t view, int64_t on);
/* Lower title bar (LUXCOMP_THEME_TITLE_HEIGHT_COMPACT): foreign apps, utility windows */
void luxcomp_view_set_compact(int64_t view, int64_t on);
/* Small label after the traffic lights of the server-side title bar (sandboxed apps); NULL or "" = none */
void luxcomp_view_set_badge(int64_t view, const char *text);
/* app_id and title the shell sees instead of what the client sets (the rootful Xwayland of a
 * sandbox shows "Xwayland on :0"); NULL or "" = the client's own */
void luxcomp_view_set_names(int64_t view, const char *app_id, const char *title);
/* wp-security-context-v1 metadata of a sandboxed view ("" when not sandboxed or not set) */
const char *luxcomp_view_sandbox_engine(int64_t view);
const char *luxcomp_view_sandbox_app_id(int64_t view);
const char *luxcomp_view_sandbox_instance(int64_t view);
/* Identifikator okna v ext-foreign-toplevel-list (grim -T, nahled v Alt+Tab); "" dokud okno neni mapovane */
const char *luxcomp_view_capture_id(int64_t view);
void luxcomp_view_set_visible(int64_t view, int64_t on);	/* minimize = 0 */
void luxcomp_view_close(int64_t view);
void luxcomp_view_begin_move(int64_t view);		/* until the button is released */
void luxcomp_view_begin_resize(int64_t view, int64_t edges);

/* Workspaces: groups of views that are shown or hidden together */
int64_t luxcomp_workspace_new(void);
void luxcomp_workspace_show(int64_t workspace, int64_t on);
/* Slides @from out and @to in (dir 1 = to comes from the right), then hides @from and sends
 * LUXCOMP_EV_SLIDE_DONE. Runs in C at the output refresh rate; ms <= 0 or frames too slow
 * (pixman) = instant. A new slide during a slide continues from the current position. */
void luxcomp_workspace_slide(int64_t from, int64_t to, int64_t dir, int64_t ms);

/* Input */
void luxcomp_set_keymap(const char *layout, const char *variant, const char *options);
void luxcomp_set_repeat(int64_t rate, int64_t delay_ms);
/* @key is an xkb keysym name ("Tab", "Left", "grave"), matched in the current and the first
 * layout, or "code:N" for a physical key (xkb keycode, 49 = the key under Esc). 0 = bad name. */
int64_t luxcomp_bind_key(int64_t mods, const char *key);
/* Stejne jako bind_key, ale drzeny klavesovy vstup opakuje az do uvolneni klavesy. */
int64_t luxcomp_bind_key_repeat(int64_t mods, const char *key);
void luxcomp_unbind_key(int64_t binding);
int64_t luxcomp_modifiers(void);			/* LUXCOMP_MOD_* currently held */
/* Keyboard layouts of the keymap from luxcomp_set_keymap() ("us,cz" = 2 layouts) */
void luxcomp_set_layout(int64_t index);
int64_t luxcomp_layout(void);
int64_t luxcomp_caps_lock(void);			/* 1 = Caps Lock on */
int64_t luxcomp_layout_count(void);
const char *luxcomp_layout_name(int64_t index);		/* xkb name, "English (US)"; "" = none */

/* Mice and touchpads (libinput devices; virtual pointers and the headless backend have none).
 * luxcomp_input_set() stores the value for every current and later plugged device of that kind;
 * LUXCOMP_INPUT_DEFAULT returns the device default. A device without the option ignores it. */
enum luxcomp_input_kind {
	LUXCOMP_INPUT_MOUSE = 1,	/* also trackballs and trackpoints */
	LUXCOMP_INPUT_TOUCHPAD,		/* devices that can tap */
};

enum luxcomp_input_prop {
	LUXCOMP_INPUT_KIND = 1,		/* luxcomp_input_get() only: LUXCOMP_INPUT_MOUSE/TOUCHPAD */
	LUXCOMP_INPUT_SPEED,		/* pointer acceleration speed -100..100 (libinput -1..1) */
	LUXCOMP_INPUT_ACCEL_PROFILE,	/* 0 adaptive, 1 flat */
	LUXCOMP_INPUT_NATURAL_SCROLL,	/* 0/1 */
	LUXCOMP_INPUT_LEFT_HANDED,
	LUXCOMP_INPUT_MIDDLE_EMULATION,	/* left + right together = middle button */
	LUXCOMP_INPUT_TAP,		/* tap to click */
	LUXCOMP_INPUT_TAP_DRAG,
	LUXCOMP_INPUT_DISABLE_WHILE_TYPING,
	LUXCOMP_INPUT_CLICK_METHOD,	/* 0 none, 1 button areas, 2 clickfinger */
	LUXCOMP_INPUT_SCROLL_METHOD,	/* 0 none, 1 two fingers, 2 edge, 3 on button down */
};

#define LUXCOMP_INPUT_DEFAULT (-1000)	/* luxcomp_input_set(): the device default */
#define LUXCOMP_INPUT_NONE (-1001)	/* luxcomp_input_get(): the device has no such option */

void luxcomp_input_set(int64_t kind, int64_t prop, int64_t value);
/* Read-back of what libinput really has, per device: 0 starts/ends the list */
int64_t luxcomp_input_next(int64_t device);
const char *luxcomp_input_name(int64_t device);
int64_t luxcomp_input_get(int64_t device, int64_t prop);

/* Privileged globals (screen capture, data-control, foreign-toplevel management, virtual input,
 * output management, session lock) are offered only to clients whose executable (/proc/PID/exe)
 * is on this list, never to clients of a wp-security-context socket. NULL clears the list. */
void luxcomp_privileged_allow(const char *exe_path);

/* XWayland, started lazily by the first X11 client. 0 = ok. X11 windows are ordinary views. */
int64_t luxcomp_xwayland_start(void);
const char *luxcomp_xwayland_display(void);	/* ":N" or NULL */
int64_t luxcomp_xwayland_running(void);		/* 1 while the X server runs */

/* IPC socket for the shell (docs/developers/luxwm-ipc.md): lines in, lines out. Connections from
 * another uid are refused (SO_PEERCRED); b of IPC_CONNECT says whether the executable is on the
 * privileged list. luxcomp_ipc_send() appends the newline and returns 0 when the client is gone
 * (no IPC_CLOSE follows then). */
int64_t luxcomp_ipc_listen(const char *path);		/* 0 = ok */
const char *luxcomp_ipc_line(int64_t client);
int64_t luxcomp_ipc_send(int64_t client, const char *line);
void luxcomp_ipc_close(int64_t client);

int64_t luxcomp_locked(void);			/* ext-session-lock active (also after the locker died) */

/* Games. A view on top of an output in LUXCOMP_LAYER_FULLSCREEN with the fullscreen state is scanned out
 * directly when nothing is drawn over it (no title bar, shadow, rounded corners, material). Clients get
 * pointer-constraints + relative-pointer (only in the focused view), keyboard-shortcuts-inhibit (key
 * bindings go to the client; Super+Escape toggles them back, Ctrl+Alt+F1..F12 always switches the VT),
 * tearing-control, content-type, gamma-control, drm-lease (non-desktop outputs, DRM only),
 * linux-dmabuf with scanout feedback and linux-drm-syncobj (when renderer and backend support them). */
int64_t luxcomp_pointer_constraint(void);	/* 0 none, 1 pointer locked, 2 confined */
void luxcomp_idle_inhibit(int64_t on);		/* policy keeps the screen on (fullscreen video or game) */

/* Night light and software brightness of every output: colour temperature in kelvin (<= 0 or 6500 =
 * neutral, 1000..6500) and brightness in % (10..100, for screens without a backlight). Uses the output's
 * gamma table (KMS GAMMA_LUT, no rendering cost); outputs without one (VMs, headless) get a warm and a
 * black translucent rectangle over everything instead (approximate, visible in screenshots). A gamma-control
 * client (gammastep, wlsunset) takes precedence on its output. */
void luxcomp_set_night_light(int64_t kelvin, int64_t brightness);
int64_t luxcomp_night_light_mode(int64_t output);	/* 0 off, 1 gamma table, 2 overlay */

/* Server-side decorations */
void luxcomp_theme_set(int64_t prop, int64_t value);
void luxcomp_theme_set_font(const char *pango_font);

/* Material of layer surfaces that ask for it with a namespace suffix "name@material[:radius]"
 * (and of their xdg popups, material "menu"): blurred backdrop under the surface plus a shadow.
 * @fallback is the opaque colour used when blur is off or too slow, @shadow the shadow colour
 * with alpha (0 = none), size and downward offset in px. Unknown names are added. */
void luxcomp_material_set(const char *name, int64_t radius, int64_t fallback, int64_t shadow,
	int64_t shadow_size, int64_t shadow_y);
/* Blur radius (logical px), saturation in % (160 = 1.6) and mode (0 = solid colour, 1 = auto) */
void luxcomp_blur_set(int64_t radius, int64_t saturation_pct, int64_t mode);
int64_t luxcomp_blur_tier(void);	/* 2 = gles2 dual Kawase, 1 = pixman in C, 0 = solid colour */
/* Material under a rectangle of a view's content (a translucent sidebar), in window geometry
 * coordinates (xdg window geometry: without the client's shadow margins), clipped to the window.
 * Same blur tiers and fallback colour as layer surfaces, no shadow of its own; corners lying in the
 * rounded corners of the window get the window radius. Follows the view (move, resize, workspace,
 * minimize); the backdrop is everything below the view. NULL or "" name or w/h <= 0 removes it. */
void luxcomp_view_set_material(int64_t view, const char *name, int64_t x, int64_t y, int64_t w, int64_t h);

/* Pointer image of the compositor (desktop, title bars); also exported as XCURSOR_THEME/SIZE
 * for clients started later. NULL theme = libxcursor default. Size in logical px. */
void luxcomp_set_cursor(const char *theme, int64_t size);

/* Launch feedback: after a client gets an xdg-activation token (Dock, Launchpad: GTK asks for one
 * when it starts an app) or after luxcomp_launch_start(), the arrow becomes the animated "progress"
 * pointer (desktop, title bars and clients that ask for the "default" shape) until the token is
 * used, a new window maps or timeout_ms passed. Shown only after 150 ms, so a window activating
 * itself with a fresh token does not blink it. 0 = off (the default). */
void luxcomp_launch_feedback(int64_t timeout_ms);
void luxcomp_launch_start(void);	/* the policy started a program itself (key binding) */

/* Window animations, stepped in C before every output frame; only the window's region is
 * redrawn. Each kind has a duration, 0 = off (the default). Input is never blocked: a closing or
 * minimising window is a picture of its last frame that takes no input, an opening or restored
 * window is live (clicks land on it while it grows). On pixman two slow frames in a row end the
 * running animations. A new animation of a view ends its previous one. */
enum luxcomp_anim {
	LUXCOMP_ANIM_OPEN = 1,	/* grows from 90 % and fades in; call after placing a mapped view */
	LUXCOMP_ANIM_CLOSE,	/* shrinks to 90 % and fades out; call on VIEW_UNMAP */
	LUXCOMP_ANIM_MINIMIZE,	/* shrinks into the Dock icon (set_rectangle of wlr-foreign-toplevel,
				 * else the bottom centre of its output); call before hiding the view */
	LUXCOMP_ANIM_RESTORE,	/* grows out of the Dock icon; call after showing the view */
};
void luxcomp_anim_set(int64_t kind, int64_t ms);
void luxcomp_view_animate(int64_t view, int64_t kind);	/* no-op for a hidden view or kind off */

/* Login transition like luxos-session-cover --login of the X11 session: a solid colour over everything
 * but the lock screen, already in the first frame when set before luxcomp_start() (with luxcomp_hold()
 * the cover ends the hold: the first commit carries it, no black modeset frame); it takes no input.
 * luxcomp_cover_frame() puts the greeter's last frame on the first output ("LUXFRAME1 <w> <h>\n" +
 * w*h*4 bytes BGRx, at most max_age_s old; 1 = loaded). luxcomp_cover_stage(0) shows the Plymouth-like
 * progress bar (220x6 where the password field was), stages 1..4 move it on (4 = done, it fills up).
 * luxcomp_cover_fade() fades everything out with opacity (1 - t)^2 and removes it, ms <= 0 at once;
 * argb with alpha 0 removes it too. */
void luxcomp_cover(int64_t argb);
int64_t luxcomp_cover_frame(const char *path, int64_t max_age_s);
void luxcomp_cover_stage(int64_t stage);
void luxcomp_cover_fade(int64_t ms);

#pragma GCC visibility pop

#endif /* LUXCOMP_H */
