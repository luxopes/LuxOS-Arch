/*
 * ext-session-lock-v1. Zamek kryje vsechno nepruhlednou plochou v barve LuxOS hned pri
 * zamceni; zamykaci plochy (jedna na vystup) jsou nad ni. Klavesnici a ukazatel dostavaji jen
 * ony (seat_focus_surface, hit_test v input.c). Kdyz zamykac skonci bez odemceni, obrazovka
 * zustane zakryta a zamknuta, dokud ji neodemkne novy zamykac.
 */
#include <stdlib.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_session_lock_v1.h>
#include "internal.h"

struct lock_surface {
	struct wlr_session_lock_surface_v1 *surface;
	struct wlr_scene_tree *tree;
	struct wl_listener map, destroy;
};

static void
set_cover_color(void)
{
	uint32_t c = comp.lock_color;
	float color[4] = { (c >> 16 & 0xff) / 255.0f, (c >> 8 & 0xff) / 255.0f,
		(c & 0xff) / 255.0f, 1.0f };
	wlr_scene_rect_set_color(comp.lock_cover, color);
}

static void
focus_lock_surface(struct wlr_surface *surface)
{
	seat_focus_surface(surface);
	cursor_rebase();
}

static void
lock_surface_map(struct wl_listener *listener, void *data)
{
	struct lock_surface *ls = wl_container_of(listener, ls, map);
	struct wlr_surface *focused = comp.seat->keyboard_state.focused_surface;
	if (!focused || !wlr_session_lock_surface_v1_try_from_wlr_surface(focused)) {
		focus_lock_surface(ls->surface->surface);
	}
}

static void
lock_surface_destroy(struct wl_listener *listener, void *data)
{
	struct lock_surface *ls = wl_container_of(listener, ls, destroy);
	wl_list_remove(&ls->map.link);
	wl_list_remove(&ls->destroy.link);
	wlr_scene_node_destroy(&ls->tree->node);
	if (comp.seat->keyboard_state.focused_surface == ls->surface->surface) {
		wlr_seat_keyboard_notify_clear_focus(comp.seat);
		/* klavesnice na jinou zamykaci plochu, je-li */
		struct wlr_session_lock_surface_v1 *other;
		if (comp.lock) {
			wl_list_for_each(other, &comp.lock->surfaces, link) {
				if (other != ls->surface && other->surface->mapped) {
					focus_lock_surface(other->surface);
					break;
				}
			}
		}
	}
	free(ls);
}

static void
new_lock_surface(struct wl_listener *listener, void *data)
{
	struct wlr_session_lock_surface_v1 *s = data;
	struct lock_surface *ls = calloc(1, sizeof(*ls));
	ls->surface = s;
	ls->tree = wlr_scene_subsurface_tree_create(comp.lock_tree, s->surface);
	struct wlr_box box;
	wlr_output_layout_get_box(comp.layout, s->output, &box);
	wlr_scene_node_set_position(&ls->tree->node, box.x, box.y);
	wlr_session_lock_surface_v1_configure(s, box.width, box.height);
	ls->map.notify = lock_surface_map;
	wl_signal_add(&s->surface->events.map, &ls->map);
	ls->destroy.notify = lock_surface_destroy;
	wl_signal_add(&s->events.destroy, &ls->destroy);
}

static void
detach(void)
{
	wl_list_remove(&comp.lock_surface.link);
	wl_list_remove(&comp.lock_unlock.link);
	wl_list_remove(&comp.lock_destroy.link);
	comp.lock = NULL;
}

static void
lock_unlock(struct wl_listener *listener, void *data)
{
	detach();
	comp.locked = false;
	wlr_scene_node_set_enabled(&comp.lock_cover->node, false);
	wlr_scene_node_set_enabled(&comp.lock_tree->node, false);
	if (comp.layer_focus) {
		seat_focus_surface(comp.layer_focus);
	} else {
		luxcomp_view_focus(comp.focused ? comp.focused->id : 0);
	}
	cursor_rebase();
	emit(LUXCOMP_EV_LOCK, 0, 0, 0, 0);
}

/* Zamykac skoncil (pad, kill) bez unlock: zustava zamceno */
static void
lock_destroy(struct wl_listener *listener, void *data)
{
	detach();
	emit(LUXCOMP_EV_LOCK, 0, 1, 1, 0);
}

static void
new_lock(struct wl_listener *listener, void *data)
{
	struct wlr_session_lock_v1 *lock = data;
	if (comp.lock) {
		/* zamyka uz jiny zivy zamykac */
		wlr_session_lock_v1_destroy(lock);
		return;
	}
	comp.lock = lock;
	comp.lock_surface.notify = new_lock_surface;
	wl_signal_add(&lock->events.new_surface, &comp.lock_surface);
	comp.lock_unlock.notify = lock_unlock;
	wl_signal_add(&lock->events.unlock, &comp.lock_unlock);
	comp.lock_destroy.notify = lock_destroy;
	wl_signal_add(&lock->events.destroy, &comp.lock_destroy);
	bool was = comp.locked;
	comp.locked = true;
	comp.grab = GRAB_NONE;
	comp.grab_view = NULL;
	set_cover_color();
	wlr_scene_node_set_enabled(&comp.lock_tree->node, true);
	wlr_scene_node_set_enabled(&comp.lock_cover->node, true);
	wlr_seat_keyboard_notify_clear_focus(comp.seat);
	cursor_rebase();
	/* locked az kryci plochu ukazal kazdy vystup (lock_frame_done) */
	comp.lock_sent = false;
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		o->lock_shown = false;
	}
	lock_frame_done(NULL);
	if (!was) {
		emit(LUXCOMP_EV_LOCK, 0, 1, 0, 0);
	}
}

/* Po vykresleni snimku vystupu @o (NULL = jen kontrola) */
void
lock_frame_done(struct output *o)
{
	if (!comp.lock || comp.lock_sent) {
		return;
	}
	if (o) {
		o->lock_shown = true;
	}
	wl_list_for_each(o, &comp.outputs, link) {
		if (!o->lock_shown && o->wlr_output->enabled) {
			return;
		}
	}
	comp.lock_sent = true;
	wlr_session_lock_v1_send_locked(comp.lock);
}

void
lock_init(void)
{
	struct wlr_session_lock_manager_v1 *mgr = wlr_session_lock_manager_v1_create(comp.display);
	comp.new_lock.notify = new_lock;
	wl_signal_add(&mgr->events.new_lock, &comp.new_lock);
	security_mark(mgr->global, GLOBAL_PRIVILEGED);
	comp.lock_tree = wlr_scene_tree_create(&comp.scene->tree);
	comp.lock_color = 0x1c1c1e;
	float color[4] = { 0, 0, 0, 1 };
	comp.lock_cover = wlr_scene_rect_create(comp.lock_tree, 32768, 32768, color);
	wlr_scene_node_set_enabled(&comp.lock_tree->node, false);
}

int64_t
luxcomp_locked(void)
{
	return comp.locked;
}
