/*
 * Material: rozmazane pozadi pod plochami layer-shell a jejich popupy (lista, Dock, vyskakovaci okna,
 * oznameni, Launchpad). Plocha o nej pozada priponou jmenneho prostoru ("luxos-cc@popup:16", viz
 * docs/developers/luxcomp-api.md). Pod povrch klienta jde uzel s rozmazanym vyrezem sceny pod nim
 * a stin podle urovne materialu; klient kresli jen tonovani.
 *
 * Vyrez se pocita znovu jen kdyz se zmenilo, co pod plochou je: podpis uzlu pod ni (poloha, buffer,
 * poradove cislo commitu povrchu). Pri klidu se nepocita nic.
 *
 * gles2: zachyceni pruchodem rendereru, dual Kawase (4 pruchody dolu, 4 nahoru) shadery GLES2,
 * v poslednim saturace a zaobleni. pixman: zachyceni ve ctvrtinovem rozliseni, trikrat box blur v C,
 * zvetseni rendererem a zaobleni rohu. Kdyz snimky s prepoctem trvaji tri po sobe pres 8 ms,
 * vystup prejde na jednolitou barvu materialu (tier C).
 */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <drm_fourcc.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wlr/render/allocator.h>
#include <wlr/render/egl.h>
#include <wlr/render/gles2.h>
#include <wlr/render/pass.h>
#include <wlr/render/swapchain.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/render/wlr_texture.h>
#include <wlr/interfaces/wlr_buffer.h>
#include <wlr/types/wlr_buffer.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/util/log.h>
#include "internal.h"

#define MAX_MATERIALS 16
#define LEVELS 4		/* dual Kawase: pruchody dolu = pruchody nahoru */
#define SLOW_NS 8000000	/* rozpocet snimku 1080p pod pixman; testy: LUXCOMP_BLUR_SLOW_MS */
#define SLOW_FRAMES 3

struct material {
	char name[16];
	int radius;
	uint32_t fallback, shadow;
	int shadow_size, shadow_y;
};

/* Vychozi hodnoty = svetly rezim tokenu LuxOS (luxos_tokens.lsl MATERIAL, ELEVATION); luxwm je prepise */
static struct material materials[MAX_MATERIALS] = {
	{ "bar", 0, 0xfff6f7fc, 0, 0, 0 },
	{ "dock", 24, 0xfff6f7fc, 0x2e000000, 24, 8 },
	{ "menu", 12, 0xfff6f7fc, 0x38000000, 30, 10 },
	{ "popup", 16, 0xfff6f7fc, 0x3d000000, 44, 16 },
	{ "toast", 16, 0xfff6f7fc, 0x38000000, 32, 12 },
	{ "sheet", 24, 0xfff6f7fc, 0x59000000, 80, 30 },
	{ "dim", 0, 0xff3a3c48, 0, 0, 0 },
};

static struct {
	int radius;		/* efektivni polomer rozmazani v logickych px */
	int saturation;		/* % */
	int mode;		/* 0 vypnuto (jednolita barva), 1 automaticky */
	bool gpu_broken;
	/* gles2 */
	bool gl_ready;
	GLuint prog[3], vbo;
	GLint u_tex[3], u_half[3], u_off[3], u_sat, u_size, u_radius, a_pos[3];
	/* LUXCOMP_STATS */
	bool stats;
	int frames, updates;
	int64_t max_ns, sum_ns, blur_max_ns, blur_sum_ns;
} cfg = { .radius = 32, .saturation = 160, .mode = 1 };

struct blur {
	struct wl_list link;
	struct wlr_scene_tree *parent;
	struct wlr_scene_buffer *node;
	struct shadow *shadow;
	char material[16];
	int radius;
	struct wlr_box box;		/* v souradnicich parent */
	uint64_t sig;
	bool solid, dirty;
	struct wlr_buffer *out[2];	/* hotovy obraz, stridave (scena drzi predchozi) */
	int cur, out_w, out_h;
	bool out_gpu;			/* out[] z alokatoru (gles2), jinak v pameti */
	/* pixman: ctvrtinovy vyrez */
	struct wlr_buffer *small;
	int small_w, small_h;
	/* gles2: urovne dual Kawase, 0 = zachyceni */
	struct wlr_buffer *level[LEVELS + 1];
	int lw[LEVELS + 1], lh[LEVELS + 1];
	struct wl_listener parent_destroy;
};

static struct wl_list blurs = { &blurs, &blurs };
static int slow_frames;
static bool degraded;

/* ---- buffer v pameti s pristupem pro zapis (renderer pixman do nej kresli) ---- */

struct mem_buffer {
	struct wlr_buffer base;
	uint32_t *data;
	size_t stride;
};

static void
mem_destroy(struct wlr_buffer *b)
{
	struct mem_buffer *m = wl_container_of(b, m, base);
	free(m->data);
	free(m);
}

static bool
mem_begin(struct wlr_buffer *b, uint32_t flags, void **data, uint32_t *format, size_t *stride)
{
	struct mem_buffer *m = wl_container_of(b, m, base);
	*data = m->data;
	*format = DRM_FORMAT_ARGB8888;
	*stride = m->stride;
	return true;
}

static void
mem_end(struct wlr_buffer *b)
{
}

static const struct wlr_buffer_impl mem_impl = {
	.destroy = mem_destroy,
	.begin_data_ptr_access = mem_begin,
	.end_data_ptr_access = mem_end,
};

