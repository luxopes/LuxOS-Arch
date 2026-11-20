/* Necinnost uzivatele (ext-idle-notify-v1): zamceni a ztlumeni obrazovky po case bez vstupu. */
#include <stdlib.h>
#include <string.h>
#include "internal.h"
#include "ext-idle-notify-v1-client-protocol.h"

struct watch {
	struct wl_list link;
	int id;
	struct ext_idle_notification_v1 *wl;
};

static struct wl_list watches = {&watches, &watches};

static void idled(void *data, struct ext_idle_notification_v1 *n)
{
	struct watch *w = data;
	(void)n;
	lwl_emit(LWL_IDLE, w->id, 0, 0);
}

static void resumed(void *data, struct ext_idle_notification_v1 *n)
{
	struct watch *w = data;
	(void)n;
	lwl_emit(LWL_RESUMED, w->id, 0, 0);
}

static const struct ext_idle_notification_v1_listener listener = {
	.idled = idled,
	.resumed = resumed,
};

/* input_only: jen vstup (v2: inhibitory jako prehravani videa se neberou v potaz, ty resi volajici);
 * jinak i inhibitory - tak to chce zamek obrazovky (pri filmu se nezamyka). */
LWL_EXPORT int lwl_idle_watch_full(int timeout_ms, int input_only)
{
	if (!lwl.idle_notifier || !lwl.seat || timeout_ms <= 0)
		return 0;
	struct watch *w = calloc(1, sizeof *w);
	if (!w)
		return 0;
	w->id = lwl_new_id();
	if (input_only && lwl.idle_notifier_version >= EXT_IDLE_NOTIFIER_V1_GET_INPUT_IDLE_NOTIFICATION_SINCE_VERSION)
		w->wl = ext_idle_notifier_v1_get_input_idle_notification(lwl.idle_notifier, (uint32_t)timeout_ms, lwl.seat);
	else
		w->wl = ext_idle_notifier_v1_get_idle_notification(lwl.idle_notifier, (uint32_t)timeout_ms, lwl.seat);
	ext_idle_notification_v1_add_listener(w->wl, &listener, w);
	wl_list_insert(watches.prev, &w->link);
	wl_display_flush(lwl.display);
	return w->id;
}

LWL_EXPORT int lwl_idle_watch(int timeout_ms)
{
	return lwl_idle_watch_full(timeout_ms, 1);
}

static void watch_free(struct watch *w)
{
	ext_idle_notification_v1_destroy(w->wl);
	wl_list_remove(&w->link);
	free(w);
}

LWL_EXPORT void lwl_idle_release(int id)
{
	struct watch *w;
	wl_list_for_each(w, &watches, link) {
		if (w->id == id) {
			watch_free(w);
			return;
		}
	}
}

bool lwl_idle_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	if (strcmp(interface, ext_idle_notifier_v1_interface.name) != 0)
		return false;
	lwl.idle_notifier_version = version < 2 ? version : 2;
	lwl.idle_notifier = wl_registry_bind(registry, name, &ext_idle_notifier_v1_interface, lwl.idle_notifier_version);
	return true;
}

void lwl_idle_reset(void)
{
	struct watch *w, *tmp;
	wl_list_for_each_safe(w, tmp, &watches, link)
		watch_free(w);
	if (lwl.idle_notifier)
		ext_idle_notifier_v1_destroy(lwl.idle_notifier);
}
