/* wlt-client - testovaci okno xdg-shell (jednobarevna plocha s pruhy, bez fontu)
 * Pouziti: wlt-client [--title T] [--app-id ID] [--size WxH] [--color RRGGBB] [--hstripes] [--solid] [--events]
 * --events vypisuje na stdout udalosti (configure, enter, button, key) pro kontrolu vstupu.
 * --hstripes: vodorovne pruhy pro rychly vodorovny pohyb (prejezd ploch). Svisle pruhy posunute
 * o ~100 px mezi snimky se v pulce bloku nahodou shoduji a detektor blikani by mezisnimek oznacil.
 * --solid: jen barva --color bez pruhu (obsah jako terminal nebo dokument). */
#define _GNU_SOURCE
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include "xdg-shell-client-protocol.h"
#include "xdg-decoration-unstable-v1-client-protocol.h"

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct wl_seat *seat;
static struct xdg_wm_base *wm_base;
static struct zxdg_decoration_manager_v1 *deco_manager;
static struct wl_surface *surface;
static struct xdg_toplevel *toplevel;
static struct xkb_context *xkb;
static struct xkb_state *xkb_state;
static int width = 400, height = 300, pending_w, pending_h, running = 1, events, hstripes, solid;
static uint32_t color = 0x3b82f6;

