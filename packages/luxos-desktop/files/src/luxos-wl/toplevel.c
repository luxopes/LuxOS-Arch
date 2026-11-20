/* Okna aplikaci: wlr-foreign-toplevel-management (seznam + aktivace, minimalizace, zavreni)
 * a ext-foreign-toplevel-list (jen seznam, ale se stalym identifikatorem pro snimek okna). */
#include <stdlib.h>
#include <string.h>
#include "internal.h"
#include "wlr-foreign-toplevel-management-unstable-v1-client-protocol.h"
#include "ext-foreign-toplevel-list-v1-client-protocol.h"

struct toplevel {
	struct wl_list link;
	int id;
	struct zwlr_foreign_toplevel_handle_v1 *wlr;
	struct ext_foreign_toplevel_handle_v1 *ext;
	char *app_id, *title, *identifier;
	int state, pending_state;
	bool announced, dead;
};

static struct wl_list toplevels = {&toplevels, &toplevels};

static struct toplevel *find(int id)
{
	struct toplevel *t;
	wl_list_for_each(t, &toplevels, link)
		if (t->id == id && !t->dead)
			return t;
	return NULL;
}

static struct toplevel *add(void)
{
	struct toplevel *t = calloc(1, sizeof *t);
	if (!t)
		return NULL;
	t->id = lwl_new_id();
	t->app_id = lwl_strdup("");
	t->title = lwl_strdup("");
	t->identifier = lwl_strdup("");
	wl_list_insert(toplevels.prev, &t->link);
	return t;
}

static void done(struct toplevel *t, int first, int changed)
{
	if (t->dead)
		return;
	lwl_emit(t->announced ? changed : first, t->id, 0, 0);
	t->announced = true;
}

static void closed(struct toplevel *t, int kind)
{
	if (t->dead)
		return;
	t->dead = true;
	if (t->announced)
		lwl_emit(kind, t->id, 0, 0);
}

/* ---- wlr ---- */

static void wlr_title(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, const char *title)
{
	struct toplevel *t = data;
	(void)h;
	lwl_set_string(&t->title, title);
}

static void wlr_app_id(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, const char *app_id)
{
	struct toplevel *t = data;
	(void)h;
	lwl_set_string(&t->app_id, app_id);
}

static void wlr_output_enter(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, struct wl_output *o)
{
	(void)data; (void)h; (void)o;
}

static void wlr_output_leave(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, struct wl_output *o)
{
	(void)data; (void)h; (void)o;
}

static void wlr_state(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, struct wl_array *states)
{
	struct toplevel *t = data;
	uint32_t *s;
	(void)h;
	t->pending_state = 0;
	wl_array_for_each(s, states) {
		switch (*s) {
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_ACTIVATED: t->pending_state |= LWL_STATE_ACTIVATED; break;
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_MAXIMIZED: t->pending_state |= LWL_STATE_MAXIMIZED; break;
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_MINIMIZED: t->pending_state |= LWL_STATE_MINIMIZED; break;
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_FULLSCREEN: t->pending_state |= LWL_STATE_FULLSCREEN; break;
		}
	}
}

static void wlr_done(void *data, struct zwlr_foreign_toplevel_handle_v1 *h)
{
	struct toplevel *t = data;
	(void)h;
	t->state = t->pending_state;
	done(t, LWL_TOPLEVEL_NEW, LWL_TOPLEVEL_CHANGED);
}

static void wlr_closed(void *data, struct zwlr_foreign_toplevel_handle_v1 *h)
{
	(void)h;
	closed(data, LWL_TOPLEVEL_CLOSED);
}

static void wlr_parent(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, struct zwlr_foreign_toplevel_handle_v1 *p)
{
	(void)data; (void)h; (void)p;
}

static const struct zwlr_foreign_toplevel_handle_v1_listener wlr_listener = {
	.title = wlr_title,
	.app_id = wlr_app_id,
	.output_enter = wlr_output_enter,
	.output_leave = wlr_output_leave,
	.state = wlr_state,
	.done = wlr_done,
	.closed = wlr_closed,
	.parent = wlr_parent,
};