static struct wlr_buffer *
mem_create(int w, int h)
{
	struct mem_buffer *m = calloc(1, sizeof(*m));
	wlr_buffer_init(&m->base, &mem_impl, w, h);
	m->stride = (size_t)w * 4;
	m->data = calloc((size_t)w * h, 4);
	return &m->base;
}

static uint32_t *
mem_data(struct wlr_buffer *b)
{
	struct mem_buffer *m = wl_container_of(b, m, base);
	return m->data;
}

static void
drop(struct wlr_buffer **b)
{
	if (*b) {
		wlr_buffer_drop(*b);
		*b = NULL;
	}
}

/* ---- tabulka materialu ---- */

static const struct material *
material_find(const char *name)
{
	for (int i = 0; i < MAX_MATERIALS && materials[i].name[0]; i++) {
		if (!strcmp(materials[i].name, name)) {
			return &materials[i];
		}
	}
	return NULL;
}

void
luxcomp_material_set(const char *name, int64_t radius, int64_t fallback, int64_t shadow,
		int64_t shadow_size, int64_t shadow_y)
{
	if (!name || !*name || strlen(name) >= sizeof(materials[0].name)) {
		return;
	}
	struct material *m = (struct material *)material_find(name);
	for (int i = 0; !m && i < MAX_MATERIALS; i++) {
		if (!materials[i].name[0]) {
			m = &materials[i];
			strcpy(m->name, name);
		}
	}
	if (!m) {
		return;
	}
	m->radius = radius;
	m->fallback = (uint32_t)fallback;
	m->shadow = (uint32_t)shadow;
	m->shadow_size = shadow_size;
	m->shadow_y = shadow_y;
	struct blur *b;
	wl_list_for_each(b, &blurs, link) {
		if (!strcmp(b->material, name)) {
			b->dirty = true;
			blur_set_box(b, b->box);
		}
	}
}

void
luxcomp_blur_set(int64_t radius, int64_t saturation_pct, int64_t mode)
{
	cfg.radius = radius > 0 ? radius : 32;
	cfg.saturation = saturation_pct > 0 ? saturation_pct : 100;
	cfg.mode = mode ? 1 : 0;
	degraded = false;
	slow_frames = 0;
	struct blur *b;
	wl_list_for_each(b, &blurs, link) {
		b->dirty = true;
	}
}

/* 2 = gles2 shadery, 1 = pixman v C, 0 = jednolita barva */
int64_t
luxcomp_blur_tier(void)
{
	if (!cfg.mode || degraded || cfg.gpu_broken) {
		return 0;
	}
	return comp.software ? 1 : 2;
}

/* "nazev@material:polomer" -> material a polomer; false = plocha o material nezada */
bool
blur_parse_namespace(const char *ns, char material[16], int *radius)
{
	const char *at = ns ? strrchr(ns, '@') : NULL;
	if (!at || !at[1]) {
		return false;
	}
	size_t n = strcspn(at + 1, ":");
	if (n == 0 || n >= 16) {
		return false;
	}
	memcpy(material, at + 1, n);
	material[n] = '\0';
	const struct material *m = material_find(material);
	*radius = m ? m->radius : 0;
	if (at[1 + n] == ':') {
		*radius = atoi(at + 2 + n);
	}
	if (*radius < 0) {
		*radius = 0;
	}
	return true;
}

/* ---- uzly ---- */

static bool
no_input(struct wlr_scene_buffer *buffer, double *sx, double *sy)
{
	return false;
}

/* Strom plochy zanika se svym povrchem drive, nez se o tom dozvi vlastnik (layer_destroy): uzly
 * zrusit hned, strukturu az s vlastnikem */
static void
parent_destroyed(struct wl_listener *listener, void *data)
{
	struct blur *b = wl_container_of(listener, b, parent_destroy);
	wl_list_remove(&b->parent_destroy.link);
	shadow_destroy(b->shadow);
	wlr_scene_node_destroy(&b->node->node);
	b->shadow = NULL;
	b->node = NULL;
	b->parent = NULL;
}

struct blur *
blur_create(struct wlr_scene_tree *parent, const char *material, int radius)
{
	struct blur *b = calloc(1, sizeof(*b));
	b->parent = parent;
	snprintf(b->material, sizeof(b->material), "%s", material);
	b->radius = radius;
	b->node = wlr_scene_buffer_create(parent, NULL);
	b->node->point_accepts_input = no_input;
	wlr_scene_node_lower_to_bottom(&b->node->node);
	b->shadow = shadow_create(parent);
	b->dirty = true;
	b->parent_destroy.notify = parent_destroyed;
	wl_signal_add(&parent->node.events.destroy, &b->parent_destroy);
	wl_list_insert(&blurs, &b->link);
	cfg.stats = getenv("LUXCOMP_STATS") != NULL;
	return b;
}

static void
free_levels(struct blur *b)
{
	for (int i = 0; i <= LEVELS; i++) {
		drop(&b->level[i]);
	}
	drop(&b->small);
}

void
blur_destroy(struct blur *b)
{
	if (!b) {
		return;
	}
	wl_list_remove(&b->link);
	if (b->parent) {
		parent_destroyed(&b->parent_destroy, NULL);
	}
	free_levels(b);
	drop(&b->out[0]);
	drop(&b->out[1]);
	free(b);
}

