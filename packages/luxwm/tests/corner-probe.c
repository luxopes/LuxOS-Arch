/*
 * Testovaci klient pro zaoblene rohy oken s vlastnim zahlavim (test_luxwm_corners.py).
 *
 *   corner-probe MODE [W H]     okno W x H (vychozi 300x200), bez zahlavi kompozitoru, jednobarevne
 *     opaque      nepruhledny povrch (jako okno GTK s headerbarem)
 *     rounded     klient si sam zaobli vsechny rohy polomerem 12 (GTK 4, libadwaita), za obloukem pruhledno
 *     glass       pruhledny obsah (alfa 50 %, jako Terminal a Hodiny se sklem)
 *     subsurface  korenovy povrch pruhledny, obsah v podpovrchu pres celou geometrii (Firefox)
 * Radek "color RRGGBB" na stdin prekresli obsah (u subsurface jen podpovrch, desync, bez commitu korene),
 * po commitu vypise "drawn".
 */
#define _GNU_SOURCE
#include <math.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"

enum { OPAQUE, ROUNDED, GLASS, SUBSURFACE };

static struct wl_compositor *compositor;
static struct wl_subcompositor *subcompositor;
static struct wl_shm *shm;
static struct xdg_wm_base *wm_base;
static bool configured, closed;

static void
global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	if (!strcmp(interface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 4);
	} else if (!strcmp(interface, wl_subcompositor_interface.name)) {
		subcompositor = wl_registry_bind(registry, name, &wl_subcompositor_interface, 1);
	} else if (!strcmp(interface, wl_shm_interface.name)) {
		shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (!strcmp(interface, xdg_wm_base_interface.name)) {
		wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
	}
}

static void
global_remove(void *data, struct wl_registry *registry, uint32_t name)
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
surface_configure(void *data, struct xdg_surface *s, uint32_t serial)
{
	xdg_surface_ack_configure(s, serial);
	configured = true;
}

static const struct xdg_surface_listener surface_listener = { surface_configure };

static void
toplevel_configure(void *data, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *states)
{
}

static void
toplevel_close(void *data, struct xdg_toplevel *t)
{
	closed = true;
}

static const struct xdg_toplevel_listener toplevel_listener = { toplevel_configure, toplevel_close };

/* rgb 0xRRGGBB, alpha 0..255; radius > 0 = pruhledno za obloukem v rozich */
static struct wl_buffer *
make_buffer(int w, int h, uint32_t rgb, uint32_t alpha, int radius)
{
	int fd = memfd_create("corner-probe", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, w * h * 4) < 0) {
		exit(2);
	}
	uint32_t *px = mmap(NULL, w * h * 4, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	uint32_t pre = alpha << 24 | ((rgb >> 16 & 0xff) * alpha / 255) << 16
		| ((rgb >> 8 & 0xff) * alpha / 255) << 8 | (rgb & 0xff) * alpha / 255;
	for (int y = 0; y < h; y++) {
		for (int x = 0; x < w; x++) {
			double dx = x < radius ? radius - x - 0.5 : x >= w - radius ? x + 0.5 - (w - radius) : 0;
			double dy = y < radius ? radius - y - 0.5 : y >= h - radius ? y + 0.5 - (h - radius) : 0;
			bool out = dx > 0 && dy > 0 && hypot(dx, dy) > radius;
			px[y * w + x] = out ? 0 : pre;
		}
	}
	munmap(px, w * h * 4);
	struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, w * h * 4);
	struct wl_buffer *b = wl_shm_pool_create_buffer(pool, 0, w, h, w * 4, WL_SHM_FORMAT_ARGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return b;
}

static void
buffer_release(void *data, struct wl_buffer *b)
{
	wl_buffer_destroy(b);
}

static const struct wl_buffer_listener buffer_listener = { buffer_release };

static void
draw(struct wl_surface *s, int w, int h, uint32_t rgb, uint32_t alpha, int radius)
{
	struct wl_buffer *b = make_buffer(w, h, rgb, alpha, radius);
	wl_buffer_add_listener(b, &buffer_listener, NULL);
	wl_surface_attach(s, b, 0, 0);
	wl_surface_damage_buffer(s, 0, 0, w, h);
	wl_surface_commit(s);
}

int
main(int argc, char *argv[])
{
	static const char *modes[] = { "opaque", "rounded", "glass", "subsurface" };
	int mode = -1;
	for (int i = 0; argc > 1 && i < 4; i++) {
		if (!strcmp(argv[1], modes[i])) {
			mode = i;
		}
	}
	if (mode < 0) {
		fprintf(stderr, "usage: corner-probe opaque|rounded|glass|subsurface [W H]\n");
		return 2;
	}
	int w = argc > 3 ? atoi(argv[2]) : 300, h = argc > 3 ? atoi(argv[3]) : 200;
	struct wl_display *d = wl_display_connect(NULL);
	if (!d) {
		return 2;
	}
	wl_registry_add_listener(wl_display_get_registry(d), &registry_listener, NULL);
	wl_display_roundtrip(d);
	if (!compositor || !shm || !wm_base || !subcompositor) {
		printf("missing-globals\n");
		return 2;
	}
	xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
	struct wl_surface *root = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, root);
	xdg_surface_add_listener(xs, &surface_listener, NULL);
	struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
	xdg_toplevel_add_listener(top, &toplevel_listener, NULL);
	xdg_toplevel_set_app_id(top, "corner-probe");
	xdg_toplevel_set_title(top, modes[mode]);
	wl_surface_commit(root);
	while (!configured && wl_display_dispatch(d) >= 0) {
	}
	struct wl_surface *content = root;
	uint32_t alpha = mode == GLASS ? 128 : 255;
	int radius = mode == ROUNDED ? 12 : 0;
	if (mode == SUBSURFACE) {
		content = wl_compositor_create_surface(compositor);
		struct wl_subsurface *sub = wl_subcompositor_get_subsurface(subcompositor, content, root);
		wl_subsurface_set_desync(sub);
		draw(root, w, h, 0, 0, 0);
	}
	draw(content, w, h, 0xf6f6fa, alpha, radius);
	wl_display_roundtrip(d);
	printf("mapped\n");
	fflush(stdout);
	char line[256];
	size_t len = 0;
	while (!closed) {
		wl_display_flush(d);
		struct pollfd fds[2] = { { wl_display_get_fd(d), POLLIN, 0 }, { 0, POLLIN, 0 } };
		if (poll(fds, 2, 1000) < 0) {
			break;
		}
		if (fds[0].revents & POLLIN && wl_display_dispatch(d) < 0) {
			break;
		}
		if (fds[1].revents & (POLLIN | POLLHUP)) {
			ssize_t n = read(0, line + len, sizeof(line) - len - 1);
			if (n <= 0) {
				break;
			}
			len += n;
			line[len] = '\0';
			char *nl;
			while ((nl = strchr(line, '\n'))) {
				*nl = '\0';
				unsigned rgb;
				if (sscanf(line, "color %x", &rgb) == 1) {
					draw(content, w, h, rgb, alpha, radius);
					wl_display_roundtrip(d);
					printf("drawn\n");
					fflush(stdout);
				}
				len -= nl + 1 - line;
				memmove(line, nl + 1, len + 1);
			}
		}
	}
	return 0;
}
