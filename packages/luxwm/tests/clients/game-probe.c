/*
 * Testovaci klient her pro luxwm (test_luxwm_gaming.py): nepruhledne okno (XRGB, skryty kurzor jako hra)
 * s protokoly pro hry. Vypisuje radky (vzdy hned flush):
 *   configure W H fs  |  ready  |  enter  |  leave  |  motion X Y  |  rel DX DY  |  locked  |  unlocked
 *   confined  |  unconfined  |  kbfocus 0/1  |  key CODE 0/1  |  inhibit active/inactive
 *
 *   game-probe [--title T] [--size WxH] [--fullscreen] [--lock] [--confine] [--inhibit] [--tearing]
 *              [--content photo|video|game]
 *   game-probe --inject DX DY N   N relativnich pohybu pres zwlr_virtual_pointer_v1 (allowlist)
 *   game-probe --idle MS          ext-idle-notify s casovacem MS: "idled" / "resumed"
 *   game-probe --globals          "global JMENO VERZE" za kazdy nabizeny global
 */
#define _GNU_SOURCE
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include "pointer-constraints-unstable-v1-client-protocol.h"
#include "relative-pointer-unstable-v1-client-protocol.h"
#include "keyboard-shortcuts-inhibit-unstable-v1-client-protocol.h"
#include "tearing-control-v1-client-protocol.h"
#include "content-type-v1-client-protocol.h"
#include "ext-idle-notify-v1-client-protocol.h"
#include "wlr-virtual-pointer-unstable-v1-client-protocol.h"

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct wl_seat *seat;
static struct xdg_wm_base *wm_base;
static struct zwp_pointer_constraints_v1 *constraints;
static struct zwp_relative_pointer_manager_v1 *relative;
static struct zwp_keyboard_shortcuts_inhibit_manager_v1 *inhibit_mgr;
static struct wp_tearing_control_manager_v1 *tearing_mgr;
static struct wp_content_type_manager_v1 *content_mgr;
static struct ext_idle_notifier_v1 *idle_notifier;
static struct zwlr_virtual_pointer_manager_v1 *vpointer_mgr;

static struct wl_surface *surface;
static struct wl_pointer *pointer;
static int width = 400, height = 300, configured_w, configured_h;
static int want_lock, want_confine;
static int ready, print_globals;

static void
out(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	vprintf(fmt, ap);
	va_end(ap);
	putchar('\n');
	fflush(stdout);
}