static void say(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void say(const char *fmt, ...)
{
	if (!events)
		return;
	va_list ap;
	va_start(ap, fmt);
	vprintf(fmt, ap);
	va_end(ap);
	putchar('\n');
	fflush(stdout);
}

static void buffer_release(void *data, struct wl_buffer *buf)
{
	wl_buffer_destroy(buf);
}

static const struct wl_buffer_listener buffer_listener = { buffer_release };

static void draw(void)
{
	int stride = width * 4, size = stride * height;
	int fd = memfd_create("wlt-client", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, size) < 0)
		exit(1);
	uint32_t *px = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (px == MAP_FAILED)
		exit(1);
	/* svisle pruhy: pri tazeni okna je posun dobre videt i ve zmensenem snimku */
	uint32_t dark = solid ? color : (color >> 1) & 0x7f7f7f;
	for (int y = 0; y < height; y++)
		for (int x = 0; x < width; x++)
			px[y * width + x] = 0xff000000 | (((hstripes ? y : x) / 40) % 2 ? dark : color);
	munmap(px, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, size);
	struct wl_buffer *buf = wl_shm_pool_create_buffer(pool, 0, width, height, stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	wl_buffer_add_listener(buf, &buffer_listener, NULL);
	wl_surface_attach(surface, buf, 0, 0);
	wl_surface_damage_buffer(surface, 0, 0, width, height);
	wl_surface_commit(surface);
}

static void xdg_surface_configure(void *data, struct xdg_surface *xs, uint32_t serial)
{
	xdg_surface_ack_configure(xs, serial);
	if (pending_w > 0 && pending_h > 0) {
		width = pending_w;
		height = pending_h;
	}
	say("configure %d %d", width, height);
	draw();
}

static const struct xdg_surface_listener xdg_surface_listener = { xdg_surface_configure };

static void tl_configure(void *data, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *states)
{
	pending_w = w;
	pending_h = h;
}

static void tl_close(void *data, struct xdg_toplevel *t)
{
	running = 0;
}

static void tl_bounds(void *data, struct xdg_toplevel *t, int32_t w, int32_t h) {}
static void tl_caps(void *data, struct xdg_toplevel *t, struct wl_array *caps) {}

static const struct xdg_toplevel_listener toplevel_listener = { tl_configure, tl_close, tl_bounds, tl_caps };

static void ping(void *data, struct xdg_wm_base *b, uint32_t serial)
{
	xdg_wm_base_pong(b, serial);
}

static const struct xdg_wm_base_listener wm_base_listener = { ping };

static void p_enter(void *d, struct wl_pointer *p, uint32_t s, struct wl_surface *sf, wl_fixed_t x, wl_fixed_t y)
{
	say("enter %d %d", wl_fixed_to_int(x), wl_fixed_to_int(y));
}
static void p_leave(void *d, struct wl_pointer *p, uint32_t s, struct wl_surface *sf) { say("leave"); }
static void p_motion(void *d, struct wl_pointer *p, uint32_t t, wl_fixed_t x, wl_fixed_t y) {}
static void p_button(void *d, struct wl_pointer *p, uint32_t s, uint32_t t, uint32_t b, uint32_t st)
{
	say("button %u %s", b, st ? "down" : "up");
}
static void p_axis(void *d, struct wl_pointer *p, uint32_t t, uint32_t a, wl_fixed_t v) {}
static void p_frame(void *d, struct wl_pointer *p) {}
static void p_axis_source(void *d, struct wl_pointer *p, uint32_t s) {}
static void p_axis_stop(void *d, struct wl_pointer *p, uint32_t t, uint32_t a) {}
static void p_axis_discrete(void *d, struct wl_pointer *p, uint32_t a, int32_t v) {}

static const struct wl_pointer_listener pointer_listener = {
	.enter = p_enter, .leave = p_leave, .motion = p_motion, .button = p_button, .axis = p_axis,
	.frame = p_frame, .axis_source = p_axis_source, .axis_stop = p_axis_stop, .axis_discrete = p_axis_discrete,
};

static void k_keymap(void *d, struct wl_keyboard *k, uint32_t fmt, int fd, uint32_t size)
{
	char *map = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
	close(fd);
	if (map == MAP_FAILED)
		return;
	struct xkb_keymap *km = xkb_keymap_new_from_string(xkb, map, XKB_KEYMAP_FORMAT_TEXT_V1, 0);
	munmap(map, size);
	if (!km)
		return;
	if (xkb_state)
		xkb_state_unref(xkb_state);
	xkb_state = xkb_state_new(km);
	xkb_keymap_unref(km);
}
static void k_enter(void *d, struct wl_keyboard *k, uint32_t s, struct wl_surface *sf, struct wl_array *keys)
{
	/* cas CLOCK_MONOTONIC v us: testy z nej pocitaji prodlevu zkratka -> zamereni */
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	say("focus %lld", (long long)ts.tv_sec * 1000000 + ts.tv_nsec / 1000);
}
static void k_leave(void *d, struct wl_keyboard *k, uint32_t s, struct wl_surface *sf) { say("unfocus"); }
static void k_key(void *d, struct wl_keyboard *k, uint32_t s, uint32_t t, uint32_t key, uint32_t st)
{
	char name[64] = "?";
	if (xkb_state)
		xkb_keysym_get_name(xkb_state_key_get_one_sym(xkb_state, key + 8), name, sizeof name);
	say("key %s %s", name, st ? "down" : "up");
}
static void k_mods(void *d, struct wl_keyboard *k, uint32_t s, uint32_t dep, uint32_t lat, uint32_t lock, uint32_t grp)
{
	if (xkb_state)
		xkb_state_update_mask(xkb_state, dep, lat, lock, 0, 0, grp);
}
static void k_repeat(void *d, struct wl_keyboard *k, int32_t rate, int32_t delay) {}

static const struct wl_keyboard_listener keyboard_listener = { k_keymap, k_enter, k_leave, k_key, k_mods, k_repeat };

/* ukazatel a klavesnice vzniknou az s prvnim (i virtualnim) zarizenim */
static void seat_caps(void *data, struct wl_seat *s, uint32_t caps)
{
	static struct wl_pointer *pointer;
	static struct wl_keyboard *keyboard;
	if ((caps & WL_SEAT_CAPABILITY_POINTER) && !pointer) {
		pointer = wl_seat_get_pointer(s);
		wl_pointer_add_listener(pointer, &pointer_listener, NULL);
	}
	if ((caps & WL_SEAT_CAPABILITY_KEYBOARD) && !keyboard) {
		keyboard = wl_seat_get_keyboard(s);
		wl_keyboard_add_listener(keyboard, &keyboard_listener, NULL);
	}
}

static void seat_name(void *data, struct wl_seat *s, const char *name) {}

static const struct wl_seat_listener seat_listener = { seat_caps, seat_name };

static void global(void *data, struct wl_registry *reg, uint32_t name, const char *iface, uint32_t ver)
{
	if (!strcmp(iface, wl_compositor_interface.name))
		compositor = wl_registry_bind(reg, name, &wl_compositor_interface, 4);
	else if (!strcmp(iface, wl_shm_interface.name))
		shm = wl_registry_bind(reg, name, &wl_shm_interface, 1);
	else if (!strcmp(iface, wl_seat_interface.name) && !seat)
		seat = wl_registry_bind(reg, name, &wl_seat_interface, ver < 5 ? ver : 5);
	else if (!strcmp(iface, xdg_wm_base_interface.name))
		wm_base = wl_registry_bind(reg, name, &xdg_wm_base_interface, 1);
	else if (!strcmp(iface, zxdg_decoration_manager_v1_interface.name))
		deco_manager = wl_registry_bind(reg, name, &zxdg_decoration_manager_v1_interface, 1);
}

static void global_remove(void *data, struct wl_registry *reg, uint32_t name) {}

static const struct wl_registry_listener reg_listener = { global, global_remove };

int main(int argc, char **argv)
{
	const char *title = "wlt-client", *app_id = "wlt-client";
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--events"))
			events = 1;
		else if (!strcmp(argv[i], "--hstripes"))
			hstripes = 1;
		else if (!strcmp(argv[i], "--solid"))
			solid = 1;
		else if (i + 1 < argc && !strcmp(argv[i], "--title"))
			title = argv[++i];
		else if (i + 1 < argc && !strcmp(argv[i], "--app-id"))
			app_id = argv[++i];
		else if (i + 1 < argc && !strcmp(argv[i], "--size"))
			sscanf(argv[++i], "%dx%d", &width, &height);
		else if (i + 1 < argc && !strcmp(argv[i], "--color"))
			color = strtoul(argv[++i], NULL, 16);
		else {
			fprintf(stderr, "usage: wlt-client [--title T] [--app-id ID] [--size WxH] [--color RRGGBB] [--hstripes] [--solid] [--events]\n");
			return 2;
		}
	}
	struct wl_display *display = wl_display_connect(NULL);
	if (!display) {
		fprintf(stderr, "cannot connect to wayland display\n");
		return 1;
	}
	wl_registry_add_listener(wl_display_get_registry(display), &reg_listener, NULL);
	wl_display_roundtrip(display);
	if (!compositor || !shm || !wm_base) {
		fprintf(stderr, "compositor lacks wl_compositor/wl_shm/xdg_wm_base\n");
		return 1;
	}
	xkb = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	xdg_wm_base_add_listener(wm_base, &wm_base_listener, NULL);
	if (seat)
		wl_seat_add_listener(seat, &seat_listener, NULL);
	surface = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
	xdg_surface_add_listener(xs, &xdg_surface_listener, NULL);
	toplevel = xdg_surface_get_toplevel(xs);
	xdg_toplevel_add_listener(toplevel, &toplevel_listener, NULL);
	xdg_toplevel_set_title(toplevel, title);
	xdg_toplevel_set_app_id(toplevel, app_id);
	/* okno s titulkem od kompozitoru (SSD), at jde tahat jako bezna aplikace */
	if (deco_manager)
		zxdg_toplevel_decoration_v1_set_mode(
			zxdg_decoration_manager_v1_get_toplevel_decoration(deco_manager, toplevel),
			ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
	wl_surface_commit(surface);
	while (running && wl_display_dispatch(display) != -1)
		;
	wl_display_disconnect(display);
	return 0;
}
