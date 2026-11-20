/* Snimek vystupu nebo okna (ext-image-copy-capture-v1 + ext-image-capture-source-v1), jeden
 * snimek do buferu wl_shm. Pixely zustavaji v pameti knihovny do lwl_capture_free. */
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "internal.h"
#include "ext-image-capture-source-v1-client-protocol.h"
#include "ext-image-copy-capture-v1-client-protocol.h"

struct capture {
	struct wl_list link;
	int id;
	struct ext_image_capture_source_v1 *source;
	struct ext_image_copy_capture_session_v1 *session;
	struct ext_image_copy_capture_frame_v1 *frame;
	struct wl_buffer *buffer;
	void *data;
	size_t size;
	int width, height, stride;
	uint32_t format;
	bool have_format, done;
};

static struct wl_list captures = {&captures, &captures};

static struct capture *find(int id)
{
	struct capture *c;
	wl_list_for_each(c, &captures, link)
		if (c->id == id)
			return c;
	return NULL;
}

/* zdroj a relace uz nejsou potreba, pixely ano */
static void end_session(struct capture *c)
{
	if (c->frame)
		ext_image_copy_capture_frame_v1_destroy(c->frame);
	if (c->session)
		ext_image_copy_capture_session_v1_destroy(c->session);
	if (c->source)
		ext_image_capture_source_v1_destroy(c->source);
	if (c->buffer)
		wl_buffer_destroy(c->buffer);
	c->frame = NULL;
	c->session = NULL;
	c->source = NULL;
	c->buffer = NULL;
}

static void fail(struct capture *c, int reason)
{
	end_session(c);
	c->done = true;
	lwl_emit(LWL_CAPTURE_FAILED, c->id, reason, 0);
}

static void frame_transform(void *data, struct ext_image_copy_capture_frame_v1 *f, uint32_t transform)
{
	(void)data; (void)f; (void)transform;
}

static void frame_damage(void *data, struct ext_image_copy_capture_frame_v1 *f, int32_t x, int32_t y, int32_t w, int32_t h)
{
	(void)data; (void)f; (void)x; (void)y; (void)w; (void)h;
}

static void frame_presentation_time(void *data, struct ext_image_copy_capture_frame_v1 *f, uint32_t hi, uint32_t lo, uint32_t ns)
{
	(void)data; (void)f; (void)hi; (void)lo; (void)ns;
}

static void frame_ready(void *data, struct ext_image_copy_capture_frame_v1 *f)
{
	struct capture *c = data;
	(void)f;
	end_session(c);
	c->done = true;
	lwl_emit(LWL_CAPTURE_READY, c->id, c->width, c->height);
}

static void frame_failed(void *data, struct ext_image_copy_capture_frame_v1 *f, uint32_t reason)
{
	(void)f;
	fail(data, (int)reason);
}

static const struct ext_image_copy_capture_frame_v1_listener frame_listener = {
	.transform = frame_transform,
	.damage = frame_damage,
	.presentation_time = frame_presentation_time,
	.ready = frame_ready,
	.failed = frame_failed,
};

static void session_buffer_size(void *data, struct ext_image_copy_capture_session_v1 *s, uint32_t width, uint32_t height)
{
	struct capture *c = data;
	(void)s;
	c->width = (int)width;
	c->height = (int)height;
}

static void session_shm_format(void *data, struct ext_image_copy_capture_session_v1 *s, uint32_t format)
{
	struct capture *c = data;
	(void)s;
	/* cairo umi ARGB32 i RGB24 primo; jine formaty jen kdyz nic z toho neni */
	if (format == WL_SHM_FORMAT_XRGB8888 || format == WL_SHM_FORMAT_ARGB8888) {
		if (!c->have_format || c->format != WL_SHM_FORMAT_XRGB8888)
			c->format = format;
		c->have_format = true;
	}
}

static void session_dmabuf_device(void *data, struct ext_image_copy_capture_session_v1 *s, struct wl_array *dev)
{
	(void)data; (void)s; (void)dev;
}

static void session_dmabuf_format(void *data, struct ext_image_copy_capture_session_v1 *s, uint32_t format, struct wl_array *mods)
{
	(void)data; (void)s; (void)format; (void)mods;
}

