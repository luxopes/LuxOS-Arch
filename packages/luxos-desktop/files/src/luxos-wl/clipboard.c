/* Schranka bez okna (ext-data-control-v1): nastaveni textu, sledovani vyberu a cteni nabidky.
 * Zapis i cteni roury jdou pres GLib bez blokovani - cteme-li vlastni vyber, pise i cte tentyz
 * proces a blokujici zapis by uvazl na plne roure. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <glib.h>
#include <glib-unix.h>
#include "internal.h"
#include "ext-data-control-v1-client-protocol.h"

#define MAX_READ (16 << 20)

static const char *text_types[] = {"text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "TEXT", "STRING"};

struct offer {
	struct ext_data_control_offer_v1 *wl;
	GString *types;     /* "a\nb\n" */
};

/* nas zdroj: text patri zdroji, ne vyberu (pozdni send stareho zdroje dostane jeho text) */
struct source {
	struct ext_data_control_source_v1 *wl;
	int primary;
	char *text;
};

struct selection {
	struct offer *offer;
	struct source *source;
};

struct writer {
	char *text;
	size_t len, done;
	int fd;
};

struct request {
	struct wl_list link;
	int id;
	int fd;
	guint watch;
	GString *data;
	bool done;
};

static struct ext_data_control_device_v1 *device;
static struct selection selections[2];   /* 0 schranka, 1 primarni vyber */
static struct wl_list requests = {&requests, &requests};

static void offer_free(struct offer *o)
{
	if (!o)
		return;
	ext_data_control_offer_v1_destroy(o->wl);
	g_string_free(o->types, TRUE);
	free(o);
}

static bool offers_text(struct offer *o)
{
	if (!o)
		return false;
	for (size_t i = 0; i < G_N_ELEMENTS(text_types); i++) {
		size_t n = strlen(text_types[i]);
		for (const char *p = o->types->str; *p; p = strchr(p, '\n') + 1)
			if (strncmp(p, text_types[i], n) == 0 && p[n] == '\n')
				return true;
	}
	return false;
}

/* ---- nabidky ---- */

static void offer_type(void *data, struct ext_data_control_offer_v1 *wl, const char *mime)
{
	struct offer *o = data;
	(void)wl;
	g_string_append(o->types, mime);
	g_string_append_c(o->types, '\n');
}

static const struct ext_data_control_offer_v1_listener offer_listener = {.offer = offer_type};

static void device_data_offer(void *data, struct ext_data_control_device_v1 *d, struct ext_data_control_offer_v1 *wl)
{
	(void)data; (void)d;
	struct offer *o = calloc(1, sizeof *o);
	if (!o) {
		ext_data_control_offer_v1_destroy(wl);
		return;
	}
	o->wl = wl;
	o->types = g_string_new(NULL);
	ext_data_control_offer_v1_add_listener(wl, &offer_listener, o);
}

static void set_offer(int primary, struct ext_data_control_offer_v1 *wl)
{
	struct selection *s = &selections[primary];
	offer_free(s->offer);
	s->offer = wl ? wl_proxy_get_user_data((struct wl_proxy *)wl) : NULL;
	lwl_emit(LWL_CLIPBOARD_CHANGED, 0, primary, offers_text(s->offer));
}

static void device_selection(void *data, struct ext_data_control_device_v1 *d, struct ext_data_control_offer_v1 *wl)
{
	(void)data; (void)d;
	set_offer(0, wl);
}

static void device_primary(void *data, struct ext_data_control_device_v1 *d, struct ext_data_control_offer_v1 *wl)
{
	(void)data; (void)d;
	set_offer(1, wl);
}

static void device_finished(void *data, struct ext_data_control_device_v1 *d)
{
	(void)data;
	ext_data_control_device_v1_destroy(d);
	device = NULL;
}

static const struct ext_data_control_device_v1_listener device_listener = {
	.data_offer = device_data_offer,
	.selection = device_selection,
	.finished = device_finished,
	.primary_selection = device_primary,
};

/* ---- nas vyber ---- */

static gboolean write_more(gint fd, GIOCondition cond, gpointer data)
{
	struct writer *w = data;
	(void)cond;
	while (w->done < w->len) {
		ssize_t n = write(fd, w->text + w->done, w->len - w->done);
		if (n < 0 && errno == EAGAIN)
			return G_SOURCE_CONTINUE;
		if (n <= 0)
			break;
		w->done += (size_t)n;
	}
	close(fd);
	free(w->text);
	free(w);
	return G_SOURCE_REMOVE;
}

static void source_send(void *data, struct ext_data_control_source_v1 *wl, const char *mime, int32_t fd)
{
	struct source *src = data;
	(void)wl; (void)mime;
	struct writer *w = calloc(1, sizeof *w);
	if (!w || !(w->text = strdup(src->text))) {
		free(w);
		close(fd);
		return;
	}
	w->len = strlen(w->text);
	w->fd = fd;
	fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
	if (write_more(fd, G_IO_OUT, w) == G_SOURCE_CONTINUE)
		g_unix_fd_add(fd, G_IO_OUT | G_IO_ERR | G_IO_HUP, write_more, w);
}

static void source_free(struct source *src)
{
	ext_data_control_source_v1_destroy(src->wl);
	free(src->text);
	free(src);
}

