/* Vstup: seat, klavesnice a zkratky, kurzor, presun a zmena velikosti oken */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wlr/backend.h>
#include <wlr/backend/session.h>
#include <wlr/interfaces/wlr_keyboard.h>
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
#include <wlr/types/wlr_session_lock_v1.h>
#include <wlr/types/wlr_virtual_keyboard_v1.h>
#include <wlr/types/wlr_virtual_pointer_v1.h>
#include <wlr/types/wlr_cursor_shape_v1.h>
#include <wlr/types/wlr_xcursor_manager.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/util/log.h>
#include <xkbcommon/xkbcommon.h>
#include "internal.h"

#define MOD_MASK (LUXCOMP_MOD_SHIFT | LUXCOMP_MOD_CTRL | LUXCOMP_MOD_ALT | LUXCOMP_MOD_SUPER)

struct keyboard {
	struct wl_list link;
	struct wlr_keyboard *wlr;
	uint32_t swallowed[8];		/* klavesy zkratek: jejich uvolneni klient nedostane */
	bool own_keymap;		/* virtualni klavesnice s keymapou klienta */
	bool resend_mods;		/* nova keymapa: klient si stav vynuloval, poslat ho s dalsi klavesou */
	struct wl_listener key, modifiers, keymap, destroy;
};

static bool syncing_group;

