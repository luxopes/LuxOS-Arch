/* wlt-input - vstup do kompozitoru pres zwlr_virtual_pointer_v1 a zwp_virtual_keyboard_v1
 * Pouziti: WLT_LAYOUT=1280x720 wlt-input 'move 100 100' 'click right' 'type ahoj' 'key ctrl+a'
 *          (bez argumentu cte prikazy ze stdin, viz scen.c) */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <linux/input-event-codes.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include "scen.h"
#include "wlr-virtual-pointer-unstable-v1-client-protocol.h"
#include "virtual-keyboard-unstable-v1-client-protocol.h"

struct ctx {
	struct wl_display *display;
	struct wl_seat *seat;
	struct zwlr_virtual_pointer_manager_v1 *vpm;
	struct zwp_virtual_keyboard_manager_v1 *vkm;
	struct zwlr_virtual_pointer_v1 *ptr;
	struct zwp_virtual_keyboard_v1 *kbd;
	struct xkb_keymap *keymap;
	struct xkb_state *state;
	uint32_t w, h;
};

static uint32_t ms(void)
{
	return (uint32_t)(scen_now() * 1000);
}

static void global(void *data, struct wl_registry *reg, uint32_t name, const char *iface, uint32_t ver)
{
	struct ctx *c = data;
	if (!strcmp(iface, wl_seat_interface.name) && !c->seat)
		c->seat = wl_registry_bind(reg, name, &wl_seat_interface, 1);
	else if (!strcmp(iface, zwlr_virtual_pointer_manager_v1_interface.name))
		c->vpm = wl_registry_bind(reg, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
	else if (!strcmp(iface, zwp_virtual_keyboard_manager_v1_interface.name))
		c->vkm = wl_registry_bind(reg, name, &zwp_virtual_keyboard_manager_v1_interface, 1);
}

static void global_remove(void *data, struct wl_registry *reg, uint32_t name) {}

static const struct wl_registry_listener reg_listener = { global, global_remove };

static void p_move(void *data, double x, double y)
{
	struct ctx *c = data;
	if (x < 0) x = 0;
	if (y < 0) y = 0;
	if (x > c->w - 1) x = c->w - 1;
	if (y > c->h - 1) y = c->h - 1;
	zwlr_virtual_pointer_v1_motion_absolute(c->ptr, ms(), (uint32_t)x, (uint32_t)y, c->w, c->h);
	zwlr_virtual_pointer_v1_frame(c->ptr);
}

static void p_button(void *data, int btn, int down)
{
	static const uint32_t codes[] = { BTN_LEFT, BTN_RIGHT, BTN_MIDDLE };
	struct ctx *c = data;
	zwlr_virtual_pointer_v1_button(c->ptr, ms(), codes[btn],
		down ? WL_POINTER_BUTTON_STATE_PRESSED : WL_POINTER_BUTTON_STATE_RELEASED);
	zwlr_virtual_pointer_v1_frame(c->ptr);
}

/* keysym -> klavesa v keymape a uroven (1 = se Shiftem) */
static int find_key(struct xkb_keymap *km, xkb_keysym_t sym, xkb_keycode_t *code, int *level)
{
	for (xkb_keycode_t k = xkb_keymap_min_keycode(km); k <= xkb_keymap_max_keycode(km); k++) {
		for (int l = 0; l < 2; l++) {
			const xkb_keysym_t *syms;
			int n = xkb_keymap_key_get_syms_by_level(km, k, 0, l, &syms);
			for (int i = 0; i < n; i++)
				if (syms[i] == sym) {
					*code = k;
					*level = l;
					return 0;
				}
		}
	}
	return -1;
}

static void send_key(struct ctx *c, xkb_keycode_t code, int down)
{
	/* evdev kod = xkb kod - 8 */
	zwp_virtual_keyboard_v1_key(c->kbd, ms(), code - 8,
		down ? WL_KEYBOARD_KEY_STATE_PRESSED : WL_KEYBOARD_KEY_STATE_RELEASED);
	/* wlroots u virtualni klavesnice stav modifikatoru z klaves nepocita, posila ho klient */
	if (xkb_state_update_key(c->state, code, down ? XKB_KEY_DOWN : XKB_KEY_UP) & XKB_STATE_MODS_EFFECTIVE)
		zwp_virtual_keyboard_v1_modifiers(c->kbd,
			xkb_state_serialize_mods(c->state, XKB_STATE_MODS_DEPRESSED),
			xkb_state_serialize_mods(c->state, XKB_STATE_MODS_LATCHED),
			xkb_state_serialize_mods(c->state, XKB_STATE_MODS_LOCKED),
			xkb_state_serialize_layout(c->state, XKB_STATE_LAYOUT_EFFECTIVE));
}

static int k_key(void *data, const char *name, int down)
{
	static const char *alias[][2] = {
		{ "ctrl", "Control_L" }, { "alt", "Alt_L" }, { "shift", "Shift_L" },
		{ "super", "Super_L" }, { "logo", "Super_L" }, { "esc", "Escape" },
		{ "enter", "Return" }, { "ret", "Return" }, { "spc", "space" },
	};
	struct ctx *c = data;
	for (size_t i = 0; i < sizeof alias / sizeof alias[0]; i++)
		if (!strcasecmp(name, alias[i][0]))
			name = alias[i][1];
	xkb_keysym_t sym = xkb_keysym_from_name(name, XKB_KEYSYM_NO_FLAGS);
	if (sym == XKB_KEY_NoSymbol)
		sym = xkb_keysym_from_name(name, XKB_KEYSYM_CASE_INSENSITIVE);
	xkb_keycode_t code;
	int level;
	if (sym == XKB_KEY_NoSymbol || find_key(c->keymap, sym, &code, &level) < 0) {
		fprintf(stderr, "unknown key: %s\n", name);
		return -1;
	}
	double t = scen_now();
	send_key(c, code, down);
	/* cas stisku pro mereni odezvy (klavesa -> prvni snimek klienta), CLOCK_MONOTONIC v us */
	if (down && getenv("WLT_STAMP")) {
		printf("stamp %s %lld\n", name, (long long)(t * 1e6));
		fflush(stdout);
	}
	return 0;
}

static int k_text(void *data, const char *s)
{
	struct ctx *c = data;
	xkb_keycode_t shift, code;
	int lvl;
	find_key(c->keymap, XKB_KEY_Shift_L, &shift, &lvl);
	for (; *s; s++) {
		xkb_keysym_t sym = xkb_utf32_to_keysym((unsigned char)*s);
		if (find_key(c->keymap, sym, &code, &lvl) < 0) {
			fprintf(stderr, "cannot type: %c\n", *s);
			return -1;
		}
		if (lvl)
			send_key(c, shift, 1);
		send_key(c, code, 1);
		send_key(c, code, 0);
		if (lvl)
			send_key(c, shift, 0);
		wl_display_roundtrip(c->display);
		scen_sleep(0.01);
	}
	return 0;
}

static void flush(void *data)
{
	struct ctx *c = data;
	wl_display_roundtrip(c->display);
}

static const struct scen_ops ops = { p_move, p_button, k_key, k_text, flush };

static int setup_keyboard(struct ctx *c)
{
	struct xkb_context *xc = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	struct xkb_rule_names names = { .layout = getenv("WLT_XKB_LAYOUT") ? getenv("WLT_XKB_LAYOUT") : "us" };
	c->keymap = xc ? xkb_keymap_new_from_names(xc, &names, XKB_KEYMAP_COMPILE_NO_FLAGS) : NULL;
	if (!c->keymap)
		return -1;
	c->state = xkb_state_new(c->keymap);
	char *str = xkb_keymap_get_as_string(c->keymap, XKB_KEYMAP_FORMAT_TEXT_V1);
	size_t len = strlen(str) + 1;
	int fd = memfd_create("wlt-keymap", MFD_CLOEXEC);
	if (fd < 0 || write(fd, str, len) != (ssize_t)len)
		return -1;
	free(str);
	c->kbd = zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(c->vkm, c->seat);
	zwp_virtual_keyboard_v1_keymap(c->kbd, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, fd, len);
	close(fd);
	return 0;
}

int main(int argc, char **argv)
{
	struct ctx c = { 0 };
	const char *layout = getenv("WLT_LAYOUT");
	if (!layout || sscanf(layout, "%ux%u", &c.w, &c.h) != 2 || !c.w || !c.h) {
		fprintf(stderr, "WLT_LAYOUT=WxH is required\n");
		return 2;
	}
	c.display = wl_display_connect(NULL);
	if (!c.display) {
		fprintf(stderr, "cannot connect to wayland display\n");
		return 1;
	}
	wl_registry_add_listener(wl_display_get_registry(c.display), &reg_listener, &c);
	wl_display_roundtrip(c.display);
	if (!c.seat || !c.vpm || !c.vkm) {
		fprintf(stderr, "compositor lacks %s\n", !c.seat ? "wl_seat" : !c.vpm ?
			"zwlr_virtual_pointer_manager_v1" : "zwp_virtual_keyboard_manager_v1");
		return 1;
	}
	c.ptr = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(c.vpm, c.seat);
	if (setup_keyboard(&c) < 0) {
		fprintf(stderr, "cannot set up keymap\n");
		return 1;
	}
	wl_display_roundtrip(c.display);
	int r = scen_run(&ops, &c, argc - 1, argv + 1);
	wl_display_roundtrip(c.display);
	zwp_virtual_keyboard_v1_destroy(c.kbd);
	zwlr_virtual_pointer_v1_destroy(c.ptr);
	wl_display_roundtrip(c.display);
	wl_display_disconnect(c.display);
	return r < 0 ? 1 : 0;
}
