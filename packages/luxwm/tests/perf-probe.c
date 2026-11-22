/*
 * Zatez pro mereni vykonu kompozitoru (test_luxwm_perf.py), wl_shm jako Firefox pod pixman.
 *
 *   perf-probe panel NAMESPACE HEIGHT [WIDTH]   pruhledna plocha layer-shell s materialem a exkluzivni zonou: bez WIDTH lista
 *                                               nahore pres celou sirku, s WIDTH Dock dole uprostred
 *   perf-probe scroll SECONDS                   maximalizovane okno, kazdy snimek posunuty obsah (cele poskozeni)
 *   perf-probe type SECONDS                     maximalizovane okno, 15x za sekundu znak 10x18 px (male poskozeni)
 * Okno vypise "mapped", na konci "frames N fps F" (snimky, ktere kompozitor potvrdil frame callbackem).
 */
#define _GNU_SOURCE
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "wlr-layer-shell-unstable-v1-client-protocol.h"
#include "xdg-shell-client-protocol.h"

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct xdg_wm_base *wm_base;
static struct zwlr_layer_shell_v1 *layer_shell;
static int width, height;
static bool configured, closed, frame_due = true;

static void
global(void *data, struct wl_registry *r, uint32_t name, const char *iface, uint32_t version)
{
	if (!strcmp(iface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
	} else if (!strcmp(iface, wl_shm_interface.name)) {
		shm = wl_registry_bind(r, name, &wl_shm_interface, 1);
	} else if (!strcmp(iface, xdg_wm_base_interface.name)) {
		wm_base = wl_registry_bind(r, name, &xdg_wm_base_interface, 1);
	} else if (!strcmp(iface, zwlr_layer_shell_v1_interface.name)) {
		layer_shell = wl_registry_bind(r, name, &zwlr_layer_shell_v1_interface, 1);
	}
}

static void
global_remove(void *data, struct wl_registry *r, uint32_t name)
{
}

static const struct wl_registry_listener registry_listener = { global, global_remove };

static void
ping(void *data, struct xdg_wm_base *b, uint32_t serial)
{
	xdg_wm_base_pong(b, serial);
}

static const struct xdg_wm_base_listener wm_listener = { ping };

static void
xs_configure(void *data, struct xdg_surface *s, uint32_t serial)
{
	xdg_surface_ack_configure(s, serial);
	configured = true;
}

static const struct xdg_surface_listener xs_listener = { xs_configure };

static void
top_configure(void *data, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *states)
{
	if (w > 0 && h > 0) {
		width = w;
		height = h;
	}
}

static void
top_close(void *data, struct xdg_toplevel *t)
{
	closed = true;
}

static const struct xdg_toplevel_listener top_listener = { top_configure, top_close };

static void
layer_configure(void *data, struct zwlr_layer_surface_v1 *l, uint32_t serial, uint32_t w, uint32_t h)
{
	zwlr_layer_surface_v1_ack_configure(l, serial);
	width = w;
	height = h;
	configured = true;
}

static void
layer_closed(void *data, struct zwlr_layer_surface_v1 *l)
{
	closed = true;
}

static const struct zwlr_layer_surface_v1_listener layer_listener = { layer_configure, layer_closed };

/* Dva buffery stridave, jako klient s double bufferingem */
struct buf {
	struct wl_buffer *wl;
	uint32_t *px;
	bool busy;
	int w, h;
};

static void
buf_release(void *data, struct wl_buffer *b)
{
	((struct buf *)data)->busy = false;
}

static const struct wl_buffer_listener buf_listener = { buf_release };

static struct buf *
buf_get(struct buf bufs[2], uint32_t format)
{
	for (int i = 0; i < 2; i++) {
		struct buf *b = &bufs[i];
		if (b->busy) {
			continue;
		}
		if (b->w != width || b->h != height) {
			if (b->wl) {
				wl_buffer_destroy(b->wl);
				munmap(b->px, b->w * b->h * 4);
			}
			int fd = memfd_create("perf-probe", MFD_CLOEXEC);
			if (fd < 0 || ftruncate(fd, width * height * 4) < 0) {
				exit(2);
			}
			b->px = mmap(NULL, width * height * 4, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
			struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, width * height * 4);
			b->wl = wl_shm_pool_create_buffer(pool, 0, width, height, width * 4, format);
			wl_buffer_add_listener(b->wl, &buf_listener, b);
			wl_shm_pool_destroy(pool);
			close(fd);
			b->w = width;
			b->h = height;
		}
		b->busy = true;
		return b;
	}
	return NULL;
}

static void frame_done(void *data, struct wl_callback *cb, uint32_t t);
static const struct wl_callback_listener frame_listener = { frame_done };
static int frames;

static void
frame_done(void *data, struct wl_callback *cb, uint32_t t)
{
	wl_callback_destroy(cb);
	frame_due = true;
	frames++;
}

static double
now(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void
panel(struct wl_display *d, const char *ns, int h, int w)
{
	struct wl_surface *s = wl_compositor_create_surface(compositor);
	struct zwlr_layer_surface_v1 *l = zwlr_layer_shell_v1_get_layer_surface(layer_shell, s, NULL,
		ZWLR_LAYER_SHELL_V1_LAYER_TOP, ns);
	zwlr_layer_surface_v1_add_listener(l, &layer_listener, NULL);
	if (w) {
		zwlr_layer_surface_v1_set_anchor(l, ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM);
		zwlr_layer_surface_v1_set_size(l, w, h);
		zwlr_layer_surface_v1_set_margin(l, 0, 0, 6, 0);
		zwlr_layer_surface_v1_set_exclusive_zone(l, h + 6);	/* luxos-dock bez automatickeho skryvani */
	} else {
		zwlr_layer_surface_v1_set_anchor(l, ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT
			| ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT);
		zwlr_layer_surface_v1_set_size(l, 0, h);
		zwlr_layer_surface_v1_set_exclusive_zone(l, h);
	}
	wl_surface_commit(s);
	while (!configured && wl_display_dispatch(d) >= 0) {
	}
	static struct buf bufs[2];
	struct buf *b = buf_get(bufs, WL_SHM_FORMAT_ARGB8888);
	for (int i = 0; i < width * height; i++) {
		b->px[i] = 0x99939599;	/* tonovani materialu (premultiplikovane), alfa 0,6 */
	}
	wl_surface_attach(s, b->wl, 0, 0);
	wl_surface_damage_buffer(s, 0, 0, width, height);
	wl_surface_commit(s);
	wl_display_roundtrip(d);
	printf("mapped\n");
	fflush(stdout);
	while (!closed && wl_display_dispatch(d) >= 0) {
	}
}

static void
window(struct wl_display *d, bool scroll, double seconds)
{
	xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
	struct wl_surface *s = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, s);
	xdg_surface_add_listener(xs, &xs_listener, NULL);
	struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
	xdg_toplevel_add_listener(top, &top_listener, NULL);
	xdg_toplevel_set_app_id(top, "perf-probe");
	xdg_toplevel_set_title(top, scroll ? "scroll" : "type");
	width = 800;
	height = 600;
	wl_surface_commit(s);
	while (!configured && wl_display_dispatch(d) >= 0) {
	}
	static struct buf bufs[2];
	double start = 0, next_key = 0;
	int step = 0, col = 0, drawn_w = 0, drawn_h = 0;
	bool mapped = false;
	while (!closed) {
		double t = now();
		if (mapped && start == 0) {
			start = t;
			frames = 0;
		}
		if (start && t - start >= seconds) {
			break;
		}
		bool want = scroll ? frame_due : (frame_due && t >= next_key);
		struct buf *b = want || !mapped ? buf_get(bufs, WL_SHM_FORMAT_XRGB8888) : NULL;
		if (b) {
			bool full = !mapped || scroll || drawn_w != width || drawn_h != height;
			if (full) {
				/* vodorovne pruhy 24 px posunute o step: stranka posouvana koleckem */
				for (int y = 0; y < height; y++) {
					uint32_t c = (y + step) / 24 % 2 ? 0xfff6f6fa : 0xffdfe3ea;
					for (int x = 0; x < width; x++) {
						b->px[y * width + x] = x % 97 < 3 ? 0xff3d7bff : c;
					}
				}
				wl_surface_damage_buffer(s, 0, 0, width, height);
				step += 3;
				drawn_w = width;
				drawn_h = height;
			} else {
				/* jen dalsi znak (terminal), do obou bufferu, at druhy nema stary obsah */
				int x0 = 20 + col % 60 * 11, y0 = 40 + col / 60 % 30 * 20;
				for (int i = 0; i < 2; i++) {
					if (!bufs[i].px || bufs[i].w != width) {
						continue;
					}
					for (int y = y0; y < y0 + 18 && y < height; y++) {
						for (int x = x0; x < x0 + 10 && x < width; x++) {
							bufs[i].px[y * width + x] = 0xff1d1d2b;
						}
					}
				}
				wl_surface_damage_buffer(s, x0, y0, 10, 18);
				col++;
				next_key = t + 1.0 / 15;
			}
			wl_surface_attach(s, b->wl, 0, 0);
			wl_callback_add_listener(wl_surface_frame(s), &frame_listener, NULL);
			frame_due = false;
			wl_surface_commit(s);
			if (!mapped) {
				xdg_toplevel_set_maximized(top);
				wl_display_roundtrip(d);
				wl_display_roundtrip(d);
				mapped = true;
				printf("mapped\n");
				fflush(stdout);
			}
		}
		wl_display_flush(d);
		struct pollfd pfd = { wl_display_get_fd(d), POLLIN, 0 };
		int timeout = scroll ? 100 : 10;
		if (poll(&pfd, 1, timeout) > 0 && wl_display_dispatch(d) < 0) {
			break;
		}
		wl_display_dispatch_pending(d);
	}
	double took = now() - start;
	printf("frames %d fps %.1f\n", frames, frames / took);
	fflush(stdout);
}

int
main(int argc, char *argv[])
{
	struct wl_display *d = wl_display_connect(NULL);
	if (!d || argc < 3) {
		fprintf(stderr, "usage: perf-probe panel NS HEIGHT [WIDTH] | scroll SECONDS | type SECONDS\n");
		return 2;
	}
	wl_registry_add_listener(wl_display_get_registry(d), &registry_listener, NULL);
	wl_display_roundtrip(d);
	if (!strcmp(argv[1], "panel") && argc > 3 && layer_shell) {
		panel(d, argv[2], atoi(argv[3]), argc > 4 ? atoi(argv[4]) : 0);
	} else if ((!strcmp(argv[1], "scroll") || !strcmp(argv[1], "type")) && wm_base) {
		window(d, !strcmp(argv[1], "scroll"), atof(argv[2]));
	} else {
		return 2;
	}
	return 0;
}
