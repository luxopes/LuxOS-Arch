/* Okna (xdg toplevel), popupy a API pro okna */
#include <stdlib.h>
#include <wlr/config.h>
#include <wlr/types/wlr_layer_shell_v1.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_xdg_decoration_v1.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/util/edges.h>
#if WLR_HAS_XWAYLAND
#include <wlr/xwayland/xwayland.h>
#else
#define wlr_xwayland_surface_configure(...)
#define wlr_xwayland_surface_activate(...)
#define wlr_xwayland_surface_restack(...)
#define wlr_xwayland_surface_set_fullscreen(...)
#define wlr_xwayland_surface_set_maximized(...)
#define wlr_xwayland_surface_set_minimized(...)
#define wlr_xwayland_surface_close(...)
#define XCB_STACK_MODE_ABOVE 0
#endif
#include "internal.h"

struct view *
view_by_id(int64_t id)
{
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (v->id == id) {
			return v;
		}
	}
	return NULL;
}

static struct view *
view_from_toplevel(struct wlr_xdg_toplevel *t)
{
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (t && v->toplevel == t) {
			return v;
		}
	}
	return NULL;
}

struct wlr_surface *
view_surface(struct view *v)
{
	return v->toplevel ? v->toplevel->base->surface : v->xsurface->surface;
}

int
view_width(struct view *v)
{
	return v->toplevel ? v->toplevel->base->geometry.width : v->xsurface->width;
}

int
view_height(struct view *v)
{
	return v->toplevel ? v->toplevel->base->geometry.height : v->xsurface->height;
}

struct view *
view_from_surface(struct wlr_surface *surface)
{
	if (!surface) {
		return NULL;
	}
	surface = wlr_surface_get_root_surface(surface);
	struct wlr_xdg_toplevel *t = wlr_xdg_toplevel_try_from_wlr_surface(surface);
	if (t) {
		return view_from_toplevel(t);
	}
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (v->xsurface && v->xsurface->surface == surface) {
			return v;
		}
	}
	return NULL;
}

/* Strom povrchu (wlr_scene_subsurface_tree) zanikne sam s povrchem a poradi vuci nasim
 * udalostem (dissociate, destroy role) neni dane; ukazatel na nej se pak vynuluje */
struct tree_ref {
	struct wlr_scene_tree **ptr;
	struct wl_listener destroy;
};

static void
tree_ref_destroy(struct wl_listener *listener, void *data)
{
	struct tree_ref *r = wl_container_of(listener, r, destroy);
	*r->ptr = NULL;
	wl_list_remove(&r->destroy.link);
	free(r);
}

void
tree_track(struct wlr_scene_tree **ptr)
{
	struct tree_ref *r = calloc(1, sizeof(*r));
	r->ptr = ptr;
	r->destroy.notify = tree_ref_destroy;
	wl_signal_add(&(*ptr)->node.events.destroy, &r->destroy);
}

bool
view_shown(struct view *v)
{
	return v->mapped && v->visible && v->workspace->shown;
}

static struct wlr_scene_tree *
parent_tree(struct view *v)
{
	switch (v->layer) {
	case LUXCOMP_LAYER_ABOVE: return comp.above;
	case LUXCOMP_LAYER_FULLSCREEN: return comp.fullscreen;
	default: return v->workspace->tree;
	}
}

void
view_update_enabled(struct view *v)
{
	/* mimo vrstvu NORMAL okno neschova strom plochy, tak to hlidame tady */
	bool on = v->mapped && v->visible
		&& (v->layer == LUXCOMP_LAYER_NORMAL || v->workspace->shown);
	wlr_scene_node_set_enabled(&v->tree->node, on);
	idle_update();
}

static void
apply_decoration_mode(struct view *v)
{
	if (v->xdg_deco && v->toplevel->base->initialized) {
		wlr_xdg_toplevel_decoration_v1_set_mode(v->xdg_deco, v->decorated
			? WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE
			: WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_CLIENT_SIDE);
	}
}

