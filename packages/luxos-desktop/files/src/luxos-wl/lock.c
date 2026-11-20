/* Zamceni obrazovky (ext-session-lock-v1): zamykaci plochy s vlastnimi bufery wl_shm (kresli
 * se do nich cairem z LSL) a klavesnice pres xkbcommon pro zadani hesla. Kdyz zamykac spadne,
 * kompozitor nechava obrazovku zamcenou - proto tu neni nic, co by zamek rusilo samo.
 *
 * Heslo (lwl_lock_secret): znaky jdou rovnou do jedineho bufferu zamceneho v RAM, do LSL nikdy -
 * tam by z retezcu zustaly kopie, ktere nejde smazat. Ven jde jen jednou do roury pomocneho
 * programu PAM (lwl_lock_secret_write) a buffer se hned prepise nulami. Mrtve klavesy a Compose
 * (ť = dead_caron + t) sklada xkbcommon-compose rovnou do tehoz bufferu; opakovani drzene klavesy
 * (wl_keyboard.repeat_info) bezi tu v C, aby ani opakovane znaky neprosly LSL. */
#define _GNU_SOURCE
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <glib.h>
#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-compose.h>
#include "internal.h"
#include "ext-session-lock-v1-client-protocol.h"
#include "fractional-scale-v1-client-protocol.h"
#include "viewporter-client-protocol.h"

struct buffer {
	struct surface *owner;
	struct wl_buffer *wl;
	void *data;
	size_t size;
	int width, height;
	bool busy;
};

struct surface {
	struct wl_list link;
	int id;
	int output;
	struct wl_surface *wl;
	struct ext_session_lock_surface_v1 *lock;
	int width, height;
	int scale;                      /* v 1/120 jako wp_fractional_scale_v1; drzi se meritka vystupu */
	int drawn_scale;
	struct wp_fractional_scale_v1 *fractional;
	struct wp_viewport *viewport;
	struct buffer buffers[2];
	struct buffer *drawing, *current;
};

static struct ext_session_lock_v1 *lock;
static bool locked;
static struct wl_list surfaces = {&surfaces, &surfaces};
static struct wp_fractional_scale_manager_v1 *fractional_manager;
static struct wp_viewporter *viewporter;
static guint spare_timer;

static struct wl_keyboard *keyboard;
static struct xkb_context *xkb;
static struct xkb_keymap *keymap;
static struct xkb_state *xkb_state;
static struct surface *focus;
static struct xkb_compose_table *compose_table;
static struct xkb_compose_state *compose;
static int32_t repeat_rate = 25, repeat_delay = 600;
static xkb_keycode_t repeat_code;
static guint repeat_timer;

#define SECRET_MAX 1024
#define LAYOUTS_MAX 4
static char secret[SECRET_MAX];
static size_t secret_len;
static bool secret_on, secret_locked;
static int caps_shown = -1, group_shown = -1;
static char layout_codes[LAYOUTS_MAX][16];
static int layout_count;

static void secret_clear(void);

/* ---- bufery ---- */

static void buffer_free(struct buffer *b)
{
	if (b->wl)
		wl_buffer_destroy(b->wl);
	if (b->data)
		munmap(b->data, b->size);
	memset(b, 0, sizeof *b);
}

/* Druhy bufer je potreba jen behem animace (zatreseni, tecky pri psani); v klidu na plose
 * zustava jen ten posledni, at zamek u 4K monitoru nedrzi zbytecne 33 MB. */
static gboolean free_spares(gpointer data)
{
	struct surface *s;
	(void)data;
	spare_timer = 0;
	wl_list_for_each(s, &surfaces, link)
		for (int i = 0; i < 2; i++)
			if (&s->buffers[i] != s->current && s->buffers[i].wl && !s->buffers[i].busy)
				buffer_free(&s->buffers[i]);
	return G_SOURCE_REMOVE;
}

