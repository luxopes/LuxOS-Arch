/* Jadro libluxos-wl: spojeni, registry, vystupy, doruceni udalosti, hlavni smycka GLib. */
#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <glib.h>
#include "internal.h"
#include "xdg-output-unstable-v1-client-protocol.h"

struct lwl_state lwl;

struct event { int kind, handle, a, b; };

static lwl_handler handler;
static void *handler_user;
static struct event *events;
static size_t events_len, events_cap;
static bool flushing;
static guint flush_idle;
static GSource *source;
static char *bind_only;

int lwl_new_id(void)
{
	return ++lwl.next_id;
}

char *lwl_strdup(const char *text)
{
	return strdup(text ? text : "");
}

void lwl_set_string(char **slot, const char *text)
{
	free(*slot);
	*slot = lwl_strdup(text);
}

uint32_t lwl_now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

int lwl_shm_fd(size_t size)
{
	int fd = memfd_create("luxos-wl", MFD_CLOEXEC | MFD_ALLOW_SEALING);
	if (fd < 0)
		return -1;
	if (ftruncate(fd, (off_t)size) < 0) {
		close(fd);
		return -1;
	}
	return fd;
}

/* ---- doruceni udalosti ---- */

static gboolean flush_cb(gpointer data)
{
	(void)data;
	flush_idle = 0;
	lwl_flush();
	return G_SOURCE_REMOVE;
}

void lwl_emit(int kind, int handle, int a, int b)
{
	if (events_len == events_cap) {
		size_t cap = events_cap ? events_cap * 2 : 32;
		struct event *grown = realloc(events, cap * sizeof *events);
		if (!grown)
			return;
		events = grown;
		events_cap = cap;
	}
	events[events_len++] = (struct event){kind, handle, a, b};
	/* sdilene spojeni GTK dispatchuje GDK: doruceni az po jeho kole */
	if (!flushing && !flush_idle)
		flush_idle = g_idle_add_full(G_PRIORITY_HIGH, flush_cb, NULL, NULL);
}

static void sweep_outputs(void)
{
	struct lwl_output *o, *tmp;
	wl_list_for_each_safe(o, tmp, &lwl.outputs, link) {
		if (!o->dead)
			continue;
		lwl_lock_output_gone(o->id);
		wl_list_remove(&o->link);
		if (o->xdg)
			zxdg_output_v1_destroy(o->xdg);
		if (o->wl)
			wl_output_release(o->wl);
		free(o->name);
		free(o->description);
		free(o);
	}
}

void lwl_sweep(void)
{
	sweep_outputs();
	lwl_toplevel_sweep();
	lwl_heads_sweep();
}

void lwl_flush(void)
{
	if (flushing)
		return;
	flushing = true;
	/* obsluha muze vyvolat dalsi udalosti, berou se ve stejnem kole */
	for (size_t i = 0; i < events_len; i++) {
		struct event e = events[i];
		if (handler)
			handler(handler_user, e.kind, e.handle, e.a, e.b);
	}
	events_len = 0;
	if (events_cap > 256) {
		free(events);
		events = NULL;
		events_cap = 0;
	}
	lwl_sweep();
	flushing = false;
	if (lwl.display)
		wl_display_flush(lwl.display);
}

LWL_EXPORT void lwl_set_handler(lwl_handler cb, void *user)
{
	handler = cb;
	handler_user = user;
}

/* ---- vystupy ---- */

struct lwl_output *lwl_find_output(int id)
{
	struct lwl_output *o;
	wl_list_for_each(o, &lwl.outputs, link)
		if (o->id == id)
			return o;
	return NULL;
}

static void output_geometry(void *data, struct wl_output *wl, int32_t x, int32_t y, int32_t pw, int32_t ph,
	int32_t subpixel, const char *make, const char *model, int32_t transform)
{
	struct lwl_output *o = data;
	(void)wl; (void)pw; (void)ph; (void)subpixel; (void)make; (void)model; (void)transform;
	if (!o->xdg) {
		o->x = x;
		o->y = y;
	}
}

static void output_mode(void *data, struct wl_output *wl, uint32_t flags, int32_t width, int32_t height, int32_t refresh)
{
	struct lwl_output *o = data;
	(void)wl; (void)refresh;
	if (flags & WL_OUTPUT_MODE_CURRENT) {
		o->width = width;
		o->height = height;
	}
}

static void output_done(void *data, struct wl_output *wl)
{
	struct lwl_output *o = data;
	(void)wl;
	if (!o->announced) {
		o->announced = true;
		lwl_emit(LWL_OUTPUT_NEW, o->id, 0, 0);
	} else {
		lwl_lock_output_changed(o->id);
	}
}

