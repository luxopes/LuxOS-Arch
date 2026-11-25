/*
 * Okna pro shell: wlr-foreign-toplevel-management (Dock: aktivace, minimalizace, obnoveni,
 * maximalizace, cela obrazovka, zavreni), ext-foreign-toplevel-list a snimek jednoho okna
 * (ext-foreign-toplevel-image-capture-source, vlastni scena okna). Pozadavky z Docku jdou politice jako
 * VIEW_REQUEST s puvodem LUXCOMP_ORIGIN_TASKBAR, rozhoduje ona.
 */
#include <stdlib.h>
#include <string.h>
#include <wlr/render/allocator.h>
#include <wlr/types/wlr_ext_foreign_toplevel_list_v1.h>
#include <wlr/types/wlr_ext_image_capture_source_v1.h>
#include <wlr/types/wlr_foreign_toplevel_management_v1.h>
#include <wlr/types/wlr_layer_shell_v1.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_xdg_shell.h>
#include "internal.h"

static void
ftl_activate(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, ftl_activate);
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_ACTIVATE, LUXCOMP_ORIGIN_TASKBAR, 0);
}

static void
ftl_minimize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, ftl_minimize);
	struct wlr_foreign_toplevel_handle_v1_minimized_event *e = data;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_MINIMIZE, e->minimized,
		LUXCOMP_ORIGIN_TASKBAR);
}

static void
ftl_maximize(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, ftl_maximize);
	struct wlr_foreign_toplevel_handle_v1_maximized_event *e = data;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_MAXIMIZE, e->maximized,
		LUXCOMP_ORIGIN_TASKBAR);
}

static void
ftl_fullscreen(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, ftl_fullscreen);
	struct wlr_foreign_toplevel_handle_v1_fullscreen_event *e = data;
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_FULLSCREEN, e->fullscreen,
		LUXCOMP_ORIGIN_TASKBAR);
}

static void
ftl_close(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, ftl_close);
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_CLOSE, 0, LUXCOMP_ORIGIN_TASKBAR);
}

/* Ikona okna v Docku: cil animace minimalizace */
static void
ftl_rectangle(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, ftl_rectangle);
	struct wlr_foreign_toplevel_handle_v1_set_rectangle_event *e = data;
	struct wlr_layer_surface_v1 *ls = e->surface
		? wlr_layer_surface_v1_try_from_wlr_surface(e->surface) : NULL;
	struct wlr_scene_tree *tree = ls ? ls->data : NULL;
	int lx, ly;
	if (!tree || e->width <= 0 || e->height <= 0 || !wlr_scene_node_coords(&tree->node, &lx, &ly)) {
		v->icon_box = (struct wlr_box){ 0 };
		return;
	}
	v->icon_box = (struct wlr_box){ lx + e->x, ly + e->y, e->width, e->height };
}

void
foreign_map(struct view *v)
{
	const char *title = luxcomp_view_title(v->id), *app_id = luxcomp_view_app_id(v->id);
	struct wlr_ext_foreign_toplevel_handle_v1_state state = {
		.title = title ? title : "", .app_id = app_id ? app_id : "",
	};
	v->ext = wlr_ext_foreign_toplevel_handle_v1_create(comp.ext_list, &state);
	if (v->ext) {
		v->ext->data = v;
	}
	v->ftl = wlr_foreign_toplevel_handle_v1_create(comp.ftl_mgr);
	if (!v->ftl) {
		return;
	}
	v->ftl->data = v;
	v->ftl_activate.notify = ftl_activate;
	wl_signal_add(&v->ftl->events.request_activate, &v->ftl_activate);
	v->ftl_minimize.notify = ftl_minimize;
	wl_signal_add(&v->ftl->events.request_minimize, &v->ftl_minimize);
	v->ftl_maximize.notify = ftl_maximize;
	wl_signal_add(&v->ftl->events.request_maximize, &v->ftl_maximize);
	v->ftl_fullscreen.notify = ftl_fullscreen;
	wl_signal_add(&v->ftl->events.request_fullscreen, &v->ftl_fullscreen);
	v->ftl_close.notify = ftl_close;
	wl_signal_add(&v->ftl->events.request_close, &v->ftl_close);
	v->ftl_rectangle.notify = ftl_rectangle;
	wl_signal_add(&v->ftl->events.set_rectangle, &v->ftl_rectangle);
	struct view *parent = view_by_id(luxcomp_view_get(v->id, LUXCOMP_VIEW_PARENT));
	if (parent && parent->ftl) {
		wlr_foreign_toplevel_handle_v1_set_parent(v->ftl, parent->ftl);
	}
	foreign_update(v);
}

