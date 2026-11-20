/* Nastaveni monitoru (wlr-output-management-unstable-v1): hlavy s rezimy, poloha, meritko,
 * otoceni a zapnuti; zmena jako jedna konfigurace (test nebo pouziti). */
#include <stdlib.h>
#include <string.h>
#include "internal.h"
#include "wlr-output-management-unstable-v1-client-protocol.h"

struct mode {
	struct wl_list link;
	struct zwlr_output_mode_v1 *wl;
	int width, height, refresh;
	bool preferred;
};

struct head {
	struct wl_list link;
	int id;
	struct zwlr_output_head_v1 *wl;
	char *name, *description;
	bool enabled, announced, changed, dead;
	int x, y, transform, scale;   /* meritko v tisicinach */
	struct mode *current;
	struct wl_list modes;
};

static struct wl_list heads = {&heads, &heads};
static uint32_t serial;
static struct zwlr_output_configuration_v1 *config;
/* hlavy konfigurace nemaji destruktor v protokolu, proxy se ale musi uvolnit (dlouho bezici proces) */
static struct wl_proxy *config_heads[16];
static int config_head_count;

static void config_free(void)
{
	for (int i = 0; i < config_head_count; i++)
		wl_proxy_destroy(config_heads[i]);
	config_head_count = 0;
	if (config)
		zwlr_output_configuration_v1_destroy(config);
	config = NULL;
}

static struct head *find(int id)
{
	struct head *h;
	wl_list_for_each(h, &heads, link)
		if (h->id == id)
			return h;
	return NULL;
}

/* ---- rezimy ---- */

static void mode_size(void *data, struct zwlr_output_mode_v1 *m, int32_t width, int32_t height)
{
	struct mode *mode = data;
	(void)m;
	mode->width = width;
	mode->height = height;
}

static void mode_refresh(void *data, struct zwlr_output_mode_v1 *m, int32_t refresh)
{
	struct mode *mode = data;
	(void)m;
	mode->refresh = refresh;
}

static void mode_preferred(void *data, struct zwlr_output_mode_v1 *m)
{
	struct mode *mode = data;
	(void)m;
	mode->preferred = true;
}

static void mode_free(struct mode *mode)
{
	wl_list_remove(&mode->link);
	if (zwlr_output_mode_v1_get_version(mode->wl) >= ZWLR_OUTPUT_MODE_V1_RELEASE_SINCE_VERSION)
		zwlr_output_mode_v1_release(mode->wl);
	else
		zwlr_output_mode_v1_destroy(mode->wl);
	free(mode);
}

static void mode_finished(void *data, struct zwlr_output_mode_v1 *m)
{
	struct mode *mode = data;
	struct head *h;
	(void)m;
	wl_list_for_each(h, &heads, link)
		if (h->current == mode)
			h->current = NULL;
	mode_free(mode);
}

static const struct zwlr_output_mode_v1_listener mode_listener = {
	.size = mode_size,
	.refresh = mode_refresh,
	.preferred = mode_preferred,
	.finished = mode_finished,
};

/* ---- hlavy ---- */

#define HEAD(data) struct head *h = data; (void)wl; h->changed = true

static void head_name(void *data, struct zwlr_output_head_v1 *wl, const char *name)
{
	HEAD(data);
	lwl_set_string(&h->name, name);
}

static void head_description(void *data, struct zwlr_output_head_v1 *wl, const char *description)
{
	HEAD(data);
	lwl_set_string(&h->description, description);
}

static void head_physical_size(void *data, struct zwlr_output_head_v1 *wl, int32_t w, int32_t hh)
{
	(void)data; (void)wl; (void)w; (void)hh;
}

static void head_mode(void *data, struct zwlr_output_head_v1 *wl, struct zwlr_output_mode_v1 *m)
{
	HEAD(data);
	struct mode *mode = calloc(1, sizeof *mode);
	if (!mode) {
		zwlr_output_mode_v1_destroy(m);
		return;
	}
	mode->wl = m;
	zwlr_output_mode_v1_add_listener(m, &mode_listener, mode);
	wl_list_insert(h->modes.prev, &mode->link);
}

static void head_enabled(void *data, struct zwlr_output_head_v1 *wl, int32_t enabled)
{
	HEAD(data);
	h->enabled = enabled != 0;
	if (!h->enabled)
		h->current = NULL;
}

static void head_current_mode(void *data, struct zwlr_output_head_v1 *wl, struct zwlr_output_mode_v1 *m)
{
	HEAD(data);
	struct mode *mode;
	wl_list_for_each(mode, &h->modes, link)
		if (mode->wl == m)
			h->current = mode;
}

static void head_position(void *data, struct zwlr_output_head_v1 *wl, int32_t x, int32_t y)
{
	HEAD(data);
	h->x = x;
	h->y = y;
}