static void source_cancelled(void *data, struct ext_data_control_source_v1 *wl)
{
	struct source *src = data;
	struct selection *s = &selections[src->primary];
	(void)wl;
	if (s->source == src) {
		s->source = NULL;
		lwl_emit(LWL_CLIPBOARD_CANCELLED, 0, src->primary, 0);
	}
	source_free(src);
}

static const struct ext_data_control_source_v1_listener source_listener = {
	.send = source_send,
	.cancelled = source_cancelled,
};

LWL_EXPORT int lwl_clipboard_set(const char *text, int primary)
{
	if (!device || !text)
		return 0;
	struct source *src = calloc(1, sizeof *src);
	if (!src || !(src->text = strdup(text))) {
		free(src);
		return 0;
	}
	src->primary = primary != 0;
	src->wl = ext_data_control_manager_v1_create_data_source(lwl.data_control);
	ext_data_control_source_v1_add_listener(src->wl, &source_listener, src);
	for (size_t i = 0; i < G_N_ELEMENTS(text_types); i++)
		ext_data_control_source_v1_offer(src->wl, text_types[i]);
	/* stary zdroj uvolni az jeho udalost cancelled */
	selections[src->primary].source = src;
	if (src->primary)
		ext_data_control_device_v1_set_primary_selection(device, src->wl);
	else
		ext_data_control_device_v1_set_selection(device, src->wl);
	wl_display_flush(lwl.display);
	return 1;
}

LWL_EXPORT const char *lwl_clipboard_mime_types(int primary)
{
	struct offer *o = selections[primary != 0].offer;
	return o ? o->types->str : "";
}

/* ---- cteni ---- */

static struct request *find(int id)
{
	struct request *r;
	wl_list_for_each(r, &requests, link)
		if (r->id == id)
			return r;
	return NULL;
}

static gboolean read_more(gint fd, GIOCondition cond, gpointer data)
{
	struct request *r = data;
	char chunk[8192];
	(void)cond;
	for (;;) {
		ssize_t n = read(fd, chunk, sizeof chunk);
		if (n < 0 && errno == EAGAIN)
			return G_SOURCE_CONTINUE;
		if (n > 0 && r->data->len + (size_t)n <= MAX_READ) {
			g_string_append_len(r->data, chunk, n);
			continue;
		}
		close(fd);
		r->fd = -1;
		r->watch = 0;
		r->done = true;
		lwl_emit(LWL_CLIPBOARD_DATA, r->id, (int)r->data->len, n == 0 ? 0 : -1);
		return G_SOURCE_REMOVE;
	}
}

LWL_EXPORT int lwl_clipboard_request(const char *mime, int primary)
{
	struct offer *o = selections[primary != 0].offer;
	int fds[2];
	if (!o || !mime || pipe2(fds, O_CLOEXEC | O_NONBLOCK) < 0)
		return 0;
	struct request *r = calloc(1, sizeof *r);
	if (!r) {
		close(fds[0]);
		close(fds[1]);
		return 0;
	}
	ext_data_control_offer_v1_receive(o->wl, mime, fds[1]);
	wl_display_flush(lwl.display);
	close(fds[1]);
	r->id = lwl_new_id();
	r->fd = fds[0];
	r->data = g_string_new(NULL);
	r->watch = g_unix_fd_add(fds[0], G_IO_IN | G_IO_ERR | G_IO_HUP, read_more, r);
	wl_list_insert(requests.prev, &r->link);
	return r->id;
}

LWL_EXPORT const char *lwl_clipboard_data(int id)
{
	struct request *r = find(id);
	return r && r->done ? r->data->str : "";
}

static void request_free(struct request *r)
{
	if (r->watch)
		g_source_remove(r->watch);
	if (r->fd >= 0)
		close(r->fd);
	g_string_free(r->data, TRUE);
	wl_list_remove(&r->link);
	free(r);
}

LWL_EXPORT void lwl_clipboard_free(int id)
{
	struct request *r = find(id);
	if (r)
		request_free(r);
}

/* ---- globaly ---- */

void lwl_clipboard_seat(void)
{
	if (device || !lwl.data_control || !lwl.seat)
		return;
	device = ext_data_control_manager_v1_get_data_device(lwl.data_control, lwl.seat);
	ext_data_control_device_v1_add_listener(device, &device_listener, NULL);
}

bool lwl_clipboard_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	(void)version;
	if (strcmp(interface, ext_data_control_manager_v1_interface.name) != 0)
		return false;
	lwl.data_control = wl_registry_bind(registry, name, &ext_data_control_manager_v1_interface, 1);
	lwl_clipboard_seat();
	return true;
}

void lwl_clipboard_reset(void)
{
	struct request *r, *tmp;
	wl_list_for_each_safe(r, tmp, &requests, link)
		request_free(r);
	for (int i = 0; i < 2; i++) {
		offer_free(selections[i].offer);
		if (selections[i].source)
			source_free(selections[i].source);
		memset(&selections[i], 0, sizeof selections[i]);
	}
	if (device)
		ext_data_control_device_v1_destroy(device);
	device = NULL;
	if (lwl.data_control)
		ext_data_control_manager_v1_destroy(lwl.data_control);
}