static void output_scale(void *data, struct wl_output *wl, int32_t factor)
{
	struct lwl_output *o = data;
	(void)wl;
	o->scale = factor;
}

static void output_name(void *data, struct wl_output *wl, const char *name)
{
	struct lwl_output *o = data;
	(void)wl;
	lwl_set_string(&o->name, name);
}

static void output_description(void *data, struct wl_output *wl, const char *description)
{
	struct lwl_output *o = data;
	(void)wl;
	lwl_set_string(&o->description, description);
}

static const struct wl_output_listener output_listener = {
	.geometry = output_geometry,
	.mode = output_mode,
	.done = output_done,
	.scale = output_scale,
	.name = output_name,
	.description = output_description,
};

/* xdg-output v3: zmeny plati az s wl_output.done (vlastni done je zastarale) */
static void xdg_position(void *data, struct zxdg_output_v1 *xdg, int32_t x, int32_t y)
{
	struct lwl_output *o = data;
	(void)xdg;
	o->x = x;
	o->y = y;
}

static void xdg_size(void *data, struct zxdg_output_v1 *xdg, int32_t width, int32_t height)
{
	(void)data; (void)xdg; (void)width; (void)height;
}

static void xdg_done(void *data, struct zxdg_output_v1 *xdg)
{
	(void)data; (void)xdg;
}

static void xdg_name(void *data, struct zxdg_output_v1 *xdg, const char *name)
{
	struct lwl_output *o = data;
	(void)xdg;
	if (!*o->name)
		lwl_set_string(&o->name, name);
}

static void xdg_description(void *data, struct zxdg_output_v1 *xdg, const char *description)
{
	(void)data; (void)xdg; (void)description;
}

static const struct zxdg_output_v1_listener xdg_listener = {
	.logical_position = xdg_position,
	.logical_size = xdg_size,
	.done = xdg_done,
	.name = xdg_name,
	.description = xdg_description,
};

static void watch_xdg_output(struct lwl_output *o)
{
	if (o->xdg || !lwl.xdg_outputs)
		return;
	o->xdg = zxdg_output_manager_v1_get_xdg_output(lwl.xdg_outputs, o->wl);
	zxdg_output_v1_add_listener(o->xdg, &xdg_listener, o);
}

static void add_output(struct wl_registry *registry, uint32_t name, uint32_t version)
{
	struct lwl_output *o = calloc(1, sizeof *o);
	if (!o)
		return;
	o->id = lwl_new_id();
	o->global = name;
	o->scale = 1;
	o->name = lwl_strdup("");
	o->description = lwl_strdup("");
	/* v4 kvuli jmenu vystupu (DP-1); starsi kompozitory jen bez jmena */
	o->wl = wl_registry_bind(registry, name, &wl_output_interface, version < 4 ? version : 4);
	wl_output_add_listener(o->wl, &output_listener, o);
	wl_list_insert(lwl.outputs.prev, &o->link);
	watch_xdg_output(o);
}

LWL_EXPORT int lwl_output_count(void)
{
	int n = 0;
	struct lwl_output *o;
	wl_list_for_each(o, &lwl.outputs, link)
		n += o->announced && !o->dead;
	return n;
}

LWL_EXPORT int lwl_output_at(int index)
{
	struct lwl_output *o;
	wl_list_for_each(o, &lwl.outputs, link)
		if (o->announced && !o->dead && index-- == 0)
			return o->id;
	return 0;
}

#define OUTPUT_GETTER(field, type, fallback) \
	LWL_EXPORT type lwl_output_##field(int id) \
	{ \
		struct lwl_output *o = lwl_find_output(id); \
		return o ? o->field : fallback; \
	}
OUTPUT_GETTER(name, const char *, "")
OUTPUT_GETTER(description, const char *, "")
OUTPUT_GETTER(x, int, 0)
OUTPUT_GETTER(y, int, 0)
OUTPUT_GETTER(width, int, 0)
OUTPUT_GETTER(height, int, 0)
OUTPUT_GETTER(scale, int, 1)

/* ---- seat ---- */

static void seat_capabilities(void *data, struct wl_seat *seat, uint32_t caps)
{
	(void)data; (void)seat;
	lwl.seat_caps = caps;
	lwl_lock_keyboard_update();
}

static void seat_name(void *data, struct wl_seat *seat, const char *name)
{
	(void)data; (void)seat; (void)name;
}

static const struct wl_seat_listener seat_listener = {
	.capabilities = seat_capabilities,
	.name = seat_name,
};

/* ---- registry ---- */

static bool wanted(const char *interface)
{
	if (!bind_only)
		return true;
	size_t n = strlen(interface);
	for (const char *p = bind_only; (p = strstr(p, interface)); p += n)
		if ((p == bind_only || p[-1] == ',') && (p[n] == ',' || p[n] == 0))
			return true;
	return false;
}