void
blur_set_box(struct blur *b, struct wlr_box box)
{
	if (!b->parent) {
		return;
	}
	if (!wlr_box_equal(&box, &b->box)) {
		b->dirty = true;
	}
	b->box = box;
	wlr_scene_node_set_position(&b->node->node, box.x, box.y);
	wlr_scene_node_set_enabled(&b->node->node, !wlr_box_empty(&box));
	const struct material *m = material_find(b->material);
	int r = b->radius < box.width / 2 ? b->radius : box.width / 2;
	r = r < box.height / 2 ? r : box.height / 2;
	shadow_update(b->shadow, box, m ? m->shadow_size : 0, r, m ? m->shadow : 0,
		m ? m->shadow_y : 0, 1);
}

/* ---- co je pod plochou ---- */

struct walk {
	struct wlr_scene_node *stop;
	struct wlr_box box;		/* vyrez v souradnicich rozlozeni */
	bool done;
	uint64_t sig;
	/* kresleni; pass NULL = jen podpis */
	struct wlr_render_pass *pass;
	double k;			/* px vyrezu na logicky px */
	struct wlr_texture *temp[64];
	int n_temp;
};

static void
mix(uint64_t *h, uint64_t v)
{
	*h = (*h ^ v) * 0x100000001b3ULL;
}

static struct wlr_box
scaled(struct walk *w, int x, int y, int width, int height)
{
	int x0 = (int)floor((x - w->box.x) * w->k), y0 = (int)floor((y - w->box.y) * w->k);
	int x1 = (int)ceil((x + width - w->box.x) * w->k), y1 = (int)ceil((y + height - w->box.y) * w->k);
	return (struct wlr_box){ x0, y0, x1 - x0, y1 - y0 };
}

static void
walk_buffer(struct walk *w, struct wlr_scene_buffer *sb, int x, int y)
{
	if (!sb->buffer || sb->opacity <= 0) {
		return;
	}
	int width = sb->dst_width, height = sb->dst_height;
	if (width <= 0 || height <= 0) {
		width = sb->src_box.width > 0 ? (int)sb->src_box.width : sb->buffer->width;
		height = sb->src_box.height > 0 ? (int)sb->src_box.height : sb->buffer->height;
	}
	struct wlr_box nb = { x, y, width, height }, hit;
	if (!wlr_box_intersection(&hit, &nb, &w->box)) {
		return;
	}
	mix(&w->sig, (uintptr_t)sb);
	mix(&w->sig, (uintptr_t)sb->buffer);
	mix(&w->sig, ((uint64_t)(uint32_t)x << 32) | (uint32_t)y);
	mix(&w->sig, ((uint64_t)(uint32_t)width << 32) | (uint32_t)height);
	mix(&w->sig, (uint64_t)(sb->opacity * 1000));
	struct wlr_scene_surface *ss = wlr_scene_surface_try_from_buffer(sb);
	if (ss) {
		mix(&w->sig, ss->surface->current.seq);
	}
	if (!w->pass) {
		return;
	}
	struct wlr_texture *tex = NULL;
	struct wlr_client_buffer *cb = wlr_client_buffer_get(sb->buffer);
	if (cb && cb->texture) {
		tex = cb->texture;
	} else if (w->n_temp < (int)(sizeof(w->temp) / sizeof(*w->temp))) {
		tex = wlr_texture_from_buffer(comp.renderer, sb->buffer);
		if (tex) {
			w->temp[w->n_temp++] = tex;
		}
	}
	if (!tex) {
		return;
	}
	float alpha = sb->opacity;
	wlr_render_pass_add_texture(w->pass, &(struct wlr_render_texture_options){
		.texture = tex,
		.src_box = sb->src_box,
		.dst_box = scaled(w, x, y, width, height),
		.alpha = &alpha,
		.transform = sb->transform,
		.filter_mode = WLR_SCALE_FILTER_BILINEAR,
	});
}

static void
walk_node(struct walk *w, struct wlr_scene_node *node, int x, int y)
{
	if (w->done || node == w->stop) {
		w->done = true;
		return;
	}
	if (!node->enabled) {
		return;
	}
	x += node->x;
	y += node->y;
	switch (node->type) {
	case WLR_SCENE_NODE_TREE: {
		struct wlr_scene_tree *tree = wlr_scene_tree_from_node(node);
		struct wlr_scene_node *child;
		wl_list_for_each(child, &tree->children, link) {
			walk_node(w, child, x, y);
			if (w->done) {
				return;
			}
		}
		break;
	}
	case WLR_SCENE_NODE_RECT: {
		struct wlr_scene_rect *r = wlr_scene_rect_from_node(node);
		struct wlr_box nb = { x, y, r->width, r->height }, hit;
		if (r->color[3] <= 0 || !wlr_box_intersection(&hit, &nb, &w->box)) {
			break;
		}
		mix(&w->sig, (uintptr_t)r);
		mix(&w->sig, ((uint64_t)(uint32_t)hit.x << 32) | (uint32_t)hit.y);
		mix(&w->sig, ((uint64_t)(uint32_t)hit.width << 32) | (uint32_t)hit.height);
		for (int i = 0; i < 4; i++) {
			mix(&w->sig, (uint64_t)(r->color[i] * 65535));
		}
		if (w->pass) {
			wlr_render_pass_add_rect(w->pass, &(struct wlr_render_rect_options){
				.box = scaled(w, hit.x, hit.y, hit.width, hit.height),
				.color = { r->color[0], r->color[1], r->color[2], r->color[3] },
			});
		}
		break;
	}
	case WLR_SCENE_NODE_BUFFER:
		walk_buffer(w, wlr_scene_buffer_from_node(node), x, y);
		break;
	}
}