static uint32_t
now_ms(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

/* Stisknute klavesy pro vstup do plochy, bez tech, ktere spolkla zkratka: jejich uvolneni klient
 * nedostane a XWayland by je opakoval donekonecna (Super+Q zavre dialog X11, hlavni okno pak pise "qqq") */
static size_t
held_keys(struct wlr_keyboard *wlr, uint32_t *out)
{
	struct keyboard *kb, *own = NULL;
	wl_list_for_each(kb, &comp.keyboards, link) {
		if (kb->wlr == wlr) {
			own = kb;
		}
	}
	size_t n = 0;
	for (size_t i = 0; i < wlr->num_keycodes; i++) {
		bool swallowed = false;
		for (size_t j = 0; own && j < 8; j++) {
			swallowed |= own->swallowed[j] == wlr->keycodes[i] + 8;
		}
		if (!swallowed) {
			out[n++] = wlr->keycodes[i];
		}
	}
	return n;
}

void
seat_focus_surface(struct wlr_surface *surface)
{
	/* pod zamkem dostane klavesnici jen zamykaci plocha */
	if (comp.locked && surface && !wlr_session_lock_surface_v1_try_from_wlr_surface(surface)) {
		return;
	}
	if (!surface) {
		wlr_seat_keyboard_notify_clear_focus(comp.seat);
		return;
	}
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(comp.seat);
	if (kb) {
		uint32_t keys[WLR_KEYBOARD_KEYS_CAP];
		wlr_seat_keyboard_notify_enter(comp.seat, surface, keys, held_keys(kb, keys), &kb->modifiers);
	} else {
		wlr_seat_keyboard_notify_enter(comp.seat, surface, NULL, 0, NULL);
	}
}

/* Primo, mimo grab seatu: grab xdg_popup zmenu zamereni jinak zahodi */
void
seat_enter_direct(struct wlr_surface *surface)
{
	if (comp.locked && surface && !wlr_session_lock_surface_v1_try_from_wlr_surface(surface)) {
		return;
	}
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(comp.seat);
	if (!surface) {
		wlr_seat_keyboard_clear_focus(comp.seat);
	} else if (kb) {
		uint32_t keys[WLR_KEYBOARD_KEYS_CAP];
		wlr_seat_keyboard_enter(comp.seat, surface, keys, held_keys(kb, keys), &kb->modifiers);
	} else {
		wlr_seat_keyboard_enter(comp.seat, surface, NULL, 0, NULL);
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

/* Ctrl+Alt+F1..F12 prepne konzoli (xkb to preklada na XF86Switch_VT_N); plati i pod zamkem,
 * zamek zustava a druha konzole ma vlastni prihlaseni */
static bool
switch_vt(struct xkb_state *state, uint32_t keycode)
{
	if (!comp.session) {
		return false;
	}
	const xkb_keysym_t *syms;
	int n = xkb_state_key_get_syms(state, keycode, &syms);
	for (int i = 0; i < n; i++) {
		if (syms[i] >= XKB_KEY_XF86Switch_VT_1 && syms[i] <= XKB_KEY_XF86Switch_VT_12) {
			wlr_session_change_vt(comp.session, syms[i] - XKB_KEY_XF86Switch_VT_1 + 1);
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
	idle_activity();

	if (event->state == WL_KEYBOARD_KEY_STATE_RELEASED) {
		if (swallow(kb, keycode, false)) {
			return;
		}
	} else if (switch_vt(kb->wlr->xkb_state, keycode)) {
		swallow(kb, keycode, true);
		return;
	} else if (!comp.locked) {
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
	/* jina klavesnice: klient dostane jeji keymapu i stav (skupina rozlozeni), jinak by klavesy
	 * vykladal se stavem predchozi klavesnice */
	if (wlr_seat_get_keyboard(comp.seat) != kb->wlr || kb->resend_mods) {
		wlr_seat_set_keyboard(comp.seat, kb->wlr);
		wlr_seat_keyboard_notify_modifiers(comp.seat, &kb->wlr->modifiers);
		kb->resend_mods = false;
	}
	wlr_seat_keyboard_notify_key(comp.seat, event->time_msec, event->keycode,
		event->state);
}

/* Rozlozeni je jedno pro vsechny klavesnice. Virtualni klavesnice s vlastni keymapou ho dostane,
 * jen kdyz tolik rozlozeni ma (emoji maji jedno). */
static void
apply_group(struct keyboard *kb)
{
	struct wlr_keyboard *w = kb->wlr;
	if (!w->keymap || xkb_keymap_num_layouts(w->keymap) <= comp.kb_group
			|| xkb_state_serialize_layout(w->xkb_state, XKB_STATE_LAYOUT_EFFECTIVE) == comp.kb_group) {
		return;
	}
	wlr_keyboard_notify_modifiers(w, w->modifiers.depressed, w->modifiers.latched,
		w->modifiers.locked, comp.kb_group);
}

/* Srovnat skupinu na vsech klavesnicich; seat pak dostane modifikatory jen sve klavesnice */
static void
sync_group(void)
{
	syncing_group = true;
	struct keyboard *kb;
	wl_list_for_each(kb, &comp.keyboards, link) {
		apply_group(kb);
	}
	syncing_group = false;
	struct wlr_keyboard *seat_kb = wlr_seat_get_keyboard(comp.seat);
	if (seat_kb) {
		wlr_seat_keyboard_notify_modifiers(comp.seat, &seat_kb->modifiers);
	}
}

static void
keyboard_modifiers(struct wl_listener *listener, void *data)
{
	struct keyboard *kb = wl_container_of(listener, kb, modifiers);
	if (syncing_group) {
		return;
	}
	wlr_seat_set_keyboard(comp.seat, kb->wlr);
	wlr_seat_keyboard_notify_modifiers(comp.seat, &kb->wlr->modifiers);
	if (comp.binding_mods_held && !(wlr_keyboard_get_modifiers(kb->wlr) & MOD_MASK)) {
		comp.binding_mods_held = false;
		emit(LUXCOMP_EV_MODS_RELEASED, 0, 0, 0, 0);
	}
	/* prepnuti volbou XKB grp:... na fyzicke klavesnici */
	if (!kb->own_keymap) {
		uint32_t group = xkb_state_serialize_layout(kb->wlr->xkb_state, XKB_STATE_LAYOUT_EFFECTIVE);
		if (group != comp.kb_group) {
			comp.kb_group = group;
			sync_group();
			emit(LUXCOMP_EV_LAYOUT, 0, group, 0, 0);
		}
	}
}

static void
keyboard_keymap(struct wl_listener *listener, void *data)
{
	struct keyboard *kb = wl_container_of(listener, kb, keymap);
	syncing_group = true;
	apply_group(kb);
	syncing_group = false;
	/* seat posle klientum keymapu az po teto obsluze, ti si pak stav vynuluji */
	kb->resend_mods = true;
}

static void
keyboard_destroy(struct wl_listener *listener, void *data)
{
	struct keyboard *kb = wl_container_of(listener, kb, destroy);
	wl_list_remove(&kb->key.link);
	wl_list_remove(&kb->modifiers.link);
	wl_list_remove(&kb->keymap.link);
	wl_list_remove(&kb->destroy.link);
	wl_list_remove(&kb->link);
	free(kb);
}

static void
new_keyboard(struct wlr_input_device *device, bool own_keymap)
{
	struct keyboard *kb = calloc(1, sizeof(*kb));
	kb->wlr = wlr_keyboard_from_input_device(device);
	kb->own_keymap = own_keymap;
	if (!own_keymap) {
		if (!comp.kb_keymap) {
			comp.kb_keymap = make_keymap();
		}
		wlr_keyboard_set_keymap(kb->wlr, comp.kb_keymap);
		apply_group(kb);
	}
	wlr_keyboard_set_repeat_info(kb->wlr, comp.repeat_rate, comp.repeat_delay);
	kb->key.notify = keyboard_key;
	wl_signal_add(&kb->wlr->events.key, &kb->key);
	kb->modifiers.notify = keyboard_modifiers;
	wl_signal_add(&kb->wlr->events.modifiers, &kb->modifiers);
	kb->keymap.notify = keyboard_keymap;
	wl_signal_add(&kb->wlr->events.keymap, &kb->keymap);
	kb->destroy.notify = keyboard_destroy;
	wl_signal_add(&device->events.destroy, &kb->destroy);
	wl_list_insert(&comp.keyboards, &kb->link);
	wlr_seat_set_keyboard(comp.seat, kb->wlr);
}

static void
add_device(struct wlr_input_device *device, bool own_keymap)
{
	if (device->type == WLR_INPUT_DEVICE_KEYBOARD) {
		new_keyboard(device, own_keymap);
	} else if (device->type == WLR_INPUT_DEVICE_POINTER) {
		wlr_cursor_attach_input_device(comp.cursor, device);
	}
}

static void
new_input(struct wl_listener *listener, void *data)
{
	add_device(data, false);
}

/* Virtualni klavesnice si posila vlastni keymapu, tu nechame */
static void
new_virtual_keyboard(struct wl_listener *listener, void *data)
{
	struct wlr_virtual_keyboard_v1 *vk = data;
	add_device(&vk->keyboard.base, true);
}

static void
new_virtual_pointer(struct wl_listener *listener, void *data)
{
	struct wlr_virtual_pointer_v1_new_pointer_event *event = data;
	add_device(&event->new_pointer->pointer.base, false);
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
	struct wlr_scene_node *root = comp.locked ? &comp.lock_tree->node : &comp.scene->tree.node;
	/* ikona tazeni je pod kurzorem: cil hledat pod ni */
	bool dragging = comp.drag_icons->node.enabled;
	wlr_scene_node_set_enabled(&comp.drag_icons->node, false);
	struct wlr_scene_node *node = wlr_scene_node_at(root, x, y, sx, sy);
	wlr_scene_node_set_enabled(&comp.drag_icons->node, dragging);
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
	int min_w = luxcomp_view_get(v->id, LUXCOMP_VIEW_MIN_W);
	int min_h = luxcomp_view_get(v->id, LUXCOMP_VIEW_MIN_H);
	min_w = min_w > 0 ? min_w : 1;
	min_h = min_h > 0 ? min_h : 1;
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
	luxcomp_view_resize(v->id, right - left, bottom - top);
}

static void
process_motion(uint32_t time)
{
	wlr_scene_node_set_position(&comp.drag_icons->node, comp.cursor->x, comp.cursor->y);
	if (comp.grab != GRAB_NONE) {
		process_grab();
		return;
	}
	struct view *v;
	struct layer *l;
	struct wlr_surface *surface;
	double sx, sy;
	int part = hit_test(comp.cursor->x, comp.cursor->y, &v, &l, &surface, &sx, &sy);
	deco_hover(v ? v->deco : NULL, part);
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
	idle_activity();
	process_motion(e->time_msec);
}

static void
cursor_motion_abs(struct wl_listener *listener, void *data)
{
	struct wlr_pointer_motion_absolute_event *e = data;
	wlr_cursor_warp_absolute(comp.cursor, &e->pointer->base, e->x, e->y);
	idle_activity();
	process_motion(e->time_msec);
}

static void
cursor_button(struct wl_listener *listener, void *data)
{
	struct wlr_pointer_button_event *e = data;
	bool pressed = e->state == WL_POINTER_BUTTON_STATE_PRESSED;
	idle_activity();
	struct view *v;
	struct layer *l;
	struct wlr_surface *surface;
	double sx, sy;
	int part = hit_test(comp.cursor->x, comp.cursor->y, &v, &l, &surface, &sx, &sy);

	if (!pressed && comp.grab != GRAB_NONE) {
		if (getenv("LUXCOMP_STATS") && comp.grab_frames > 0) {
			wlr_log(WLR_ERROR, "luxcomp: drag %d frames, slowest render %.2f ms, mean %.2f ms",
				comp.grab_frames, comp.grab_render_max_ns / 1e6,
				comp.grab_render_sum_ns / 1e6 / comp.grab_frames);
		}
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
	} else if (pressed && v && comp.layer_focus && layer_on_demand(comp.layer_focus)) {
		/* klik do okna vraci klavesnici z vrstvy na pozadani; jine okno zameri politika */
		comp.layer_focus = NULL;
		if (v == comp.focused) {
			seat_focus_surface(view_surface(v));
		}
	}
	/* pusteni tlacitka mimo povrch musi tazeni ukoncit */
	if (surface || comp.seat->drag) {
		wlr_seat_pointer_notify_button(comp.seat, e->time_msec, e->button, e->state);
	}
	emit(LUXCOMP_EV_BUTTON, v ? v->id : 0, e->button, pressed, part);
}

static void
cursor_axis(struct wl_listener *listener, void *data)
{
	struct wlr_pointer_axis_event *e = data;
	idle_activity();
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

/* cursor-shape-v1: GTK 3 a 4 nastavuji kurzor jen jmenem. Bez obsluhy zustal posledni obrazek, i skryty
 * (aplikace kurzor skryla pres wl_pointer, ostatni ho pak uz neukazaly). Tvar, ktery tema nema, je sipka. */
static void
request_shape(struct wl_listener *listener, void *data)
{
	struct wlr_cursor_shape_manager_v1_request_set_shape_event *e = data;
	if (e->device_type != WLR_CURSOR_SHAPE_MANAGER_V1_DEVICE_TYPE_POINTER
			|| comp.seat->pointer_state.focused_client != e->seat_client) {
		return;
	}
	const char *name = wlr_cursor_shape_v1_name(e->shape);
	if (!wlr_xcursor_manager_get_xcursor(comp.cursor_mgr, name, 1)) {
		name = "default";
	}
	wlr_cursor_set_xcursor(comp.cursor, comp.cursor_mgr, name);
}

static void
request_selection(struct wl_listener *listener, void *data)
{
	struct wlr_seat_request_set_selection_event *e = data;
	wlr_seat_set_selection(comp.seat, e->source, e->serial);
}

/* Drag and drop mezi klienty (soubory z plochy do spravce souboru): jen s platnym serialem stisku */
static void
request_start_drag(struct wl_listener *listener, void *data)
{
	struct wlr_seat_request_start_drag_event *e = data;
	if (wlr_seat_validate_pointer_grab_serial(comp.seat, e->origin, e->serial)) {
		wlr_seat_start_pointer_drag(comp.seat, e->drag, e->serial);
	} else {
		wlr_data_source_destroy(e->drag->source);
	}
}

static void
start_drag(struct wl_listener *listener, void *data)
{
	struct wlr_drag *drag = data;
	if (drag->icon) {
		wlr_scene_drag_icon_create(comp.drag_icons, drag->icon);
	}
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
	/* ukazatel a klavesnici nabizet trvale: kdyz zmizi posledni klavesnice (odpojeni USB, konec
	 * virtualni), klienti by dostali leave a jejich wl_keyboard by uz zamereni nedostal */
	comp.seat = wlr_seat_create(comp.display, "seat0");
	wlr_seat_set_capabilities(comp.seat, WL_SEAT_CAPABILITY_POINTER | WL_SEAT_CAPABILITY_KEYBOARD);
	comp.cursor = wlr_cursor_create();
	wlr_cursor_attach_output_layout(comp.cursor, comp.layout);
	const char *size = getenv("XCURSOR_SIZE");
	comp.cursor_mgr = wlr_xcursor_manager_create(getenv("XCURSOR_THEME"),
		size && atoi(size) > 0 ? atoi(size) : 24);
	/* HiDPI: wlr_cursor si z manazeru nacte obrazky pro meritko kazdeho vystupu */

	comp.new_input.notify = new_input;
	wl_signal_add(&comp.backend->events.new_input, &comp.new_input);
	/* Vstup od klientu (psani shellu, testy pres scripts/wl-test). Klient jim muze psat do
	 * jinych oken, proto jen pro allowlist (security.c), s LUXCOMP_VIRTUAL_INPUT pro kazdeho
	 * klienta mimo sandbox. */
	struct wlr_virtual_keyboard_manager_v1 *vk =
		wlr_virtual_keyboard_manager_v1_create(comp.display);
	comp.new_virtual_keyboard.notify = new_virtual_keyboard;
	wl_signal_add(&vk->events.new_virtual_keyboard, &comp.new_virtual_keyboard);
	struct wlr_virtual_pointer_manager_v1 *vp =
		wlr_virtual_pointer_manager_v1_create(comp.display);
	comp.new_virtual_pointer.notify = new_virtual_pointer;
	wl_signal_add(&vp->events.new_virtual_pointer, &comp.new_virtual_pointer);
	security_mark(vk->global, GLOBAL_VIRTUAL_INPUT);
	security_mark(vp->global, GLOBAL_VIRTUAL_INPUT);
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
	struct wlr_cursor_shape_manager_v1 *shapes = wlr_cursor_shape_manager_v1_create(comp.display, 1);
	comp.request_shape.notify = request_shape;
	wl_signal_add(&shapes->events.request_set_shape, &comp.request_shape);
	comp.drag_icons = wlr_scene_tree_create(&comp.scene->tree);
	comp.request_start_drag.notify = request_start_drag;
	wl_signal_add(&comp.seat->events.request_start_drag, &comp.request_start_drag);
	comp.start_drag.notify = start_drag;
	wl_signal_add(&comp.seat->events.start_drag, &comp.start_drag);
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
	wl_list_remove(&comp.request_shape.link);
	wl_list_remove(&comp.request_selection.link);
	wl_list_remove(&comp.request_primary.link);
	wl_list_remove(&comp.request_start_drag.link);
	wl_list_remove(&comp.start_drag.link);
	wl_list_remove(&comp.new_virtual_keyboard.link);
	wl_list_remove(&comp.new_virtual_pointer.link);
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
	comp.grab_box = (struct wlr_box){ v->x, v->y, view_width(v), view_height(v) };
	comp.grab_frames = 0;
	comp.grab_render_max_ns = comp.grab_render_sum_ns = 0;
	deco_hover(NULL, 0);
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
	if (comp.kb_keymap) {
		xkb_keymap_unref(comp.kb_keymap);
	}
	comp.kb_keymap = make_keymap();
	if (comp.kb_group >= xkb_keymap_num_layouts(comp.kb_keymap)) {
		comp.kb_group = 0;
	}
	struct keyboard *kb;
	wl_list_for_each(kb, &comp.keyboards, link) {
		if (!kb->own_keymap) {
			wlr_keyboard_set_keymap(kb->wlr, comp.kb_keymap);
		}
	}
	sync_group();
}

void
luxcomp_set_layout(int64_t index)
{
	if (index < 0 || index >= luxcomp_layout_count()) {
		return;
	}
	comp.kb_group = index;
	sync_group();
}

int64_t
luxcomp_layout(void)
{
	return comp.kb_group;
}

int64_t
luxcomp_layout_count(void)
{
	if (!comp.kb_keymap) {
		comp.kb_keymap = make_keymap();
	}
	return comp.kb_keymap ? xkb_keymap_num_layouts(comp.kb_keymap) : 0;
}

const char *
luxcomp_layout_name(int64_t index)
{
	if (index < 0 || index >= luxcomp_layout_count()) {
		return "";
	}
	const char *name = xkb_keymap_layout_get_name(comp.kb_keymap, index);
	return name ? name : "";
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

void
luxcomp_set_cursor(const char *theme, int64_t size)
{
	size = size > 0 ? size : 24;
	struct wlr_xcursor_manager *mgr =
		wlr_xcursor_manager_create(theme && *theme ? theme : NULL, size);
	/* wlr_cursor muze drzet obrazek stareho manazeru, proto nejdriv prepnout */
	wlr_cursor_set_xcursor(comp.cursor, mgr, "default");
	wlr_xcursor_manager_destroy(comp.cursor_mgr);
	comp.cursor_mgr = mgr;
	cursor_rebase();
	xwayland_root_cursor();
	if (theme && *theme) {
		setenv("XCURSOR_THEME", theme, 1);
	} else {
		unsetenv("XCURSOR_THEME");
	}
	char text[16];
	snprintf(text, sizeof(text), "%d", (int)size);
	setenv("XCURSOR_SIZE", text, 1);
}