static void
view_commit(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, commit);
	struct wlr_xdg_surface *base = v->toplevel->base;
	if (base->initial_commit) {
		/* velikost vybere klient, okno umisti politika pri VIEW_MAP */
		wlr_xdg_toplevel_set_size(v->toplevel, 0, 0);
		wlr_xdg_toplevel_set_wm_capabilities(v->toplevel,
			WLR_XDG_TOPLEVEL_WM_CAPABILITIES_MAXIMIZE
			| WLR_XDG_TOPLEVEL_WM_CAPABILITIES_FULLSCREEN
			| WLR_XDG_TOPLEVEL_WM_CAPABILITIES_MINIMIZE);
		apply_decoration_mode(v);
		return;
	}
	if (v->deco) {
		deco_update(v->deco);
	}
}

void
view_map_common(struct view *v)
{
	v->mapped = true;
	v->visible = true;
	wl_list_remove(&v->link);
	wl_list_insert(&comp.views_list, &v->link);
	wlr_scene_node_raise_to_top(&v->tree->node);
	view_update_enabled(v);
	foreign_map(v);
	emit(LUXCOMP_EV_VIEW_MAP, v->id, view_width(v), view_height(v), 0);
}

static void
view_map(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, map);
	view_map_common(v);
}

void
view_unmap_common(struct view *v)
{
	v->mapped = false;
	foreign_unmap(v);
	view_update_enabled(v);
	if (comp.grab_view == v) {
		comp.grab = GRAB_NONE;
		comp.grab_view = NULL;
	}
	if (comp.focused == v) {
		comp.focused = NULL;
	}
	emit(LUXCOMP_EV_VIEW_UNMAP, v->id, 0, 0, 0);
}

static void
view_unmap(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, unmap);
	view_unmap_common(v);
}

struct view *
view_create(void)
{
	struct view *v = calloc(1, sizeof(*v));
	v->kind = KIND_VIEW;
	v->id = ++comp.next_id;
	v->workspace = comp.default_ws;
	v->tree = wlr_scene_tree_create(v->workspace->tree);
	v->tree->node.data = v;
	wlr_scene_node_set_enabled(&v->tree->node, false);
	wl_list_insert(&comp.views_list, &v->link);
	return v;
}

void
view_destroy_common(struct view *v)
{
	emit(LUXCOMP_EV_VIEW_DESTROY, v->id, 0, 0, 0);
	if (v->mapped) {
		foreign_unmap(v);
	}
	wl_list_remove(&v->link);
	if (v->deco) {
		deco_destroy(v->deco);
	}
	wlr_scene_node_destroy(&v->tree->node);
	free(v);
}

static void
view_destroy(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, destroy);
	wl_list_remove(&v->map.link);
	wl_list_remove(&v->unmap.link);
	wl_list_remove(&v->commit.link);
	wl_list_remove(&v->destroy.link);
	wl_list_remove(&v->request_move.link);
	wl_list_remove(&v->request_resize.link);
	wl_list_remove(&v->request_maximize.link);
	wl_list_remove(&v->request_fullscreen.link);
	wl_list_remove(&v->request_minimize.link);
	wl_list_remove(&v->set_title.link);
	wl_list_remove(&v->set_app_id.link);
	if (v->xdg_deco) {
		wl_list_remove(&v->deco_request_mode.link);
		wl_list_remove(&v->deco_destroy.link);
	}
	view_destroy_common(v);
}

/* Na pozadavky klienta se musi vzdy odpovedet configure, i kdyz je politika ignoruje */
static void
request(struct view *v, int64_t what, int64_t arg)
{
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, what, arg, 0);
	if (v->toplevel->base->initialized) {
		wlr_xdg_surface_schedule_configure(v->toplevel->base);
	}
}

static void
request_move(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_move);
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_MOVE, 0, 0);
}

static void
request_resize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_resize);
	struct wlr_xdg_toplevel_resize_event *event = data;
	/* WLR_EDGE_* ma stejne hodnoty jako LUXCOMP_EDGE_* */
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_RESIZE, event->edges, 0);
}

static void
request_maximize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_maximize);
	request(v, LUXCOMP_REQ_MAXIMIZE, v->toplevel->requested.maximized);
}

static void
request_fullscreen(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_fullscreen);
	request(v, LUXCOMP_REQ_FULLSCREEN, v->toplevel->requested.fullscreen);
}

static void
request_minimize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, request_minimize);
	request(v, LUXCOMP_REQ_MINIMIZE, 1);
}

