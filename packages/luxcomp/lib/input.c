/* Vstup: seat, klavesnice a zkratky, kurzor, presun a zmena velikosti oken */
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wlr/backend.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_input_device.h>
#include <wlr/types/wlr_keyboard.h>
#include <wlr/types/wlr_layer_shell_v1.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_pointer.h>
#include <wlr/types/wlr_data_device.h>
#include <wlr/types/wlr_primary_selection.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_xcursor_manager.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <xkbcommon/xkbcommon.h>
#include "internal.h"

#define MOD_MASK (LUXCOMP_MOD_SHIFT | LUXCOMP_MOD_CTRL | LUXCOMP_MOD_ALT | LUXCOMP_MOD_SUPER)

struct keyboard {
	struct wl_list link;
	struct wlr_keyboard *wlr;
	uint32_t swallowed[8];		/* klavesy zkratek: jejich uvolneni klient nedostane */
	struct wl_listener key, modifiers, destroy;
};

static uint32_t
now_ms(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

void
seat_focus_surface(struct wlr_surface *surface)
{
	if (!surface) {
		wlr_seat_keyboard_notify_clear_focus(comp.seat);
		return;
	}
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(comp.seat);
	if (kb) {
		wlr_seat_keyboard_notify_enter(comp.seat, surface, kb->keycodes,
			kb->num_keycodes, &kb->modifiers);
	} else {
		wlr_seat_keyboard_notify_enter(comp.seat, surface, NULL, 0, NULL);
	}
}

/* ---- klavesnice ---- */

static struct xkb_keymap *
make_keymap(void)
{
	struct xkb_rule_names names = {
		.layout = comp.kb_layout,
		.variant = comp.kb_variant,
		.options = comp.kb_options,
	};
	struct xkb_context *ctx = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	struct xkb_keymap *map = xkb_keymap_new_from_names(ctx, &names,
		XKB_KEYMAP_COMPILE_NO_FLAGS);
	if (!map) {
		/* spatne rozlozeni nesmi nechat system bez klavesnice */
		map = xkb_keymap_new_from_names(ctx, NULL, XKB_KEYMAP_COMPILE_NO_FLAGS);
	}
	xkb_context_unref(ctx);
	return map;
}

static bool
binding_matches(struct keybind *b, struct xkb_state *state, uint32_t keycode,
		uint32_t mods)
{
	if (b->mods != mods) {
		return false;
	}
	if (b->keycode) {
		return b->keycode == keycode;
	}
	const xkb_keysym_t *syms;
	int n = xkb_state_key_get_syms(state, keycode, &syms);
	for (int i = 0; i < n; i++) {
		if (xkb_keysym_to_lower(syms[i]) == b->keysym) {
			return true;
		}
	}
	/* zkratky s latinkou funguji i v ceskem nebo ruskem rozlozeni (prvni rozlozeni, uroven 0) */
	struct xkb_keymap *map = xkb_state_get_keymap(state);
	n = xkb_keymap_key_get_syms_by_level(map, keycode, 0, 0, &syms);
	for (int i = 0; i < n; i++) {
		if (xkb_keysym_to_lower(syms[i]) == b->keysym) {
			return true;
		}
	}
	return false;
}

static bool
swallow(struct keyboard *kb, uint32_t keycode, bool add)
{
	for (size_t i = 0; i < 8; i++) {
		if (add && !kb->swallowed[i]) {
			kb->swallowed[i] = keycode;
			return true;
		}
		if (!add && kb->swallowed[i] == keycode) {
			kb->swallowed[i] = 0;
			return true;
		}
	}
	return false;
}

static void
keyboard_key(struct wl_listener *listener, void *data)
{
	struct keyboard *kb = wl_container_of(listener, kb, key);
	struct wlr_keyboard_key_event *event = data;
	uint32_t keycode = event->keycode + 8;

	if (event->state == WL_KEYBOARD_KEY_STATE_RELEASED) {
		if (swallow(kb, keycode, false)) {
			return;
		}
	} else {
		uint32_t mods = wlr_keyboard_get_modifiers(kb->wlr) & MOD_MASK;
		struct keybind *b;
		wl_list_for_each(b, &comp.keybinds, link) {
			if (binding_matches(b, kb->wlr->xkb_state, keycode, mods)) {
				swallow(kb, keycode, true);
				comp.binding_mods_held = mods != 0;
				emit(LUXCOMP_EV_KEYBIND, b->id, 0, 0, 0);
				return;
			}
		}
	}
	wlr_seat_set_keyboard(comp.seat, kb->wlr);
	wlr_seat_keyboard_notify_key(comp.seat, event->time_msec, event->keycode,
		event->state);
}

static void
keyboard_modifiers(struct wl_listener *listener, void *data)
{
	struct keyboard *kb = wl_container_of(listener, kb, modifiers);
	wlr_seat_set_keyboard(comp.seat, kb->wlr);
	wlr_seat_keyboard_notify_modifiers(comp.seat, &kb->wlr->modifiers);
	if (comp.binding_mods_held && !(wlr_keyboard_get_modifiers(kb->wlr) & MOD_MASK)) {
		comp.binding_mods_held = false;
		emit(LUXCOMP_EV_MODS_RELEASED, 0, 0, 0, 0);
	}
}

static void
keyboard_destroy(struct wl_listener *listener, void *data)
{
	struct keyboard *kb = wl_container_of(listener, kb, destroy);
	wl_list_remove(&kb->key.link);
	wl_list_remove(&kb->modifiers.link);
	wl_list_remove(&kb->destroy.link);
	wl_list_remove(&kb->link);
	free(kb);
}

static void
new_keyboard(struct wlr_input_device *device)
{
	struct keyboard *kb = calloc(1, sizeof(*kb));
	kb->wlr = wlr_keyboard_from_input_device(device);
	struct xkb_keymap *map = make_keymap();
	wlr_keyboard_set_keymap(kb->wlr, map);
	xkb_keymap_unref(map);
	wlr_keyboard_set_repeat_info(kb->wlr, comp.repeat_rate, comp.repeat_delay);
	kb->key.notify = keyboard_key;
	wl_signal_add(&kb->wlr->events.key, &kb->key);
	kb->modifiers.notify = keyboard_modifiers;
	wl_signal_add(&kb->wlr->events.modifiers, &kb->modifiers);
	kb->destroy.notify = keyboard_destroy;
	wl_signal_add(&device->events.destroy, &kb->destroy);
	wl_list_insert(&comp.keyboards, &kb->link);
	wlr_seat_set_keyboard(comp.seat, kb->wlr);
}

static void
new_input(struct wl_listener *listener, void *data)
{
	struct wlr_input_device *device = data;
	if (device->type == WLR_INPUT_DEVICE_KEYBOARD) {
		new_keyboard(device);
	} else if (device->type == WLR_INPUT_DEVICE_POINTER) {
		wlr_cursor_attach_input_device(comp.cursor, device);
	}
	uint32_t caps = WL_SEAT_CAPABILITY_POINTER;
	if (!wl_list_empty(&comp.keyboards)) {
		caps |= WL_SEAT_CAPABILITY_KEYBOARD;
	}
	wlr_seat_set_capabilities(comp.seat, caps);
}

/* ---- kurzor ---- */

/* Co je pod kurzorem: okno nebo vrstva, povrch a cast okna */
static int
hit_test(double x, double y, struct view **view_out, struct layer **layer_out,
		struct wlr_surface **surface, double *sx, double *sy)
{
	*view_out = NULL;
	*layer_out = NULL;
	*surface = NULL;
	struct wlr_scene_node *node = wlr_scene_node_at(&comp.scene->tree.node, x, y, sx, sy);
	if (!node) {
		return LUXCOMP_PART_NONE;
	}
	if (node->type == WLR_SCENE_NODE_BUFFER) {
		struct wlr_scene_surface *ss =
			wlr_scene_surface_try_from_buffer(wlr_scene_buffer_from_node(node));
		if (ss) {
			*surface = ss->surface;
		}
	}
	struct wlr_scene_node *n = node;
	while (n && !n->data) {
		n = n->parent ? &n->parent->node : NULL;
	}
	if (!n) {
		return LUXCOMP_PART_NONE;
	}
	if (*(int *)n->data == KIND_LAYER) {
		*layer_out = n->data;
		return LUXCOMP_PART_LAYER;
	}
	struct view *v = n->data;
	*view_out = v;
	if (v->deco && deco_owns_node(v->deco, node)) {
		return deco_part_at(v->deco, x - v->x, y - v->y);
	}
	return LUXCOMP_PART_CLIENT;
}

static void
process_grab(void)
{
	struct view *v = comp.grab_view;
	double cx = comp.cursor->x, cy = comp.cursor->y;
	if (comp.grab == GRAB_MOVE) {
		luxcomp_view_move(v->id, cx - comp.grab_x, cy - comp.grab_y);
		return;
	}
	struct wlr_box b = comp.grab_box;
	int left = b.x, right = b.x + b.width, top = b.y, bottom = b.y + b.height;
	int min_w = v->toplevel->current.min_width > 0 ? v->toplevel->current.min_width : 1;
	int min_h = v->toplevel->current.min_height > 0 ? v->toplevel->current.min_height : 1;
	double dx = cx - comp.grab_x, dy = cy - comp.grab_y;
	if (comp.grab_edges & LUXCOMP_EDGE_TOP) {
		top = b.y + dy;
		if (bottom - top < min_h) top = bottom - min_h;
	} else if (comp.grab_edges & LUXCOMP_EDGE_BOTTOM) {
		bottom = b.y + b.height + dy;
		if (bottom - top < min_h) bottom = top + min_h;
	}
	if (comp.grab_edges & LUXCOMP_EDGE_LEFT) {
		left = b.x + dx;
		if (right - left < min_w) left = right - min_w;
	} else if (comp.grab_edges & LUXCOMP_EDGE_RIGHT) {
		right = b.x + b.width + dx;
		if (right - left < min_w) right = left + min_w;
	}
	luxcomp_view_move(v->id, left, top);
	wlr_xdg_toplevel_set_size(v->toplevel, right - left, bottom - top);
}

static void
process_motion(uint32_t time)
{
	if (comp.grab != GRAB_NONE) {
		process_grab();
		return;
	}
	struct view *v;
	struct layer *l;
	struct wlr_surface *surface;
	double sx, sy;
	hit_test(comp.cursor->x, comp.cursor->y, &v, &l, &surface, &sx, &sy);
	if (surface) {
		wlr_seat_pointer_notify_enter(comp.seat, surface, sx, sy);
		wlr_seat_pointer_notify_motion(comp.seat, time, sx, sy);
	} else {
		wlr_cursor_set_xcursor(comp.cursor, comp.cursor_mgr, "default");
		wlr_seat_pointer_clear_focus(comp.seat);
	}
}

void
cursor_rebase(void)
{
	process_motion(now_ms());
}

static void
cursor_motion(struct wl_listener *listener, void *data)
{
	struct wlr_pointer_motion_event *e = data;
	wlr_cursor_move(comp.cursor, &e->pointer->base, e->delta_x, e->delta_y);
	process_motion(e->time_msec);
}

static void
cursor_motion_abs(struct wl_listener *listener, void *data)
{
	struct wlr_pointer_motion_absolute_event *e = data;
	wlr_cursor_warp_absolute(comp.cursor, &e->pointer->base, e->x, e->y);
	process_motion(e->time_msec);
}

static void
cursor_button(struct wl_listener *listener, void *data)
{
	struct wlr_pointer_button_event *e = data;
	bool pressed = e->state == WL_POINTER_BUTTON_STATE_PRESSED;
	struct view *v;
	struct layer *l;
	struct wlr_surface *surface;
	double sx, sy;
	int part = hit_test(comp.cursor->x, comp.cursor->y, &v, &l, &surface, &sx, &sy);

	if (!pressed && comp.grab != GRAB_NONE) {
		comp.grab = GRAB_NONE;
		comp.grab_view = NULL;
		wlr_seat_pointer_notify_button(comp.seat, e->time_msec, e->button, e->state);
		cursor_rebase();
		emit(LUXCOMP_EV_BUTTON, v ? v->id : 0, e->button, 0, part);
		return;
	}
	if (pressed && l && l->surface->current.keyboard_interactive
			== ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_ON_DEMAND) {
		comp.layer_focus = l->surface->surface;
		seat_focus_surface(comp.layer_focus);
	} else if (pressed && v && comp.layer_focus) {
		/* klik do okna vraci klavesnici z vrstvy na demand oknu */
		struct wlr_layer_surface_v1 *ls =
			wlr_layer_surface_v1_try_from_wlr_surface(comp.layer_focus);
		if (!ls || ls->current.keyboard_interactive
				!= ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE) {
			comp.layer_focus = NULL;
		}
	}
	if (surface) {
		wlr_seat_pointer_notify_button(comp.seat, e->time_msec, e->button, e->state);
	}
	emit(LUXCOMP_EV_BUTTON, v ? v->id : 0, e->button, pressed, part);
}

static void
cursor_axis(struct wl_listener *listener, void *data)
{
	struct wlr_pointer_axis_event *e = data;
	wlr_seat_pointer_notify_axis(comp.seat, e->time_msec, e->orientation, e->delta,
		e->delta_discrete, e->source, e->relative_direction);
}

static void
cursor_frame(struct wl_listener *listener, void *data)
{
	wlr_seat_pointer_notify_frame(comp.seat);
}

static void
request_cursor(struct wl_listener *listener, void *data)
{
	struct wlr_seat_pointer_request_set_cursor_event *e = data;
	if (comp.seat->pointer_state.focused_client == e->seat_client) {
		wlr_cursor_set_surface(comp.cursor, e->surface, e->hotspot_x, e->hotspot_y);
	}
}

static void
request_selection(struct wl_listener *listener, void *data)
{
	struct wlr_seat_request_set_selection_event *e = data;
	wlr_seat_set_selection(comp.seat, e->source, e->serial);
}

static void
request_primary(struct wl_listener *listener, void *data)
{
	struct wlr_seat_request_set_primary_selection_event *e = data;
	wlr_seat_set_primary_selection(comp.seat, e->source, e->serial);
}

void
input_init(void)
{
	comp.seat = wlr_seat_create(comp.display, "seat0");
	comp.cursor = wlr_cursor_create();
	wlr_cursor_attach_output_layout(comp.cursor, comp.layout);
	const char *size = getenv("XCURSOR_SIZE");
	comp.cursor_mgr = wlr_xcursor_manager_create(getenv("XCURSOR_THEME"),
		size && atoi(size) > 0 ? atoi(size) : 24);

	comp.new_input.notify = new_input;
	wl_signal_add(&comp.backend->events.new_input, &comp.new_input);
	comp.cursor_motion.notify = cursor_motion;
	wl_signal_add(&comp.cursor->events.motion, &comp.cursor_motion);
	comp.cursor_motion_abs.notify = cursor_motion_abs;
	wl_signal_add(&comp.cursor->events.motion_absolute, &comp.cursor_motion_abs);
	comp.cursor_button.notify = cursor_button;
	wl_signal_add(&comp.cursor->events.button, &comp.cursor_button);
	comp.cursor_axis.notify = cursor_axis;
	wl_signal_add(&comp.cursor->events.axis, &comp.cursor_axis);
	comp.cursor_frame.notify = cursor_frame;
	wl_signal_add(&comp.cursor->events.frame, &comp.cursor_frame);
	comp.request_cursor.notify = request_cursor;
	wl_signal_add(&comp.seat->events.request_set_cursor, &comp.request_cursor);
	comp.request_selection.notify = request_selection;
	wl_signal_add(&comp.seat->events.request_set_selection, &comp.request_selection);
	comp.request_primary.notify = request_primary;
	wl_signal_add(&comp.seat->events.request_set_primary_selection,
		&comp.request_primary);
}

void
input_finish(void)
{
	wl_list_remove(&comp.cursor_motion.link);
	wl_list_remove(&comp.cursor_motion_abs.link);
	wl_list_remove(&comp.cursor_button.link);
	wl_list_remove(&comp.cursor_axis.link);
	wl_list_remove(&comp.cursor_frame.link);
	wl_list_remove(&comp.request_cursor.link);
	wl_list_remove(&comp.request_selection.link);
	wl_list_remove(&comp.request_primary.link);
	wlr_xcursor_manager_destroy(comp.cursor_mgr);
	wlr_cursor_destroy(comp.cursor);
}

/* ---- API ---- */

int64_t
luxcomp_cursor_x(void)
{
	return comp.cursor->x;
}

int64_t
luxcomp_cursor_y(void)
{
	return comp.cursor->y;
}

static void
begin_grab(struct view *v, enum grab_mode mode, uint32_t edges)
{
	comp.grab = mode;
	comp.grab_view = v;
	comp.grab_edges = edges;
	comp.grab_x = comp.cursor->x - (mode == GRAB_MOVE ? v->x : 0);
	comp.grab_y = comp.cursor->y - (mode == GRAB_MOVE ? v->y : 0);
	comp.grab_box = (struct wlr_box){ v->x, v->y,
		v->toplevel->base->geometry.width, v->toplevel->base->geometry.height };
	wlr_seat_pointer_clear_focus(comp.seat);
}

void
luxcomp_view_begin_move(int64_t id)
{
	struct view *v = view_by_id(id);
	if (v && v->mapped) {
		begin_grab(v, GRAB_MOVE, 0);
	}
}

void
luxcomp_view_begin_resize(int64_t id, int64_t edges)
{
	struct view *v = view_by_id(id);
	if (v && v->mapped && edges) {
		begin_grab(v, GRAB_RESIZE, edges);
	}
}

void
luxcomp_set_keymap(const char *layout, const char *variant, const char *options)
{
	free(comp.kb_layout);
	free(comp.kb_variant);
	free(comp.kb_options);
	comp.kb_layout = layout && *layout ? strdup(layout) : NULL;
	comp.kb_variant = variant && *variant ? strdup(variant) : NULL;
	comp.kb_options = options && *options ? strdup(options) : NULL;
	struct xkb_keymap *map = make_keymap();
	struct keyboard *kb;
	wl_list_for_each(kb, &comp.keyboards, link) {
		wlr_keyboard_set_keymap(kb->wlr, map);
	}
	xkb_keymap_unref(map);
}

void
luxcomp_set_repeat(int64_t rate, int64_t delay_ms)
{
	comp.repeat_rate = rate;
	comp.repeat_delay = delay_ms;
	struct keyboard *kb;
	wl_list_for_each(kb, &comp.keyboards, link) {
		wlr_keyboard_set_repeat_info(kb->wlr, rate, delay_ms);
	}
}

int64_t
luxcomp_bind_key(int64_t mods, const char *key)
{
	if (!key) {
		return 0;
	}
	struct keybind b = { .mods = mods & MOD_MASK };
	if (!strncmp(key, "code:", 5)) {
		b.keycode = atoi(key + 5);
		if (!b.keycode) {
			return 0;
		}
	} else {
		b.keysym = xkb_keysym_to_lower(xkb_keysym_from_name(key,
			XKB_KEYSYM_CASE_INSENSITIVE));
		if (b.keysym == XKB_KEY_NoSymbol) {
			return 0;
		}
	}
	struct keybind *nb = malloc(sizeof(*nb));
	*nb = b;
	nb->id = ++comp.next_id;
	wl_list_insert(comp.keybinds.prev, &nb->link);
	return nb->id;
}

void
luxcomp_unbind_key(int64_t id)
{
	struct keybind *b;
	wl_list_for_each(b, &comp.keybinds, link) {
		if (b->id == id) {
			wl_list_remove(&b->link);
			free(b);
			return;
		}
	}
}

int64_t
luxcomp_modifiers(void)
{
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(comp.seat);
	return kb ? wlr_keyboard_get_modifiers(kb) & MOD_MASK : 0;
}
