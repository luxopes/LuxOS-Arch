/*
 * Kdo smi na privilegovane globaly (snimani obrazovky, data-control, sprava cizich oken,
 * virtualni vstup, sprava vystupu, zamek). Klient pres soket wp-security-context (sandbox,
 * WP-14) je nedostane nikdy; ostatni jen kdyz jejich program (/proc/PID/exe z povereni soketu)
 * je v allowlistu politiky (luxwm: /usr/share/luxwm/privileged.conf). Kompromisy popisuje
 * docs/developers/luxcomp-api.md.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wlr/types/wlr_security_context_v1.h>
#include "internal.h"

#define MAX_MARKED 32

static struct {
	struct wl_global *global;
	int level;
} marked[MAX_MARKED];
static size_t n_marked;

void
security_mark(struct wl_global *global, int level)
{
	if (global && n_marked < MAX_MARKED) {
		marked[n_marked].global = global;
		marked[n_marked++].level = level;
	}
}

static int
level_of(const struct wl_global *global)
{
	for (size_t i = 0; i < n_marked; i++) {
		if (marked[i].global == global) {
			return marked[i].level;
		}
	}
	return 0;
}

bool
pid_privileged(pid_t pid)
{
	if (pid <= 0) {
		return false;
	}
	char link[64], exe[4096];
	snprintf(link, sizeof(link), "/proc/%d/exe", (int)pid);
	ssize_t n = readlink(link, exe, sizeof(exe) - 1);
	if (n <= 0) {
		return false;
	}
	exe[n] = '\0';
	/* bezici shell po aktualizaci baliku: cesta je stejna, jen soubor uz byl nahrazen */
	char *deleted = strstr(exe, " (deleted)");
	if (deleted && deleted[10] == '\0') {
		*deleted = '\0';
	}
	for (size_t i = 0; i < comp.n_privileged; i++) {
		if (!strcmp(comp.privileged[i], exe)) {
			return true;
		}
	}
	return false;
}

bool
client_privileged(struct wl_client *client)
{
	if (wlr_security_context_manager_v1_lookup_client(comp.security, client)) {
		return false;
	}
	pid_t pid = 0;
	wl_client_get_credentials(client, &pid, NULL, NULL);
	return pid_privileged(pid);
}

static bool
global_filter(const struct wl_client *client, const struct wl_global *global, void *data)
{
	int level = level_of(global);
	if (!level) {
		return true;
	}
	struct wl_client *c = (struct wl_client *)client;
	bool sandboxed = wlr_security_context_manager_v1_lookup_client(comp.security, c) != NULL;
	if (sandboxed) {
		return false;
	}
	if (level == GLOBAL_SANDBOX_DENIED || (level == GLOBAL_VIRTUAL_INPUT && comp.virtual_input_open)) {
		return true;
	}
	return client_privileged(c);
}

void
security_init(void)
{
	comp.security = wlr_security_context_manager_v1_create(comp.display);
	security_mark(comp.security->global, GLOBAL_SANDBOX_DENIED);
	const char *vi = getenv("LUXCOMP_VIRTUAL_INPUT");
	comp.virtual_input_open = vi && *vi && strcmp(vi, "0");
	wl_display_set_global_filter(comp.display, global_filter, NULL);
}

void
luxcomp_privileged_allow(const char *exe_path)
{
	if (!exe_path || !*exe_path) {
		for (size_t i = 0; i < comp.n_privileged; i++) {
			free(comp.privileged[i]);
		}
		free(comp.privileged);
		comp.privileged = NULL;
		comp.n_privileged = 0;
		return;
	}
	char **list = realloc(comp.privileged, (comp.n_privileged + 1) * sizeof(*list));
	if (!list) {
		return;
	}
	comp.privileged = list;
	comp.privileged[comp.n_privileged++] = strdup(exe_path);
}