static void
walk_scene(struct walk *w)
{
	walk_node(w, &comp.scene->tree.node, 0, 0);
}

/* ---- pomucky ---- */

static int64_t
now_ns(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000000000LL + t.tv_nsec;
}

/* Alfa pixelu (x, y) obdelniku w x h se zaoblenymi rohy r; vyhlazena hrana */
static double
corner_alpha(int x, int y, int w, int h, double r)
{
	double cx = x + 0.5, cy = y + 0.5, dx = 0, dy = 0;
	if (cx < r) {
		dx = r - cx;
	} else if (cx > w - r) {
		dx = cx - (w - r);
	}
	if (cy < r) {
		dy = r - cy;
	} else if (cy > h - r) {
		dy = cy - (h - r);
	}
	if (dx == 0 || dy == 0) {
		return 1;
	}
	double d = sqrt(dx * dx + dy * dy) - r;
	return d <= -0.5 ? 1 : d >= 0.5 ? 0 : 0.5 - d;
}

/* Zaobleni rohu hotoveho obrazu: jen ctverce r x r v rozich */
static void
round_corners(uint32_t *px, int stride, int w, int h, int r)
{
	if (r <= 0) {
		return;
	}
	for (int y = 0; y < h; y++) {
		if (y >= r && y < h - r) {
			continue;
		}
		for (int x = 0; x < w; x++) {
			if (x >= r && x < w - r) {
				x = w - r - 1;
				continue;
			}
			double a = corner_alpha(x, y, w, h, r);
			if (a >= 1) {
				continue;
			}
			uint32_t p = px[y * stride + x];
			uint32_t c[4] = { p >> 24, p >> 16 & 0xff, p >> 8 & 0xff, p & 0xff };
			for (int i = 0; i < 4; i++) {
				c[i] = (uint32_t)(c[i] * a + 0.5);
			}
			px[y * stride + x] = c[0] << 24 | c[1] << 16 | c[2] << 8 | c[3];
		}
	}
}

static void
set_opaque(struct blur *b, int w, int h)
{
	pixman_region32_t region;
	int r = b->radius;
	pixman_region32_init_rect(&region, 0, r, w, h > 2 * r ? h - 2 * r : 0);
	pixman_region32_union_rect(&region, &region, r, 0, w > 2 * r ? w - 2 * r : 0, h);
	wlr_scene_buffer_set_opaque_region(b->node, &region);
	pixman_region32_fini(&region);
}

static struct wlr_buffer *gl_buffer(struct output *o, int w, int h);

/* Hotovy obraz do sceny; scena drzi predchozi buffer, proto stridave dva */
static struct wlr_buffer *
next_out(struct blur *b, struct output *o, int w, int h, bool gpu)
{
	if (b->out_w != w || b->out_h != h || b->out_gpu != gpu) {
		drop(&b->out[0]);
		drop(&b->out[1]);
		b->out_w = w;
		b->out_h = h;
		b->out_gpu = gpu;
	}
	b->cur ^= 1;
	if (!b->out[b->cur]) {
		b->out[b->cur] = gpu ? gl_buffer(o, w, h) : mem_create(w, h);
	}
	return b->out[b->cur];
}

static void
show(struct blur *b, struct wlr_buffer *buffer, int w, int h)
{
	wlr_scene_buffer_set_buffer(b->node, buffer);
	wlr_scene_buffer_set_dest_size(b->node, b->box.width, b->box.height);
	wlr_scene_buffer_set_filter_mode(b->node, WLR_SCALE_FILTER_BILINEAR);
	set_opaque(b, b->box.width, b->box.height);
}

/* Tier C: jednolita barva materialu (nebo vypnuty blur) */
static void
paint_solid(struct blur *b, struct output *o)
{
	const struct material *m = material_find(b->material);
	uint32_t c = m ? m->fallback : 0xfff6f7fc;
	int w = b->box.width, h = b->box.height;
	struct wlr_buffer *buf = next_out(b, o, w, h, false);
	uint32_t a = c >> 24, pre = a << 24 | ((c >> 16 & 0xff) * a / 255) << 16
		| ((c >> 8 & 0xff) * a / 255) << 8 | (c & 0xff) * a / 255;
	uint32_t *px = mem_data(buf);
	for (int i = 0; i < w * h; i++) {
		px[i] = pre;
	}
	round_corners(px, w, w, h, b->radius);
	show(b, buf, w, h);
}

/* ---- pixman: ctvrtinove rozliseni, box blur v C ---- */

/* Box blur radku nebo sloupce; kanaly v ctyrech 16bitovych pruzich uint64 (soucet okna se vejde),
 * deleni nasobenim prevracenou hodnotou */
static inline uint64_t
spread(uint32_t p)
{
	return (uint64_t)(p & 0xff000000) << 24 | (uint64_t)(p & 0xff0000) << 16
		| (uint64_t)(p & 0xff00) << 8 | (p & 0xff);
}

