/*
 * Testovaci klient pro material okna (set_window_material, test_luxwm_window_material.py).
 *
 *   material-probe stripes W H        nepruhledne okno s cerno-bilymi svislymi pruhy 4 px (pozadi)
 *   material-probe colors W H         nepruhledne okno s barevnymi ctverci 48 px (pozadi snimku pro navrh)
 *   material-probe glass APP [--sandbox|--late]
 *                       povrch 400x300 s pruhlednym okrajem 20 px kolem geometrie okna (jako stin CSD),
 *                       geometrie 360x260: levych 120 px pruhlednych (panel), zbytek nepruhledny 0x8080a0.
 *                       Radky ze stdin jdou na soket IPC luxwm, odpovedi na stdout jako "reply JSON";
 *                       radek "map" vytvori okno (--late: az tehdy), "disconnect" zavre spojeni IPC.
 *                       --sandbox: okno pres soket wp-security-context (spojeni IPC ne).
 *                       Stisk tlacitka v okne zacne presun (jako zahlavi CSD).
 */
#define _GNU_SOURCE
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <wayland-client.h>
#include "security-context-v1-client-protocol.h"
#include "xdg-shell-client-protocol.h"

#define MARGIN 20
#define SIDEBAR 120

static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct xdg_wm_base *wm_base;
static struct wp_security_context_manager_v1 *manager;
static struct wl_seat *seat;
static struct xdg_toplevel *toplevel;
static bool configured, closed;