void
foreign_unmap(struct view *v)
{
	if (v->ftl) {
		wl_list_remove(&v->ftl_activate.link);
		wl_list_remove(&v->ftl_minimize.link);
		wl_list_remove(&v->ftl_maximize.link);
		wl_list_remove(&v->ftl_fullscreen.link);
		wl_list_remove(&v->ftl_close.link);
		wl_list_remove(&v->ftl_rectangle.link);
		/* deti ukazuji na rodice; handle rodice by jinak visel */
		struct view *c;
		wl_list_for_each(c, &comp.views_list, link) {
			if (c->ftl && c->ftl->parent == v->ftl) {
				wlr_foreign_toplevel_handle_v1_set_parent(c->ftl, NULL);
			}
		}
		wlr_foreign_toplevel_handle_v1_destroy(v->ftl);
		v->ftl = NULL;
		v->ftl_output = NULL;
	}
	if (v->ext) {
		wlr_ext_foreign_toplevel_handle_v1_destroy(v->ext);
		v->ext = NULL;
	}
	/* zanikne i zdroj snimku (posloucha zanik korene sceny) */
	if (v->capture_scene) {
		wlr_scene_node_destroy(&v->capture_scene->tree.node);
		v->capture_scene = NULL;
		v->capture_tree = NULL;
	}
}

void
foreign_update(struct view *v)
{
	if (!v->ftl) {
		return;
	}
	const char *title = luxcomp_view_title(v->id), *app_id = luxcomp_view_app_id(v->id);
	title = title ? title : "";
	app_id = app_id ? app_id : "";
	/* knihovna posila udalost jen pri zmene */
	wlr_foreign_toplevel_handle_v1_set_title(v->ftl, title);
	wlr_foreign_toplevel_handle_v1_set_app_id(v->ftl, app_id);
	wlr_foreign_toplevel_handle_v1_set_activated(v->ftl, comp.focused == v);
	wlr_foreign_toplevel_handle_v1_set_minimized(v->ftl, !v->visible);
	wlr_foreign_toplevel_handle_v1_set_maximized(v->ftl,
		luxcomp_view_get(v->id, LUXCOMP_VIEW_MAXIMIZED));
	wlr_foreign_toplevel_handle_v1_set_fullscreen(v->ftl,
		luxcomp_view_get(v->id, LUXCOMP_VIEW_FULLSCREEN));
	struct output *o = output_by_id(luxcomp_view_get(v->id, LUXCOMP_VIEW_OUTPUT));
	struct wlr_output *wo = o ? o->wlr_output : NULL;
	if (wo != v->ftl_output) {
		if (v->ftl_output) {
			wlr_foreign_toplevel_handle_v1_output_leave(v->ftl, v->ftl_output);
		}
		if (wo) {
			wlr_foreign_toplevel_handle_v1_output_enter(v->ftl, wo);
		}
		v->ftl_output = wo;
	}
	if (v->ext && (strcmp(v->ext->title ? v->ext->title : "", title)
			|| strcmp(v->ext->app_id ? v->ext->app_id : "", app_id))) {
		struct wlr_ext_foreign_toplevel_handle_v1_state state = {
			.title = title, .app_id = app_id,
		};
		wlr_ext_foreign_toplevel_handle_v1_update_state(v->ext, &state);
	}
}

/* ---- snimek okna ---- */

static void
capture_destroy(struct wl_listener *listener, void *data)
{
	struct view *v = wl_container_of(listener, v, capture_destroy);
	wl_list_remove(&v->capture_destroy.link);
	v->capture = NULL;
}