static void
box_line(uint32_t *p, int n, int step, int r, uint64_t *tmp)
{
	int win = 2 * r + 1;
	uint64_t mul = ((1ULL << 24) + win - 1) / win, half = (uint64_t)(win / 2) * 0x0001000100010001ULL;
	uint64_t s = 0;
	for (int i = 0; i < n; i++) {
		tmp[i] = spread(p[i * step]);
	}
	/* okraj opakuje krajni pixel: vyrez ma uz okraj o polomer navic */
	for (int i = -r; i <= r; i++) {
		s += tmp[i < 0 ? 0 : i >= n ? n - 1 : i];
	}
	for (int i = 0; i < n; i++) {
		uint64_t v = s + half;
		p[i * step] = (uint32_t)(((v >> 48 & 0xffff) * mul) >> 24) << 24
			| (uint32_t)(((v >> 32 & 0xffff) * mul) >> 24) << 16
			| (uint32_t)(((v >> 16 & 0xffff) * mul) >> 24) << 8
			| (uint32_t)(((v & 0xffff) * mul) >> 24);
		s += tmp[i + r + 1 >= n ? n - 1 : i + r + 1];
		s -= tmp[i - r < 0 ? 0 : i - r];
	}
}

static void
saturate(uint32_t *px, int n, double sat)
{
	int k = (int)(sat * 256);
	for (int i = 0; i < n; i++) {
		uint32_t p = px[i];
		int r = p >> 16 & 0xff, g = p >> 8 & 0xff, b = p & 0xff;
		int l = (54 * r + 183 * g + 19 * b) >> 8;
		int c[3] = { l + (((r - l) * k) >> 8), l + (((g - l) * k) >> 8), l + (((b - l) * k) >> 8) };
		for (int j = 0; j < 3; j++) {
			c[j] = c[j] < 0 ? 0 : c[j] > 255 ? 255 : c[j];
		}
		px[i] = 0xff000000 | c[0] << 16 | c[1] << 8 | c[2];
	}
}

/* Vyrez s okrajem o polomer rozmazani, oriznuty na vystup; v souradnicich rozlozeni */
static struct wlr_box
capture_box(struct blur *b, struct output *o, struct wlr_box abs)
{
	struct wlr_box out, cap = { abs.x - cfg.radius, abs.y - cfg.radius,
		abs.width + 2 * cfg.radius, abs.height + 2 * cfg.radius }, hit;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &out);
	if (!wlr_box_intersection(&hit, &cap, &out)) {
		return abs;
	}
	return hit;
}

static bool
blur_cpu(struct blur *b, struct output *o, struct wlr_box abs)
{
	const int down = 4;
	struct wlr_box cap = capture_box(b, o, abs);
	int sw = (cap.width + down - 1) / down, sh = (cap.height + down - 1) / down;
	if (!b->small || b->small_w != sw || b->small_h != sh) {
		drop(&b->small);
		b->small = mem_create(sw, sh);
		b->small_w = sw;
		b->small_h = sh;
	}
	struct walk w = { .stop = &b->parent->node, .box = cap, .k = 1.0 / down };
	w.pass = wlr_renderer_begin_buffer_pass(comp.renderer, b->small, NULL);
	if (!w.pass) {
		return false;
	}
	wlr_render_pass_add_rect(w.pass, &(struct wlr_render_rect_options){
		.box = { 0, 0, sw, sh }, .color = { 0, 0, 0, 1 },
		.blend_mode = WLR_RENDER_BLEND_MODE_NONE,
	});
	walk_scene(&w);
	bool ok = wlr_render_pass_submit(w.pass);
	for (int i = 0; i < w.n_temp; i++) {
		wlr_texture_destroy(w.temp[i]);
	}
	if (!ok) {
		return false;
	}
	/* tri box blury ~ gauss; polomer je v logickych px, tady ve ctvrtinach */
	int r = cfg.radius / (2 * down);
	r = r < 1 ? 1 : r;
	uint32_t *px = mem_data(b->small);
	int n = sw > sh ? sw : sh;
	uint64_t *tmp = malloc((size_t)n * 8);
	for (int pass = 0; pass < 3; pass++) {
		for (int y = 0; y < sh; y++) {
			box_line(px + y * sw, sw, 1, r, tmp);
		}
		for (int x = 0; x < sw; x++) {
			box_line(px + x, sh, sw, r, tmp);
		}
	}
	free(tmp);
	saturate(px, sw * sh, cfg.saturation / 100.0);

	/* zvetseni rendererem (bilinearne) na plnou velikost plochy, pak rohy */
	int ow = abs.width, oh = abs.height;
	struct wlr_buffer *buf = next_out(b, o, ow, oh, false);
	struct wlr_texture *tex = wlr_texture_from_buffer(comp.renderer, b->small);
	struct wlr_render_pass *pass = tex ? wlr_renderer_begin_buffer_pass(comp.renderer, buf, NULL) : NULL;
	if (!pass) {
		if (tex) {
			wlr_texture_destroy(tex);
		}
		return false;
	}
	double k = 1.0 / down;
	wlr_render_pass_add_texture(pass, &(struct wlr_render_texture_options){
		.texture = tex,
		.src_box = { (abs.x - cap.x) * k, (abs.y - cap.y) * k, ow * k, oh * k },
		.dst_box = { 0, 0, ow, oh },
		.filter_mode = WLR_SCALE_FILTER_BILINEAR,
		.blend_mode = WLR_RENDER_BLEND_MODE_NONE,
	});
	ok = wlr_render_pass_submit(pass);
	wlr_texture_destroy(tex);
	if (!ok) {
		return false;
	}
	round_corners(mem_data(buf), ow, ow, oh, b->radius);
	show(b, buf, ow, oh);
	return true;
}