static void buffer_release(void *data, struct wl_buffer *wl)
{
	struct buffer *b = data;
	(void)wl;
	b->busy = false;
	if (b != b->owner->current && !spare_timer)
		spare_timer = g_timeout_add_seconds(1, free_spares, NULL);
}

static const struct wl_buffer_listener buffer_listener = {.release = buffer_release};

static bool buffer_alloc(struct surface *owner, struct buffer *b, int width, int height)
{
	int stride = width * 4;
	size_t size = (size_t)stride * height;
	int fd = lwl_shm_fd(size);
	if (fd < 0)
		return false;
	void *data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (data == MAP_FAILED) {
		close(fd);
		return false;
	}
	struct wl_shm_pool *pool = wl_shm_create_pool(lwl.shm, fd, (int32_t)size);
	b->wl = wl_shm_pool_create_buffer(pool, 0, width, height, stride, WL_SHM_FORMAT_ARGB8888);
	wl_shm_pool_destroy(pool);
	close(fd);
	wl_buffer_add_listener(b->wl, &buffer_listener, b);
	b->owner = owner;
	b->data = data;
	b->size = size;
	b->width = width;
	b->height = height;
	return true;
}

/* ---- zamykaci plochy ---- */

static struct surface *find(int id)
{
	struct surface *s;
	wl_list_for_each(s, &surfaces, link)
		if (s->id == id)
			return s;
	return NULL;
}

static void surface_configure(void *data, struct ext_session_lock_surface_v1 *ls, uint32_t serial, uint32_t width, uint32_t height)
{
	struct surface *s = data;
	s->width = (int)width;
	s->height = (int)height;
	ext_session_lock_surface_v1_ack_configure(ls, serial);
	lwl_emit(LWL_SURFACE_CONFIGURE, s->id, s->width, s->height);
}

static const struct ext_session_lock_surface_v1_listener surface_listener = {.configure = surface_configure};

/* Meritko plochy v 1/120: preferovane z wp_fractional_scale_v1, jinak cele meritko vystupu. */
static int surface_scale(struct surface *s)
{
	if (s->fractional)
		return s->scale;
	struct lwl_output *o = lwl_find_output(s->output);
	return o && o->scale > 1 ? o->scale * 120 : 120;
}

/* jine meritko nez naposledy nakreslene: LSL dostane configure znovu a prekresli */
static void scale_changed(struct surface *s)
{
	if (s->width > 0 && s->drawn_scale && surface_scale(s) != s->drawn_scale)
		lwl_emit(LWL_SURFACE_CONFIGURE, s->id, s->width, s->height);
}

static void preferred_scale(void *data, struct wp_fractional_scale_v1 *f, uint32_t scale)
{
	struct surface *s = data;
	(void)f;
	s->scale = scale >= 60 && scale <= 120 * 8 ? (int)scale : 120;
	scale_changed(s);
}

static const struct wp_fractional_scale_v1_listener fractional_listener = {.preferred_scale = preferred_scale};

void lwl_lock_output_changed(int output)
{
	struct surface *s;
	wl_list_for_each(s, &surfaces, link)
		if (s->output == output && !s->fractional)
			scale_changed(s);
}

static void surface_destroy(struct surface *s)
{
	if (focus == s)
		focus = NULL;
	wl_list_remove(&s->link);
	if (s->fractional)
		wp_fractional_scale_v1_destroy(s->fractional);
	if (s->viewport)
		wp_viewport_destroy(s->viewport);
	if (s->lock)
		ext_session_lock_surface_v1_destroy(s->lock);
	if (s->wl)
		wl_surface_destroy(s->wl);
	buffer_free(&s->buffers[0]);
	buffer_free(&s->buffers[1]);
	free(s);
}

/* odpojeny vystup: jeho zamykaci plocha uz nema kde byt */
void lwl_lock_output_gone(int output)
{
	struct surface *s, *tmp;
	wl_list_for_each_safe(s, tmp, &surfaces, link)
		if (s->output == output)
			surface_destroy(s);
}

