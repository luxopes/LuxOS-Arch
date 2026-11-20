/* Zamceni obrazovky (ext-session-lock-v1): zamykaci plochy s vlastnimi bufery wl_shm (kresli
 * se do nich cairem z LSL) a klavesnice pres xkbcommon pro zadani hesla. Kdyz zamykac spadne,
 * kompozitor nechava obrazovku zamcenou - proto tu neni nic, co by zamek rusilo samo. */
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <xkbcommon/xkbcommon.h>
#include "internal.h"
#include "ext-session-lock-v1-client-protocol.h"

struct buffer {
	struct wl_buffer *wl;
	void *data;
	size_t size;
	int width, height;
	bool busy;
};

struct surface {
	struct wl_list link;
	int id;
	struct wl_surface *wl;
	struct ext_session_lock_surface_v1 *lock;
	int width, height;
	struct buffer buffers[2];
	struct buffer *drawing;
};

static struct ext_session_lock_v1 *lock;
static bool locked;
static struct wl_list surfaces = {&surfaces, &surfaces};

static struct wl_keyboard *keyboard;
static struct xkb_context *xkb;
static struct xkb_keymap *keymap;
static struct xkb_state *xkb_state;
static struct surface *focus;

/* ---- bufery ---- */

static void buffer_release(void *data, struct wl_buffer *wl)
{
	struct buffer *b = data;
	(void)wl;
	b->busy = false;
}

static const struct wl_buffer_listener buffer_listener = {.release = buffer_release};

static void buffer_free(struct buffer *b)
{
	if (b->wl)
		wl_buffer_destroy(b->wl);
	if (b->data)
		munmap(b->data, b->size);
	memset(b, 0, sizeof *b);
}

static bool buffer_alloc(struct buffer *b, int width, int height)
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

static void surface_destroy(struct surface *s)
{
	if (focus == s)
		focus = NULL;
	wl_list_remove(&s->link);
	if (s->lock)
		ext_session_lock_surface_v1_destroy(s->lock);
	if (s->wl)
		wl_surface_destroy(s->wl);
	buffer_free(&s->buffers[0]);
	buffer_free(&s->buffers[1]);
	free(s);
}

static void destroy_all(void)
{
	struct surface *s, *tmp;
	wl_list_for_each_safe(s, tmp, &surfaces, link)
		surface_destroy(s);
	if (keyboard) {
		wl_keyboard_release(keyboard);
		keyboard = NULL;
	}
}

/* ---- klavesnice ---- */

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
}

static void kb_enter(void *data, struct wl_keyboard *kb, uint32_t serial, struct wl_surface *wl, struct wl_array *keys)
{
	struct surface *s;
	(void)data; (void)kb; (void)serial; (void)keys;
	focus = NULL;
	wl_list_for_each(s, &surfaces, link)
		if (s->wl == wl)
			focus = s;
}

static void kb_leave(void *data, struct wl_keyboard *kb, uint32_t serial, struct wl_surface *wl)
{
	(void)data; (void)kb; (void)serial; (void)wl;
	focus = NULL;
}

static void kb_key(void *data, struct wl_keyboard *kb, uint32_t serial, uint32_t time, uint32_t key, uint32_t state)
{
	(void)data; (void)kb; (void)serial; (void)time;
	/* klavesy pro okna GTK na sdilenem spojeni sem nepatri */
	if (!focus || !xkb_state || state != WL_KEYBOARD_KEY_STATE_PRESSED)
		return;
	xkb_keysym_t sym = xkb_state_key_get_one_sym(xkb_state, key + 8);
	uint32_t cp = xkb_state_key_get_utf32(xkb_state, key + 8);
	lwl_emit(LWL_KEY, focus->id, (int)sym, (int)cp);
}

static void kb_modifiers(void *data, struct wl_keyboard *kb, uint32_t serial, uint32_t depressed, uint32_t latched,
	uint32_t locked_mods, uint32_t group)
{
	(void)data; (void)kb; (void)serial;
	if (xkb_state)
		xkb_state_update_mask(xkb_state, depressed, latched, locked_mods, 0, 0, group);
}

static void kb_repeat(void *data, struct wl_keyboard *kb, int32_t rate, int32_t delay)
{
	(void)data; (void)kb; (void)rate; (void)delay;
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
	if (strcmp(interface, ext_session_lock_manager_v1_interface.name) != 0)
		return false;
	lwl.lock_manager = wl_registry_bind(registry, name, &ext_session_lock_manager_v1_interface, 1);
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
	xkb_state_unref(xkb_state);
	xkb_keymap_unref(keymap);
	xkb_context_unref(xkb);
	xkb_state = NULL;
	keymap = NULL;
	xkb = NULL;
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
	s->wl = wl_compositor_create_surface(lwl.compositor);
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

/* Volny bufer velikosti posledniho configure (ARGB32, stride = sirka * 4); NULL pred configure. */
LWL_EXPORT void *lwl_surface_begin(int id)
{
	struct surface *s = find(id);
	if (!s || s->width <= 0 || s->height <= 0)
		return NULL;
	for (int i = 0; i < 2; i++) {
		struct buffer *b = &s->buffers[i];
		if (b->busy)
			continue;
		if (b->wl && (b->width != s->width || b->height != s->height))
			buffer_free(b);
		if (!b->wl && !buffer_alloc(b, s->width, s->height))
			return NULL;
		s->drawing = b;
		return b->data;
	}
	return NULL;
}

LWL_EXPORT int lwl_surface_commit(int id)
{
	struct surface *s = find(id);
	if (!s || !s->drawing)
		return 0;
	struct buffer *b = s->drawing;
	s->drawing = NULL;
	b->busy = true;
	wl_surface_attach(s->wl, b->wl, 0, 0);
	wl_surface_damage_buffer(s->wl, 0, 0, b->width, b->height);
	wl_surface_commit(s->wl);
	wl_display_flush(lwl.display);
	return 1;
}
