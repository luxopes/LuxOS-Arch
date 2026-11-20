/*
 * Testovaci aplikace pro okna sandboxu na Waylandu (test_wayland.py). Bezi v sandboxu i mimo nej.
 *
 *   wl-sandbox-app --globals              "global JMENO CISLO" za kazdy nabizeny global
 *   wl-sandbox-app --bind JMENO CISLO     zkusi global bindnout i bez nabidky: "bound" / "refused"
 *   wl-sandbox-app --connect CESTA        spojeni na soket UNIX (@jmeno = abstraktni): "connected" / "refused"
 *   wl-sandbox-app --window APP TITULEK [--copy TEXT] [--activate-ms MS] [--stay MS]
 *       okno 320x200 (zahlavi od kompozitoru, kdyz nabizi xdg-decoration); vypisuje "mapped",
 *       "focus-in", "focus-out", "key KOD", "button", "selection" a "clip TEXT" (obsah schranky
 *       text/plain, kdyz ji kompozitor posle). --copy: pri prvnim zamereni nastavi schranku na TEXT.
 *       --activate-ms: po MS ms pozada o aktivaci vlastnim tokenem (bez vstupu), vypise "activate".
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include "xdg-decoration-unstable-v1-client-protocol.h"
#include "xdg-activation-v1-client-protocol.h"

static struct wl_display *display;
static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct wl_seat *seat;
static struct xdg_wm_base *wm_base;
static struct zxdg_decoration_manager_v1 *deco_manager;
static struct xdg_activation_v1 *activation;
static struct wl_data_device_manager *ddm;
static bool print_globals;
static const char *wanted;
static uint32_t wanted_version = 1;

static void
say(const char *fmt, ...)
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
		say("global %s %u", iface, name);
	}
	if (wanted && !strcmp(iface, wanted)) {
		wanted_version = version;
	}
	if (!strcmp(iface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
	} else if (!strcmp(iface, wl_shm_interface.name)) {
		shm = wl_registry_bind(r, name, &wl_shm_interface, 1);
	} else if (!strcmp(iface, wl_seat_interface.name) && !seat) {
		seat = wl_registry_bind(r, name, &wl_seat_interface, 5);
	} else if (!strcmp(iface, xdg_wm_base_interface.name)) {
		wm_base = wl_registry_bind(r, name, &xdg_wm_base_interface, 1);
	} else if (!strcmp(iface, zxdg_decoration_manager_v1_interface.name)) {
		deco_manager = wl_registry_bind(r, name, &zxdg_decoration_manager_v1_interface, 1);
	} else if (!strcmp(iface, xdg_activation_v1_interface.name)) {
		activation = wl_registry_bind(r, name, &xdg_activation_v1_interface, 1);
	} else if (!strcmp(iface, wl_data_device_manager_interface.name)) {
		ddm = wl_registry_bind(r, name, &wl_data_device_manager_interface, 3);
	}
}

static void
global_remove(void *data, struct wl_registry *r, uint32_t name)
{
}

static const struct wl_registry_listener registry_listener = { global, global_remove };

static void
connect_display(void)
{
	display = wl_display_connect(NULL);
	if (!display) {
		say("no-display");
		exit(2);
	}
	wl_registry_add_listener(wl_display_get_registry(display), &registry_listener, NULL);
	wl_display_roundtrip(display);
}

/* ---- --connect ---- */

static int
try_connect(const char *path)
{
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	socklen_t len;
	if (path[0] == '@') {
		strncpy(addr.sun_path + 1, path + 1, sizeof(addr.sun_path) - 2);
		len = offsetof(struct sockaddr_un, sun_path) + 1 + strlen(path + 1);
	} else {
		strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);
		len = sizeof(addr);
	}
	int fd = socket(AF_UNIX, SOCK_STREAM, 0);
	bool ok = fd >= 0 && connect(fd, (struct sockaddr *)&addr, len) == 0;
	say(ok ? "connected" : "refused %s", strerror(errno));
	return 0;
}

/* ---- okno ---- */

static struct wl_surface *surface;
static bool configured, focused_once, done;
static const char *copy_text;
static struct wl_data_device *data_device;
static struct wl_data_offer *selection_offer;
static bool offer_text;
static char token[256];

static void
ping(void *data, struct xdg_wm_base *b, uint32_t serial)
{
	xdg_wm_base_pong(b, serial);
}

static const struct xdg_wm_base_listener wm_listener = { ping };

static void
surface_configure(void *data, struct xdg_surface *s, uint32_t serial)
{
	xdg_surface_ack_configure(s, serial);
	configured = true;
}

static const struct xdg_surface_listener surface_listener = { surface_configure };

static void
top_configure(void *data, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *states)
{
}

static void
top_close(void *data, struct xdg_toplevel *t)
{
	done = true;
}

static const struct xdg_toplevel_listener top_listener = { top_configure, top_close };

