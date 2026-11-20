/*
 * XWayland na pozadani: server wlroots se spusti az s prvnim X11 klientem (lazy) a skonci
 * 10 s po poslednim. Spravovana X11 okna jsou obycejna okna (struct view, stejne udalosti
 * VIEW_* pro politiku: umisteni, zamereni, zahlavi). Okna override-redirect (menu, tooltipy)
 * politika nevidi; lezi nad okny na sve X poloze.
 */
#define _GNU_SOURCE
#include <stdlib.h>
#include <wlr/config.h>
#include "internal.h"

#if WLR_HAS_XWAYLAND
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/xwayland/server.h>
#include <wlr/xwayland/xwayland.h>

/* ---- spravovana okna ---- */

static void
x_map(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, map);
	view_map_common(v);
}

static void
x_unmap(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, unmap);
	view_unmap_common(v);
}

static void
x_commit(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, commit);
	if (v->deco) {
		deco_update(v->deco);
	}
}

static void
x_associate(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, x_associate);
	struct wlr_surface *s = v->xsurface->surface;
	v->surface_tree = wlr_scene_subsurface_tree_create(v->tree, s);
	v->map.notify = x_map;
	wl_signal_add(&s->events.map, &v->map);
	v->unmap.notify = x_unmap;
	wl_signal_add(&s->events.unmap, &v->unmap);
	v->commit.notify = x_commit;
	wl_signal_add(&s->events.commit, &v->commit);
}

static void
x_dissociate(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, x_dissociate);
	if (v->mapped) {
		view_unmap_common(v);
	}
	wl_list_remove(&v->map.link);
	wl_list_remove(&v->unmap.link);
	wl_list_remove(&v->commit.link);
	wlr_scene_node_destroy(&v->surface_tree->node);
	v->surface_tree = NULL;
}

/* Velikost si X klient urci sam, polohu az politika pri VIEW_MAP */
static void
x_configure(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, x_configure);
	struct wlr_xwayland_surface_configure_event *e = data;
	if (v->mapped) {
		wlr_xwayland_surface_configure(v->xsurface, v->x, v->y, e->width, e->height);
	} else {
		v->x = e->x;
		v->y = e->y;
		wlr_xwayland_surface_configure(v->xsurface, e->x, e->y, e->width, e->height);
	}
}

static void
x_request_move(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_move);
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_MOVE, 0, 0);
}

static void
x_request_resize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_resize);
	struct wlr_xwayland_resize_event *e = data;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_RESIZE, e->edges, 0);
}

/* xsurface uz drzi pozadovany stav (_NET_WM_STATE) */
static void
x_request_maximize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_maximize);
	struct wlr_xwayland_surface *xs = v->xsurface;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_MAXIMIZE,
		xs->maximized_horz || xs->maximized_vert, 0);
}

static void
x_request_fullscreen(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_fullscreen);
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_FULLSCREEN, v->xsurface->fullscreen, 0);
}

static void
x_request_minimize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_minimize);
	struct wlr_xwayland_minimize_event *e = data;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_MINIMIZE, e->minimize, 0);
}

static void
x_request_activate(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, x_activate);
	if (v->mapped) {
		emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_ACTIVATE, LUXCOMP_ORIGIN_CLIENT, 0);
	}
}

static void
x_set_title(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, set_title);
	if (v->deco) {
		deco_update(v->deco);
	}
	foreign_update(v);
	emit(LUXCOMP_EV_VIEW_TITLE, v->id, 0, 0, 0);
}

static void
x_set_class(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, set_app_id);
	foreign_update(v);
	emit(LUXCOMP_EV_VIEW_APP_ID, v->id, 0, 0, 0);
}

/* _MOTIF_WM_HINTS: okno s vlastnim zahlavim (Chrome, Steam) nechce nase */
static void
x_set_decorations(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, x_decorations);
	bool server = v->xsurface->decorations == WLR_XWAYLAND_SURFACE_DECORATIONS_ALL;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_DECORATION, server, 0);
}

