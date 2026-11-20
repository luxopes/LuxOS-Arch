/* Psani textu virtualni klavesnici (virtual-keyboard-unstable-v1), napr. emoji z vyberu.
 * Jako wtype: pro kazdy text vlastni keymapa s jednou klavesou na znak (keysym U+xxxx), pak
 * stisk a pusteni kazde klavesy. Funguje pro libovolny znak bez ohledu na rozlozeni uzivatele. */
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <glib.h>
#include <xkbcommon/xkbcommon.h>
#include "internal.h"
#include "virtual-keyboard-unstable-v1-client-protocol.h"

#define MAX_KEYS 240     /* keycody 9..248 v keymape */

static struct zwp_virtual_keyboard_v1 *keyboard;

static xkb_keysym_t keysym_for(gunichar c)
{
	switch (c) {
	case '\n': return XKB_KEY_Return;
	case '\t': return XKB_KEY_Tab;
	case '\b': return XKB_KEY_BackSpace;
	}
	return xkb_utf32_to_keysym(c);
}

/* Keymapa pro znaky textu; keys[i] = index klavesy pro i-ty znak. Vraci pocet klaves. */
static int build_keymap(const gunichar *chars, int count, int *keys, GString *map)
{
	xkb_keysym_t syms[MAX_KEYS];
	int n = 0;
	for (int i = 0; i < count; i++) {
		xkb_keysym_t sym = keysym_for(chars[i]);
		int k = 0;
		while (k < n && syms[k] != sym)
			k++;
		if (k == n) {
			if (n == MAX_KEYS)
				return -1;
			syms[n++] = sym;
		}
		keys[i] = k;
	}
	g_string_append_printf(map, "xkb_keymap {\nxkb_keycodes \"luxos\" {\nminimum = 8;\nmaximum = %d;\n", n + 9);
	for (int k = 0; k < n; k++)
		g_string_append_printf(map, "<K%d> = %d;\n", k, k + 9);
	g_string_append(map, "};\nxkb_types \"luxos\" { include \"complete\" };\n"
		"xkb_compatibility \"luxos\" { include \"complete\" };\nxkb_symbols \"luxos\" {\n");
	for (int k = 0; k < n; k++) {
		char name[64];
		if (xkb_keysym_get_name(syms[k], name, sizeof name) < 0)
			return -1;
		g_string_append_printf(map, "key <K%d> {[ %s ]};\n", k, name);
	}
	g_string_append(map, "};\n};\n");
	return n;
}

static bool upload(GString *map)
{
	size_t size = map->len + 1;
	int fd = lwl_shm_fd(size);
	if (fd < 0)
		return false;
	bool ok = write(fd, map->str, size) == (ssize_t)size;
	if (ok)
		zwp_virtual_keyboard_v1_keymap(keyboard, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, fd, (uint32_t)size);
	close(fd);
	return ok;
}

/* Napise text do okna s fokusem; 1 hotovo, 0 neumime (chybi protokol nebo prilis mnoho ruznych znaku). */
LWL_EXPORT int lwl_type(const char *text)
{
	if (!text || !g_utf8_validate(text, -1, NULL))
		return 0;
	if (!keyboard) {
		if (!lwl.vk_manager || !lwl.seat)
			return 0;
		keyboard = zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(lwl.vk_manager, lwl.seat);
	}
	/* prazdny text jen pripravi klavesnici (seat ji ohlasi klientum predem) */
	if (!*text) {
		wl_display_flush(lwl.display);
		return 1;
	}
	glong count = 0;
	gunichar *chars = g_utf8_to_ucs4_fast(text, -1, &count);
	int *keys = g_new(int, count);
	GString *map = g_string_new(NULL);
	int n = build_keymap(chars, (int)count, keys, map);
	int ok = n > 0 && upload(map);
	if (ok) {
		uint32_t t = lwl_now_ms();
		zwp_virtual_keyboard_v1_modifiers(keyboard, 0, 0, 0, 0);
		for (glong i = 0; i < count; i++) {
			zwp_virtual_keyboard_v1_key(keyboard, t, (uint32_t)keys[i] + 1, WL_KEYBOARD_KEY_STATE_PRESSED);
			zwp_virtual_keyboard_v1_key(keyboard, t, (uint32_t)keys[i] + 1, WL_KEYBOARD_KEY_STATE_RELEASED);
		}
		wl_display_flush(lwl.display);
	}
	g_string_free(map, TRUE);
	g_free(keys);
	g_free(chars);
	return ok;
}

bool lwl_vkbd_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	(void)version;
	if (strcmp(interface, zwp_virtual_keyboard_manager_v1_interface.name) != 0)
		return false;
	lwl.vk_manager = wl_registry_bind(registry, name, &zwp_virtual_keyboard_manager_v1_interface, 1);
	return true;
}

void lwl_vkbd_reset(void)
{
	if (keyboard)
		zwp_virtual_keyboard_v1_destroy(keyboard);
	keyboard = NULL;
	if (lwl.vk_manager)
		zwp_virtual_keyboard_manager_v1_destroy(lwl.vk_manager);
}
