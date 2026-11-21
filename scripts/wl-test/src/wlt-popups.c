/* wlt-popups - zatez pro material kompozitoru: vyskakovaci plochy layer-shell s materialem "popup" (prusvitne
 * tonovani, kompozitor pod ne kresli rozmazane pozadi) a pripadne ztmaveni cele obrazovky jako Launchpad.
 * Pouziti: wlt-popups [--count N] [--size WxH] [--dim] [--cycles N]
 *   --cycles N: plochy N krat zavrit a znovu otevrit (kazde otevreni ceka na prvni snimek), pak konec;
 *               bez nej plochy zustanou otevrene do ukonceni */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include "wlr-layer-shell-unstable-v1-client-protocol.h"

#define MAX_POPUPS 16

struct plane {
	struct wl_surface *surface;
	struct zwlr_layer_surface_v1 *layer;
	uint32_t argb;		/* predem nasobena alfou */
	int shown;
};

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct zwlr_layer_shell_v1 *layer_shell;

static void buffer_release(void *data, struct wl_buffer *buf)
{
	wl_buffer_destroy(buf);
}

static const struct wl_buffer_listener buffer_listener = { buffer_release };

static void frame_done(void *data, struct wl_callback *cb, uint32_t t)
{
	((struct plane *)data)->shown = 1;
	wl_callback_destroy(cb);
}

static const struct wl_callback_listener frame_listener = { frame_done };

static void draw(struct plane *p, int w, int h)
{
	int stride = w * 4, size = stride * h;
	int fd = memfd_create("wlt-popups", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, size) < 0)
		exit(1);
	uint32_t *px = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (px == MAP_FAILED)
		exit(1);
	for (int i = 0; i < w * h; i++)
		px[i] = p->argb;
	munmap(px, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, size);
	struct wl_buffer *buf = wl_shm_pool_create_buffer(pool, 0, w, h, stride, WL_SHM_FORMAT_ARGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	wl_buffer_add_listener(buf, &buffer_listener, NULL);
	wl_surface_attach(p->surface, buf, 0, 0);
	wl_surface_damage_buffer(p->surface, 0, 0, w, h);
	wl_callback_add_listener(wl_surface_frame(p->surface), &frame_listener, p);
	wl_surface_commit(p->surface);
}

static void ls_configure(void *data, struct zwlr_layer_surface_v1 *ls, uint32_t serial, uint32_t w, uint32_t h)
{
	zwlr_layer_surface_v1_ack_configure(ls, serial);
	draw(data, w, h);
}

static void ls_closed(void *data, struct zwlr_layer_surface_v1 *ls)
{
	exit(0);
}

static const struct zwlr_layer_surface_v1_listener ls_listener = { ls_configure, ls_closed };

static void open_plane(struct plane *p, uint32_t layer, const char *ns, int x, int y, int w, int h)
{
	p->shown = 0;
	p->surface = wl_compositor_create_surface(compositor);
	p->layer = zwlr_layer_shell_v1_get_layer_surface(layer_shell, p->surface, NULL, layer, ns);
	zwlr_layer_surface_v1_add_listener(p->layer, &ls_listener, p);
	if (w) {
		zwlr_layer_surface_v1_set_anchor(p->layer, ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT);
		zwlr_layer_surface_v1_set_margin(p->layer, y, 0, 0, x);
		zwlr_layer_surface_v1_set_size(p->layer, w, h);
	} else {
		zwlr_layer_surface_v1_set_anchor(p->layer, ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT
			| ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT | ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM);
		zwlr_layer_surface_v1_set_exclusive_zone(p->layer, -1);
	}
	wl_surface_commit(p->surface);
}

static void close_plane(struct plane *p)
{
	zwlr_layer_surface_v1_destroy(p->layer);
	wl_surface_destroy(p->surface);
}

static void global(void *data, struct wl_registry *reg, uint32_t name, const char *iface, uint32_t ver)
{
	if (!strcmp(iface, wl_compositor_interface.name))
		compositor = wl_registry_bind(reg, name, &wl_compositor_interface, 4);
	else if (!strcmp(iface, wl_shm_interface.name))
		shm = wl_registry_bind(reg, name, &wl_shm_interface, 1);
	else if (!strcmp(iface, zwlr_layer_shell_v1_interface.name))
		layer_shell = wl_registry_bind(reg, name, &zwlr_layer_shell_v1_interface, 1);
}

static void global_remove(void *data, struct wl_registry *reg, uint32_t name) {}

static const struct wl_registry_listener reg_listener = { global, global_remove };

int main(int argc, char *argv[])
{
	int count = 3, w = 400, h = 500, dim = 0, cycles = 0;
	for (int i = 1; i < argc; i++) {
		if (i + 1 < argc && !strcmp(argv[i], "--count"))
			count = atoi(argv[++i]);
		else if (i + 1 < argc && !strcmp(argv[i], "--size"))
			sscanf(argv[++i], "%dx%d", &w, &h);
		else if (!strcmp(argv[i], "--dim"))
			dim = 1;
		else if (i + 1 < argc && !strcmp(argv[i], "--cycles"))
			cycles = atoi(argv[++i]);
		else {
			fprintf(stderr, "usage: wlt-popups [--count N] [--size WxH] [--dim] [--cycles N]\n");
			return 2;
		}
	}
	if (count < 0 || count > MAX_POPUPS || w < 1 || h < 1)
		return 2;
	struct wl_display *display = wl_display_connect(NULL);
	if (!display) {
		fprintf(stderr, "cannot connect to wayland display\n");
		return 1;
	}
	struct wl_registry *reg = wl_display_get_registry(display);
	wl_registry_add_listener(reg, &reg_listener, NULL);
	wl_display_roundtrip(display);
	if (!compositor || !shm || !layer_shell) {
		fprintf(stderr, "compositor lacks wl_compositor/wl_shm/zwlr_layer_shell_v1\n");
		return 1;
	}
	/* tonovani jako svetly material LuxOS (246,247,252 pri 72 %), ztmaveni Launchpadu cerne pri 25 % */
	struct plane dim_plane = { .argb = 0x40000000 }, popups[MAX_POPUPS];
	if (dim)
		open_plane(&dim_plane, ZWLR_LAYER_SHELL_V1_LAYER_TOP, "wlt-dim@dim", 0, 0, 0, 0);
	for (int cycle = 0; cycle <= cycles; cycle++) {
		for (int i = 0; i < count; i++) {
			popups[i].argb = 0xb8b1b2b5;
			open_plane(&popups[i], ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY, "wlt-popup@popup:16",
				60 + i * (w * 3 / 4), 60 + i * 40, w, h);
		}
		for (int i = 0; i < count; i++)
			while (!popups[i].shown && wl_display_dispatch(display) != -1)
				;
		if (cycle == cycles)
			break;
		for (int i = 0; i < count; i++)
			close_plane(&popups[i]);
		wl_display_roundtrip(display);
		if ((cycle + 1) % 100 == 0) {
			printf("cycles %d\n", cycle + 1);
			fflush(stdout);
		}
	}
	if (cycles) {
		printf("done %d\n", cycles);
		return 0;
	}
	printf("ready\n");
	fflush(stdout);
	while (wl_display_dispatch(display) != -1)
		;
	return 0;
}
