/*
 * Testovaci klient pro allowlist privilegovanych protokolu luxwm (test_luxwm_protocols.py).
 *
 *   wl-probe             vypise "global JMENO" za kazdy nabizeny global
 *   wl-probe --sandbox   vytvori soket wp-security-context (jako flatpak/bwrap), pripoji se pres
 *                        nej a vypise globaly, ktere vidi sandboxovany klient ("sandbox JMENO")
 *   wl-probe --bind JMENO CISLO   zkusi global bindnout i bez nabidky (cislo z neomezeneho
 *                        spojeni); "bound" nebo "refused" (chyba protokolu)
 *   wl-probe --window APP MS   okno 200x150; po MS ms se zada o aktivaci tokenem
 *                        z XDG_ACTIVATION_TOKEN (spusteni shellem), jinak vlastnim tokenem bez vstupu
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <time.h>
#include <sys/un.h>
#include <unistd.h>
#include <wayland-client.h>
#include "security-context-v1-client-protocol.h"
#include "xdg-shell-client-protocol.h"
#include "xdg-activation-v1-client-protocol.h"

static struct wp_security_context_manager_v1 *manager;
static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct xdg_wm_base *wm_base;
static struct xdg_activation_v1 *activation;
static const char *prefix = "global";
static const char *wanted;
static uint32_t wanted_name, wanted_version;

static void
global(void *data, struct wl_registry *registry, uint32_t name, const char *interface,
		uint32_t version)
{
	printf("%s %s %u\n", prefix, interface, name);
	if (!strcmp(interface, wp_security_context_manager_v1_interface.name) && !manager) {
		manager = wl_registry_bind(registry, name, &wp_security_context_manager_v1_interface, 1);
	}
	if (!strcmp(interface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 4);
	} else if (!strcmp(interface, wl_shm_interface.name)) {
		shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (!strcmp(interface, xdg_wm_base_interface.name)) {
		wm_base = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
	} else if (!strcmp(interface, xdg_activation_v1_interface.name)) {
		activation = wl_registry_bind(registry, name, &xdg_activation_v1_interface, 1);
	}
	if (wanted && !strcmp(interface, wanted)) {
		wanted_name = name;
		wanted_version = version;
	}
}

static void
global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
}

static const struct wl_registry_listener registry_listener = { global, global_remove };

static struct wl_display *
list(const char *socket)
{
	struct wl_display *d = wl_display_connect(socket);
	if (!d) {
		fprintf(stderr, "cannot connect to %s\n", socket ? socket : "$WAYLAND_DISPLAY");
		exit(2);
	}
	wl_registry_add_listener(wl_display_get_registry(d), &registry_listener, NULL);
	wl_display_roundtrip(d);
	return d;
}

/* ---- okno ---- */

static bool configured;
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
token_done(void *data, struct xdg_activation_token_v1 *t, const char *name)
{
	snprintf(token, sizeof(token), "%s", name);
}

static const struct xdg_activation_token_v1_listener token_listener = { token_done };

static struct wl_buffer *
make_buffer(int w, int h, uint32_t color)
{
	int fd = memfd_create("wl-probe", MFD_CLOEXEC);
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

static int64_t
now_ms(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static void
dispatch_for(struct wl_display *d, int ms)
{
	int64_t end = now_ms() + ms;
	while (now_ms() < end) {
		wl_display_flush(d);
		wl_display_roundtrip(d);
		usleep(20000);
	}
}

static int
window(const char *app, int delay)
{
	struct wl_display *d = list(NULL);
	if (!compositor || !shm || !wm_base || !activation) {
		printf("missing-globals\n");
		return 2;
	}
	xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
	struct wl_surface *surface = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
	xdg_surface_add_listener(xs, &surface_listener, NULL);
	struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
	xdg_toplevel_set_app_id(top, app);
	xdg_toplevel_set_title(top, app);
	wl_surface_commit(surface);
	while (!configured && wl_display_dispatch(d) >= 0) {
	}
	wl_surface_attach(surface, make_buffer(200, 150, 0xffff8000), 0, 0);
	wl_surface_commit(surface);
	printf("mapped\n");
	fflush(stdout);
	dispatch_for(d, delay);
	const char *env = getenv("XDG_ACTIVATION_TOKEN");
	if (env && *env) {
		snprintf(token, sizeof(token), "%s", env);
		printf("token env\n");
	} else {
		struct xdg_activation_token_v1 *t = xdg_activation_v1_get_activation_token(activation);
		xdg_activation_token_v1_add_listener(t, &token_listener, NULL);
		xdg_activation_token_v1_set_surface(t, surface);
		xdg_activation_token_v1_set_app_id(t, app);
		xdg_activation_token_v1_commit(t);
		while (!token[0] && wl_display_dispatch(d) >= 0) {
		}
		printf("token own\n");
	}
	xdg_activation_v1_activate(activation, token, surface);
	printf("activate\n");
	fflush(stdout);
	dispatch_for(d, 5000);
	return 0;
}

int
main(int argc, char *argv[])
{
	if (argc > 3 && !strcmp(argv[1], "--window")) {
		return window(argv[2], atoi(argv[3]));
	}
	bool sandbox = argc > 1 && !strcmp(argv[1], "--sandbox");
	if (argc > 2 && !strcmp(argv[1], "--bind")) {
		/* jmeno globalu zjistime z vypisu; filtr ho skryva, ale klient muze cislo zkusit */
		wanted = argv[2];
		prefix = "seen";
		struct wl_display *d = list(NULL);
		uint32_t name = wanted_name ? wanted_name : (uint32_t)atoi(argc > 3 ? argv[3] : "0");
		struct wl_registry *r = wl_display_get_registry(d);
		/* rozhrani neni potreba znat presne: libwayland posle jmeno rozhrani a verzi */
		static const struct wl_interface fake = { 0 };
		struct wl_interface iface = fake;
		iface.name = wanted;
		iface.version = wanted_version ? wanted_version : 1;
		wl_registry_bind(r, name, &iface, iface.version);
		int ret = wl_display_roundtrip(d);
		printf(ret < 0 ? "refused\n" : "bound\n");
		return 0;
	}
	struct wl_display *d = list(NULL);
	if (!sandbox) {
		return 0;
	}
	if (!manager) {
		printf("no-security-context\n");
		return 1;
	}
	const char *dir = getenv("XDG_RUNTIME_DIR");
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	snprintf(addr.sun_path, sizeof(addr.sun_path), "%s/probe-sandbox-%d", dir, (int)getpid());
	int listen_fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	unlink(addr.sun_path);
	if (bind(listen_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(listen_fd, 4) < 0) {
		perror("socket");
		return 2;
	}
	int close_fds[2];
	if (pipe(close_fds) < 0) {
		return 2;
	}
	struct wp_security_context_v1 *ctx =
		wp_security_context_manager_v1_create_listener(manager, listen_fd, close_fds[1]);
	wp_security_context_v1_set_sandbox_engine(ctx, "org.luxos.test");
	wp_security_context_v1_set_app_id(ctx, "org.luxos.probe");
	wp_security_context_v1_commit(ctx);
	wl_display_roundtrip(d);
	close(listen_fd);
	prefix = "sandbox";
	manager = NULL;
	struct wl_display *inner = list(addr.sun_path);
	wl_display_disconnect(inner);
	unlink(addr.sun_path);
	close(close_fds[0]);
	wl_display_disconnect(d);
	return 0;
}