static struct wl_buffer *
make_buffer(int w, int h, uint32_t color)
{
	int fd = memfd_create("wl-sandbox-app", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, w * h * 4) < 0) {
		exit(2);
	}
	uint32_t *px = mmap(NULL, w * h * 4, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	for (int i = 0; i < w * h; i++) {
		px[i] = color;
	}
	munmap(px, w * h * 4);
	struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, w * h * 4);
	struct wl_buffer *b = wl_shm_pool_create_buffer(pool, 0, w, h, w * 4, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return b;
}

/* schranka: zdroj (--copy) */

static void
source_target(void *data, struct wl_data_source *s, const char *mime)
{
}

static void
source_send(void *data, struct wl_data_source *s, const char *mime, int32_t fd)
{
	if (write(fd, copy_text, strlen(copy_text)) < 0) {
		say("send-failed");
	}
	close(fd);
}

static void
source_cancelled(void *data, struct wl_data_source *s)
{
	wl_data_source_destroy(s);
}

static const struct wl_data_source_listener source_listener = { source_target, source_send, source_cancelled };

/* schranka: prijemce */

static void
offer_offer(void *data, struct wl_data_offer *o, const char *mime)
{
	if (!strcmp(mime, "text/plain;charset=utf-8") || !strcmp(mime, "text/plain")) {
		offer_text = true;
	}
}

static const struct wl_data_offer_listener offer_listener = { offer_offer };

static void
dd_data_offer(void *data, struct wl_data_device *d, struct wl_data_offer *o)
{
	offer_text = false;
	wl_data_offer_add_listener(o, &offer_listener, NULL);
}

static void
dd_enter(void *data, struct wl_data_device *d, uint32_t serial, struct wl_surface *s, wl_fixed_t x,
		wl_fixed_t y, struct wl_data_offer *o)
{
}

static void
dd_leave(void *data, struct wl_data_device *d)
{
}

static void
dd_motion(void *data, struct wl_data_device *d, uint32_t time, wl_fixed_t x, wl_fixed_t y)
{
}

static void
dd_drop(void *data, struct wl_data_device *d)
{
}

static void
dd_selection(void *data, struct wl_data_device *d, struct wl_data_offer *o)
{
	if (selection_offer) {
		wl_data_offer_destroy(selection_offer);
	}
	selection_offer = o;
	if (!o || !offer_text || copy_text) {
		return;
	}
	say("selection");
	int fds[2];
	if (pipe(fds) < 0) {
		return;
	}
	wl_data_offer_receive(o, "text/plain", fds[1]);
	close(fds[1]);
	wl_display_flush(display);
	char buf[256];
	size_t n = 0;
	struct pollfd p = { fds[0], POLLIN, 0 };
	while (n < sizeof(buf) - 1 && poll(&p, 1, 2000) > 0) {
		ssize_t r = read(fds[0], buf + n, sizeof(buf) - 1 - n);
		if (r <= 0) {
			break;
		}
		n += r;
	}
	buf[n] = '\0';
	close(fds[0]);
	say("clip %s", buf);
}

static const struct wl_data_device_listener dd_listener = {
	dd_data_offer, dd_enter, dd_leave, dd_motion, dd_drop, dd_selection,
};

/* vstup */

static void
kb_keymap(void *data, struct wl_keyboard *k, uint32_t format, int32_t fd, uint32_t size)
{
	close(fd);
}

static void
kb_enter(void *data, struct wl_keyboard *k, uint32_t serial, struct wl_surface *s, struct wl_array *keys)
{
	say("focus-in");
	if (copy_text && !focused_once) {
		struct wl_data_source *src = wl_data_device_manager_create_data_source(ddm);
		wl_data_source_add_listener(src, &source_listener, NULL);
		wl_data_source_offer(src, "text/plain;charset=utf-8");
		wl_data_source_offer(src, "text/plain");
		wl_data_device_set_selection(data_device, src, serial);
		say("copied");
	}
	focused_once = true;
}

static void
kb_leave(void *data, struct wl_keyboard *k, uint32_t serial, struct wl_surface *s)
{
	say("focus-out");
}

static void
kb_key(void *data, struct wl_keyboard *k, uint32_t serial, uint32_t time, uint32_t key, uint32_t state)
{
	if (state == WL_KEYBOARD_KEY_STATE_PRESSED) {
		say("key %u", key);
	}
}

static void
kb_modifiers(void *data, struct wl_keyboard *k, uint32_t serial, uint32_t d, uint32_t l, uint32_t lk,
		uint32_t g)
{
}

static void
kb_repeat(void *data, struct wl_keyboard *k, int32_t rate, int32_t delay)
{
}

static const struct wl_keyboard_listener kb_listener = {
	kb_keymap, kb_enter, kb_leave, kb_key, kb_modifiers, kb_repeat,
};

static void
ptr_enter(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *s, wl_fixed_t x, wl_fixed_t y)
{
}

static void
ptr_leave(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *s)
{
}

static void
ptr_motion(void *data, struct wl_pointer *p, uint32_t time, wl_fixed_t x, wl_fixed_t y)
{
}

static void
ptr_button(void *data, struct wl_pointer *p, uint32_t serial, uint32_t time, uint32_t button, uint32_t state)
{
	if (state == WL_POINTER_BUTTON_STATE_PRESSED) {
		say("button");
	}
}