/* ---- gles2: dual Kawase ---- */

static const char *vs_src =
	"attribute vec2 pos;\n"
	"varying vec2 uv;\n"
	"void main() { uv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }\n";

static const char *down_src =
	"precision mediump float;\n"
	"uniform sampler2D tex; uniform vec2 half_px; uniform float offset; varying vec2 uv;\n"
	"void main() {\n"
	"  vec2 o = half_px * offset;\n"
	"  vec4 s = texture2D(tex, uv) * 4.0;\n"
	"  s += texture2D(tex, uv - o) + texture2D(tex, uv + o);\n"
	"  s += texture2D(tex, uv + vec2(o.x, -o.y)) + texture2D(tex, uv - vec2(o.x, -o.y));\n"
	"  gl_FragColor = s / 8.0;\n"
	"}\n";

#define UP_BODY \
	"  vec2 o = half_px * offset;\n" \
	"  vec4 s = texture2D(tex, uv + vec2(-o.x * 2.0, 0.0));\n" \
	"  s += texture2D(tex, uv + vec2(-o.x, o.y)) * 2.0;\n" \
	"  s += texture2D(tex, uv + vec2(0.0, o.y * 2.0));\n" \
	"  s += texture2D(tex, uv + vec2(o.x, o.y)) * 2.0;\n" \
	"  s += texture2D(tex, uv + vec2(o.x * 2.0, 0.0));\n" \
	"  s += texture2D(tex, uv + vec2(o.x, -o.y)) * 2.0;\n" \
	"  s += texture2D(tex, uv + vec2(0.0, -o.y * 2.0));\n" \
	"  s += texture2D(tex, uv + vec2(-o.x, -o.y)) * 2.0;\n" \
	"  s /= 12.0;\n"

static const char *up_src =
	"precision mediump float;\n"
	"uniform sampler2D tex; uniform vec2 half_px; uniform float offset; varying vec2 uv;\n"
	"void main() {\n" UP_BODY "  gl_FragColor = s;\n}\n";

/* posledni pruchod nahoru: saturace a zaobleny obdelnik (vyhlazena hrana) */
static const char *final_src =
	"precision mediump float;\n"
	"uniform sampler2D tex; uniform vec2 half_px; uniform float offset; varying vec2 uv;\n"
	"uniform float sat; uniform vec2 size; uniform float radius;\n"
	"void main() {\n" UP_BODY
	"  float l = dot(s.rgb, vec3(0.2126, 0.7152, 0.0722));\n"
	"  vec3 c = clamp(mix(vec3(l), s.rgb, sat), 0.0, 1.0);\n"
	"  vec2 q = abs(uv * size - size * 0.5) - (size * 0.5 - vec2(radius));\n"
	"  float d = length(max(q, 0.0)) - radius;\n"
	"  gl_FragColor = vec4(c, 1.0) * clamp(0.5 - d, 0.0, 1.0);\n"
	"}\n";

static GLuint
shader(GLenum type, const char *src)
{
	GLuint s = glCreateShader(type);
	glShaderSource(s, 1, &src, NULL);
	glCompileShader(s);
	GLint ok = 0;
	glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
	if (!ok) {
		char log[512] = "";
		glGetShaderInfoLog(s, sizeof(log), NULL, log);
		wlr_log(WLR_ERROR, "luxcomp: blur shader: %s", log);
		glDeleteShader(s);
		return 0;
	}
	return s;
}

static GLuint
program(const char *fs_src)
{
	GLuint vs = shader(GL_VERTEX_SHADER, vs_src), fs = shader(GL_FRAGMENT_SHADER, fs_src);
	if (!vs || !fs) {
		return 0;
	}
	GLuint p = glCreateProgram();
	glAttachShader(p, vs);
	glAttachShader(p, fs);
	glLinkProgram(p);
	glDeleteShader(vs);
	glDeleteShader(fs);
	GLint ok = 0;
	glGetProgramiv(p, GL_LINK_STATUS, &ok);
	if (!ok) {
		glDeleteProgram(p);
		return 0;
	}
	return p;
}

static bool
gl_setup(void)
{
	if (cfg.gl_ready) {
		return true;
	}
	const char *src[3] = { down_src, up_src, final_src };
	for (int i = 0; i < 3; i++) {
		cfg.prog[i] = program(src[i]);
		if (!cfg.prog[i]) {
			return false;
		}
		cfg.u_tex[i] = glGetUniformLocation(cfg.prog[i], "tex");
		cfg.u_half[i] = glGetUniformLocation(cfg.prog[i], "half_px");
		cfg.u_off[i] = glGetUniformLocation(cfg.prog[i], "offset");
		cfg.a_pos[i] = glGetAttribLocation(cfg.prog[i], "pos");
	}
	cfg.u_sat = glGetUniformLocation(cfg.prog[2], "sat");
	cfg.u_size = glGetUniformLocation(cfg.prog[2], "size");
	cfg.u_radius = glGetUniformLocation(cfg.prog[2], "radius");
	static const GLfloat quad[] = { -1, -1, 1, -1, -1, 1, 1, 1 };
	glGenBuffers(1, &cfg.vbo);
	glBindBuffer(GL_ARRAY_BUFFER, cfg.vbo);
	glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
	glBindBuffer(GL_ARRAY_BUFFER, 0);
	cfg.gl_ready = true;
	return true;
}