static void
x_destroy(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, destroy);
	if (v->surface_tree) {
		x_dissociate(&v->x_dissociate, NULL);
	}
	struct wl_listener *ls[] = { &v->destroy, &v->x_associate, &v->x_dissociate,
		&v->x_configure, &v->request_move, &v->request_resize, &v->request_maximize,
		&v->request_fullscreen, &v->request_minimize, &v->x_activate, &v->set_title,
		&v->set_app_id, &v->x_decorations };
	for (size_t i = 0; i < sizeof(ls) / sizeof(*ls); i++) {
		wl_list_remove(&ls[i]->link);
	}
	v->xsurface->data = NULL;
	view_destroy_common(v);
}

static void
manage(struct wlr_xwayland_surface *xs)
{
	struct view *v = view_create();
	v->xsurface = xs;
	xs->data = v;
	struct {
		struct wl_signal *signal;
		struct wl_listener *listener;
		wl_notify_func_t fn;
	} ls[] = {
		{ &xs->events.destroy, &v->destroy, x_destroy },
		{ &xs->events.associate, &v->x_associate, x_associate },
		{ &xs->events.dissociate, &v->x_dissociate, x_dissociate },
		{ &xs->events.request_configure, &v->x_configure, x_configure },
		{ &xs->events.request_move, &v->request_move, x_request_move },
		{ &xs->events.request_resize, &v->request_resize, x_request_resize },
		{ &xs->events.request_maximize, &v->request_maximize, x_request_maximize },
		{ &xs->events.request_fullscreen, &v->request_fullscreen, x_request_fullscreen },
		{ &xs->events.request_minimize, &v->request_minimize, x_request_minimize },
		{ &xs->events.request_activate, &v->x_activate, x_request_activate },
		{ &xs->events.set_title, &v->set_title, x_set_title },
		{ &xs->events.set_class, &v->set_app_id, x_set_class },
		{ &xs->events.set_decorations, &v->x_decorations, x_set_decorations },
	};
	for (size_t i = 0; i < sizeof(ls) / sizeof(*ls); i++) {
		ls[i].listener->notify = ls[i].fn;
		wl_signal_add(ls[i].signal, ls[i].listener);
	}
	if (xs->surface) {
		x_associate(&v->x_associate, NULL);
	}
	luxcomp_view_set_decorated(v->id, xs->decorations == WLR_XWAYLAND_SURFACE_DECORATIONS_ALL);
	struct view *parent = xs->parent ? xs->parent->data : NULL;
	emit(LUXCOMP_EV_VIEW_NEW, v->id, parent ? parent->id : 0, 0, 0);
}

/* ---- override-redirect (menu, tooltip, drag ikona) ---- */

struct unmanaged {
	struct wlr_xwayland_surface *xs;
	struct wlr_scene_tree *tree;
	struct wl_listener associate, dissociate, map, unmap, geometry, configure, destroy;
};

static void
um_place(struct unmanaged *u)
{
	if (u->tree) {
		wlr_scene_node_set_position(&u->tree->node, u->xs->x, u->xs->y);
	}
}

static void
um_map(struct wl_listener *listener, void *data)
{
	struct unmanaged *u = wl_container_of(listener, u, map);
	u->tree = wlr_scene_subsurface_tree_create(comp.unmanaged, u->xs->surface);
	um_place(u);
	if (wlr_xwayland_surface_override_redirect_wants_focus(u->xs)) {
		seat_focus_surface(u->xs->surface);
	}
	cursor_rebase();
}

static void
um_unmap(struct wl_listener *listener, void *data)
{
	struct unmanaged *u = wl_container_of(listener, u, unmap);
	if (u->tree) {
		wlr_scene_node_destroy(&u->tree->node);
		u->tree = NULL;
	}
	if (comp.seat->keyboard_state.focused_surface == u->xs->surface) {
		luxcomp_view_focus(comp.focused ? comp.focused->id : 0);
	}
	cursor_rebase();
}

static void
um_associate(struct wl_listener *listener, void *data)
{
	struct unmanaged *u = wl_container_of(listener, u, associate);
	u->map.notify = um_map;
	wl_signal_add(&u->xs->surface->events.map, &u->map);
	u->unmap.notify = um_unmap;
	wl_signal_add(&u->xs->surface->events.unmap, &u->unmap);
}