static void repeat_stop(void);

static void destroy_all(void)
{
	struct surface *s, *tmp;
	repeat_stop();
	if (compose)
		xkb_compose_state_reset(compose);
	secret_clear();
	wl_list_for_each_safe(s, tmp, &surfaces, link)
		surface_destroy(s);
	if (keyboard) {
		wl_keyboard_release(keyboard);
		keyboard = NULL;
	}
	if (spare_timer) {
		g_source_remove(spare_timer);
		spare_timer = 0;
	}
}

/* ---- heslo ---- */

static void secret_clear(void)
{
	explicit_bzero(secret, sizeof secret);
	secret_len = 0;
}

static int secret_chars(void)
{
	int n = 0;
	for (size_t i = 0; i < secret_len; i++)
		n += ((unsigned char)secret[i] & 0xc0) != 0x80;
	return n;
}

static void secret_drop_last(void)
{
	while (secret_len > 0) {
		unsigned char c = (unsigned char)secret[--secret_len];
		secret[secret_len] = 0;
		if ((c & 0xc0) != 0x80)
			break;
	}
}

/* Znak, ktery xkbcommon prave zapsal na konec hesla (n bajtu, vraci jako snprintf), se prijme;
 * ridici znaky (Tab, Enter) a plny buffer nic nepridaji. */
static bool secret_take(int n)
{
	char *end = secret + secret_len;
	size_t room = sizeof secret - secret_len;
	if (n <= 0 || (size_t)n >= room || (unsigned char)end[0] < 0x20 || end[0] == 0x7f) {
		explicit_bzero(end, room);
		return false;
	}
	secret_len += (size_t)n;
	return true;
}

static bool secret_append(xkb_keycode_t code)
{
	return secret_take(xkb_state_key_get_utf8(xkb_state, code, secret + secret_len, sizeof secret - secret_len));
}

static bool secret_append_composed(void)
{
	return secret_take(xkb_compose_state_get_utf8(compose, secret + secret_len, sizeof secret - secret_len));
}

LWL_EXPORT int lwl_lock_secret(int on)
{
	/* mimo swap; kdyz mlock nejde (RLIMIT_MEMLOCK), heslo funguje dal */
	if (on && !secret_locked)
		secret_locked = mlock(secret, sizeof secret) == 0;
	secret_on = on != 0;
	secret_clear();
	return secret_locked;
}

LWL_EXPORT int lwl_lock_secret_length(void)
{
	return secret_chars();
}

LWL_EXPORT void lwl_lock_secret_clear(void)
{
	secret_clear();
}

/* Ramec pro luxos-auth: delka (uint32, poradi bajtu stroje) a bajty hesla; pak buffer smazat. */
LWL_EXPORT int lwl_lock_secret_write(int fd)
{
	uint32_t len = (uint32_t)secret_len;
	char head[4];
	memcpy(head, &len, 4);
	const char *parts[2] = {head, secret};
	size_t sizes[2] = {4, secret_len};
	bool ok = true;
	for (int i = 0; i < 2 && ok; i++) {
		size_t done = 0;
		while (done < sizes[i]) {
			ssize_t n = write(fd, parts[i] + done, sizes[i] - done);
			if (n < 0 && errno == EINTR)
				continue;
			if (n <= 0) {
				ok = false;
				break;
			}
			done += (size_t)n;
		}
	}
	secret_clear();
	return ok;
}

/* ---- klavesnice ---- */

/* Kody rozlozeni z nazvu symbolu keymapy. libxkbcommon ho zapisuje jako "pc_cz_us_2_inet(evdev)"
 * (starsi zapis "pc+cz+us:2+inet(evdev)"): druhy dil je skupina 1, dil s cislem za sebou je skupina N.
 * Skutecny keymap od kompozitoru je jediny spolehlivy zdroj; nazvy rozlozeni ("Czech") jsou na stitek dlouhe. */
