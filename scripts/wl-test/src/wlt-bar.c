/* wlt-bar - testovaci lista pres layer-shell: horni (nebo dolni) okraj, exkluzivni zona, jednolita barva.
 * Pouziti: wlt-bar [--height N] [--bottom] [--color RRGGBB] [--layer top|bottom|overlay|background] */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include "wlr-layer-shell-unstable-v1-client-protocol.h"

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct zwlr_layer_shell_v1 *layer_shell;
static struct wl_surface *surface;
static uint32_t color = 0xf4f4f8;
static int running = 1;

static void buffer_release(void *data, struct wl_buffer *buf)
{
	wl_buffer_destroy(buf);
}

static const struct wl_buffer_listener buffer_listener = { buffer_release };

static void draw(int w, int h)
{
	int stride = w * 4, size = stride * h;
	int fd = memfd_create("wlt-bar", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, size) < 0)
		exit(1);
	uint32_t *px = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (px == MAP_FAILED)
		exit(1);
	for (int i = 0; i < w * h; i++)
		px[i] = 0xff000000 | color;
	munmap(px, size);
	struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, size);
	struct wl_buffer *buf = wl_shm_pool_create_buffer(pool, 0, w, h, stride, WL_SHM_FORMAT_XRGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	wl_buffer_add_listener(buf, &buffer_listener, NULL);
	wl_surface_attach(surface, buf, 0, 0);
	wl_surface_damage_buffer(surface, 0, 0, w, h);
	wl_surface_commit(surface);
}

static void ls_configure(void *data, struct zwlr_layer_surface_v1 *ls, uint32_t serial, uint32_t w, uint32_t h)
{
	zwlr_layer_surface_v1_ack_configure(ls, serial);
	draw(w ? w : 1024, h);
}

static void ls_closed(void *data, struct zwlr_layer_surface_v1 *ls)
{
	running = 0;
}

static const struct zwlr_layer_surface_v1_listener ls_listener = { ls_configure, ls_closed };

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
	int height = 30, bottom = 0;
	uint32_t layer = ZWLR_LAYER_SHELL_V1_LAYER_TOP;
	for (int i = 1; i < argc; i++) {
		if (i + 1 < argc && !strcmp(argv[i], "--height"))
			height = atoi(argv[++i]);
		else if (!strcmp(argv[i], "--bottom"))
			bottom = 1;
		else if (i + 1 < argc && !strcmp(argv[i], "--color"))
			color = strtoul(argv[++i], NULL, 16);
		else if (i + 1 < argc && !strcmp(argv[i], "--layer")) {
			i++;
			layer = !strcmp(argv[i], "bottom") ? ZWLR_LAYER_SHELL_V1_LAYER_BOTTOM
				: !strcmp(argv[i], "overlay") ? ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY
				: !strcmp(argv[i], "background") ? ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND
				: ZWLR_LAYER_SHELL_V1_LAYER_TOP;
		} else {
			fprintf(stderr, "usage: wlt-bar [--height N] [--bottom] [--color RRGGBB] [--layer top|bottom|overlay|background]\n");
			return 2;
		}
	}
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
	surface = wl_compositor_create_surface(compositor);
	struct zwlr_layer_surface_v1 *ls = zwlr_layer_shell_v1_get_layer_surface(layer_shell, surface, NULL,
		layer, "wlt-bar");
	zwlr_layer_surface_v1_add_listener(ls, &ls_listener, NULL);
	zwlr_layer_surface_v1_set_anchor(ls, ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT
		| (bottom ? ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM : ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP));
	zwlr_layer_surface_v1_set_size(ls, 0, height);
	/* pozadi (tapeta) nic neodsouva */
	zwlr_layer_surface_v1_set_exclusive_zone(ls, layer == ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND ? 0 : height);
	wl_surface_commit(surface);
	while (running && wl_display_dispatch(display) != -1)
		;
	return 0;
}
