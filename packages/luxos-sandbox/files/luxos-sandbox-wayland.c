/*
 * luxos-sandbox-wayland SOKET APP_ID INSTANCE_ID CLOSE_FD
 *
 * Vytvori naslouchajici soket Waylandu pro jednu aplikaci v sandboxu (wp-security-context-v1):
 * kompozitor prijima spojeni na SOKET a jeho klienty oznaci jako sandbox "cz.luxos.sandbox"
 * s danym app_id a instance_id. Takovi klienti nedostanou zadne privilegovane protokoly
 * (snimani obrazovky, schranka mimo zamereni, seznam cizich oken, virtualni vstup, layer-shell).
 *
 * CLOSE_FD je zapisovy konec roury: kompozitor soket zavre, az se cteci konec zavre (luxos-sandbox ho
 * drzi po celou dobu behu aplikace). Program po potvrzeni od kompozitoru skonci.
 * Navratovy kod: 0 hotovo, 3 kompozitor security-context neumi, 2 jina chyba.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <wayland-client.h>
#include "security-context-v1-client-protocol.h"

static struct wp_security_context_manager_v1 *manager;

static void
global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	if (!strcmp(interface, wp_security_context_manager_v1_interface.name)) {
		manager = wl_registry_bind(registry, name, &wp_security_context_manager_v1_interface, 1);
	}
}

static void
global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
}

static const struct wl_registry_listener registry_listener = { global, global_remove };

int
main(int argc, char *argv[])
{
	if (argc != 5) {
		fprintf(stderr, "usage: luxos-sandbox-wayland SOCKET APP_ID INSTANCE_ID CLOSE_FD\n");
		return 2;
	}
	int close_fd = atoi(argv[4]);
	struct stat st;
	if (close_fd < 3 || fstat(close_fd, &st) < 0 || !S_ISFIFO(st.st_mode)) {
		fprintf(stderr, "luxos-sandbox-wayland: CLOSE_FD is not a pipe\n");
		return 2;
	}
	/* bind relativne v adresari soketu: cela cesta muze byt delsi nez sun_path (108 znaku) */
	char *slash = strrchr(argv[1], '/');
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	if (!slash || strlen(slash + 1) >= sizeof(addr.sun_path) || !slash[1]) {
		fprintf(stderr, "luxos-sandbox-wayland: bad socket path\n");
		return 2;
	}
	strcpy(addr.sun_path, slash + 1);
	*slash = '\0';
	if (chdir(*argv[1] ? argv[1] : "/") < 0) {
		perror("luxos-sandbox-wayland: socket directory");
		return 2;
	}

	struct wl_display *d = wl_display_connect(NULL);
	if (!d) {
		fprintf(stderr, "luxos-sandbox-wayland: cannot connect to the Wayland display\n");
		return 2;
	}
	wl_registry_add_listener(wl_display_get_registry(d), &registry_listener, NULL);
	if (wl_display_roundtrip(d) < 0) {
		return 2;
	}
	if (!manager) {
		fprintf(stderr, "luxos-sandbox-wayland: the compositor has no wp-security-context-v1\n");
		return 3;
	}

	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	if (fd < 0 || bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(fd, 16) < 0) {
		perror("luxos-sandbox-wayland: socket");
		return 2;
	}
	struct wp_security_context_v1 *ctx = wp_security_context_manager_v1_create_listener(manager, fd, close_fd);
	wp_security_context_v1_set_sandbox_engine(ctx, "cz.luxos.sandbox");
	wp_security_context_v1_set_app_id(ctx, argv[2]);
	wp_security_context_v1_set_instance_id(ctx, argv[3]);
	wp_security_context_v1_commit(ctx);
	wp_security_context_v1_destroy(ctx);
	/* chyba protokolu (napr. vnoreny sandbox) se projevi az po odpovedi kompozitoru */
	if (wl_display_roundtrip(d) < 0) {
		fprintf(stderr, "luxos-sandbox-wayland: the compositor refused the listener\n");
		unlink(addr.sun_path);
		return 2;
	}
	close(fd);
	wl_display_disconnect(d);
	return 0;
}