static void global_add(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	(void)data;
	if (!wanted(interface))
		return;
	if (strcmp(interface, wl_compositor_interface.name) == 0) {
		lwl.compositor = wl_registry_bind(registry, name, &wl_compositor_interface, version < 4 ? version : 4);
	} else if (strcmp(interface, wl_shm_interface.name) == 0) {
		lwl.shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (strcmp(interface, wl_seat_interface.name) == 0) {
		if (!lwl.seat) {
			lwl.seat = wl_registry_bind(registry, name, &wl_seat_interface, version < 7 ? version : 7);
			wl_seat_add_listener(lwl.seat, &seat_listener, NULL);
			lwl_clipboard_seat();
		}
	} else if (strcmp(interface, wl_output_interface.name) == 0) {
		add_output(registry, name, version);
	} else if (strcmp(interface, zxdg_output_manager_v1_interface.name) == 0) {
		lwl.xdg_outputs = wl_registry_bind(registry, name, &zxdg_output_manager_v1_interface, version < 3 ? version : 3);
		struct lwl_output *o;
		wl_list_for_each(o, &lwl.outputs, link)
			watch_xdg_output(o);
	} else if (!lwl_toplevel_bind(registry, name, interface, version) &&
		!lwl_lock_bind(registry, name, interface, version) &&
		!lwl_capture_bind(registry, name, interface, version) &&
		!lwl_clipboard_bind(registry, name, interface, version) &&
		!lwl_vkbd_bind(registry, name, interface, version) &&
		!lwl_heads_bind(registry, name, interface, version)) {
		lwl_idle_bind(registry, name, interface, version);
	}
}

static void global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
	struct lwl_output *o;
	(void)data; (void)registry;
	wl_list_for_each(o, &lwl.outputs, link) {
		if (o->global == name && !o->dead) {
			o->dead = true;
			if (o->announced)
				lwl_emit(LWL_OUTPUT_REMOVED, o->id, 0, 0);
		}
	}
}

static const struct wl_registry_listener registry_listener = {
	.global = global_add,
	.global_remove = global_remove,
};

/* ---- vlastni spojeni v hlavni smycce GLib ---- */

struct wl_source {
	GSource base;
	gpointer tag;
	bool reading, failed;
};

static gboolean source_prepare(GSource *base, gint *timeout)
{
	struct wl_source *s = (struct wl_source *)base;
	*timeout = -1;
	if (s->failed)
		return TRUE;
	/* pri pripravenem zdroji s vyssi prioritou (signal) GLib check vynecha: cteni z minule zustava
	 * pripravene a druhy wl_display_prepare_read by wl_display_read_events zablokoval navzdy */
	if (!s->reading) {
		if (wl_display_prepare_read(lwl.display) != 0)
			return TRUE;
		s->reading = true;
	}
	if (wl_display_flush(lwl.display) < 0 && errno != EAGAIN)
		s->failed = true;
	return s->failed;
}

static gboolean source_check(GSource *base)
{
	struct wl_source *s = (struct wl_source *)base;
	if (!s->reading)
		return s->failed;
	s->reading = false;
	if (g_source_query_unix_fd(base, s->tag) & (G_IO_IN | G_IO_ERR | G_IO_HUP)) {
		if (wl_display_read_events(lwl.display) < 0)
			s->failed = true;
		return TRUE;
	}
	wl_display_cancel_read(lwl.display);
	return FALSE;
}

static gboolean source_dispatch(GSource *base, GSourceFunc cb, gpointer data)
{
	struct wl_source *s = (struct wl_source *)base;
	(void)cb; (void)data;
	if (s->failed || wl_display_dispatch_pending(lwl.display) < 0) {
		source = NULL;
		lwl_emit(LWL_DISCONNECTED, 0, 0, 0);
		lwl_flush();
		return G_SOURCE_REMOVE;
	}
	lwl_flush();
	return G_SOURCE_CONTINUE;
}

static void source_finalize(GSource *base)
{
	struct wl_source *s = (struct wl_source *)base;
	if (s->reading && lwl.display)
		wl_display_cancel_read(lwl.display);
	s->reading = false;
}

static GSourceFuncs source_funcs = {
	.prepare = source_prepare,
	.check = source_check,
	.dispatch = source_dispatch,
	.finalize = source_finalize,
};

static int setup(void)
{
	/* zapis do roury schranky, kterou ctenar zavrel, nesmi proces shellu ukoncit */
	signal(SIGPIPE, SIG_IGN);
	wl_list_init(&lwl.outputs);
	lwl.registry = wl_display_get_registry(lwl.display);
	wl_registry_add_listener(lwl.registry, &registry_listener, NULL);
	/* 1. globaly, 2. jejich pocatecni stav (vystupy, okna, hlavy) */
	if (wl_display_roundtrip(lwl.display) < 0 || wl_display_roundtrip(lwl.display) < 0)
		return 0;
	lwl_flush();
	return 1;
}