static void parse_layouts(void)
{
	char *tokens[32];
	int n = 0;
	layout_count = 0;
	memset(layout_codes, 0, sizeof layout_codes);
	char *text = xkb_keymap_get_as_string(keymap, XKB_KEYMAP_FORMAT_TEXT_V1);
	char *start = text ? strstr(text, "xkb_symbols \"") : NULL;
	char *end = start ? strchr(start + 13, '"') : NULL;
	if (end) {
		*end = 0;
		/* oddelovace mimo zavorky (varianta muze mit podtrzitko: colemak_dh) */
		int depth = 0;
		char *tok = start + 13;
		for (char *c = tok; ; c++) {
			if (*c == '(')
				depth++;
			else if (*c == ')')
				depth--;
			else if (*c == 0 || (depth == 0 && (*c == '_' || *c == '+' || *c == ':'))) {
				bool last = *c == 0;
				*c = 0;
				if (n < 32)
					tokens[n++] = tok;
				if (last)
					break;
				tok = c + 1;
			}
		}
		for (int i = 1; i < n; i++) {
			int group = 0;
			if (i + 1 < n && tokens[i + 1][0] >= '1' && tokens[i + 1][0] <= '9')
				group = atoi(tokens[i + 1]);
			else if (i == 1)
				group = 1;
			/* volby s cislem skupiny (level3(...):2) prichazeji az za rozlozenimi */
			if (group < 1 || group > LAYOUTS_MAX || layout_codes[group - 1][0])
				continue;
			char *paren = strchr(tokens[i], '(');
			if (paren)
				*paren = 0;
			for (int k = 0; tokens[i][k] && k < 15; k++)
				layout_codes[group - 1][k] = (char)(tokens[i][k] >= 'a' && tokens[i][k] <= 'z' ? tokens[i][k] - 32 : tokens[i][k]);
			if (group > layout_count)
				layout_count = group;
		}
	}
	free(text);
	int count = (int)xkb_keymap_num_layouts(keymap);
	if (count < layout_count || layout_count == 0)
		layout_count = count < LAYOUTS_MAX ? count : LAYOUTS_MAX;
	/* nerozpoznane: prvni slovo nazvu rozlozeni */
	for (int i = 0; i < layout_count; i++) {
		if (layout_codes[i][0])
			continue;
		const char *name = xkb_keymap_layout_get_name(keymap, (xkb_layout_index_t)i);
		snprintf(layout_codes[i], sizeof layout_codes[i], "%.*s", name ? (int)strcspn(name, " (") : 0, name ? name : "");
	}
}

/* Caps Lock a rozlozeni: udalost jen pri zmene (a po vstupu na plochu) */
static void keyboard_state(bool force)
{
	if (!xkb_state)
		return;
	int caps = xkb_state_mod_name_is_active(xkb_state, XKB_MOD_NAME_CAPS, XKB_STATE_MODS_LOCKED) > 0;
	int group = (int)xkb_state_serialize_layout(xkb_state, XKB_STATE_LAYOUT_EFFECTIVE);
	if (!force && caps == caps_shown && group == group_shown)
		return;
	caps_shown = caps;
	group_shown = group;
	lwl_emit(LWL_KEYBOARD, focus ? focus->id : 0, caps, group);
}

LWL_EXPORT int lwl_lock_caps(void)
{
	return caps_shown > 0;
}

LWL_EXPORT int lwl_lock_layout(void)
{
	return group_shown > 0 ? group_shown : 0;
}

LWL_EXPORT int lwl_lock_layout_count(void)
{
	return layout_count;
}

LWL_EXPORT const char *lwl_lock_layout_code(int group)
{
	return group >= 0 && group < layout_count ? layout_codes[group] : "";
}