static void head_transform(void *data, struct zwlr_output_head_v1 *wl, int32_t transform)
{
	HEAD(data);
	h->transform = transform;
}

static void head_scale(void *data, struct zwlr_output_head_v1 *wl, wl_fixed_t scale)
{
	HEAD(data);
	h->scale = (int)(wl_fixed_to_double(scale) * 1000 + 0.5);
}

static void head_finished(void *data, struct zwlr_output_head_v1 *wl)
{
	struct head *h = data;
	(void)wl;
	if (h->dead)
		return;
	h->dead = true;
	if (h->announced)
		lwl_emit(LWL_HEAD_REMOVED, h->id, 0, 0);
}

static void head_string(void *data, struct zwlr_output_head_v1 *wl, const char *text)
{
	(void)data; (void)wl; (void)text;
}

static void head_adaptive_sync(void *data, struct zwlr_output_head_v1 *wl, uint32_t state)
{
	(void)data; (void)wl; (void)state;
}

static const struct zwlr_output_head_v1_listener head_listener = {
	.name = head_name,
	.description = head_description,
	.physical_size = head_physical_size,
	.mode = head_mode,
	.enabled = head_enabled,
	.current_mode = head_current_mode,
	.position = head_position,
	.transform = head_transform,
	.scale = head_scale,
	.finished = head_finished,
	.make = head_string,
	.model = head_string,
	.serial_number = head_string,
	.adaptive_sync = head_adaptive_sync,
};

static void manager_head(void *data, struct zwlr_output_manager_v1 *m, struct zwlr_output_head_v1 *wl)
{
	(void)data; (void)m;
	struct head *h = calloc(1, sizeof *h);
	if (!h) {
		zwlr_output_head_v1_destroy(wl);
		return;
	}
	h->id = lwl_new_id();
	h->wl = wl;
	h->name = lwl_strdup("");
	h->description = lwl_strdup("");
	h->scale = 1000;
	wl_list_init(&h->modes);
	zwlr_output_head_v1_add_listener(wl, &head_listener, h);
	wl_list_insert(heads.prev, &h->link);
}

static void manager_done(void *data, struct zwlr_output_manager_v1 *m, uint32_t s)
{
	struct head *h;
	(void)data; (void)m;
	serial = s;
	wl_list_for_each(h, &heads, link) {
		if (h->dead || !h->changed)
			continue;
		lwl_emit(h->announced ? LWL_HEAD_CHANGED : LWL_HEAD_NEW, h->id, 0, 0);
		h->announced = true;
		h->changed = false;
	}
}

static void manager_finished(void *data, struct zwlr_output_manager_v1 *m)
{
	(void)data;
	zwlr_output_manager_v1_destroy(m);
	lwl.output_manager = NULL;
}

static const struct zwlr_output_manager_v1_listener manager_listener = {
	.head = manager_head,
	.done = manager_done,
	.finished = manager_finished,
};

static void head_free(struct head *h)
{
	struct mode *mode, *tmp;
	wl_list_for_each_safe(mode, tmp, &h->modes, link)
		mode_free(mode);
	wl_list_remove(&h->link);
	if (zwlr_output_head_v1_get_version(h->wl) >= ZWLR_OUTPUT_HEAD_V1_RELEASE_SINCE_VERSION)
		zwlr_output_head_v1_release(h->wl);
	else
		zwlr_output_head_v1_destroy(h->wl);
	free(h->name);
	free(h->description);
	free(h);
}

void lwl_heads_sweep(void)
{
	struct head *h, *tmp;
	wl_list_for_each_safe(h, tmp, &heads, link)
		if (h->dead)
			head_free(h);
}

bool lwl_heads_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
	if (strcmp(interface, zwlr_output_manager_v1_interface.name) != 0)
		return false;
	lwl.output_manager = wl_registry_bind(registry, name, &zwlr_output_manager_v1_interface, version < 4 ? version : 4);
	zwlr_output_manager_v1_add_listener(lwl.output_manager, &manager_listener, NULL);
	return true;
}

void lwl_heads_reset(void)
{
	struct head *h, *tmp;
	wl_list_for_each_safe(h, tmp, &heads, link)
		head_free(h);
	config_free();
	if (lwl.output_manager)
		zwlr_output_manager_v1_destroy(lwl.output_manager);
}

/* ---- API ---- */

LWL_EXPORT int lwl_head_count(void)
{
	int n = 0;
	struct head *h;
	wl_list_for_each(h, &heads, link)
		n += h->announced && !h->dead;
	return n;
}

LWL_EXPORT int lwl_head_at(int index)
{
	struct head *h;
	wl_list_for_each(h, &heads, link)
		if (h->announced && !h->dead && index-- == 0)
			return h->id;
	return 0;
}