LWL_EXPORT void lwl_bind_only(const char *interfaces)
{
	free(bind_only);
	bind_only = interfaces ? strdup(interfaces) : NULL;
}

LWL_EXPORT int lwl_connect(const char *name)
{
	if (lwl.display)
		return 1;
	struct wl_display *display = wl_display_connect(name && *name ? name : NULL);
	if (!display)
		return 0;
	lwl.display = display;
	lwl.own = true;
	if (!setup()) {
		lwl_disconnect();
		return 0;
	}
	struct wl_source *s = (struct wl_source *)g_source_new(&source_funcs, sizeof *s);
	s->tag = g_source_add_unix_fd(&s->base, wl_display_get_fd(display), G_IO_IN | G_IO_ERR | G_IO_HUP);
	g_source_set_priority(&s->base, G_PRIORITY_DEFAULT);
	g_source_attach(&s->base, NULL);
	source = &s->base;
	return 1;
}

/* Spojeni GDK: proxy na vychozi fronte, udalosti rozesila zdroj GDK (druhy zdroj nad stejnym
 * soketem by v jednom vlakne uvazl ve wl_display_read_events). */
LWL_EXPORT int lwl_attach(struct wl_display *display)
{
	if (lwl.display)
		return lwl.display == display;
	if (!display)
		return 0;
	lwl.display = display;
	lwl.own = false;
	if (!setup()) {
		lwl_disconnect();
		return 0;
	}
	return 1;
}

LWL_EXPORT int lwl_roundtrip(void)
{
	if (!lwl.display || wl_display_roundtrip(lwl.display) < 0)
		return 0;
	lwl_flush();
	return 1;
}

LWL_EXPORT void lwl_disconnect(void)
{
	if (!lwl.display)
		return;
	if (source) {
		g_source_destroy(source);
		g_source_unref(source);
		source = NULL;
	}
	if (flush_idle) {
		g_source_remove(flush_idle);
		flush_idle = 0;
	}
	events_len = 0;
	lwl_idle_reset();
	lwl_heads_reset();
	lwl_vkbd_reset();
	lwl_clipboard_reset();
	lwl_capture_reset();
	lwl_lock_reset();
	lwl_toplevel_reset();
	struct lwl_output *o;
	wl_list_for_each(o, &lwl.outputs, link)
		o->dead = true;
	sweep_outputs();
	if (lwl.xdg_outputs)
		zxdg_output_manager_v1_destroy(lwl.xdg_outputs);
	if (lwl.seat)
		wl_seat_destroy(lwl.seat);
	if (lwl.shm)
		wl_shm_destroy(lwl.shm);
	if (lwl.compositor)
		wl_compositor_destroy(lwl.compositor);
	if (lwl.registry)
		wl_registry_destroy(lwl.registry);
	struct wl_display *display = lwl.display;
	bool own = lwl.own;
	int next_id = lwl.next_id;
	memset(&lwl, 0, sizeof lwl);
	lwl.next_id = next_id;   /* handly se nepouziji znovu ani po novem pripojeni */
	if (own)
		wl_display_disconnect(display);
	else
		wl_display_flush(display);
}

LWL_EXPORT int lwl_has(const char *interface)
{
	struct { const char *name; const void *proxy; } known[] = {
		{"wl_shm", lwl.shm},
		{"wl_seat", lwl.seat},
		{"zwlr_foreign_toplevel_manager_v1", lwl.wlr_toplevels},
		{"ext_foreign_toplevel_list_v1", lwl.ext_toplevels},
		{"ext_session_lock_manager_v1", lwl.lock_manager},
		{"ext_output_image_capture_source_manager_v1", lwl.output_sources},
		{"ext_foreign_toplevel_image_capture_source_manager_v1", lwl.toplevel_sources},
		{"ext_image_copy_capture_manager_v1", lwl.copy_capture},
		{"ext_data_control_manager_v1", lwl.data_control},
		{"zwp_virtual_keyboard_manager_v1", lwl.vk_manager},
		{"zwlr_output_manager_v1", lwl.output_manager},
		{"ext_idle_notifier_v1", lwl.idle_notifier},
		{"zxdg_output_manager_v1", lwl.xdg_outputs},
	};
	for (size_t i = 0; i < sizeof known / sizeof *known; i++)
		if (strcmp(known[i].name, interface) == 0)
			return known[i].proxy ? (int)wl_proxy_get_version((struct wl_proxy *)known[i].proxy) : 0;
	return 0;
}