/* Tabulka Compose podle locale (vcetne ~/.XCompose); heslo je vzdy UTF-8, takze bez UTF-8 locale
 * plati C.UTF-8 (en_US.UTF-8/Compose). Bez tabulky mrtve klavesy jen nic nenapisou. */
static void compose_setup(void)
{
	if (compose) {
		xkb_compose_state_reset(compose);
		return;
	}
	const char *names[] = {"LC_ALL", "LC_CTYPE", "LANG"};
	const char *locale = NULL;
	for (int i = 0; i < 3 && !locale; i++) {
		const char *v = getenv(names[i]);
		if (v && *v)
			locale = v;
	}
	if (!locale || !(strstr(locale, "UTF-8") || strstr(locale, "utf8")))
		locale = "C.UTF-8";
	compose_table = xkb_compose_table_new_from_locale(xkb, locale, XKB_COMPOSE_COMPILE_NO_FLAGS);
	if (!compose_table)
		compose_table = xkb_compose_table_new_from_locale(xkb, "C.UTF-8", XKB_COMPOSE_COMPILE_NO_FLAGS);
	if (compose_table)
		compose = xkb_compose_state_new(compose_table, XKB_COMPOSE_STATE_NO_FLAGS);
}

static void kb_keymap(void *data, struct wl_keyboard *kb, uint32_t format, int32_t fd, uint32_t size)
{
	(void)data; (void)kb;
	if (format != WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1) {
		close(fd);
		return;
	}
	char *text = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
	close(fd);
	if (text == MAP_FAILED)
		return;
	if (!xkb)
		xkb = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	struct xkb_keymap *map = xkb ? xkb_keymap_new_from_buffer(xkb, text, strnlen(text, size),
		XKB_KEYMAP_FORMAT_TEXT_V1, XKB_KEYMAP_COMPILE_NO_FLAGS) : NULL;
	munmap(text, size);
	if (!map)
		return;
	xkb_state_unref(xkb_state);
	xkb_keymap_unref(keymap);
	keymap = map;
	xkb_state = xkb_state_new(map);
	repeat_stop();
	compose_setup();
	parse_layouts();
	keyboard_state(true);
}

static void kb_enter(void *data, struct wl_keyboard *kb, uint32_t serial, struct wl_surface *wl, struct wl_array *keys)
{
	struct surface *s;
	(void)data; (void)kb; (void)serial; (void)keys;
	focus = NULL;
	wl_list_for_each(s, &surfaces, link)
		if (s->wl == wl)
			focus = s;
	keyboard_state(true);
}

static void kb_leave(void *data, struct wl_keyboard *kb, uint32_t serial, struct wl_surface *wl)
{
	(void)data; (void)kb; (void)serial; (void)wl;
	focus = NULL;
	repeat_stop();
}

/* Stisk v rezimu hesla; vraci, zda se klavesa pri drzeni opakuje (znak nebo Backspace). */
static bool secret_key(xkb_keycode_t code, xkb_keysym_t sym)
{
	bool ctrl = xkb_state_mod_name_is_active(xkb_state, XKB_MOD_NAME_CTRL, XKB_STATE_MODS_EFFECTIVE) > 0;
	bool repeats = false;
	if (sym == XKB_KEY_Return || sym == XKB_KEY_KP_Enter || sym == XKB_KEY_Escape) {
		if (compose)
			xkb_compose_state_reset(compose);
		if (sym == XKB_KEY_Escape)
			secret_clear();
	} else if (compose && !ctrl && xkb_compose_state_feed(compose, sym) == XKB_COMPOSE_FEED_ACCEPTED &&
		xkb_compose_state_get_status(compose) != XKB_COMPOSE_NOTHING) {
		/* rozepsana sekvence nebo zrusena (dead_caron + Backspace): nic nepridat */
		if (xkb_compose_state_get_status(compose) == XKB_COMPOSE_COMPOSED)
			secret_append_composed();
		if (xkb_compose_state_get_status(compose) != XKB_COMPOSE_COMPOSING)
			xkb_compose_state_reset(compose);
		sym = 0;
	} else if (sym == XKB_KEY_BackSpace) {
		if (ctrl)
			secret_clear();
		else
			secret_drop_last();
		repeats = !ctrl;
	} else if (ctrl && (sym == XKB_KEY_u || sym == XKB_KEY_U)) {
		secret_clear();
		sym = XKB_KEY_Escape;
	} else if (!ctrl && secret_append(code)) {
		sym = 0;
		repeats = true;
	}
	lwl_emit(LWL_KEY, focus->id, (int)sym, secret_chars());
	return repeats && xkb_keymap_key_repeats(keymap, code);
}

