/* Vstup: seat, klavesnice a zkratky, kurzor, presun a zmena velikosti oken */
#define _GNU_SOURCE
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wlr/backend.h>
#include <wlr/backend/libinput.h>
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
#include <linux/input-event-codes.h>
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

/* Mysi a touchpady z libinput: nastaveni podle druhu plati pro pripojena i pozdeji pripojena zarizeni */
#define INPUT_PROPS (LUXCOMP_INPUT_SCROLL_METHOD + 1)

struct pointer {
	struct wl_list link;
	int64_t id;
	struct wlr_input_device *wlr;
	struct wl_listener destroy;
};

static struct wl_list pointers;
static int64_t input_conf[3][INPUT_PROPS];	/* [druh][vlastnost], LUXCOMP_INPUT_DEFAULT = nechat */

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

static void new_pointer(struct wlr_input_device *device);

static void
add_device(struct wlr_input_device *device, bool own_keymap)
{
	if (device->type == WLR_INPUT_DEVICE_KEYBOARD) {
		new_keyboard(device, own_keymap);
	} else if (device->type == WLR_INPUT_DEVICE_POINTER) {
		wlr_cursor_attach_input_device(comp.cursor, device);
		if (wlr_input_device_is_libinput(device)) {
			new_pointer(device);
		}
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
	struct wlr_scene_node *node = NULL;
	if (comp.cover->node.enabled && !comp.locked) {
		/* zakryti po prihlaseni je jen obraz, vstup jde na plochu pod nim */
		struct wlr_scene_node *child;
		wl_list_for_each_reverse(child, &comp.scene->tree.children, link) {
			if (child != &comp.cover->node
					&& (node = wlr_scene_node_at(child, x, y, sx, sy))) {
				break;
			}
		}
	} else {
		node = wlr_scene_node_at(root, x, y, sx, sy);
	}
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

/* Posledni tvar kurzoru od klienta pod ukazatelem; NULL = klient ma vlastni obrazek (nebo zadny) */
static const char *client_shape;

/* Sipka behem spousteni aplikace = animovany "progress" (launch_busy) */
static const char *
pointer_name(const char *name)
{
	if (launch_busy() && !strcmp(name, "default")
			&& wlr_xcursor_manager_get_xcursor(comp.cursor_mgr, "progress", 1)) {
		return "progress";
	}
	return name;
}

void
cursor_busy_update(void)
{
	if (comp.grab != GRAB_NONE) {
		return;
	}
	if (!comp.seat->pointer_state.focused_surface) {
		wlr_cursor_set_xcursor(comp.cursor, comp.cursor_mgr, pointer_name("default"));
	} else if (client_shape) {
		wlr_cursor_set_xcursor(comp.cursor, comp.cursor_mgr, pointer_name(client_shape));
	}
}

/* Kolik okna zustava na obrazovce pri presunu mysi: vodorovne kus zahlavi, svisle cele zahlavi */
#define REACH_X 100
#define REACH_TITLE 30

/* Zahlavi presouvaneho okna musi zustat dosazitelne: ram nahore ne pod listou (exkluzivni zony monitoru
 * pod kurzorem), nahore aspon vyska zahlavi nad spodnim okrajem plochy a vodorovne kus okna na obrazovce.
 * Okno zatazene pod listu uz neslo chytit ani zavrit (pripominka 28). */
static void
keep_reachable(struct view *v, int *x, int *y)
{
	struct output *o = output_at(comp.cursor->x, comp.cursor->y);
	if (!o || wlr_box_empty(&o->usable)) {
		return;
	}
	struct wlr_box u = o->usable, all;
	int top = luxcomp_view_get(v->id, LUXCOMP_VIEW_DECO_TOP);
	int fy = *y - top, title = top > 0 ? top : REACH_TITLE;
	if (fy > u.y + u.height - title) {
		fy = u.y + u.height - title;
	}
	if (fy < u.y) {
		fy = u.y;
	}
	*y = fy + top;
	wlr_output_layout_get_box(comp.layout, NULL, &all);
	if (*x > all.x + all.width - REACH_X) {
		*x = all.x + all.width - REACH_X;
	}
	if (*x < all.x + REACH_X - view_width(v)) {
		*x = all.x + REACH_X - view_width(v);
	}
}

static void
process_grab(void)
{
	struct view *v = comp.grab_view;
	double cx = comp.cursor->x, cy = comp.cursor->y;
	if (comp.grab == GRAB_MOVE) {
		int x = lround(cx - comp.grab_x), y = lround(cy - comp.grab_y);
		keep_reachable(v, &x, &y);
		luxcomp_view_move(v->id, x, y);
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
		int x = left;
		keep_reachable(v, &x, &top);
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
		wlr_cursor_set_xcursor(comp.cursor, comp.cursor_mgr, pointer_name("default"));
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

static void begin_grab(struct view *v, enum grab_mode mode, uint32_t edges);

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
	/* Super + leve tlacitko kdekoli v okne presouva okno (jako v Xfce s Alt), klient klik nedostane */
	if (pressed && e->button == BTN_LEFT && v && v->mapped && (luxcomp_modifiers() & LUXCOMP_MOD_SUPER)
			&& !luxcomp_view_get(v->id, LUXCOMP_VIEW_MAXIMIZED)
			&& !luxcomp_view_get(v->id, LUXCOMP_VIEW_FULLSCREEN)) {
		begin_grab(v, GRAB_MOVE, 0);
		emit(LUXCOMP_EV_BUTTON, v->id, e->button, 1, LUXCOMP_PART_CLIENT);
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
		client_shape = NULL;
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
	client_shape = name;
	wlr_cursor_set_xcursor(comp.cursor, comp.cursor_mgr, pointer_name(name));
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

	wl_list_init(&pointers);
	for (int k = 0; k < 3; k++) {
		for (int p = 0; p < INPUT_PROPS; p++) {
			input_conf[k][p] = LUXCOMP_INPUT_DEFAULT;
		}
	}

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

/* ---- mys a touchpad (libinput) ---- */

static int
pointer_kind(struct libinput_device *dev)
{
	return libinput_device_config_tap_get_finger_count(dev) > 0 ? LUXCOMP_INPUT_TOUCHPAD : LUXCOMP_INPUT_MOUSE;
}

static const uint32_t click_methods[] = { LIBINPUT_CONFIG_CLICK_METHOD_NONE,
	LIBINPUT_CONFIG_CLICK_METHOD_BUTTON_AREAS, LIBINPUT_CONFIG_CLICK_METHOD_CLICKFINGER };
static const uint32_t scroll_methods[] = { LIBINPUT_CONFIG_SCROLL_NO_SCROLL, LIBINPUT_CONFIG_SCROLL_2FG,
	LIBINPUT_CONFIG_SCROLL_EDGE, LIBINPUT_CONFIG_SCROLL_ON_BUTTON_DOWN };

static int64_t
method_index(const uint32_t *methods, size_t n, uint32_t method)
{
	for (size_t i = 0; i < n; i++) {
		if (methods[i] == method) {
			return i;
		}
	}
	return LUXCOMP_INPUT_NONE;
}

/* Hodnota, kterou ma libinput, nebo vychozi hodnota zarizeni; LUXCOMP_INPUT_NONE = volbu nema */
static int64_t
pointer_value(struct libinput_device *dev, int prop, bool def)
{
	switch (prop) {
	case LUXCOMP_INPUT_KIND:
		return pointer_kind(dev);
	case LUXCOMP_INPUT_SPEED:
		if (!libinput_device_config_accel_is_available(dev)) {
			return LUXCOMP_INPUT_NONE;
		}
		return lround(100 * (def ? libinput_device_config_accel_get_default_speed(dev)
			: libinput_device_config_accel_get_speed(dev)));
	case LUXCOMP_INPUT_ACCEL_PROFILE: {
		uint32_t profiles = libinput_device_config_accel_get_profiles(dev);
		if (!(profiles & LIBINPUT_CONFIG_ACCEL_PROFILE_FLAT) || !(profiles & LIBINPUT_CONFIG_ACCEL_PROFILE_ADAPTIVE)) {
			return LUXCOMP_INPUT_NONE;
		}
		enum libinput_config_accel_profile p = def ? libinput_device_config_accel_get_default_profile(dev)
			: libinput_device_config_accel_get_profile(dev);
		return p == LIBINPUT_CONFIG_ACCEL_PROFILE_FLAT;
	}
	case LUXCOMP_INPUT_NATURAL_SCROLL:
		if (!libinput_device_config_scroll_has_natural_scroll(dev)) {
			return LUXCOMP_INPUT_NONE;
		}
		return def ? libinput_device_config_scroll_get_default_natural_scroll_enabled(dev)
			: libinput_device_config_scroll_get_natural_scroll_enabled(dev);
	case LUXCOMP_INPUT_LEFT_HANDED:
		if (!libinput_device_config_left_handed_is_available(dev)) {
			return LUXCOMP_INPUT_NONE;
		}
		return def ? libinput_device_config_left_handed_get_default(dev)
			: libinput_device_config_left_handed_get(dev);
	case LUXCOMP_INPUT_MIDDLE_EMULATION:
		if (!libinput_device_config_middle_emulation_is_available(dev)) {
			return LUXCOMP_INPUT_NONE;
		}
		return (def ? libinput_device_config_middle_emulation_get_default_enabled(dev)
			: libinput_device_config_middle_emulation_get_enabled(dev)) == LIBINPUT_CONFIG_MIDDLE_EMULATION_ENABLED;
	case LUXCOMP_INPUT_TAP:
		if (libinput_device_config_tap_get_finger_count(dev) == 0) {
			return LUXCOMP_INPUT_NONE;
		}
		return (def ? libinput_device_config_tap_get_default_enabled(dev)
			: libinput_device_config_tap_get_enabled(dev)) == LIBINPUT_CONFIG_TAP_ENABLED;
	case LUXCOMP_INPUT_TAP_DRAG:
		if (libinput_device_config_tap_get_finger_count(dev) == 0) {
			return LUXCOMP_INPUT_NONE;
		}
		return (def ? libinput_device_config_tap_get_default_drag_enabled(dev)
			: libinput_device_config_tap_get_drag_enabled(dev)) == LIBINPUT_CONFIG_DRAG_ENABLED;
	case LUXCOMP_INPUT_DISABLE_WHILE_TYPING:
		if (!libinput_device_config_dwt_is_available(dev)) {
			return LUXCOMP_INPUT_NONE;
		}
		return (def ? libinput_device_config_dwt_get_default_enabled(dev)
			: libinput_device_config_dwt_get_enabled(dev)) == LIBINPUT_CONFIG_DWT_ENABLED;
	case LUXCOMP_INPUT_CLICK_METHOD:
		if (libinput_device_config_click_get_methods(dev) == LIBINPUT_CONFIG_CLICK_METHOD_NONE) {
			return LUXCOMP_INPUT_NONE;
		}
		return method_index(click_methods, 3, def ? libinput_device_config_click_get_default_method(dev)
			: libinput_device_config_click_get_method(dev));
	case LUXCOMP_INPUT_SCROLL_METHOD:
		if (libinput_device_config_scroll_get_methods(dev) == LIBINPUT_CONFIG_SCROLL_NO_SCROLL) {
			return LUXCOMP_INPUT_NONE;
		}
		return method_index(scroll_methods, 4, def ? libinput_device_config_scroll_get_default_method(dev)
			: libinput_device_config_scroll_get_method(dev));
	}
	return LUXCOMP_INPUT_NONE;
}

static enum libinput_config_status
pointer_apply(struct libinput_device *dev, int prop, int64_t value)
{
	if (value == LUXCOMP_INPUT_DEFAULT) {
		value = pointer_value(dev, prop, true);
	}
	if (value == LUXCOMP_INPUT_NONE || pointer_value(dev, prop, false) == LUXCOMP_INPUT_NONE) {
		return LIBINPUT_CONFIG_STATUS_UNSUPPORTED;
	}
	switch (prop) {
	case LUXCOMP_INPUT_SPEED:
		value = value < -100 ? -100 : value > 100 ? 100 : value;
		return libinput_device_config_accel_set_speed(dev, value / 100.0);
	case LUXCOMP_INPUT_ACCEL_PROFILE:
		return libinput_device_config_accel_set_profile(dev, value
			? LIBINPUT_CONFIG_ACCEL_PROFILE_FLAT : LIBINPUT_CONFIG_ACCEL_PROFILE_ADAPTIVE);
	case LUXCOMP_INPUT_NATURAL_SCROLL:
		return libinput_device_config_scroll_set_natural_scroll_enabled(dev, value != 0);
	case LUXCOMP_INPUT_LEFT_HANDED:
		return libinput_device_config_left_handed_set(dev, value != 0);
	case LUXCOMP_INPUT_MIDDLE_EMULATION:
		return libinput_device_config_middle_emulation_set_enabled(dev, value
			? LIBINPUT_CONFIG_MIDDLE_EMULATION_ENABLED : LIBINPUT_CONFIG_MIDDLE_EMULATION_DISABLED);
	case LUXCOMP_INPUT_TAP:
		return libinput_device_config_tap_set_enabled(dev, value
			? LIBINPUT_CONFIG_TAP_ENABLED : LIBINPUT_CONFIG_TAP_DISABLED);
	case LUXCOMP_INPUT_TAP_DRAG:
		return libinput_device_config_tap_set_drag_enabled(dev, value
			? LIBINPUT_CONFIG_DRAG_ENABLED : LIBINPUT_CONFIG_DRAG_DISABLED);
	case LUXCOMP_INPUT_DISABLE_WHILE_TYPING:
		return libinput_device_config_dwt_set_enabled(dev, value
			? LIBINPUT_CONFIG_DWT_ENABLED : LIBINPUT_CONFIG_DWT_DISABLED);
	case LUXCOMP_INPUT_CLICK_METHOD:
		if (value < 0 || value > 2) {
			return LIBINPUT_CONFIG_STATUS_INVALID;
		}
		return libinput_device_config_click_set_method(dev, click_methods[value]);
	case LUXCOMP_INPUT_SCROLL_METHOD:
		if (value < 0 || value > 3) {
			return LIBINPUT_CONFIG_STATUS_INVALID;
		}
		return libinput_device_config_scroll_set_method(dev, scroll_methods[value]);
	}
	return LIBINPUT_CONFIG_STATUS_UNSUPPORTED;
}

static void
pointer_set(struct pointer *p, int prop, int64_t value)
{
	struct libinput_device *dev = wlr_libinput_get_device_handle(p->wlr);
	enum libinput_config_status status = pointer_apply(dev, prop, value);
	/* volbu, kterou zarizeni nema (mys a klepnuti), neni treba hlasit */
	if (status == LIBINPUT_CONFIG_STATUS_INVALID) {
		wlr_log(WLR_ERROR, "luxcomp: %s: input option %d = %" PRId64 " refused",
			libinput_device_get_name(dev), prop, value);
	}
}

static void
pointer_destroy(struct wl_listener *listener, void *data)
{
	struct pointer *p = wl_container_of(listener, p, destroy);
	wl_list_remove(&p->destroy.link);
	wl_list_remove(&p->link);
	free(p);
}

static void
new_pointer(struct wlr_input_device *device)
{
	struct pointer *p = calloc(1, sizeof(*p));
	p->id = ++comp.next_id;
	p->wlr = device;
	p->destroy.notify = pointer_destroy;
	wl_signal_add(&device->events.destroy, &p->destroy);
	wl_list_insert(pointers.prev, &p->link);
	int kind = pointer_kind(wlr_libinput_get_device_handle(device));
	for (int prop = LUXCOMP_INPUT_SPEED; prop < INPUT_PROPS; prop++) {
		if (input_conf[kind][prop] != LUXCOMP_INPUT_DEFAULT) {
			pointer_set(p, prop, input_conf[kind][prop]);
		}
	}
}

static struct pointer *
pointer_by_id(int64_t id)
{
	struct pointer *p;
	wl_list_for_each(p, &pointers, link) {
		if (p->id == id) {
			return p;
		}
	}
	return NULL;
}

void
luxcomp_input_set(int64_t kind, int64_t prop, int64_t value)
{
	if (kind < LUXCOMP_INPUT_MOUSE || kind > LUXCOMP_INPUT_TOUCHPAD
			|| prop < LUXCOMP_INPUT_SPEED || prop >= INPUT_PROPS) {
		return;
	}
	input_conf[kind][prop] = value;
	struct pointer *p;
	wl_list_for_each(p, &pointers, link) {
		if (pointer_kind(wlr_libinput_get_device_handle(p->wlr)) == kind) {
			pointer_set(p, prop, value);
		}
	}
}

int64_t
luxcomp_input_next(int64_t device)
{
	struct wl_list *from = &pointers;
	if (device) {
		struct pointer *p = pointer_by_id(device);
		if (!p) {
			return 0;
		}
		from = &p->link;
	}
	if (from->next == &pointers) {
		return 0;
	}
	struct pointer *next = wl_container_of(from->next, next, link);
	return next->id;
}

const char *
luxcomp_input_name(int64_t device)
{
	struct pointer *p = pointer_by_id(device);
	return p ? libinput_device_get_name(wlr_libinput_get_device_handle(p->wlr)) : "";
}

int64_t
luxcomp_input_get(int64_t device, int64_t prop)
{
	struct pointer *p = pointer_by_id(device);
	if (!p || prop < LUXCOMP_INPUT_KIND || prop >= INPUT_PROPS) {
		return LUXCOMP_INPUT_NONE;
	}
	return pointer_value(wlr_libinput_get_device_handle(p->wlr), prop, false);
}