static void session_done(void *data, struct ext_image_copy_capture_session_v1 *s)
{
	struct capture *c = data;
	if (c->frame || c->done)
		return;
	if (!c->have_format || c->width <= 0 || c->height <= 0) {
		fail(c, -1);
		return;
	}
	c->stride = c->width * 4;
	c->size = (size_t)c->stride * c->height;
	int fd = lwl_shm_fd(c->size);
	if (fd < 0) {
		fail(c, -1);
		return;
	}
	c->data = mmap(NULL, c->size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (c->data == MAP_FAILED) {
		c->data = NULL;
		close(fd);
		fail(c, -1);
		return;
	}
	struct wl_shm_pool *pool = wl_shm_create_pool(lwl.shm, fd, (int32_t)c->size);
	c->buffer = wl_shm_pool_create_buffer(pool, 0, c->width, c->height, c->stride, c->format);
	wl_shm_pool_destroy(pool);
	close(fd);
	c->frame = ext_image_copy_capture_session_v1_create_frame(s);
	ext_image_copy_capture_frame_v1_add_listener(c->frame, &frame_listener, c);
	ext_image_copy_capture_frame_v1_attach_buffer(c->frame, c->buffer);
	ext_image_copy_capture_frame_v1_damage_buffer(c->frame, 0, 0, c->width, c->height);
	ext_image_copy_capture_frame_v1_capture(c->frame);
}

static void session_stopped(void *data, struct ext_image_copy_capture_session_v1 *s)
{
	struct capture *c = data;
	(void)s;
	if (!c->done)
		fail(c, -1);
}

static const struct ext_image_copy_capture_session_v1_listener session_listener = {
	.buffer_size = session_buffer_size,
	.shm_format = session_shm_format,
	.dmabuf_device = session_dmabuf_device,
	.dmabuf_format = session_dmabuf_format,
	.done = session_done,
	.stopped = session_stopped,
};

static int start(struct ext_image_capture_source_v1 *source, int cursor)
{
	struct capture *c = calloc(1, sizeof *c);
	if (!c) {
		ext_image_capture_source_v1_destroy(source);
		return 0;
	}
	c->id = lwl_new_id();
	c->source = source;
	c->session = ext_image_copy_capture_manager_v1_create_session(lwl.copy_capture, source,
		cursor ? EXT_IMAGE_COPY_CAPTURE_MANAGER_V1_OPTIONS_PAINT_CURSORS : 0);
	ext_image_copy_capture_session_v1_add_listener(c->session, &session_listener, c);
	wl_list_insert(captures.prev, &c->link);
	wl_display_flush(lwl.display);
	return c->id;
}

LWL_EXPORT int lwl_capture_output(int output, int cursor)
{
	struct lwl_output *o = lwl_find_output(output);
	if (!o || o->dead || !lwl.output_sources || !lwl.copy_capture || !lwl.shm)
		return 0;
	return start(ext_output_image_capture_source_manager_v1_create_source(lwl.output_sources, o->wl), cursor);
}

LWL_EXPORT int lwl_capture_toplevel(int toplevel, int cursor)
{
	struct ext_foreign_toplevel_handle_v1 *h = lwl_toplevel_ext_handle(toplevel);
	if (!h || !lwl.toplevel_sources || !lwl.copy_capture || !lwl.shm)
		return 0;
	return start(ext_foreign_toplevel_image_capture_source_manager_v1_create_source(lwl.toplevel_sources, h), cursor);
}

/* pixely az po LWL_CAPTURE_READY; format wl_shm: 0 ARGB8888, 1 XRGB8888 (= cairo ARGB32 / RGB24) */
LWL_EXPORT void *lwl_capture_data(int id)
{
	struct capture *c = find(id);
	return c && c->done && !c->frame ? c->data : NULL;
}

LWL_EXPORT int lwl_capture_stride(int id)
{
	struct capture *c = find(id);
	return c ? c->stride : 0;
}

LWL_EXPORT int lwl_capture_format(int id)
{
	struct capture *c = find(id);
	return c ? (int)c->format : -1;
}

static void destroy(struct capture *c)
{
	end_session(c);
	if (c->data)
		munmap(c->data, c->size);
	wl_list_remove(&c->link);
	free(c);
}

LWL_EXPORT void lwl_capture_free(int id)
{
	struct capture *c = find(id);
	if (c)
		destroy(c);
}

bool lwl_capture_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	(void)version;
	if (strcmp(interface, ext_output_image_capture_source_manager_v1_interface.name) == 0)
		lwl.output_sources = wl_registry_bind(registry, name, &ext_output_image_capture_source_manager_v1_interface, 1);
	else if (strcmp(interface, ext_foreign_toplevel_image_capture_source_manager_v1_interface.name) == 0)
		lwl.toplevel_sources = wl_registry_bind(registry, name,
			&ext_foreign_toplevel_image_capture_source_manager_v1_interface, 1);
	else if (strcmp(interface, ext_image_copy_capture_manager_v1_interface.name) == 0)
		lwl.copy_capture = wl_registry_bind(registry, name, &ext_image_copy_capture_manager_v1_interface, 1);
	else
		return false;
	return true;
}

void lwl_capture_reset(void)
{
	struct capture *c, *tmp;
	wl_list_for_each_safe(c, tmp, &captures, link)
		destroy(c);
	if (lwl.output_sources)
		ext_output_image_capture_source_manager_v1_destroy(lwl.output_sources);
	if (lwl.toplevel_sources)
		ext_foreign_toplevel_image_capture_source_manager_v1_destroy(lwl.toplevel_sources);
	if (lwl.copy_capture)
		ext_image_copy_capture_manager_v1_destroy(lwl.copy_capture);
}