static void wlr_toplevel(void *data, struct zwlr_foreign_toplevel_manager_v1 *m, struct zwlr_foreign_toplevel_handle_v1 *h)
{
	(void)data; (void)m;
	struct toplevel *t = add();
	if (!t) {
		zwlr_foreign_toplevel_handle_v1_destroy(h);
		return;
	}
	t->wlr = h;
	zwlr_foreign_toplevel_handle_v1_add_listener(h, &wlr_listener, t);
}

static void wlr_finished(void *data, struct zwlr_foreign_toplevel_manager_v1 *m)
{
	(void)data;
	zwlr_foreign_toplevel_manager_v1_destroy(m);
	lwl.wlr_toplevels = NULL;
}

static const struct zwlr_foreign_toplevel_manager_v1_listener wlr_manager_listener = {
	.toplevel = wlr_toplevel,
	.finished = wlr_finished,
};

/* ---- ext ---- */

static void ext_closed(void *data, struct ext_foreign_toplevel_handle_v1 *h)
{
	(void)h;
	closed(data, LWL_LIST_TOPLEVEL_CLOSED);
}

static void ext_done(void *data, struct ext_foreign_toplevel_handle_v1 *h)
{
	(void)h;
	done(data, LWL_LIST_TOPLEVEL_NEW, LWL_LIST_TOPLEVEL_CHANGED);
}

static void ext_title(void *data, struct ext_foreign_toplevel_handle_v1 *h, const char *title)
{
	struct toplevel *t = data;
	(void)h;
	lwl_set_string(&t->title, title);
}

static void ext_app_id(void *data, struct ext_foreign_toplevel_handle_v1 *h, const char *app_id)
{
	struct toplevel *t = data;
	(void)h;
	lwl_set_string(&t->app_id, app_id);
}

static void ext_identifier(void *data, struct ext_foreign_toplevel_handle_v1 *h, const char *identifier)
{
	struct toplevel *t = data;
	(void)h;
	lwl_set_string(&t->identifier, identifier);
}

static const struct ext_foreign_toplevel_handle_v1_listener ext_listener = {
	.closed = ext_closed,
	.done = ext_done,
	.title = ext_title,
	.app_id = ext_app_id,
	.identifier = ext_identifier,
};

static void ext_toplevel(void *data, struct ext_foreign_toplevel_list_v1 *l, struct ext_foreign_toplevel_handle_v1 *h)
{
	(void)data; (void)l;
	struct toplevel *t = add();
	if (!t) {
		ext_foreign_toplevel_handle_v1_destroy(h);
		return;
	}
	t->ext = h;
	ext_foreign_toplevel_handle_v1_add_listener(h, &ext_listener, t);
}

static void ext_finished(void *data, struct ext_foreign_toplevel_list_v1 *l)
{
	(void)data;
	ext_foreign_toplevel_list_v1_destroy(l);
	lwl.ext_toplevels = NULL;
}

static const struct ext_foreign_toplevel_list_v1_listener ext_list_listener = {
	.toplevel = ext_toplevel,
	.finished = ext_finished,
};

bool lwl_toplevel_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	if (strcmp(interface, zwlr_foreign_toplevel_manager_v1_interface.name) == 0) {
		lwl.wlr_toplevels = wl_registry_bind(registry, name, &zwlr_foreign_toplevel_manager_v1_interface,
			version < 3 ? version : 3);
		zwlr_foreign_toplevel_manager_v1_add_listener(lwl.wlr_toplevels, &wlr_manager_listener, NULL);
		return true;
	}
	if (strcmp(interface, ext_foreign_toplevel_list_v1_interface.name) == 0) {
		lwl.ext_toplevels = wl_registry_bind(registry, name, &ext_foreign_toplevel_list_v1_interface, 1);
		ext_foreign_toplevel_list_v1_add_listener(lwl.ext_toplevels, &ext_list_listener, NULL);
		return true;
	}
	return false;
}

static void destroy(struct toplevel *t)
{
	wl_list_remove(&t->link);
	if (t->wlr)
		zwlr_foreign_toplevel_handle_v1_destroy(t->wlr);
	if (t->ext)
		ext_foreign_toplevel_handle_v1_destroy(t->ext);
	free(t->app_id);
	free(t->title);
	free(t->identifier);
	free(t);
}