static void
um_dissociate(struct wl_listener *listener, void *data)
{
	struct unmanaged *u = wl_container_of(listener, u, dissociate);
	if (u->tree) {
		um_unmap(&u->unmap, NULL);
	}
	wl_list_remove(&u->map.link);
	wl_list_remove(&u->unmap.link);
}

static void
um_geometry(struct wl_listener *listener, void *data)
{
	struct unmanaged *u = wl_container_of(listener, u, geometry);
	um_place(u);
}

static void
um_configure(struct wl_listener *listener, void *data)
{
	struct unmanaged *u = wl_container_of(listener, u, configure);
	struct wlr_xwayland_surface_configure_event *e = data;
	wlr_xwayland_surface_configure(u->xs, e->x, e->y, e->width, e->height);
	um_place(u);
}

static void
um_destroy(struct wl_listener *listener, void *data)
{
	struct unmanaged *u = wl_container_of(listener, u, destroy);
	if (u->xs->surface) {
		um_dissociate(&u->dissociate, NULL);
	}
	wl_list_remove(&u->associate.link);
	wl_list_remove(&u->dissociate.link);
	wl_list_remove(&u->geometry.link);
	wl_list_remove(&u->configure.link);
	wl_list_remove(&u->destroy.link);
	free(u);
}

static void
unmanaged(struct wlr_xwayland_surface *xs)
{
	struct unmanaged *u = calloc(1, sizeof(*u));
	u->xs = xs;
	u->associate.notify = um_associate;
	wl_signal_add(&xs->events.associate, &u->associate);
	u->dissociate.notify = um_dissociate;
	wl_signal_add(&xs->events.dissociate, &u->dissociate);
	u->geometry.notify = um_geometry;
	wl_signal_add(&xs->events.set_geometry, &u->geometry);
	u->configure.notify = um_configure;
	wl_signal_add(&xs->events.request_configure, &u->configure);
	u->destroy.notify = um_destroy;
	wl_signal_add(&xs->events.destroy, &u->destroy);
	if (xs->surface) {
		um_associate(&u->associate, NULL);
	}
}

static void
new_surface(struct wl_listener *listener, void *data)
{
	struct wlr_xwayland_surface *xs = data;
	if (xs->override_redirect) {
		unmanaged(xs);
	} else {
		manage(xs);
	}
}

static void
ready(struct wl_listener *listener, void *data)
{
	wlr_xwayland_set_seat(comp.xwayland, comp.seat);
}

int64_t
luxcomp_xwayland_start(void)
{
	if (comp.xwayland) {
		return 0;
	}
	comp.xwayland = wlr_xwayland_create(comp.display, comp.compositor, true);
	if (!comp.xwayland) {
		return -1;
	}
	comp.xwayland_surface.notify = new_surface;
	wl_signal_add(&comp.xwayland->events.new_surface, &comp.xwayland_surface);
	comp.xwayland_ready.notify = ready;
	wl_signal_add(&comp.xwayland->events.ready, &comp.xwayland_ready);
	setenv("DISPLAY", comp.xwayland->display_name, 1);
	return 0;
}

const char *
luxcomp_xwayland_display(void)
{
	return comp.xwayland ? comp.xwayland->display_name : NULL;
}

int64_t
luxcomp_xwayland_pid(void)
{
	return comp.xwayland && comp.xwayland->server ? comp.xwayland->server->pid : 0;
}

void
xwayland_finish(void)
{
	if (comp.xwayland) {
		wl_list_remove(&comp.xwayland_surface.link);
		wl_list_remove(&comp.xwayland_ready.link);
		wlr_xwayland_destroy(comp.xwayland);
		comp.xwayland = NULL;
	}
}

#else

int64_t luxcomp_xwayland_start(void) { return -1; }
const char *luxcomp_xwayland_display(void) { return NULL; }
int64_t luxcomp_xwayland_pid(void) { return 0; }
void xwayland_finish(void) { }

#endif