static void repeat_stop(void)
{
	if (repeat_timer)
		g_source_remove(repeat_timer);
	repeat_timer = 0;
	repeat_code = 0;
}

static gboolean repeat_tick(gpointer data)
{
	bool first = data != NULL;
	if (!focus || !xkb_state || !secret_on || !secret_key(repeat_code, xkb_state_key_get_one_sym(xkb_state, repeat_code))) {
		repeat_timer = 0;
		repeat_code = 0;
		return G_SOURCE_REMOVE;
	}
	if (!first)
		return G_SOURCE_CONTINUE;
	/* po prodleve uz v rytmu repeat_info */
	repeat_timer = g_timeout_add(1000 / repeat_rate, repeat_tick, NULL);
	return G_SOURCE_REMOVE;
}

static void kb_key(void *data, struct wl_keyboard *kb, uint32_t serial, uint32_t time, uint32_t key, uint32_t state)
{
	(void)data; (void)kb; (void)serial; (void)time;
	xkb_keycode_t code = key + 8;
	if (state != WL_KEYBOARD_KEY_STATE_PRESSED) {
		if (code == repeat_code)
			repeat_stop();
		return;
	}
	/* klavesy pro okna GTK na sdilenem spojeni sem nepatri */
	if (!focus || !xkb_state)
		return;
	repeat_stop();
	xkb_keysym_t sym = xkb_state_key_get_one_sym(xkb_state, code);
	if (!secret_on) {
		lwl_emit(LWL_KEY, focus->id, (int)sym, (int)xkb_state_key_get_utf32(xkb_state, code));
		return;
	}
	if (secret_key(code, sym) && repeat_rate > 0) {
		repeat_code = code;
		repeat_timer = g_timeout_add((guint)repeat_delay, repeat_tick, GINT_TO_POINTER(1));
	}
}

static void kb_modifiers(void *data, struct wl_keyboard *kb, uint32_t serial, uint32_t depressed, uint32_t latched,
	uint32_t locked_mods, uint32_t group)
{
	(void)data; (void)kb; (void)serial;
	if (xkb_state) {
		xkb_state_update_mask(xkb_state, depressed, latched, locked_mods, 0, 0, group);
		keyboard_state(false);
	}
}

static void kb_repeat(void *data, struct wl_keyboard *kb, int32_t rate, int32_t delay)
{
	(void)data; (void)kb;
	/* rate 0 = kompozitor opakovani nechce */
	repeat_rate = rate > 0 && rate <= 1000 ? rate : 0;
	repeat_delay = delay > 0 ? delay : 600;
	if (!repeat_rate)
		repeat_stop();
}

static const struct wl_keyboard_listener keyboard_listener = {
	.keymap = kb_keymap,
	.enter = kb_enter,
	.leave = kb_leave,
	.key = kb_key,
	.modifiers = kb_modifiers,
	.repeat_info = kb_repeat,
};