void lwl_toplevel_sweep(void)
{
	struct toplevel *t, *tmp;
	wl_list_for_each_safe(t, tmp, &toplevels, link)
		if (t->dead)
			destroy(t);
}

void lwl_toplevel_reset(void)
{
	struct toplevel *t, *tmp;
	wl_list_for_each_safe(t, tmp, &toplevels, link)
		destroy(t);
	if (lwl.wlr_toplevels)
		zwlr_foreign_toplevel_manager_v1_destroy(lwl.wlr_toplevels);
	if (lwl.ext_toplevels)
		ext_foreign_toplevel_list_v1_destroy(lwl.ext_toplevels);
}

/* ---- API ---- */

/* list = 0 okna wlr-foreign-toplevel-management, 1 okna ext-foreign-toplevel-list */
static bool listed(struct toplevel *t, int list)
{
	return t->announced && !t->dead && (list ? t->ext != NULL : t->wlr != NULL);
}

LWL_EXPORT int lwl_toplevel_count(int list)
{
	int n = 0;
	struct toplevel *t;
	wl_list_for_each(t, &toplevels, link)
		n += listed(t, list);
	return n;
}

LWL_EXPORT int lwl_toplevel_at(int list, int index)
{
	struct toplevel *t;
	wl_list_for_each(t, &toplevels, link)
		if (listed(t, list) && index-- == 0)
			return t->id;
	return 0;
}

/* zavrene okno je citelne jeste behem udalosti CLOSED */
static struct toplevel *find_any(int id)
{
	struct toplevel *t;
	wl_list_for_each(t, &toplevels, link)
		if (t->id == id)
			return t;
	return NULL;
}

LWL_EXPORT const char *lwl_toplevel_app_id(int id)
{
	struct toplevel *t = find_any(id);
	return t ? t->app_id : "";
}

LWL_EXPORT const char *lwl_toplevel_title(int id)
{
	struct toplevel *t = find_any(id);
	return t ? t->title : "";
}

LWL_EXPORT const char *lwl_toplevel_identifier(int id)
{
	struct toplevel *t = find_any(id);
	return t ? t->identifier : "";
}

LWL_EXPORT int lwl_toplevel_state(int id)
{
	struct toplevel *t = find_any(id);
	return t ? t->state : 0;
}

static struct zwlr_foreign_toplevel_handle_v1 *managed(int id)
{
	struct toplevel *t = find(id);
	return t ? t->wlr : NULL;
}

LWL_EXPORT int lwl_toplevel_activate(int id)
{
	struct zwlr_foreign_toplevel_handle_v1 *h = managed(id);
	if (!h || !lwl.seat)
		return 0;
	zwlr_foreign_toplevel_handle_v1_activate(h, lwl.seat);
	wl_display_flush(lwl.display);
	return 1;
}

LWL_EXPORT int lwl_toplevel_set_minimized(int id, int on)
{
	struct zwlr_foreign_toplevel_handle_v1 *h = managed(id);
	if (!h)
		return 0;
	if (on)
		zwlr_foreign_toplevel_handle_v1_set_minimized(h);
	else
		zwlr_foreign_toplevel_handle_v1_unset_minimized(h);
	wl_display_flush(lwl.display);
	return 1;
}

LWL_EXPORT int lwl_toplevel_set_maximized(int id, int on)
{
	struct zwlr_foreign_toplevel_handle_v1 *h = managed(id);
	if (!h)
		return 0;
	if (on)
		zwlr_foreign_toplevel_handle_v1_set_maximized(h);
	else
		zwlr_foreign_toplevel_handle_v1_unset_maximized(h);
	wl_display_flush(lwl.display);
	return 1;
}

LWL_EXPORT int lwl_toplevel_close(int id)
{
	struct zwlr_foreign_toplevel_handle_v1 *h = managed(id);
	if (!h)
		return 0;
	zwlr_foreign_toplevel_handle_v1_close(h);
	wl_display_flush(lwl.display);
	return 1;
}

/* pro snimek okna (capture.c) */
struct ext_foreign_toplevel_handle_v1 *lwl_toplevel_ext_handle(int id)
{
	struct toplevel *t = find(id);
	return t ? t->ext : NULL;
}