static void
set_title(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, set_title);
	if (v->deco) {
		deco_update(v->deco);
	}
	foreign_update(v);
	emit(LUXCOMP_EV_VIEW_TITLE, v->id, 0, 0, 0);
}

static void
set_app_id(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, set_app_id);
	foreign_update(v);
	emit(LUXCOMP_EV_VIEW_APP_ID, v->id, 0, 0, 0);
}

static void
new_toplevel(struct wl_listener *listener, void *data)
{
	struct wlr_xdg_toplevel *toplevel = data;
	struct view *v = view_create();
	v->toplevel = toplevel;
	v->surface_tree = wlr_scene_xdg_surface_create(v->tree, toplevel->base);
	toplevel->base->data = v->surface_tree;	/* rodic pro popupy */

	struct wlr_surface *s = toplevel->base->surface;
	v->map.notify = view_map;
	wl_signal_add(&s->events.map, &v->map);
	v->unmap.notify = view_unmap;
	wl_signal_add(&s->events.unmap, &v->unmap);
	v->commit.notify = view_commit;
	wl_signal_add(&s->events.commit, &v->commit);
	v->destroy.notify = view_destroy;
	wl_signal_add(&toplevel->events.destroy, &v->destroy);
	v->request_move.notify = request_move;
	wl_signal_add(&toplevel->events.request_move, &v->request_move);
	v->request_resize.notify = request_resize;
	wl_signal_add(&toplevel->events.request_resize, &v->request_resize);
	v->request_maximize.notify = request_maximize;
	wl_signal_add(&toplevel->events.request_maximize, &v->request_maximize);
	v->request_fullscreen.notify = request_fullscreen;
	wl_signal_add(&toplevel->events.request_fullscreen, &v->request_fullscreen);
	v->request_minimize.notify = request_minimize;
	wl_signal_add(&toplevel->events.request_minimize, &v->request_minimize);
	v->set_title.notify = set_title;
	wl_signal_add(&toplevel->events.set_title, &v->set_title);
	v->set_app_id.notify = set_app_id;
	wl_signal_add(&toplevel->events.set_app_id, &v->set_app_id);

	struct view *parent = view_from_toplevel(toplevel->parent);
	emit(LUXCOMP_EV_VIEW_NEW, v->id, parent ? parent->id : 0, 0, 0);
}

/* ---- popupy ---- */

struct popup {
	struct wlr_xdg_popup *popup;
	struct wl_listener commit, destroy;
};

static void
popup_commit(struct wl_listener *listener, void *data)
{
	struct popup *p = wl_container_of(listener, p, commit);
	if (!p->popup->base->initial_commit) {
		return;
	}
	/* popup nesmi vyjet z vystupu (menu u okraje obrazovky) */
	struct wlr_scene_tree *tree = p->popup->base->data;
	int lx, ly;
	struct wlr_box box = { 0 };
	if (tree && wlr_scene_node_coords(tree->node.parent ? &tree->node.parent->node
			: &tree->node, &lx, &ly)) {
		struct output *o = output_at(lx, ly);
		if (o) {
			wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
			box.x -= lx;
			box.y -= ly;
			wlr_xdg_popup_unconstrain_from_box(p->popup, &box);
		}
	}
	wlr_xdg_surface_schedule_configure(p->popup->base);
}

static void
popup_destroy(struct wl_listener *listener, void *data)
{
	struct popup *p = wl_container_of(listener, p, destroy);
	wl_list_remove(&p->commit.link);
	wl_list_remove(&p->destroy.link);
	free(p);
}

void
popup_attach(struct wlr_xdg_popup *popup, struct wlr_scene_tree *parent_tree)
{
	if (!parent_tree || popup->base->data) {
		return;
	}
	popup->base->data = wlr_scene_xdg_surface_create(parent_tree, popup->base);

	struct popup *p = calloc(1, sizeof(*p));
	p->popup = popup;
	p->commit.notify = popup_commit;
	wl_signal_add(&popup->base->surface->events.commit, &p->commit);
	p->destroy.notify = popup_destroy;
	wl_signal_add(&popup->events.destroy, &p->destroy);
}

/* Popup layer-shell (nabidka listy) prijde bez rodice; rodice mu da az zwlr_layer_surface_v1.get_popup
 * (layer_new_popup v core.c) */