/* klavesnici jen kdyz jsou zamykaci plochy a seat ji ma */
void lwl_lock_keyboard_update(void)
{
	bool want = lwl.seat && (lwl.seat_caps & WL_SEAT_CAPABILITY_KEYBOARD) && !wl_list_empty(&surfaces);
	if (want && !keyboard) {
		keyboard = wl_seat_get_keyboard(lwl.seat);
		wl_keyboard_add_listener(keyboard, &keyboard_listener, NULL);
	} else if (!want && keyboard) {
		wl_keyboard_release(keyboard);
		keyboard = NULL;
		focus = NULL;
	}
}

/* ---- zamek ---- */

static void lock_locked(void *data, struct ext_session_lock_v1 *l)
{
	(void)data; (void)l;
	locked = true;
	lwl_emit(LWL_LOCKED, 0, 0, 0);
}

static void lock_finished(void *data, struct ext_session_lock_v1 *l)
{
	(void)data;
	destroy_all();
	ext_session_lock_v1_destroy(l);
	lock = NULL;
	locked = false;
	lwl_emit(LWL_LOCK_FINISHED, 0, 0, 0);
}

static const struct ext_session_lock_v1_listener lock_listener = {
	.locked = lock_locked,
	.finished = lock_finished,
};

bool lwl_lock_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	(void)version;
	if (strcmp(interface, wp_fractional_scale_manager_v1_interface.name) == 0)
		fractional_manager = wl_registry_bind(registry, name, &wp_fractional_scale_manager_v1_interface, 1);
	else if (strcmp(interface, wp_viewporter_interface.name) == 0)
		viewporter = wl_registry_bind(registry, name, &wp_viewporter_interface, 1);
	else if (strcmp(interface, ext_session_lock_manager_v1_interface.name) == 0)
		lwl.lock_manager = wl_registry_bind(registry, name, &ext_session_lock_manager_v1_interface, 1);
	else
		return false;
	return true;
}

void lwl_lock_reset(void)
{
	destroy_all();
	/* odpojeni zamceneho klienta nechava obrazovku zamcenou (tak to ma byt) */
	if (lock)
		ext_session_lock_v1_destroy(lock);
	lock = NULL;
	locked = false;
	if (lwl.lock_manager)
		ext_session_lock_manager_v1_destroy(lwl.lock_manager);
	if (fractional_manager)
		wp_fractional_scale_manager_v1_destroy(fractional_manager);
	if (viewporter)
		wp_viewporter_destroy(viewporter);
	fractional_manager = NULL;
	viewporter = NULL;
	xkb_compose_state_unref(compose);
	xkb_compose_table_unref(compose_table);
	compose = NULL;
	compose_table = NULL;
	xkb_state_unref(xkb_state);
	xkb_keymap_unref(keymap);
	xkb_context_unref(xkb);
	xkb_state = NULL;
	keymap = NULL;
	xkb = NULL;
	secret_clear();
	secret_on = false;
	caps_shown = group_shown = -1;
}

LWL_EXPORT int lwl_lock(void)
{
	if (!lwl.lock_manager || lock)
		return 0;
	lock = ext_session_lock_manager_v1_lock(lwl.lock_manager);
	ext_session_lock_v1_add_listener(lock, &lock_listener, NULL);
	wl_display_flush(lwl.display);
	return 1;
}

LWL_EXPORT int lwl_lock_surface(int output)
{
	struct lwl_output *o = lwl_find_output(output);
	if (!lock || !o || o->dead || !lwl.compositor || !lwl.shm)
		return 0;
	struct surface *s = calloc(1, sizeof *s);
	if (!s)
		return 0;
	s->id = lwl_new_id();
	s->output = output;
	s->wl = wl_compositor_create_surface(lwl.compositor);
	s->scale = 120;
	/* zlomkove meritko jen s viewporterem (bufer se na logickou velikost zmensi pres wp_viewport) */
	if (fractional_manager && viewporter) {
		s->fractional = wp_fractional_scale_manager_v1_get_fractional_scale(fractional_manager, s->wl);
		wp_fractional_scale_v1_add_listener(s->fractional, &fractional_listener, s);
		s->viewport = wp_viewporter_get_viewport(viewporter, s->wl);
	}
	s->lock = ext_session_lock_v1_get_lock_surface(lock, s->wl, o->wl);
	ext_session_lock_surface_v1_add_listener(s->lock, &surface_listener, s);
	wl_list_insert(surfaces.prev, &s->link);
	lwl_lock_keyboard_update();
	wl_display_flush(lwl.display);
	return s->id;
}