static void
ptr_axis(void *data, struct wl_pointer *p, uint32_t time, uint32_t axis, wl_fixed_t value)
{
}

static void
ptr_frame(void *data, struct wl_pointer *p)
{
}

static void
ptr_axis_source(void *data, struct wl_pointer *p, uint32_t source)
{
}

static void
ptr_axis_stop(void *data, struct wl_pointer *p, uint32_t time, uint32_t axis)
{
}

static void
ptr_axis_discrete(void *data, struct wl_pointer *p, uint32_t axis, int32_t discrete)
{
}

static const struct wl_pointer_listener ptr_listener = {
	ptr_enter, ptr_leave, ptr_motion, ptr_button, ptr_axis, ptr_frame, ptr_axis_source, ptr_axis_stop,
	ptr_axis_discrete,
};

static void
token_done(void *data, struct xdg_activation_token_v1 *t, const char *name)
{
	snprintf(token, sizeof(token), "%s", name);
}

static const struct xdg_activation_token_v1_listener token_listener = { token_done };

static int64_t
now_ms(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int
window(const char *app, const char *title, int activate_ms, int stay_ms)
{
	connect_display();
	if (!compositor || !shm || !wm_base || !seat || !ddm) {
		say("missing-globals");
		return 2;
	}
	xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
	wl_keyboard_add_listener(wl_seat_get_keyboard(seat), &kb_listener, NULL);
	wl_pointer_add_listener(wl_seat_get_pointer(seat), &ptr_listener, NULL);
	data_device = wl_data_device_manager_get_data_device(ddm, seat);
	wl_data_device_add_listener(data_device, &dd_listener, NULL);

	surface = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
	xdg_surface_add_listener(xs, &surface_listener, NULL);
	struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
	xdg_toplevel_add_listener(top, &top_listener, NULL);
	xdg_toplevel_set_app_id(top, app);
	xdg_toplevel_set_title(top, title);
	if (deco_manager) {
		struct zxdg_toplevel_decoration_v1 *deco =
			zxdg_decoration_manager_v1_get_toplevel_decoration(deco_manager, top);
		zxdg_toplevel_decoration_v1_set_mode(deco, ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
	}
	wl_surface_commit(surface);
	while (!configured && wl_display_dispatch(display) >= 0) {
	}
	wl_surface_attach(surface, make_buffer(320, 200, copy_text ? 0xff3060c0 : 0xffc06030), 0, 0);
	wl_surface_commit(surface);
	say("mapped");

	int64_t start = now_ms(), activate_at = activate_ms >= 0 ? start + activate_ms : -1;
	while (!done && now_ms() - start < stay_ms) {
		wl_display_flush(display);
		struct pollfd p = { wl_display_get_fd(display), POLLIN, 0 };
		if (poll(&p, 1, 50) > 0 && wl_display_dispatch(display) < 0) {
			break;
		}
		wl_display_dispatch_pending(display);
		if (activate_at >= 0 && now_ms() >= activate_at && activation) {
			activate_at = -1;
			struct xdg_activation_token_v1 *t = xdg_activation_v1_get_activation_token(activation);
			xdg_activation_token_v1_add_listener(t, &token_listener, NULL);
			xdg_activation_token_v1_set_surface(t, surface);
			xdg_activation_token_v1_set_app_id(t, app);
			xdg_activation_token_v1_commit(t);
			while (!token[0] && wl_display_dispatch(display) >= 0) {
			}
			xdg_activation_v1_activate(activation, token, surface);
			say("activate");
		}
	}
	return 0;
}

int
main(int argc, char *argv[])
{
	if (argc == 2 && !strcmp(argv[1], "--globals")) {
		print_globals = true;
		connect_display();
		return 0;
	}
	if (argc == 4 && !strcmp(argv[1], "--bind")) {
		wanted = argv[2];
		connect_display();
		struct wl_registry *r = wl_display_get_registry(display);
		/* rozhrani neni potreba znat presne: libwayland posle jmeno a verzi */
		static struct wl_interface iface;
		iface.name = wanted;
		iface.version = wanted_version;
		wl_registry_bind(r, (uint32_t)atoi(argv[3]), &iface, iface.version);
		say(wl_display_roundtrip(display) < 0 ? "refused" : "bound");
		return 0;
	}
	if (argc == 3 && !strcmp(argv[1], "--connect")) {
		return try_connect(argv[2]);
	}
	if (argc >= 4 && !strcmp(argv[1], "--window")) {
		int activate_ms = -1, stay_ms = 20000;
		for (int i = 4; i + 1 < argc; i += 2) {
			if (!strcmp(argv[i], "--copy")) {
				copy_text = argv[i + 1];
			} else if (!strcmp(argv[i], "--activate-ms")) {
				activate_ms = atoi(argv[i + 1]);
			} else if (!strcmp(argv[i], "--stay")) {
				stay_ms = atoi(argv[i + 1]);
			}
		}
		return window(argv[2], argv[3], activate_ms, stay_ms);
	}
	fprintf(stderr, "usage: see the comment at the top of wl-sandbox-app.c\n");
	return 2;
}