/* Skryte uzly (podpovrch mimo orez nebo bez bufferu) presune na zacatek geometrie: wlroots je do velikosti
 * snimku pocita i vypnute, a skryty pomocny podpovrch Firefoxu na -198,-198 tak snimek roztahl o cerny pruh
 * vlevo a nahore. Jakmile podpovrch zasahne do orezu, wlroots mu polohu nastavi samo. */
static void
capture_park_hidden(struct wlr_scene_tree *tree, int x, int y, const struct wlr_box *g)
{
	struct wlr_scene_node *n;
	wl_list_for_each(n, &tree->children, link) {
		if (n->type == WLR_SCENE_NODE_TREE) {
			capture_park_hidden(wlr_scene_tree_from_node(n), x + n->x, y + n->y, g);
		} else if (n->type == WLR_SCENE_NODE_BUFFER && !n->enabled) {
			wlr_scene_node_set_position(n, g->x - x, g->y - y);
			wlr_scene_buffer_set_dest_size(wlr_scene_buffer_from_node(n), 1, 1);
		}
	}
}

/* Obsah okna bez stinu vlastniho zahlavi (CSD): orez na geometrii okna, meni se s kazdym commitem */
void
foreign_capture_clip(struct view *v)
{
	if (v->capture_tree && v->toplevel) {
		struct wlr_box *g = &v->toplevel->base->geometry;
		wlr_scene_subsurface_tree_set_clip(&v->capture_tree->node, g);
		capture_park_hidden(v->capture_tree, v->capture_tree->node.x, v->capture_tree->node.y, g);
	}
}

static void
toplevel_capture(struct wl_listener *listener, void *data)
{
	struct wlr_ext_foreign_toplevel_image_capture_source_manager_v1_request *req = data;
	struct view *v = req->toplevel_handle->data;
	/* Zdroj nad uzlem hlavni sceny by wlroots vykreslil jako celou scenu v obdelniku okna, i s okny a panely,
	 * ktere ho prekryvaji (sdileni jednoho okna by ukazalo i cizi obsah). Proto vlastni scena jen s povrchy
	 * okna (podpovrchy, bez zahlavi a stinu), jedna na okno, dokud je namapovane. */
	if (v && !v->capture && v->surface_tree && view_surface(v)) {
		v->capture_scene = wlr_scene_create();
		v->capture_tree = wlr_scene_subsurface_tree_create(&v->capture_scene->tree, view_surface(v));
		if (v->capture_tree) {
			tree_track(&v->capture_tree);
			foreign_capture_clip(v);
			v->capture = wlr_ext_image_capture_source_v1_create_with_scene_node(
				&v->capture_scene->tree.node, comp.loop, comp.allocator, comp.renderer);
		}
		if (!v->capture) {
			wlr_scene_node_destroy(&v->capture_scene->tree.node);
			v->capture_scene = NULL;
			v->capture_tree = NULL;
		}
		if (v->capture) {
			v->capture_destroy.notify = capture_destroy;
			wl_signal_add(&v->capture->events.destroy, &v->capture_destroy);
		}
	}
	/* bez zdroje dostane klient neplatny (inert) objekt, nikdy nevisi */
	wlr_ext_foreign_toplevel_image_capture_source_manager_v1_request_accept(req,
		v ? v->capture : NULL);
}

const char *
luxcomp_view_capture_id(int64_t id)
{
	struct view *v = view_by_id(id);
	return v && v->ext && v->ext->identifier ? v->ext->identifier : "";
}

void
foreign_init(void)
{
	comp.ftl_mgr = wlr_foreign_toplevel_manager_v1_create(comp.display);
	comp.ext_list = wlr_ext_foreign_toplevel_list_v1_create(comp.display, 1);
	struct wlr_ext_foreign_toplevel_image_capture_source_manager_v1 *capture =
		wlr_ext_foreign_toplevel_image_capture_source_manager_v1_create(comp.display, 1);
	comp.toplevel_capture.notify = toplevel_capture;
	wl_signal_add(&capture->events.new_request, &comp.toplevel_capture);
	security_mark(comp.ftl_mgr->global, GLOBAL_PRIVILEGED);
	security_mark(comp.ext_list->global, GLOBAL_PRIVILEGED);
	security_mark(capture->global, GLOBAL_PRIVILEGED);
}