static void
new_popup(struct wl_listener *listener, void *data)
{
	struct wlr_xdg_popup *popup = data;
	struct wlr_scene_tree *parent_tree = NULL;
	struct wlr_xdg_surface *xdg = popup->parent
		? wlr_xdg_surface_try_from_wlr_surface(popup->parent) : NULL;
	if (xdg) {
		parent_tree = xdg->data;
	} else if (popup->parent) {
		struct wlr_layer_surface_v1 *ls =
			wlr_layer_surface_v1_try_from_wlr_surface(popup->parent);
		parent_tree = ls ? ls->data : NULL;
	}
	popup_attach(popup, parent_tree);
}

/* ---- xdg-decoration: kdo kresli zahlavi ---- */

static void
deco_request_mode(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, deco_request_mode);
	bool server = v->xdg_deco->requested_mode
		!= WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_CLIENT_SIDE;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_DECORATION, server, 0);
	apply_decoration_mode(v);
}

static void
deco_destroy_handler(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, deco_destroy);
	wl_list_remove(&v->deco_request_mode.link);
	wl_list_remove(&v->deco_destroy.link);
	v->xdg_deco = NULL;
	luxcomp_view_set_decorated(v->id, 0);
}

static void
new_decoration(struct wl_listener *listener, void *data)
{
	struct wlr_xdg_toplevel_decoration_v1 *d = data;
	struct view *v = view_from_toplevel(d->toplevel);
	if (!v) {
		return;
	}
	v->xdg_deco = d;
	v->deco_request_mode.notify = deco_request_mode;
	wl_signal_add(&d->events.request_mode, &v->deco_request_mode);
	v->deco_destroy.notify = deco_destroy_handler;
	wl_signal_add(&d->events.destroy, &v->deco_destroy);
	/* vychozi: zahlavi LuxOS kresli kompozitor, politika muze zmenit */
	luxcomp_view_set_decorated(v->id, 1);
}

void
views_init(void)
{
	comp.xdg_shell = wlr_xdg_shell_create(comp.display, 6);
	comp.new_toplevel.notify = new_toplevel;
	wl_signal_add(&comp.xdg_shell->events.new_toplevel, &comp.new_toplevel);
	comp.new_popup.notify = new_popup;
	wl_signal_add(&comp.xdg_shell->events.new_popup, &comp.new_popup);
	comp.deco_mgr = wlr_xdg_decoration_manager_v1_create(comp.display);
	comp.new_decoration.notify = new_decoration;
	wl_signal_add(&comp.deco_mgr->events.new_toplevel_decoration, &comp.new_decoration);
}

/* ---- API ---- */

static int64_t
xview_get(struct view *v, int64_t prop)
{
#if WLR_HAS_XWAYLAND
	struct wlr_xwayland_surface *xs = v->xsurface;
	xcb_size_hints_t *h = xs->size_hints;
	switch (prop) {
	case LUXCOMP_VIEW_FULLSCREEN: return xs->fullscreen;
	case LUXCOMP_VIEW_MAXIMIZED: return xs->maximized_horz && xs->maximized_vert;
	case LUXCOMP_VIEW_PARENT: return xs->parent && xs->parent->data
		? ((struct view *)xs->parent->data)->id : 0;
	case LUXCOMP_VIEW_MIN_W: return h ? h->min_width : 0;
	case LUXCOMP_VIEW_MIN_H: return h ? h->min_height : 0;
	case LUXCOMP_VIEW_MAX_W: return h && h->max_width > 0 ? h->max_width : 0;
	case LUXCOMP_VIEW_MAX_H: return h && h->max_height > 0 ? h->max_height : 0;
	case LUXCOMP_VIEW_PID: return xs->pid;
	}
#endif
	return 0;
}