/* Jeden pruchod: textura z bufferu src do FBO bufferu dst */
static bool
gl_pass(int prog, struct wlr_buffer *src, int src_w, int src_h, struct wlr_buffer *dst,
		int dst_w, int dst_h, double scale, int radius)
{
	struct wlr_texture *tex = wlr_texture_from_buffer(comp.renderer, src);
	if (!tex) {
		return false;
	}
	struct wlr_gles2_texture_attribs attr;
	wlr_gles2_texture_get_attribs(tex, &attr);
	GLuint fbo = wlr_gles2_renderer_get_buffer_fbo(comp.renderer, dst);
	if (attr.target != GL_TEXTURE_2D || !fbo) {
		wlr_texture_destroy(tex);
		return false;
	}
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glViewport(0, 0, dst_w, dst_h);
	glUseProgram(cfg.prog[prog]);
	glActiveTexture(GL_TEXTURE0);
	glBindTexture(GL_TEXTURE_2D, attr.tex);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glUniform1i(cfg.u_tex[prog], 0);
	/* dolu polovina texelu cile, nahoru zdroje (Bjorge, Bandwidth-efficient rendering) */
	if (prog == 0) {
		glUniform2f(cfg.u_half[prog], 0.5f / dst_w, 0.5f / dst_h);
	} else {
		glUniform2f(cfg.u_half[prog], 0.5f / src_w, 0.5f / src_h);
	}
	glUniform1f(cfg.u_off[prog], (GLfloat)scale);
	if (prog == 2) {
		glUniform1f(cfg.u_sat, cfg.saturation / 100.0f);
		glUniform2f(cfg.u_size, (GLfloat)dst_w, (GLfloat)dst_h);
		glUniform1f(cfg.u_radius, (GLfloat)radius);
	}
	glBindBuffer(GL_ARRAY_BUFFER, cfg.vbo);
	glEnableVertexAttribArray(cfg.a_pos[prog]);
	glVertexAttribPointer(cfg.a_pos[prog], 2, GL_FLOAT, GL_FALSE, 0, 0);
	glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
	glDisableVertexAttribArray(cfg.a_pos[prog]);
	glBindBuffer(GL_ARRAY_BUFFER, 0);
	glBindTexture(GL_TEXTURE_2D, 0);
	wlr_texture_destroy(tex);
	return glGetError() == GL_NO_ERROR;
}

static struct wlr_buffer *
gl_buffer(struct output *o, int w, int h)
{
	struct wlr_swapchain *sc = o->wlr_output->swapchain;
	if (!sc || !comp.allocator) {
		return NULL;
	}
	/* stejne modifikatory jako snimky vystupu (ty renderer umi), ale s alfou kvuli rohum */
	struct wlr_drm_format fmt = sc->format;
	fmt.format = DRM_FORMAT_ARGB8888;
	return wlr_allocator_create_buffer(comp.allocator, w, h, &fmt);
}

static bool
blur_gpu(struct blur *b, struct output *o, struct wlr_box abs)
{
	double scale = o->wlr_output->scale;
	struct wlr_box cap = capture_box(b, o, abs);
	int w0 = (int)ceil(cap.width * scale), h0 = (int)ceil(cap.height * scale);
	if (!b->level[0] || b->lw[0] != w0 || b->lh[0] != h0) {
		free_levels(b);
		for (int i = 0; i <= LEVELS; i++) {
			b->lw[i] = w0 >> i > 0 ? w0 >> i : 1;
			b->lh[i] = h0 >> i > 0 ? h0 >> i : 1;
			b->level[i] = gl_buffer(o, b->lw[i], b->lh[i]);
			if (!b->level[i]) {
				return false;
			}
		}
	}
	struct walk w = { .stop = &b->parent->node, .box = cap, .k = scale };
	w.pass = wlr_renderer_begin_buffer_pass(comp.renderer, b->level[0], NULL);
	if (!w.pass) {
		return false;
	}
	wlr_render_pass_add_rect(w.pass, &(struct wlr_render_rect_options){
		.box = { 0, 0, w0, h0 }, .color = { 0, 0, 0, 1 },
		.blend_mode = WLR_RENDER_BLEND_MODE_NONE,
	});
	walk_scene(&w);
	bool ok = wlr_render_pass_submit(w.pass);
	for (int i = 0; i < w.n_temp; i++) {
		wlr_texture_destroy(w.temp[i]);
	}
	if (!ok) {
		return false;
	}

	int ow = (int)ceil(abs.width * scale), oh = (int)ceil(abs.height * scale);
	struct wlr_buffer *out = next_out(b, o, ow, oh, true);
	if (!out) {
		return false;
	}
	struct wlr_egl *egl = wlr_gles2_renderer_get_egl(comp.renderer);
	EGLDisplay dpy = wlr_egl_get_display(egl);
	EGLContext prev = eglGetCurrentContext();
	EGLSurface prev_draw = eglGetCurrentSurface(EGL_DRAW), prev_read = eglGetCurrentSurface(EGL_READ);
	if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, wlr_egl_get_context(egl))) {
		return false;
	}
	ok = gl_setup();
	glDisable(GL_BLEND);
	glDisable(GL_SCISSOR_TEST);
	/* offset 1.0 na kazde urovni: 4 pruchody davaji efektivni polomer ~2^4 * 2 = 32 px */
	double off = cfg.radius / 32.0;
	for (int i = 0; ok && i < LEVELS; i++) {
		ok = gl_pass(0, b->level[i], b->lw[i], b->lh[i], b->level[i + 1], b->lw[i + 1], b->lh[i + 1],
			off, 0);
	}
	for (int i = LEVELS; ok && i > 1; i--) {
		ok = gl_pass(1, b->level[i], b->lw[i], b->lh[i], b->level[i - 1], b->lw[i - 1], b->lh[i - 1],
			off, 0);
	}
	/* posledni pruchod rovnou do vysledku: jen cast vyrezu pod plochou */
	if (ok) {
		ok = gl_pass(2, b->level[1], b->lw[1], b->lh[1], out, ow, oh, off,
			(int)(b->radius * scale));
	}
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glUseProgram(0);
	glFlush();
	eglMakeCurrent(dpy, prev_draw, prev_read, prev);
	if (!ok) {
		return false;
	}
	show(b, out, ow, oh);
	return true;
}