static void
global(void *data, struct wl_registry *r, uint32_t name, const char *iface, uint32_t version)
{
	if (print_globals) {
		out("global %s %u", iface, version);
	}
	if (!strcmp(iface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
	} else if (!strcmp(iface, wl_shm_interface.name)) {
		shm = wl_registry_bind(r, name, &wl_shm_interface, 1);
	} else if (!strcmp(iface, wl_seat_interface.name)) {
		seat = wl_registry_bind(r, name, &wl_seat_interface, 5);
	} else if (!strcmp(iface, xdg_wm_base_interface.name)) {
		wm_base = wl_registry_bind(r, name, &xdg_wm_base_interface, 1);
	} else if (!strcmp(iface, zwp_pointer_constraints_v1_interface.name)) {
		constraints = wl_registry_bind(r, name, &zwp_pointer_constraints_v1_interface, 1);
	} else if (!strcmp(iface, zwp_relative_pointer_manager_v1_interface.name)) {
		relative = wl_registry_bind(r, name, &zwp_relative_pointer_manager_v1_interface, 1);
	} else if (!strcmp(iface, zwp_keyboard_shortcuts_inhibit_manager_v1_interface.name)) {
		inhibit_mgr = wl_registry_bind(r, name, &zwp_keyboard_shortcuts_inhibit_manager_v1_interface, 1);
	} else if (!strcmp(iface, wp_tearing_control_manager_v1_interface.name)) {
		tearing_mgr = wl_registry_bind(r, name, &wp_tearing_control_manager_v1_interface, 1);
	} else if (!strcmp(iface, wp_content_type_manager_v1_interface.name)) {
		content_mgr = wl_registry_bind(r, name, &wp_content_type_manager_v1_interface, 1);
	} else if (!strcmp(iface, ext_idle_notifier_v1_interface.name)) {
		idle_notifier = wl_registry_bind(r, name, &ext_idle_notifier_v1_interface, 1);
	} else if (!strcmp(iface, zwlr_virtual_pointer_manager_v1_interface.name)) {
		vpointer_mgr = wl_registry_bind(r, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
	}
}

static void
global_remove(void *data, struct wl_registry *r, uint32_t name)
{
}

static const struct wl_registry_listener registry_listener = { global, global_remove };

/* ---- kresleni ---- */

static void
buffer_release(void *data, struct wl_buffer *b)
{
	wl_buffer_destroy(b);
}

static const struct wl_buffer_listener buffer_listener = { buffer_release };

static void
draw(void)
{
	int stride = width * 4, size = stride * height;
	int fd = memfd_create("game-probe", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, size) < 0) {
		exit(1);
	}
	uint32_t *px = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	for (int i = 0; i < width * height; i++) {
		px[i] = 0x00c03020;
	}
	munmap(px, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, size);
	struct wl_buffer *b = wl_shm_pool_create_buffer(pool, 0, width, height, stride, WL_SHM_FORMAT_XRGB8888);
	wl_buffer_add_listener(b, &buffer_listener, NULL);
	wl_shm_pool_destroy(pool);
	close(fd);
	wl_surface_attach(surface, b, 0, 0);
	wl_surface_damage_buffer(surface, 0, 0, width, height);
	wl_surface_commit(surface);
}

/* ---- xdg ---- */

static void
wm_ping(void *data, struct xdg_wm_base *b, uint32_t serial)
{
	xdg_wm_base_pong(b, serial);
}

static const struct xdg_wm_base_listener wm_listener = { wm_ping };

static void
surface_configure(void *data, struct xdg_surface *s, uint32_t serial)
{
	xdg_surface_ack_configure(s, serial);
	if (configured_w > 0 && configured_h > 0) {
		width = configured_w;
		height = configured_h;
	}
	draw();
	if (!ready) {
		ready = 1;
		out("ready");
	}
}

static const struct xdg_surface_listener surface_listener = { surface_configure };

static void
toplevel_configure(void *data, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *states)
{
	int fs = 0;
	uint32_t *st;
	wl_array_for_each(st, states) {
		fs |= *st == XDG_TOPLEVEL_STATE_FULLSCREEN;
	}
	configured_w = w;
	configured_h = h;
	out("configure %d %d %d", w, h, fs);
}

static void
toplevel_close(void *data, struct xdg_toplevel *t)
{
	exit(0);
}

static void
toplevel_bounds(void *data, struct xdg_toplevel *t, int32_t w, int32_t h)
{
}

static void
toplevel_caps(void *data, struct xdg_toplevel *t, struct wl_array *caps)
{
}

static const struct xdg_toplevel_listener toplevel_listener = {
	toplevel_configure, toplevel_close, toplevel_bounds, toplevel_caps
};

/* ---- vstup ---- */

static void
p_enter(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *s, wl_fixed_t x, wl_fixed_t y)
{
	wl_pointer_set_cursor(p, serial, NULL, 0, 0);	/* hra kurzor skryje */
	out("enter");
}

static void
p_leave(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *s)
{
	out("leave");
}

static void
p_motion(void *data, struct wl_pointer *p, uint32_t time, wl_fixed_t x, wl_fixed_t y)
{
	out("motion %d %d", wl_fixed_to_int(x), wl_fixed_to_int(y));
}

static void
p_button(void *data, struct wl_pointer *p, uint32_t serial, uint32_t time, uint32_t button, uint32_t state)
{
}

static void
p_axis(void *data, struct wl_pointer *p, uint32_t time, uint32_t axis, wl_fixed_t value)
{
}

static void p_frame(void *data, struct wl_pointer *p) {}
static void p_axis_source(void *data, struct wl_pointer *p, uint32_t s) {}
static void p_axis_stop(void *data, struct wl_pointer *p, uint32_t t, uint32_t a) {}
static void p_axis_discrete(void *data, struct wl_pointer *p, uint32_t a, int32_t d) {}

static const struct wl_pointer_listener pointer_listener = {
	p_enter, p_leave, p_motion, p_button, p_axis, p_frame, p_axis_source, p_axis_stop, p_axis_discrete
};

static void
rel_motion(void *data, struct zwp_relative_pointer_v1 *r, uint32_t hi, uint32_t lo,
		wl_fixed_t dx, wl_fixed_t dy, wl_fixed_t udx, wl_fixed_t udy)
{
	out("rel %.0f %.0f", wl_fixed_to_double(udx), wl_fixed_to_double(udy));
}

static const struct zwp_relative_pointer_v1_listener rel_listener = { rel_motion };

static void locked(void *d, struct zwp_locked_pointer_v1 *l) { out("locked"); }
static void unlocked(void *d, struct zwp_locked_pointer_v1 *l) { out("unlocked"); }
static const struct zwp_locked_pointer_v1_listener locked_listener = { locked, unlocked };
static void confined(void *d, struct zwp_confined_pointer_v1 *c) { out("confined"); }
static void unconfined(void *d, struct zwp_confined_pointer_v1 *c) { out("unconfined"); }
static const struct zwp_confined_pointer_v1_listener confined_listener = { confined, unconfined };

static void
k_keymap(void *data, struct wl_keyboard *k, uint32_t format, int32_t fd, uint32_t size)
{
	close(fd);
}

static void
k_enter(void *data, struct wl_keyboard *k, uint32_t serial, struct wl_surface *s, struct wl_array *keys)
{
	out("kbfocus 1");
}

static void
k_leave(void *data, struct wl_keyboard *k, uint32_t serial, struct wl_surface *s)
{
	out("kbfocus 0");
}

static void
k_key(void *data, struct wl_keyboard *k, uint32_t serial, uint32_t time, uint32_t key, uint32_t state)
{
	out("key %u %u", key, state);
}

static void k_mods(void *d, struct wl_keyboard *k, uint32_t s, uint32_t a, uint32_t b, uint32_t c, uint32_t g) {}
static void k_repeat(void *d, struct wl_keyboard *k, int32_t rate, int32_t delay) {}

static const struct wl_keyboard_listener keyboard_listener = {
	k_keymap, k_enter, k_leave, k_key, k_mods, k_repeat
};

static void inhibit_active(void *d, struct zwp_keyboard_shortcuts_inhibitor_v1 *i) { out("inhibit active"); }
static void inhibit_inactive(void *d, struct zwp_keyboard_shortcuts_inhibitor_v1 *i) { out("inhibit inactive"); }
static const struct zwp_keyboard_shortcuts_inhibitor_v1_listener inhibit_listener = {
	inhibit_active, inhibit_inactive
};

static void idled(void *d, struct ext_idle_notification_v1 *n) { out("idled"); }
static void resumed(void *d, struct ext_idle_notification_v1 *n) { out("resumed"); }
static const struct ext_idle_notification_v1_listener idle_listener = { idled, resumed };

static struct wl_display *
connect(void)
{
	struct wl_display *dpy = wl_display_connect(NULL);
	if (!dpy) {
		fprintf(stderr, "game-probe: no wayland display\n");
		exit(1);
	}
	struct wl_registry *reg = wl_display_get_registry(dpy);
	wl_registry_add_listener(reg, &registry_listener, NULL);
	wl_display_roundtrip(dpy);
	return dpy;
}

static int
inject(struct wl_display *dpy, double dx, double dy, int n)
{
	if (!vpointer_mgr) {
		out("no virtual pointer");
		return 1;
	}
	struct zwlr_virtual_pointer_v1 *vp = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(vpointer_mgr, seat);
	wl_display_roundtrip(dpy);
	for (int i = 0; i < n; i++) {
		struct timespec t;
		clock_gettime(CLOCK_MONOTONIC, &t);
		zwlr_virtual_pointer_v1_motion(vp, t.tv_sec * 1000 + t.tv_nsec / 1000000,
			wl_fixed_from_double(dx), wl_fixed_from_double(dy));
		zwlr_virtual_pointer_v1_frame(vp);
		wl_display_roundtrip(dpy);
		usleep(20000);
	}
	zwlr_virtual_pointer_v1_destroy(vp);
	wl_display_roundtrip(dpy);
	out("injected");
	return 0;
}

int
main(int argc, char **argv)
{
	const char *title = "game", *content = NULL;
	int fullscreen = 0, want_inhibit = 0, want_tearing = 0;
	struct wl_display *dpy;
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--inject") && i + 3 < argc) {
			dpy = connect();
			return inject(dpy, atof(argv[i + 1]), atof(argv[i + 2]), atoi(argv[i + 3]));
		} else if (!strcmp(argv[i], "--globals")) {
			print_globals = 1;
			connect();
			return 0;
		} else if (!strcmp(argv[i], "--idle") && i + 1 < argc) {
			dpy = connect();
			if (!idle_notifier) {
				out("no idle notifier");
				return 1;
			}
			struct ext_idle_notification_v1 *n =
				ext_idle_notifier_v1_get_idle_notification(idle_notifier, atoi(argv[i + 1]), seat);
			ext_idle_notification_v1_add_listener(n, &idle_listener, NULL);
			out("watching");
			while (wl_display_dispatch(dpy) >= 0) {
			}
			return 0;
		} else if (!strcmp(argv[i], "--title") && i + 1 < argc) {
			title = argv[++i];
		} else if (!strcmp(argv[i], "--size") && i + 1 < argc) {
			sscanf(argv[++i], "%dx%d", &width, &height);
		} else if (!strcmp(argv[i], "--fullscreen")) {
			fullscreen = 1;
		} else if (!strcmp(argv[i], "--lock")) {
			want_lock = 1;
		} else if (!strcmp(argv[i], "--confine")) {
			want_confine = 1;
		} else if (!strcmp(argv[i], "--inhibit")) {
			want_inhibit = 1;
		} else if (!strcmp(argv[i], "--tearing")) {
			want_tearing = 1;
		} else if (!strcmp(argv[i], "--content") && i + 1 < argc) {
			content = argv[++i];
		}
	}
	dpy = connect();
	if (!compositor || !shm || !wm_base || !seat) {
		fprintf(stderr, "game-probe: missing core globals\n");
		return 1;
	}
	out("protocols constraints=%d relative=%d inhibit=%d tearing=%d content=%d", !!constraints, !!relative,
		!!inhibit_mgr, !!tearing_mgr, !!content_mgr);
	xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
	surface = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
	xdg_surface_add_listener(xs, &surface_listener, NULL);
	struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
	xdg_toplevel_add_listener(top, &toplevel_listener, NULL);
	xdg_toplevel_set_title(top, title);
	xdg_toplevel_set_app_id(top, "game-probe");
	if (fullscreen) {
		xdg_toplevel_set_fullscreen(top, NULL);
	}
	if (want_tearing && tearing_mgr) {
		struct wp_tearing_control_v1 *tc = wp_tearing_control_manager_v1_get_tearing_control(tearing_mgr, surface);
		wp_tearing_control_v1_set_presentation_hint(tc, WP_TEARING_CONTROL_V1_PRESENTATION_HINT_ASYNC);
	}
	if (content && content_mgr) {
		struct wp_content_type_v1 *ct = wp_content_type_manager_v1_get_surface_content_type(content_mgr, surface);
		uint32_t type = !strcmp(content, "game") ? WP_CONTENT_TYPE_V1_TYPE_GAME
			: !strcmp(content, "video") ? WP_CONTENT_TYPE_V1_TYPE_VIDEO : WP_CONTENT_TYPE_V1_TYPE_PHOTO;
		wp_content_type_v1_set_content_type(ct, type);
	}
	wl_surface_commit(surface);

	pointer = wl_seat_get_pointer(seat);
	wl_pointer_add_listener(pointer, &pointer_listener, NULL);
	struct wl_keyboard *kb = wl_seat_get_keyboard(seat);
	wl_keyboard_add_listener(kb, &keyboard_listener, NULL);
	if (relative) {
		struct zwp_relative_pointer_v1 *rp = zwp_relative_pointer_manager_v1_get_relative_pointer(relative, pointer);
		zwp_relative_pointer_v1_add_listener(rp, &rel_listener, NULL);
	}
	if (want_lock && constraints) {
		struct zwp_locked_pointer_v1 *l = zwp_pointer_constraints_v1_lock_pointer(constraints, surface, pointer,
			NULL, ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
		zwp_locked_pointer_v1_add_listener(l, &locked_listener, NULL);
		zwp_locked_pointer_v1_set_cursor_position_hint(l, wl_fixed_from_int(width / 2), wl_fixed_from_int(height / 2));
	} else if (want_confine && constraints) {
		struct zwp_confined_pointer_v1 *c = zwp_pointer_constraints_v1_confine_pointer(constraints, surface, pointer,
			NULL, ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
		zwp_confined_pointer_v1_add_listener(c, &confined_listener, NULL);
	}
	if (want_inhibit && inhibit_mgr) {
		struct zwp_keyboard_shortcuts_inhibitor_v1 *in =
			zwp_keyboard_shortcuts_inhibit_manager_v1_inhibit_shortcuts(inhibit_mgr, surface, seat);
		zwp_keyboard_shortcuts_inhibitor_v1_add_listener(in, &inhibit_listener, NULL);
	}
	while (wl_display_dispatch(dpy) >= 0) {
	}
	return 0;
}