LWL_EXPORT const char *lwl_head_name(int id)
{
	struct head *h = find(id);
	return h ? h->name : "";
}

LWL_EXPORT const char *lwl_head_description(int id)
{
	struct head *h = find(id);
	return h ? h->description : "";
}

#define HEAD_GETTER(field, expr) \
	LWL_EXPORT int lwl_head_##field(int id) \
	{ \
		struct head *h = find(id); \
		return h ? (expr) : 0; \
	}
HEAD_GETTER(enabled, h->enabled)
HEAD_GETTER(x, h->x)
HEAD_GETTER(y, h->y)
HEAD_GETTER(width, h->current ? h->current->width : 0)
HEAD_GETTER(height, h->current ? h->current->height : 0)
HEAD_GETTER(refresh, h->current ? h->current->refresh : 0)
HEAD_GETTER(scale, h->scale)
HEAD_GETTER(transform, h->transform)

LWL_EXPORT int lwl_head_mode_count(int id)
{
	struct head *h = find(id);
	return h ? wl_list_length(&h->modes) : 0;
}

/* field: 0 sirka, 1 vyska, 2 obnovovaci frekvence v mHz, 3 preferovany, 4 aktualni */
LWL_EXPORT int lwl_head_mode(int id, int index, int field)
{
	struct head *h = find(id);
	struct mode *mode;
	if (!h)
		return 0;
	wl_list_for_each(mode, &h->modes, link) {
		if (index-- != 0)
			continue;
		switch (field) {
		case 0: return mode->width;
		case 1: return mode->height;
		case 2: return mode->refresh;
		case 3: return mode->preferred;
		case 4: return mode == h->current;
		}
		return 0;
	}
	return 0;
}

static void config_result(int result)
{
	config_free();
	lwl_emit(LWL_OUTPUT_CONFIG_RESULT, 0, result, 0);
}

static void config_succeeded(void *data, struct zwlr_output_configuration_v1 *c)
{
	(void)data; (void)c;
	config_result(1);
}

static void config_failed(void *data, struct zwlr_output_configuration_v1 *c)
{
	(void)data; (void)c;
	config_result(0);
}

static void config_cancelled(void *data, struct zwlr_output_configuration_v1 *c)
{
	(void)data; (void)c;
	config_result(2);
}

static const struct zwlr_output_configuration_v1_listener config_listener = {
	.succeeded = config_succeeded,
	.failed = config_failed,
	.cancelled = config_cancelled,
};

/* Nova konfigurace; hlavy, ktere se do ni nepridaji, kompozitor odmitne (protokol chce vsechny). */
LWL_EXPORT int lwl_output_config_begin(void)
{
	if (!lwl.output_manager || config)
		return 0;
	config = zwlr_output_manager_v1_create_configuration(lwl.output_manager, serial);
	zwlr_output_configuration_v1_add_listener(config, &config_listener, NULL);
	return 1;
}

/* Rezim podle sirky/vysky/frekvence (refresh 0 = prvni s tou velikosti); kdyz neni, vlastni rezim.
 * width 0 = beze zmeny rezimu. Meritko v tisicinach. */
LWL_EXPORT int lwl_output_config_head(int id, int enabled, int width, int height, int refresh,
	int x, int y, int transform, int scale)
{
	struct head *h = find(id);
	if (!config || !h || h->dead || config_head_count == (int)(sizeof config_heads / sizeof *config_heads))
		return 0;
	if (!enabled) {
		zwlr_output_configuration_v1_disable_head(config, h->wl);
		return 1;
	}
	struct zwlr_output_configuration_head_v1 *ch = zwlr_output_configuration_v1_enable_head(config, h->wl);
	config_heads[config_head_count++] = (struct wl_proxy *)ch;
	if (width > 0) {
		struct mode *mode, *match = NULL;
		wl_list_for_each(mode, &h->modes, link)
			if (!match && mode->width == width && mode->height == height && (refresh == 0 || mode->refresh == refresh))
				match = mode;
		if (match)
			zwlr_output_configuration_head_v1_set_mode(ch, match->wl);
		else
			zwlr_output_configuration_head_v1_set_custom_mode(ch, width, height, refresh);
	}
	zwlr_output_configuration_head_v1_set_position(ch, x, y);
	zwlr_output_configuration_head_v1_set_transform(ch, transform);
	if (scale > 0)
		zwlr_output_configuration_head_v1_set_scale(ch, wl_fixed_from_double(scale / 1000.0));
	return 1;
}

LWL_EXPORT int lwl_output_config_apply(int test_only)
{
	if (!config)
		return 0;
	if (test_only)
		zwlr_output_configuration_v1_test(config);
	else
		zwlr_output_configuration_v1_apply(config);
	wl_display_flush(lwl.display);
	return 1;
}