LWL_EXPORT int lwl_unlock(void)
{
	if (!lock)
		return 0;
	destroy_all();
	/* unlock_and_destroy jen po "locked"; pred nim zadost jen zrusit */
	if (locked)
		ext_session_lock_v1_unlock_and_destroy(lock);
	else
		ext_session_lock_v1_destroy(lock);
	lock = NULL;
	locked = false;
	wl_display_roundtrip(lwl.display);
	return 1;
}

LWL_EXPORT int lwl_surface_width(int id)
{
	struct surface *s = find(id);
	return s ? s->width : 0;
}

LWL_EXPORT int lwl_surface_height(int id)
{
	struct surface *s = find(id);
	return s ? s->height : 0;
}

/* Meritko plochy v 1/120 (240 = 2x) a velikost buferu v pixelech: LSL kresli do buferu
 * s cairo_scale(meritko) v logickych jednotkach configure. */
LWL_EXPORT int lwl_surface_scale(int id)
{
	struct surface *s = find(id);
	return s ? surface_scale(s) : 120;
}

static int scaled(int size, int scale)
{
	return (size * scale + 60) / 120;
}

LWL_EXPORT int lwl_surface_buffer_width(int id)
{
	struct surface *s = find(id);
	return s ? scaled(s->width, surface_scale(s)) : 0;
}

LWL_EXPORT int lwl_surface_buffer_height(int id)
{
	struct surface *s = find(id);
	return s ? scaled(s->height, surface_scale(s)) : 0;
}

/* Volny bufer velikosti posledniho configure v pixelech (ARGB32, stride = sirka * 4); NULL pred configure. */
LWL_EXPORT void *lwl_surface_begin(int id)
{
	struct surface *s = find(id);
	if (!s || s->width <= 0 || s->height <= 0)
		return NULL;
	int width = scaled(s->width, surface_scale(s));
	int height = scaled(s->height, surface_scale(s));
	/* posledni nakresleny bufer pouzit znovu, kdyz ho kompozitor uz vratil */
	for (int pass = 0; pass < 2; pass++) {
		for (int i = 0; i < 2; i++) {
			struct buffer *b = &s->buffers[i];
			if (b->busy || (pass == 0 && b != s->current))
				continue;
			if (b->wl && (b->width != width || b->height != height))
				buffer_free(b);
			if (!b->wl && !buffer_alloc(s, b, width, height))
				return NULL;
			s->drawing = b;
			return b->data;
		}
	}
	return NULL;
}

LWL_EXPORT int lwl_surface_commit(int id)
{
	struct surface *s = find(id);
	if (!s || !s->drawing)
		return 0;
	struct buffer *b = s->drawing;
	int scale = surface_scale(s);
	s->drawing = NULL;
	s->current = b;
	s->drawn_scale = scale;
	b->busy = true;
	if (s->viewport) {
		wp_viewport_set_destination(s->viewport, s->width, s->height);
	} else if (wl_proxy_get_version((struct wl_proxy *)lwl.compositor) >= 3) {
		wl_surface_set_buffer_scale(s->wl, scale / 120);
	}
	wl_surface_attach(s->wl, b->wl, 0, 0);
	wl_surface_damage_buffer(s->wl, 0, 0, b->width, b->height);
	wl_surface_commit(s->wl);
	wl_display_flush(lwl.display);
	return 1;
}