static void
global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	if (!strcmp(interface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 4);
	} else if (!strcmp(interface, wl_shm_interface.name)) {
		shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (!strcmp(interface, xdg_wm_base_interface.name)) {
		wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
	} else if (!strcmp(interface, wl_seat_interface.name) && !seat) {
		seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
	} else if (!strcmp(interface, wp_security_context_manager_v1_interface.name)) {
		manager = wl_registry_bind(registry, name, &wp_security_context_manager_v1_interface, 1);
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

static void
pointer_enter(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *s, wl_fixed_t x, wl_fixed_t y)
{
}

static void
pointer_leave(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *s)
{
}

static void
pointer_motion(void *data, struct wl_pointer *p, uint32_t time, wl_fixed_t x, wl_fixed_t y)
{
}

static void
pointer_button(void *data, struct wl_pointer *p, uint32_t serial, uint32_t time, uint32_t button, uint32_t state)
{
	if (state == WL_POINTER_BUTTON_STATE_PRESSED && toplevel) {
		xdg_toplevel_move(toplevel, seat, serial);
	}
}

static void
pointer_axis(void *data, struct wl_pointer *p, uint32_t time, uint32_t axis, wl_fixed_t value)
{
}

static const struct wl_pointer_listener pointer_listener = {
	pointer_enter, pointer_leave, pointer_motion, pointer_button, pointer_axis,
};

static struct wl_display *
connect_to(const char *socket)
{
	struct wl_display *d = wl_display_connect(socket);
	if (!d) {
		fprintf(stderr, "cannot connect to %s\n", socket ? socket : "$WAYLAND_DISPLAY");
		exit(2);
	}
	compositor = NULL;
	shm = NULL;
	wm_base = NULL;
	seat = NULL;
	wl_registry_add_listener(wl_display_get_registry(d), &registry_listener, NULL);
	wl_display_roundtrip(d);
	return d;
}

/* Klient wp-security-context jako flatpak: vlastni soket, pres ktery se pripoji sandbox */
static struct wl_display *
connect_sandboxed(void)
{
	struct wl_display *d = connect_to(NULL);
	if (!manager) {
		printf("no-security-context\n");
		exit(1);
	}
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	snprintf(addr.sun_path, sizeof(addr.sun_path), "%s/material-sandbox-%d", getenv("XDG_RUNTIME_DIR"), (int)getpid());
	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	unlink(addr.sun_path);
	int close_fds[2];
	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(fd, 4) < 0 || pipe(close_fds) < 0) {
		perror("sandbox socket");
		exit(2);
	}
	struct wp_security_context_v1 *ctx = wp_security_context_manager_v1_create_listener(manager, fd, close_fds[1]);
	wp_security_context_v1_set_sandbox_engine(ctx, "org.luxos.test");
	wp_security_context_v1_set_app_id(ctx, "org.luxos.material");
	wp_security_context_v1_commit(ctx);
	wl_display_roundtrip(d);
	close(fd);
	return connect_to(addr.sun_path);
}

static const uint32_t palette[] = { 0xffff5f57, 0xfffebc2e, 0xff28c840, 0xff3d7bff, 0xffaf52de, 0xff5ac8fa,
	0xfff2f2f7, 0xff1d1d2b };

static struct wl_buffer *
make_buffer(int w, int h, int pattern)
{
	int fd = memfd_create("material-probe", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, w * h * 4) < 0) {
		exit(2);
	}
	uint32_t *px = mmap(NULL, w * h * 4, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	for (int y = 0; y < h; y++) {
		for (int x = 0; x < w; x++) {
			uint32_t c;
			if (pattern == 1) {
				c = x / 4 % 2 ? 0xffffffff : 0xff000000;
			} else if (pattern == 2) {
				c = palette[(x / 48 * 3 + y / 48 * 5) % 8];
			} else if (x < MARGIN || y < MARGIN || x >= w - MARGIN || y >= h - MARGIN || x < MARGIN + SIDEBAR) {
				c = 0;
			} else {
				c = 0xff8080a0;
			}
			px[y * w + x] = c;
		}
	}
	munmap(px, w * h * 4);
	struct wl_shm_pool *pool = wl_shm_create_pool(shm, fd, w * h * 4);
	struct wl_buffer *b = wl_shm_pool_create_buffer(pool, 0, w, h, w * 4,
		pattern ? WL_SHM_FORMAT_XRGB8888 : WL_SHM_FORMAT_ARGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	return b;
}

static int
ipc_connect(void)
{
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	const char *display = getenv("WAYLAND_DISPLAY");
	snprintf(addr.sun_path, sizeof(addr.sun_path), "%s/luxwm-%s.sock", getenv("XDG_RUNTIME_DIR"),
		display ? display : "wayland-0");
	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		perror("ipc");
		exit(2);
	}
	return fd;
}

/* pattern: 0 sklo, 1 pruhy, 2 barvy */
static void
create_window(struct wl_display *d, int pattern, const char *app, int w, int h)
{
	bool stripes = pattern != 0;
	xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
	struct wl_surface *surface = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
	xdg_surface_add_listener(xs, &surface_listener, NULL);
	struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
	if (!stripes && seat) {
		toplevel = top;
		wl_pointer_add_listener(wl_seat_get_pointer(seat), &pointer_listener, NULL);
	}
	xdg_toplevel_add_listener(top, &toplevel_listener, NULL);
	xdg_toplevel_set_app_id(top, app);
	xdg_toplevel_set_title(top, stripes ? "stripes" : "glass");
	if (!stripes) {
		xdg_surface_set_window_geometry(xs, MARGIN, MARGIN, w - 2 * MARGIN, h - 2 * MARGIN);
	}
	wl_surface_commit(surface);
	while (!configured && wl_display_dispatch(d) >= 0) {
	}
	wl_surface_attach(surface, make_buffer(w, h, pattern), 0, 0);
	wl_surface_commit(surface);
	wl_display_roundtrip(d);
	printf("mapped\n");
	fflush(stdout);
}

int
main(int argc, char *argv[])
{
	int pattern = argc > 3 && !strcmp(argv[1], "stripes") ? 1 : argc > 3 && !strcmp(argv[1], "colors") ? 2 : 0;
	bool stripes = pattern != 0;
	bool glass = argc > 2 && !strcmp(argv[1], "glass");
	if (!stripes && !glass) {
		fprintf(stderr, "usage: material-probe stripes|colors W H | glass APP [--sandbox|--late]\n");
		return 2;
	}
	bool sandbox = glass && argc > 3 && !strcmp(argv[3], "--sandbox");
	bool late = glass && argc > 3 && !strcmp(argv[3], "--late");
	struct wl_display *d = sandbox ? connect_sandboxed() : connect_to(NULL);
	if (!compositor || !shm || !wm_base) {
		printf("missing-globals\n");
		return 2;
	}
	int ipc = glass ? ipc_connect() : -1;
	if (stripes) {
		create_window(d, pattern, argv[1], atoi(argv[2]), atoi(argv[3]));
	} else if (!late) {
		create_window(d, 0, argv[2], 400, 300);
	}
	char in[4096], out[4096];
	size_t in_len = 0, out_len = 0;
	while (!closed) {
		wl_display_flush(d);
		struct pollfd fds[3] = { { wl_display_get_fd(d), POLLIN, 0 }, { 0, POLLIN, 0 }, { ipc, POLLIN, 0 } };
		if (poll(fds, ipc >= 0 ? 3 : glass ? 2 : 1, 1000) < 0) {
			break;
		}
		if (fds[0].revents & POLLIN && wl_display_dispatch(d) < 0) {
			break;
		}
		if (!glass) {
			continue;
		}
		if (fds[1].revents & (POLLIN | POLLHUP)) {
			ssize_t n = read(0, in + in_len, sizeof(in) - in_len);
			if (n <= 0) {
				break;
			}
			in_len += n;
			char *nl;
			while ((nl = memchr(in, '\n', in_len))) {
				size_t len = nl - in + 1;
				if (len == 4 && !memcmp(in, "map\n", 4)) {
					create_window(d, 0, argv[2], 400, 300);
				} else if (len == 11 && !memcmp(in, "disconnect\n", 11)) {
					close(ipc);
					ipc = -1;
					printf("disconnected\n");
					fflush(stdout);
				} else if (ipc < 0 || write(ipc, in, len) != (ssize_t)len) {
					return 1;
				}
				memmove(in, in + len, in_len - len);
				in_len -= len;
			}
		}
		if (ipc >= 0 && fds[2].revents & (POLLIN | POLLHUP)) {
			ssize_t n = read(ipc, out + out_len, sizeof(out) - out_len - 1);
			if (n <= 0) {
				printf("ipc-closed\n");
				break;
			}
			out_len += n;
			char *nl;
			while ((nl = memchr(out, '\n', out_len))) {
				*nl = '\0';
				printf("reply %s\n", out);
				fflush(stdout);
				size_t len = nl - out + 1;
				memmove(out, out + len, out_len - len);
				out_len -= len;
			}
		}
	}
	return 0;
}