/* ---- snimek vystupu ---- */

static bool
on_output(struct blur *b, struct output *o, struct wlr_box *abs)
{
	int x, y;
	if (!b->node || !b->node->node.enabled || !wlr_scene_node_coords(&b->node->node, &x, &y)) {
		return false;
	}
	*abs = (struct wlr_box){ x, y, b->box.width, b->box.height };
	struct wlr_box out, hit;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &out);
	/* plocha patri vystupu, na kterem je vetsina z ni (stred) */
	return wlr_box_intersection(&hit, abs, &out)
		&& wlr_box_contains_point(&out, abs->x + abs->width / 2.0, abs->y + abs->height / 2.0);
}

/* Pred vykreslenim snimku vystupu: prepocitat plochy, pod kterymi se neco zmenilo. Vraci true,
 * kdyz se nejaka prepocitala (snimek se pak pocita do rozpoctu). */
bool
blur_output_frame(struct output *o)
{
	bool worked = false;
	int64_t t0 = now_ns();
	struct blur *b;
	wl_list_for_each(b, &blurs, link) {
		struct wlr_box abs;
		if (!on_output(b, o, &abs)) {
			continue;
		}
		bool solid = luxcomp_blur_tier() == 0;
		struct wlr_box cap = solid ? abs : capture_box(b, o, abs);
		struct walk w = { .stop = &b->parent->node, .box = cap };
		if (!solid) {
			walk_scene(&w);
		}
		mix(&w.sig, ((uint64_t)(uint32_t)abs.x << 32) | (uint32_t)abs.y);
		mix(&w.sig, ((uint64_t)(uint32_t)abs.width << 32) | (uint32_t)abs.height);
		mix(&w.sig, (uint64_t)(o->wlr_output->scale * 1000) << 1 | solid);
		if (!b->dirty && w.sig == b->sig) {
			continue;
		}
		b->sig = w.sig;
		b->dirty = false;
		worked = true;
		bool ok = false;
		if (!solid) {
			ok = comp.software ? blur_cpu(b, o, abs) : blur_gpu(b, o, abs);
			if (!ok && !comp.software && !cfg.gpu_broken) {
				wlr_log(WLR_ERROR, "luxcomp: gles2 blur failed, solid material from now on");
				cfg.gpu_broken = true;
			}
		}
		if (!ok) {
			paint_solid(b, o);
		}
		b->solid = !ok;
	}
	if (worked && cfg.stats) {
		int64_t ns = now_ns() - t0;
		cfg.updates++;
		cfg.blur_sum_ns += ns;
		if (ns > cfg.blur_max_ns) {
			cfg.blur_max_ns = ns;
		}
	}
	return worked;
}

/* Cas celeho snimku (prepocet + vykresleni); tri pomale snimky s prepoctem po sobe = jednolita barva */
void
blur_frame_time(struct output *o, int64_t ns, bool worked)
{
	if (worked && comp.software && !degraded) {
		const char *env = getenv("LUXCOMP_BLUR_SLOW_MS");
		int64_t budget = env ? atoll(env) * 1000000 : SLOW_NS;
		slow_frames = ns > budget ? slow_frames + 1 : 0;
		if (slow_frames >= SLOW_FRAMES) {
			degraded = true;
			wlr_log(WLR_ERROR, "luxcomp: blur frames over %ld ms on %s, solid material from now on",
				(long)(budget / 1000000), o->wlr_output->name);
			struct blur *b;
			wl_list_for_each(b, &blurs, link) {
				b->dirty = true;
			}
			wlr_output_schedule_frame(o->wlr_output);
		}
	}
	if (!cfg.stats || wl_list_empty(&blurs)) {
		return;
	}
	cfg.frames++;
	cfg.sum_ns += ns;
	if (ns > cfg.max_ns) {
		cfg.max_ns = ns;
	}
	if (cfg.frames % 120 == 0) {
		fprintf(stderr, "luxcomp: blur stats tier %ld frames %d max %.2f ms avg %.2f ms, "
			"updates %d max %.2f ms avg %.2f ms\n", (long)luxcomp_blur_tier(), cfg.frames,
			cfg.max_ns / 1e6, cfg.sum_ns / 1e6 / cfg.frames, cfg.updates, cfg.blur_max_ns / 1e6,
			cfg.updates ? cfg.blur_sum_ns / 1e6 / cfg.updates : 0.0);
		cfg.frames = cfg.updates = 0;
		cfg.max_ns = cfg.sum_ns = cfg.blur_max_ns = cfg.blur_sum_ns = 0;
	}
}