int64_t
luxcomp_view_get(int64_t id, int64_t prop)
{
	struct view *v = view_by_id(id);
	if (!v) {
		return 0;
	}
	int w = view_width(v), h = view_height(v);
	switch (prop) {
	case LUXCOMP_VIEW_X: return v->x;
	case LUXCOMP_VIEW_Y: return v->y;
	case LUXCOMP_VIEW_W: return w;
	case LUXCOMP_VIEW_H: return h;
	case LUXCOMP_VIEW_DECO_TOP:
		return v->deco && !luxcomp_view_get(id, LUXCOMP_VIEW_FULLSCREEN) ? deco_height() : 0;
	case LUXCOMP_VIEW_OUTPUT: {
		struct output *o = output_at(v->x + w / 2, v->y + h / 2);
		return o ? o->id : 0;
	}
	case LUXCOMP_VIEW_WORKSPACE: return v->workspace->id;
	case LUXCOMP_VIEW_MAPPED: return v->mapped;
	case LUXCOMP_VIEW_VISIBLE: return v->visible;
	case LUXCOMP_VIEW_FOCUSED: return comp.focused == v;
	case LUXCOMP_VIEW_LAYER: return v->layer;
	case LUXCOMP_VIEW_X11: return v->xsurface != NULL;
	}
	if (v->xsurface) {
		return xview_get(v, prop);
	}
	struct wlr_xdg_toplevel *t = v->toplevel;
	switch (prop) {
	case LUXCOMP_VIEW_PARENT: {
		struct view *p = view_from_toplevel(t->parent);
		return p ? p->id : 0;
	}
	case LUXCOMP_VIEW_FULLSCREEN: return t->pending.fullscreen;
	case LUXCOMP_VIEW_MAXIMIZED: return t->pending.maximized;
	case LUXCOMP_VIEW_MIN_W: return t->current.min_width;
	case LUXCOMP_VIEW_MIN_H: return t->current.min_height;
	case LUXCOMP_VIEW_MAX_W: return t->current.max_width;
	case LUXCOMP_VIEW_MAX_H: return t->current.max_height;
	case LUXCOMP_VIEW_PID: {
		pid_t pid = 0;
		wl_client_get_credentials(t->base->client->client, &pid, NULL, NULL);
		return pid;
	}
	}
	return 0;
}

/* X11: app_id = WM_CLASS (trida), jako u labwc a xfwm4 */
const char *
luxcomp_view_app_id(int64_t id)
{
	struct view *v = view_by_id(id);
#if WLR_HAS_XWAYLAND
	if (v && v->xsurface) {
		return v->xsurface->class;
	}
#endif
	return v ? v->toplevel->app_id : NULL;
}

const char *
luxcomp_view_title(int64_t id)
{
	struct view *v = view_by_id(id);
#if WLR_HAS_XWAYLAND
	if (v && v->xsurface) {
		return v->xsurface->title;
	}
#endif
	return v ? v->toplevel->title : NULL;
}

int64_t
luxcomp_view_next(int64_t id)
{
	struct wl_list *pos = &comp.views_list;
	if (id) {
		struct view *v = view_by_id(id);
		if (!v) {
			return 0;
		}
		pos = &v->link;
	}
	for (pos = pos->next; pos != &comp.views_list; pos = pos->next) {
		struct view *v = wl_container_of(pos, v, link);
		if (v->mapped) {
			return v->id;
		}
	}
	return 0;
}

void
luxcomp_view_move(int64_t id, int64_t x, int64_t y)
{
	struct view *v = view_by_id(id);
	if (!v) {
		return;
	}
	v->x = x;
	v->y = y;
	wlr_scene_node_set_position(&v->tree->node, x, y);
	if (v->xsurface) {
		/* X klient musi znat svou polohu (menu, souradnice ukazatele) */
		wlr_xwayland_surface_configure(v->xsurface, x, y, view_width(v), view_height(v));
	}
	foreign_update(v);
}

void
luxcomp_view_resize(int64_t id, int64_t w, int64_t h)
{
	struct view *v = view_by_id(id);
	if (v && v->xsurface) {
		wlr_xwayland_surface_configure(v->xsurface, v->x, v->y, w, h);
	} else if (v && v->toplevel->base->initialized) {
		wlr_xdg_toplevel_set_size(v->toplevel, w, h);
	}
}

static void
set_activated(struct view *v, bool on)
{
	if (v->xsurface) {
		wlr_xwayland_surface_activate(v->xsurface, on);
	} else {
		wlr_xdg_toplevel_set_activated(v->toplevel, on);
	}
	if (v->deco) {
		deco_update(v->deco);
	}
	foreign_update(v);
}

