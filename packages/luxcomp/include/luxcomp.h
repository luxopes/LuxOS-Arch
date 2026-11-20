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

#define LUXCOMP_API_VERSION 5

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
};

enum luxcomp_request {
	LUXCOMP_REQ_MOVE = 1,		/* client asks for an interactive move (CSD title bar) */
	LUXCOMP_REQ_RESIZE,		/* b=edges (LUXCOMP_EDGE_*) */
	LUXCOMP_REQ_MAXIMIZE,		/* b=1 on, 0 off */
	LUXCOMP_REQ_FULLSCREEN,		/* b=1 on, 0 off */
	LUXCOMP_REQ_MINIMIZE,		/* b=1 minimise, 0 restore (Dock) */
	LUXCOMP_REQ_ACTIVATE,		/* b=LUXCOMP_ORIGIN_* c=view that made the xdg-activation token */
	LUXCOMP_REQ_DECORATION,		/* b=1 client wants server-side decoration, 0 client-side */
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
	LUXCOMP_THEME_SEPARATOR,
	LUXCOMP_THEME_GLYPH,		/* x - + on a hovered traffic light */
	LUXCOMP_THEME_SHADOW_ACTIVE,	/* shadow colour incl. alpha, 0 = no shadow */
	LUXCOMP_THEME_SHADOW_INACTIVE,
	LUXCOMP_THEME_SHADOW_ACTIVE_SIZE,	/* px the shadow reaches beyond the window */
	LUXCOMP_THEME_SHADOW_INACTIVE_SIZE,
};

/* Lifecycle and event loop */
int64_t luxcomp_init(luxcomp_event_fn fn, void *user);	/* 0 = ok */
const char *luxcomp_socket(void);			/* WAYLAND_DISPLAY name after init */
int64_t luxcomp_start(void);				/* starts the backend, 0 = ok */
int64_t luxcomp_fd(void);				/* poll this, then luxcomp_dispatch(0) */
int64_t luxcomp_dispatch(int64_t timeout_ms);		/* <0 = quit requested or error */
void luxcomp_run(void);					/* dispatch until luxcomp_quit() */
void luxcomp_quit(void);
void luxcomp_destroy(void);
int64_t luxcomp_spawn(const char *command);		/* sh -c in the session with an activation token, returns pid */
int64_t luxcomp_software_rendering(void);		/* 1 = pixman (no 3D), animations should be cheap */
void luxcomp_set_background(int64_t argb);		/* solid colour below the wallpaper layer */

/* Outputs */
int64_t luxcomp_output_get(int64_t output, int64_t prop);
const char *luxcomp_output_name(int64_t output);
int64_t luxcomp_output_at(int64_t x, int64_t y);
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
void luxcomp_unbind_key(int64_t binding);
int64_t luxcomp_modifiers(void);			/* LUXCOMP_MOD_* currently held */
/* Keyboard layouts of the keymap from luxcomp_set_keymap() ("us,cz" = 2 layouts) */
void luxcomp_set_layout(int64_t index);
int64_t luxcomp_layout(void);
int64_t luxcomp_layout_count(void);
const char *luxcomp_layout_name(int64_t index);		/* xkb name, "English (US)"; "" = none */

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

/* Server-side decorations */
void luxcomp_theme_set(int64_t prop, int64_t value);
void luxcomp_theme_set_font(const char *pango_font);

/* Pointer image of the compositor (desktop, title bars); also exported as XCURSOR_THEME/SIZE
 * for clients started later. NULL theme = libxcursor default. Size in logical px. */
void luxcomp_set_cursor(const char *theme, int64_t size);

#pragma GCC visibility pop

#endif /* LUXCOMP_H */