void
luxcomp_view_focus(int64_t id)
{
	struct view *v = view_by_id(id);
	if (v && !v->mapped) {
		return;
	}
	struct view *prev = comp.focused;
	comp.focused = v;
	if (prev && prev != v) {
		set_activated(prev, false);
	}
	if (v) {
		set_activated(v, true);
	}
	/* exkluzivni vrstva (zamek, spoustec) si klavesnici drzi */
	if (!comp.layer_focus) {
		seat_focus_surface(v ? view_surface(v) : NULL);
	}
}

void
luxcomp_view_raise(int64_t id)
{
	struct view *v = view_by_id(id);
	if (v) {
		wlr_scene_node_raise_to_top(&v->tree->node);
		wl_list_remove(&v->link);
		wl_list_insert(&comp.views_list, &v->link);
		if (v->xsurface) {
			wlr_xwayland_surface_restack(v->xsurface, NULL, XCB_STACK_MODE_ABOVE);
		}
	}
}

void
luxcomp_view_set_state(int64_t id, int64_t state, int64_t on)
{
	struct view *v = view_by_id(id);
	if (!v || (v->toplevel && !v->toplevel->base->initialized)) {
		return;
	}
	if (v->xsurface) {
		if (state == LUXCOMP_STATE_FULLSCREEN) {
			wlr_xwayland_surface_set_fullscreen(v->xsurface, on);
		} else if (state == LUXCOMP_STATE_MAXIMIZED) {
			wlr_xwayland_surface_set_maximized(v->xsurface, on, on);
		}
	} else if (state == LUXCOMP_STATE_FULLSCREEN) {
		wlr_xdg_toplevel_set_fullscreen(v->toplevel, on);
	} else if (state == LUXCOMP_STATE_MAXIMIZED) {
		wlr_xdg_toplevel_set_maximized(v->toplevel, on);
	} else if (state == LUXCOMP_STATE_TILED) {
		wlr_xdg_toplevel_set_tiled(v->toplevel, on ? WLR_EDGE_TOP | WLR_EDGE_BOTTOM
			| WLR_EDGE_LEFT | WLR_EDGE_RIGHT : WLR_EDGE_NONE);
	}
	if (v->deco) {
		deco_update(v->deco);
	}
	foreign_update(v);
}

void
luxcomp_view_set_layer(int64_t id, int64_t layer)
{
	struct view *v = view_by_id(id);
	if (v && layer >= LUXCOMP_LAYER_NORMAL && layer <= LUXCOMP_LAYER_FULLSCREEN) {
		v->layer = layer;
		wlr_scene_node_reparent(&v->tree->node, parent_tree(v));
		view_update_enabled(v);
	}
}

void
luxcomp_view_set_workspace(int64_t id, int64_t ws_id)
{
	struct view *v = view_by_id(id);
	struct workspace *ws = workspace_by_id(ws_id);
	if (v && ws) {
		v->workspace = ws;
		wlr_scene_node_reparent(&v->tree->node, parent_tree(v));
		view_update_enabled(v);
	}
}

void
luxcomp_view_set_decorated(int64_t id, int64_t on)
{
	struct view *v = view_by_id(id);
	if (!v) {
		return;
	}
	v->decorated = on;
	if (on && !v->deco) {
		v->deco = deco_create(v);
	} else if (!on && v->deco) {
		deco_destroy(v->deco);
		v->deco = NULL;
	}
	if (v->toplevel) {
		apply_decoration_mode(v);
	}
}

void
luxcomp_view_set_visible(int64_t id, int64_t on)
{
	struct view *v = view_by_id(id);
	if (!v) {
		return;
	}
	v->visible = on;
	view_update_enabled(v);
	if (!on && comp.focused == v) {
		luxcomp_view_focus(0);
	}
	if (v->xsurface && v->mapped) {
		wlr_xwayland_surface_set_minimized(v->xsurface, !on);
	}
	foreign_update(v);
}

void
luxcomp_view_close(int64_t id)
{
	struct view *v = view_by_id(id);
	if (v && v->xsurface) {
		wlr_xwayland_surface_close(v->xsurface);
	} else if (v) {
		wlr_xdg_toplevel_send_close(v->toplevel);
	}
}
