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
 * v poslednim saturace a zaobleni. pixman: zachyceni ve ctvrtinovem rozliseni, trikrat box blur v C;
 * plochu bez zaobleni zvetsuje scena pri skladani snimku, jinak renderer a zaobleni rohu.
 *
 * pixman navic drzi pro kazdy vystup rozmazanou tapetu (vrstva pozadi, pocita se jen pri jeji zmene).
 * Plocha, pod kterou neni nic nez tapeta, je jen jeji vyrez. Kdyz prepocet jedne plochy trva tri snimky
 * po sobe pres rozpocet, plocha docasne prejde na tentyz vyrez (sklo bez oken pod nim) a pozdeji zkusi
 * rozmazani znovu. Jednolita barva materialu (tier 0) jen pri vypnutem rozmazani a chybe GLES2.
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
#include <wlr/util/addon.h>
#include <wlr/util/log.h>
#include "internal.h"

#define MAX_MATERIALS 16
#define LEVELS 4		/* dual Kawase: pruchody dolu = pruchody nahoru */
#define DOWN 4			/* pixman: zmenseni vyrezu */
#define SLOW_NS 8000000	/* rozpocet prepoctu jedne plochy pod pixman; testy: LUXCOMP_BLUR_SLOW_MS */
#define SLOW_FRAMES 3		/* pomale prepocty po sobe ... */
#define BURST_NS 500000000LL	/* ... kazdy do 0,5 s od predchoziho */
#define RETRY_MS 2000		/* nahradni vyrez, pak znovu rozmazani; pri dalsim neuspechu dvojnasob */
#define RETRY_MAX_MS 32000
#define CALM_NS 30000000000LL	/* tak dlouho bez neuspechu = cekani zase od RETRY_MS */

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
	GLint u_tex[3], u_half[3], u_off[3], u_sat, u_size, u_radii, u_box, a_pos[3];
	/* LUXCOMP_STATS */
	bool stats;
	int frames, updates, over;
	int64_t max_ns, sum_ns, blur_max_ns, blur_sum_ns;
	int fallbacks;
} cfg = { .radius = 32, .saturation = 160, .mode = 1 };

struct blur {
	struct wl_list link;
	struct wlr_scene_tree *parent;
	struct wlr_scene_buffer *node;
	struct shadow *shadow;
	char material[16];
	int radius;
	struct wlr_box box;		/* v souradnicich parent */
	struct wlr_scene_node *stop;	/* zachyceni sceny konci pred timto uzlem (parent, u okna strom okna) */
	int corners;			/* zaoblene rohy, CORNER_* */
	bool flat;			/* material v okne: bez vlastniho stinu */
	uint64_t sig;
	bool dirty;
	/* pixman: pomale prepocty po sobe, nahradni vyrez tapety do retry_at (0 = rozmazani) */
	int slow, backoff_ms;
	int64_t last_ns, retry_at, glass_since;
	struct wlr_buffer *out[2];	/* hotovy obraz, stridave (scena drzi predchozi) */
	int cur, out_w, out_h;
	bool out_gpu;			/* out[] z alokatoru (gles2), jinak v pameti */
	/* pixman: ctvrtinovy vyrez */
	struct wlr_buffer *small;
	int small_w, small_h;
	/* gles2: urovne dual Kawase, 0 = zachyceni */
	struct wlr_buffer *level[LEVELS + 1];
	int lw[LEVELS + 1], lh[LEVELS + 1];
	GLuint ltex[LEVELS + 1], lfbo[LEVELS + 1];	/* zijou s bufferem (doplnek wlroots) */
	struct wl_listener parent_destroy;
};

static struct wl_list blurs = { &blurs, &blurs };
static struct wl_event_source *retry_timer;

enum { CORNER_TL = 1, CORNER_TR = 2, CORNER_BR = 4, CORNER_BL = 8, CORNER_ALL = 15 };

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
	/* bez wlr_buffer_finish by renderer pixman drzel obraz bufferu v mezipameti a pristi buffer na stejne
	 * adrese by kreslil do uvolnene pameti */
	wlr_buffer_finish(b);
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
	/* zmena rezimu meni barvy vsech materialu: rozmazany obraz na nich nezavisi, prepocet jen pro jednolitou
	 * barvu (jinak by se po prepnuti pocitaly vsechny plochy naraz) */
	bool repaint = m->fallback != (uint32_t)fallback;
	m->radius = radius;
	m->fallback = (uint32_t)fallback;
	m->shadow = (uint32_t)shadow;
	m->shadow_size = shadow_size;
	m->shadow_y = shadow_y;
	struct blur *b;
	wl_list_for_each(b, &blurs, link) {
		if (!strcmp(b->material, name)) {
			b->dirty |= repaint && luxcomp_blur_tier() == 0;
			blur_set_box(b, b->box);
		}
	}
}

void
luxcomp_blur_set(int64_t radius, int64_t saturation_pct, int64_t mode)
{
	radius = radius > 0 ? radius : 32;
	saturation_pct = saturation_pct > 0 ? saturation_pct : 100;
	mode = mode ? 1 : 0;
	if (radius == cfg.radius && saturation_pct == cfg.saturation && mode == cfg.mode) {
		return;
	}
	cfg.radius = radius;
	cfg.saturation = saturation_pct;
	cfg.mode = mode;
	struct blur *b;
	wl_list_for_each(b, &blurs, link) {
		b->dirty = true;
		b->retry_at = 0;
		b->slow = b->backoff_ms = 0;
	}
}

/* 2 = gles2 shadery, 1 = pixman v C, 0 = jednolita barva */
int64_t
luxcomp_blur_tier(void)
{
	if (!cfg.mode || cfg.gpu_broken) {
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
	b->stop = NULL;
}

struct blur *
blur_create(struct wlr_scene_tree *parent, const char *material, int radius)
{
	struct blur *b = calloc(1, sizeof(*b));
	b->parent = parent;
	snprintf(b->material, sizeof(b->material), "%s", material);
	b->radius = radius;
	b->stop = &parent->node;
	b->corners = CORNER_ALL;
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
	shadow_update(b->shadow, box, m && !b->flat ? m->shadow_size : 0, m ? m->shadow_y : 0, r, m ? m->shadow : 0, 1, true);
}

/* ---- material plochy layer-shell: obdelniky vstupni oblasti ---- */

/* Sklo je tam, kam jde kliknout: kazdy obdelnik vstupni oblasti povrchu (vychozi = cely povrch, Dock si
 * nastavi jen panel, oznameni jen bubliny). Obdelniky tenci nez MIN_SIDE (horka hrana skryteho Docku)
 * material nemaji. */
#define MIN_SIDE 8

/* Obdelnik, ktery primo lezi na sirsim obdelniku pod sebou, je vystupek (zvetsene ikony Docku nad panelem):
 * jde na nej kliknout, ale sklo zustava jen panel, jinak by se s ikonou zvedl cely panel */
static bool
raised(const pixman_box32_t *r, const pixman_box32_t *rects, int count)
{
	for (int i = 0; i < count; i++) {
		const pixman_box32_t *s = &rects[i];
		if (s->y1 == r->y2 && s->x1 <= r->x1 && s->x2 >= r->x2 && s->x2 - s->x1 > r->x2 - r->x1) {
			return true;
		}
	}
	return false;
}

void
blur_set_update(struct blur_set *set, struct wlr_scene_tree *parent, const pixman_region32_t *input,
		int width, int height)
{
	pixman_region32_t region;
	pixman_region32_init(&region);
	pixman_region32_intersect_rect(&region, input, 0, 0, width, height);
	int n = 0, count = 0;
	const pixman_box32_t *rects = pixman_region32_rectangles(&region, &count);
	for (int i = 0; i < count && n < BLUR_SET_MAX; i++) {
		struct wlr_box box = { rects[i].x1, rects[i].y1, rects[i].x2 - rects[i].x1, rects[i].y2 - rects[i].y1 };
		if (box.width < MIN_SIDE || box.height < MIN_SIDE || raised(&rects[i], rects, count)) {
			continue;
		}
		if (!set->blur[n]) {
			set->blur[n] = blur_create(parent, set->material, set->radius);
		}
		blur_set_box(set->blur[n++], box);
	}
	pixman_region32_fini(&region);
	for (int i = n; i < BLUR_SET_MAX; i++) {
		blur_destroy(set->blur[i]);
		set->blur[i] = NULL;
	}
}

void
blur_set_clear(struct blur_set *set)
{
	for (int i = 0; i < BLUR_SET_MAX; i++) {
		blur_destroy(set->blur[i]);
		set->blur[i] = NULL;
	}
}

/* ---- co je pod plochou ---- */

struct walk {
	struct wlr_scene_node *stop;
	struct wlr_box box;		/* vyrez v souradnicich rozlozeni */
	bool done;
	uint64_t sig;
	/* od uzlu backdrop_end dal (nad vrstvou pozadi) neco zasahuje do vyrezu */
	struct wlr_scene_node *backdrop_end;
	bool past, covered;
	/* kresleni; pass NULL = jen podpis */
	struct wlr_render_pass *pass;
	double k;			/* px vyrezu na logicky px */
	struct wlr_texture **temp;
	int n_temp, max_temp;
};

/* Textury bufferu, ktere nejsou klientske (zahlavi, stiny oken): gles2 by je pri kazdem prepoctu nahraval do GPU
 * znovu (64 textur pod ztmavenim Launchpadu ~9 ms). Textura zije s bufferem; jen pro buffery v pameti, textura
 * z dmabuf (pixman i gles2 z dmabuf) buffer zamyka, takze by se nikdy neuvolnil. */
struct tex_cache {
	struct wlr_addon addon;
	struct wlr_texture *texture;
};

static void
tex_cache_destroy(struct wlr_addon *addon)
{
	struct tex_cache *c = wl_container_of(addon, c, addon);
	wlr_addon_finish(addon);
	wlr_texture_destroy(c->texture);
	free(c);
}

static const struct wlr_addon_interface tex_cache_impl = {
	.name = "luxcomp-blur-texture",
	.destroy = tex_cache_destroy,
};

static struct wlr_texture *
cached_texture(struct wlr_buffer *buffer)
{
	struct wlr_dmabuf_attributes dmabuf;
	if (!wlr_renderer_is_gles2(comp.renderer) || wlr_buffer_get_dmabuf(buffer, &dmabuf)) {
		return NULL;
	}
	struct wlr_addon *addon = wlr_addon_find(&buffer->addons, &blurs, &tex_cache_impl);
	if (addon) {
		struct tex_cache *c = wl_container_of(addon, c, addon);
		return c->texture;
	}
	struct wlr_texture *texture = wlr_texture_from_buffer(comp.renderer, buffer);
	if (!texture) {
		return NULL;
	}
	struct tex_cache *c = calloc(1, sizeof(*c));
	c->texture = texture;
	wlr_addon_init(&c->addon, &buffer->addons, &blurs, &tex_cache_impl);
	return texture;
}

/* Buffer se bude prepisovat (vlastni hotovy obraz materialu): textura v mezipameti by byla stara */
static void
forget_texture(struct wlr_buffer *buffer)
{
	struct wlr_addon *addon = wlr_addon_find(&buffer->addons, &blurs, &tex_cache_impl);
	if (addon) {
		tex_cache_destroy(addon);
	}
}

static void
free_temp(struct walk *w)
{
	for (int i = 0; i < w->n_temp; i++) {
		wlr_texture_destroy(w->temp[i]);
	}
	free(w->temp);
}

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
	w->covered |= w->past;
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
	} else if (!(tex = cached_texture(sb->buffer))) {
		tex = wlr_texture_from_buffer(comp.renderer, sb->buffer);
		if (tex && w->n_temp == w->max_temp) {
			w->max_temp = w->max_temp ? 2 * w->max_temp : 16;
			w->temp = realloc(w->temp, w->max_temp * sizeof(*w->temp));
		}
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
	w->past |= node == w->backdrop_end;
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
		w->covered |= w->past;
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

/* Alfa pixelu (x, y) obdelniku w x h se zaoblenymi rohy r (jen rohy v masce CORNER_*); vyhlazena hrana */
static double
corner_alpha(int x, int y, int w, int h, double r, int corners)
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
	int corner = cy < r ? (cx < r ? CORNER_TL : CORNER_TR) : (cx < r ? CORNER_BL : CORNER_BR);
	if (!(corners & corner)) {
		return 1;
	}
	double d = sqrt(dx * dx + dy * dy) - r;
	return d <= -0.5 ? 1 : d >= 0.5 ? 0 : 0.5 - d;
}

/* Zaobleni rohu hotoveho obrazu: jen ctverce r x r v rozich */
static void
round_corners(uint32_t *px, int stride, int w, int h, int r, int corners)
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
			double a = corner_alpha(x, y, w, h, r, corners);
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

/* Rozmazany material neni pro scenu nepruhledny: co je pod nim, je videt (rozmazane). Scena by jinak poskozeni
 * pod nim zahodila a nekreslila snimek (pohyb okna cele pod ztmavenim Launchpadu, video pod vyskakovacim oknem
 * by zustaly v materialu stare) a zakrytym klientum by neposilala frame done. Nepruhledna je jen jednolita barva. */
static void
set_opaque(struct blur *b, int w, int h, bool opaque)
{
	pixman_region32_t region;
	int r = b->radius;
	pixman_region32_init(&region);
	if (opaque) {
		pixman_region32_union_rect(&region, &region, 0, r, w, h > 2 * r ? h - 2 * r : 0);
		pixman_region32_union_rect(&region, &region, r, 0, w > 2 * r ? w - 2 * r : 0, h);
	}
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
	} else {
		forget_texture(b->out[b->cur]);
	}
	return b->out[b->cur];
}

/* src = vyrez bufferu (ctvrtinove rozliseni, zvetsi scena), NULL = cely */
static void
show(struct blur *b, struct wlr_buffer *buffer, const struct wlr_fbox *src, bool solid)
{
	wlr_scene_buffer_set_buffer(b->node, buffer);
	wlr_scene_buffer_set_source_box(b->node, src);
	wlr_scene_buffer_set_dest_size(b->node, b->box.width, b->box.height);
	wlr_scene_buffer_set_filter_mode(b->node, WLR_SCALE_FILTER_BILINEAR);
	set_opaque(b, b->box.width, b->box.height, solid);
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
	round_corners(px, w, w, h, b->radius, b->corners);
	show(b, buf, NULL, true);
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

static int
quarter(int n)
{
	return (n + DOWN - 1) / DOWN;
}

/* Scena pod stop ve vyrezu cap rozmazana do dst (ctvrtinove rozliseni cap) */
static bool
quarter_blur(struct wlr_buffer *dst, struct wlr_box cap, struct wlr_scene_node *stop)
{
	int sw = dst->width, sh = dst->height;
	struct walk w = { .stop = stop, .box = cap, .k = 1.0 / DOWN };
	w.pass = wlr_renderer_begin_buffer_pass(comp.renderer, dst, NULL);
	if (!w.pass) {
		return false;
	}
	wlr_render_pass_add_rect(w.pass, &(struct wlr_render_rect_options){
		.box = { 0, 0, sw, sh }, .color = { 0, 0, 0, 1 },
		.blend_mode = WLR_RENDER_BLEND_MODE_NONE,
	});
	walk_scene(&w);
	bool ok = wlr_render_pass_submit(w.pass);
	free_temp(&w);
	if (!ok) {
		return false;
	}
	/* tri box blury ~ gauss; polomer je v logickych px, tady ve ctvrtinach */
	int r = cfg.radius / (2 * DOWN);
	r = r < 1 ? 1 : r;
	uint32_t *px = mem_data(dst);
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
	return true;
}

/* Cast ctvrtinoveho obrazu small (pokryva cap) pod plochou abs */
static struct wlr_fbox
part(struct wlr_box cap, struct wlr_box abs)
{
	return (struct wlr_fbox){ (double)(abs.x - cap.x) / DOWN, (double)(abs.y - cap.y) / DOWN,
		(double)abs.width / DOWN, (double)abs.height / DOWN };
}

/* Plocha cela ve vyrezu: zvetsi ji az scena pri skladani snimku (lista, ztmaveni Launchpadu) */
static bool
inside(struct wlr_box cap, struct wlr_box abs)
{
	struct wlr_box vis;
	return wlr_box_intersection(&vis, &abs, &cap) && wlr_box_equal(&vis, &abs);
}

/* Zvetseni rendererem (bilinearne) na plnou velikost plochy, pak rohy. Cast mimo vyrez (okno pri prejezdu
 * plochy, na kraji obrazovky) obraz nema: tam barva materialu */
static bool
upscale(struct blur *b, struct output *o, struct wlr_buffer *small, struct wlr_box cap, struct wlr_box abs)
{
	int ow = abs.width, oh = abs.height;
	struct wlr_box vis;
	if (!wlr_box_intersection(&vis, &abs, &cap)) {
		return false;
	}
	struct wlr_buffer *buf = next_out(b, o, ow, oh, false);
	struct wlr_texture *tex = wlr_texture_from_buffer(comp.renderer, small);
	struct wlr_render_pass *pass = tex ? wlr_renderer_begin_buffer_pass(comp.renderer, buf, NULL) : NULL;
	if (!pass) {
		if (tex) {
			wlr_texture_destroy(tex);
		}
		return false;
	}
	if (!wlr_box_equal(&vis, &abs)) {
		const struct material *m = material_find(b->material);
		uint32_t c = m ? m->fallback : 0xfff6f7fc;
		wlr_render_pass_add_rect(pass, &(struct wlr_render_rect_options){
			.box = { 0, 0, ow, oh },
			.color = { (c >> 16 & 0xff) / 255.0f, (c >> 8 & 0xff) / 255.0f, (c & 0xff) / 255.0f, 1 },
			.blend_mode = WLR_RENDER_BLEND_MODE_NONE,
		});
	}
	wlr_render_pass_add_texture(pass, &(struct wlr_render_texture_options){
		.texture = tex,
		.src_box = part(cap, vis),
		.dst_box = { vis.x - abs.x, vis.y - abs.y, vis.width, vis.height },
		.filter_mode = WLR_SCALE_FILTER_BILINEAR,
		.blend_mode = WLR_RENDER_BLEND_MODE_NONE,
	});
	bool ok = wlr_render_pass_submit(pass);
	wlr_texture_destroy(tex);
	if (!ok) {
		return false;
	}
	round_corners(mem_data(buf), ow, ow, oh, b->radius, b->corners);
	show(b, buf, NULL, false);
	return true;
}

static bool
blur_cpu(struct blur *b, struct output *o, struct wlr_box abs)
{
	struct wlr_box cap = capture_box(b, o, abs);
	int sw = quarter(cap.width), sh = quarter(cap.height);
	if (b->radius <= 0 && inside(cap, abs)) {
		struct wlr_buffer *buf = next_out(b, o, sw, sh, false);
		if (!quarter_blur(buf, cap, b->stop)) {
			return false;
		}
		struct wlr_fbox src = part(cap, abs);
		show(b, buf, &src, false);
		return true;
	}
	if (!b->small || b->small_w != sw || b->small_h != sh) {
		drop(&b->small);
		b->small = mem_create(sw, sh);
		b->small_w = sw;
		b->small_h = sh;
	}
	return quarter_blur(b->small, cap, b->stop) && upscale(b, o, b->small, cap, abs);
}

/* ---- pixman: rozmazana tapeta vystupu ---- */

struct backdrop {
	struct wlr_addon addon;		/* u wlr_output */
	struct wlr_buffer *small;	/* ctvrtinove rozliseni, novy buffer pri kazde zmene (scena drzi stary) */
	struct wlr_box box;		/* vystup v souradnicich rozlozeni */
	uint64_t sig;
};

static void
backdrop_destroy(struct wlr_addon *addon)
{
	struct backdrop *bd = wl_container_of(addon, bd, addon);
	wlr_addon_finish(addon);
	drop(&bd->small);
	free(bd);
}

static const struct wlr_addon_interface backdrop_impl = {
	.name = "luxcomp-backdrop",
	.destroy = backdrop_destroy,
};

/* Vrstva pozadi vystupu rozmazana; prepocet jen kdyz se zmenila (tapeta, velikost) */
static struct backdrop *
backdrop_update(struct output *o)
{
	struct wlr_addon *addon = wlr_addon_find(&o->wlr_output->addons, &blurs, &backdrop_impl);
	struct backdrop *bd;
	if (addon) {
		bd = wl_container_of(addon, bd, addon);
	} else {
		bd = calloc(1, sizeof(*bd));
		wlr_addon_init(&bd->addon, &o->wlr_output->addons, &blurs, &backdrop_impl);
	}
	struct wlr_box box;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
	struct walk w = { .stop = &comp.layer_bottom->node, .box = box };
	walk_scene(&w);
	mix(&w.sig, ((uint64_t)(uint32_t)box.x << 32) | (uint32_t)box.y);
	mix(&w.sig, ((uint64_t)(uint32_t)box.width << 32) | (uint32_t)box.height);
	mix(&w.sig, ((uint64_t)cfg.radius << 32) | (uint32_t)cfg.saturation);
	if (bd->small && w.sig == bd->sig) {
		return bd;
	}
	struct wlr_buffer *small = mem_create(quarter(box.width), quarter(box.height));
	if (!quarter_blur(small, box, &comp.layer_bottom->node)) {
		wlr_buffer_drop(small);
		return bd->small ? bd : NULL;
	}
	drop(&bd->small);
	bd->small = small;
	bd->box = box;
	bd->sig = w.sig;
	return bd;
}

static bool
blur_backdrop(struct blur *b, struct output *o, struct backdrop *bd, struct wlr_box abs)
{
	if (b->radius > 0 || !inside(bd->box, abs)) {
		return upscale(b, o, bd->small, bd->box, abs);
	}
	struct wlr_fbox src = part(bd->box, abs);
	show(b, bd->small, &src, false);
	return true;
}

/* ---- pixman: pomale plochy ---- */

static int
retry_due(void *data)
{
	int64_t now = now_ns(), next = 0;
	struct blur *b;
	wl_list_for_each(b, &blurs, link) {
		if (b->retry_at && b->retry_at <= now) {
			b->dirty = true;
		} else if (b->retry_at && (!next || b->retry_at < next)) {
			next = b->retry_at;
		}
	}
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		wlr_output_schedule_frame(o->wlr_output);
	}
	if (next) {
		wl_event_source_timer_update(retry_timer, (int)((next - now) / 1000000) + 1);
	}
	return 0;
}

/* Cas prepoctu plochy pod pixman. Tri pomale po sobe (kazdy do BURST_NS od predchoziho: neco se pod plochou
 * hybe) = nahradni vyrez tapety na RETRY_MS, kazdy dalsi neuspech dvojnasob; jednotlivy pomaly prepocet
 * (otevreni Launchpadu, nova tapeta) nevadi. */
static void
note_cost(struct blur *b, struct output *o, int64_t ns, int64_t now)
{
	const char *env = getenv("LUXCOMP_BLUR_SLOW_MS");
	int64_t budget = env ? atoll(env) * 1000000 : SLOW_NS;
	bool burst = b->last_ns && now - b->last_ns < BURST_NS;
	b->last_ns = now;
	if (ns <= budget) {
		b->slow = 0;
		return;
	}
	b->slow = burst ? b->slow + 1 : 1;
	if (b->slow < SLOW_FRAMES) {
		return;
	}
	if (!b->backoff_ms || now - b->glass_since > CALM_NS) {
		b->backoff_ms = RETRY_MS;
	} else if (b->backoff_ms < RETRY_MAX_MS) {
		b->backoff_ms *= 2;
	}
	b->slow = 0;
	b->retry_at = now + b->backoff_ms * 1000000LL;
	b->dirty = true;
	cfg.fallbacks++;
	wlr_log(WLR_ERROR, "luxcomp: blur of %s %dx%d over %ld ms, wallpaper glass for %d s", b->material,
		b->box.width, b->box.height, (long)(budget / 1000000), b->backoff_ms / 1000);
	if (!retry_timer) {
		retry_timer = wl_event_loop_add_timer(comp.loop, retry_due, NULL);
	}
	retry_due(NULL);
	wlr_output_schedule_frame(o->wlr_output);
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

/* p = misto ve zdrojove texture */
#define UP_BODY \
	"  vec2 o = half_px * offset;\n" \
	"  vec4 s = texture2D(tex, p + vec2(-o.x * 2.0, 0.0));\n" \
	"  s += texture2D(tex, p + vec2(-o.x, o.y)) * 2.0;\n" \
	"  s += texture2D(tex, p + vec2(0.0, o.y * 2.0));\n" \
	"  s += texture2D(tex, p + vec2(o.x, o.y)) * 2.0;\n" \
	"  s += texture2D(tex, p + vec2(o.x * 2.0, 0.0));\n" \
	"  s += texture2D(tex, p + vec2(o.x, -o.y)) * 2.0;\n" \
	"  s += texture2D(tex, p + vec2(0.0, -o.y * 2.0));\n" \
	"  s += texture2D(tex, p + vec2(-o.x, -o.y)) * 2.0;\n" \
	"  s /= 12.0;\n"

static const char *up_src =
	"precision mediump float;\n"
	"uniform sampler2D tex; uniform vec2 half_px; uniform float offset; varying vec2 uv;\n"
	"void main() {\n  vec2 p = uv;\n" UP_BODY "  gl_FragColor = s;\n}\n";

/* posledni pruchod nahoru: jen cast vyrezu pod plochou (box = poloha a velikost plochy v texture vyrezu,
 * vyrez ma okraj o polomer rozmazani), saturace a zaobleny obdelnik (vyhlazena hrana); radii = polomery
 * rohu vlevo nahore, vpravo nahore, vpravo dole, vlevo dole (uv.y = 0 je horni radek) */
static const char *final_src =
	"precision mediump float;\n"
	"uniform sampler2D tex; uniform vec2 half_px; uniform float offset; varying vec2 uv;\n"
	"uniform float sat; uniform vec2 size; uniform vec4 radii; uniform vec4 box;\n"
	"void main() {\n  vec2 p = box.xy + uv * box.zw;\n" UP_BODY
	"  float l = dot(s.rgb, vec3(0.2126, 0.7152, 0.0722));\n"
	"  vec3 c = clamp(mix(vec3(l), s.rgb, sat), 0.0, 1.0);\n"
	"  vec2 h = uv.x < 0.5 ? radii.xw : radii.yz;\n"
	"  float radius = uv.y < 0.5 ? h.x : h.y;\n"
	"  vec2 q = abs(uv * size - size * 0.5) - (size * 0.5 - vec2(radius));\n"
	"  float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;\n"
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
	cfg.u_radii = glGetUniformLocation(cfg.prog[2], "radii");
	cfg.u_box = glGetUniformLocation(cfg.prog[2], "box");
	static const GLfloat quad[] = { -1, -1, 1, -1, -1, 1, 1, 1 };
	glGenBuffers(1, &cfg.vbo);
	glBindBuffer(GL_ARRAY_BUFFER, cfg.vbo);
	glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
	glBindBuffer(GL_ARRAY_BUFFER, 0);
	cfg.gl_ready = true;
	return true;
}

/* Textura a FBO bufferu urovne. wlroots je ma ulozene u bufferu, ale kazde wlr_texture_from_buffer znovu
 * pripoji EGLImage a prepina kontext EGL; na NVIDIA to stalo ~0,2 ms za pruchod. Kreslime do nich jen
 * my v kontextu rendereru, takze staci jednou. */
static bool
gl_target(struct wlr_buffer *buffer, GLuint *tex, GLuint *fbo)
{
	struct wlr_texture *t = wlr_texture_from_buffer(comp.renderer, buffer);
	if (!t) {
		return false;
	}
	struct wlr_gles2_texture_attribs attr;
	wlr_gles2_texture_get_attribs(t, &attr);
	wlr_texture_destroy(t);
	*tex = attr.target == GL_TEXTURE_2D ? attr.tex : 0;
	*fbo = wlr_gles2_renderer_get_buffer_fbo(comp.renderer, buffer);
	return *tex && *fbo;
}

/* Jeden pruchod: textura src do FBO dst */
static bool
gl_pass(int prog, GLuint src, int src_w, int src_h, GLuint fbo, int dst_w, int dst_h, double scale,
		const GLfloat radii[4], const GLfloat box[4])
{
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glViewport(0, 0, dst_w, dst_h);
	glUseProgram(cfg.prog[prog]);
	glActiveTexture(GL_TEXTURE0);
	glBindTexture(GL_TEXTURE_2D, src);
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
		glUniform4fv(cfg.u_radii, 1, radii);
		glUniform4fv(cfg.u_box, 1, box);
	}
	glBindBuffer(GL_ARRAY_BUFFER, cfg.vbo);
	glEnableVertexAttribArray(cfg.a_pos[prog]);
	glVertexAttribPointer(cfg.a_pos[prog], 2, GL_FLOAT, GL_FALSE, 0, 0);
	glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
	glDisableVertexAttribArray(cfg.a_pos[prog]);
	glBindBuffer(GL_ARRAY_BUFFER, 0);
	glBindTexture(GL_TEXTURE_2D, 0);
	return true;
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

/* Kontext rendereru nechame aktualni natrvalo: wlroots ho kolem kazdeho pruchodu nastavi a pak vrati
 * predchozi, a uvolneni kontextu stalo na NVIDIA 0,3-1,8 ms (flush) - nekolikrat za snimek. Kdyz je
 * aktualni porad, jsou ta prepnuti prazdna. Nikdo jiny v procesu EGL nepouziva. */
static bool
gl_current(void)
{
	struct wlr_egl *egl = wlr_gles2_renderer_get_egl(comp.renderer);
	EGLContext ctx = wlr_egl_get_context(egl);
	return eglGetCurrentContext() == ctx
		|| eglMakeCurrent(wlr_egl_get_display(egl), EGL_NO_SURFACE, EGL_NO_SURFACE, ctx);
}

static bool
blur_gpu(struct blur *b, struct output *o, struct wlr_box abs, struct wlr_scene_node *stop)
{
	if (!gl_current()) {
		return false;
	}
	double scale = o->wlr_output->scale;
	struct wlr_box cap = capture_box(b, o, abs);
	int w0 = (int)ceil(cap.width * scale), h0 = (int)ceil(cap.height * scale);
	if (!b->level[0] || b->lw[0] != w0 || b->lh[0] != h0) {
		free_levels(b);
		for (int i = 0; i <= LEVELS; i++) {
			b->lw[i] = w0 >> i > 0 ? w0 >> i : 1;
			b->lh[i] = h0 >> i > 0 ? h0 >> i : 1;
			b->level[i] = gl_buffer(o, b->lw[i], b->lh[i]);
			if (!b->level[i] || !gl_target(b->level[i], &b->ltex[i], &b->lfbo[i])) {
				free_levels(b);
				return false;
			}
		}
	}
	struct walk w = { .stop = stop, .box = cap, .k = scale };
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
	free_temp(&w);
	if (!ok) {
		return false;
	}

	int ow = (int)ceil(abs.width * scale), oh = (int)ceil(abs.height * scale);
	struct wlr_buffer *out = next_out(b, o, ow, oh, true);
	GLuint out_tex, out_fbo;	/* textura vysledku tu neni potreba */
	if (!out || !gl_target(out, &out_tex, &out_fbo)) {
		return false;
	}
	ok = gl_setup();
	while (glGetError() != GL_NO_ERROR) {
	}
	glDisable(GL_BLEND);
	glDisable(GL_SCISSOR_TEST);
	/* offset 1.0 na kazde urovni: 4 pruchody davaji efektivni polomer ~2^4 * 2 = 32 px */
	double off = cfg.radius / 32.0;
	for (int i = 0; ok && i < LEVELS; i++) {
		ok = gl_pass(0, b->ltex[i], b->lw[i], b->lh[i], b->lfbo[i + 1], b->lw[i + 1], b->lh[i + 1],
			off, NULL, NULL);
	}
	for (int i = LEVELS; ok && i > 1; i--) {
		ok = gl_pass(1, b->ltex[i], b->lw[i], b->lh[i], b->lfbo[i - 1], b->lw[i - 1], b->lh[i - 1],
			off, NULL, NULL);
	}
	/* posledni pruchod rovnou do vysledku: jen cast vyrezu pod plochou */
	if (ok) {
		const GLfloat box[4] = { (GLfloat)(abs.x - cap.x) / cap.width, (GLfloat)(abs.y - cap.y) / cap.height,
			(GLfloat)abs.width / cap.width, (GLfloat)abs.height / cap.height };
		GLfloat radii[4];
		for (int i = 0; i < 4; i++) {
			radii[i] = b->corners & 1 << i ? (GLfloat)(b->radius * scale) : 0;
		}
		ok = gl_pass(2, b->ltex[1], b->lw[1], b->lh[1], out_fbo, ow, oh, off, radii, box);
	}
	ok = ok && glGetError() == GL_NO_ERROR;
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glUseProgram(0);
	/* bez glFlush: scena kresli vysledek ve stejnem kontextu, poradi prikazu GL staci */
	if (!ok) {
		return false;
	}
	show(b, out, NULL, false);
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
 * kdyz se nejaka prepocitala. */
bool
blur_output_frame(struct output *o)
{
	bool worked = false, solid = luxcomp_blur_tier() == 0, tried = false;
	struct backdrop *bd = NULL;
	int64_t t0 = now_ns();
	struct blur *b;
	wl_list_for_each(b, &blurs, link) {
		struct wlr_box abs;
		if (!on_output(b, o, &abs) || node_under_fullscreen(&b->node->node, o)) {
			continue;
		}
		/* plocha pres cely vystup (ztmaveni Launchpadu a Hledani) rozmazava jen vrstvu pozadi, jako macOS a 1.0:
		 * okna pod ni nejsou videt a pod pixman by prepocet celeho vystupu stal cely snimek */
		struct wlr_box out, cap = solid ? abs : capture_box(b, o, abs);
		wlr_output_layout_get_box(comp.layout, o->wlr_output, &out);
		bool full = wlr_box_equal(&abs, &out);
		struct wlr_scene_node *stop = full ? &comp.layer_bottom->node : b->stop;
		struct walk w = { .stop = stop, .box = cap, .backdrop_end = &comp.layer_bottom->node };
		if (!solid) {
			walk_scene(&w);
		}
		/* pixman: vyrez rozmazane tapety, kdyz je pod plochou jen tapeta, a v nahradnim rezimu */
		bool from_backdrop = false;
		if (!solid && comp.software) {
			if (b->retry_at && t0 >= b->retry_at) {
				b->retry_at = 0;
				b->slow = 0;
				b->glass_since = t0;
			}
			if (b->retry_at || !w.covered) {
				if (!tried) {
					bd = backdrop_update(o);
					tried = true;
				}
				from_backdrop = bd != NULL;
			}
		}
		uint64_t sig = from_backdrop ? bd->sig : w.sig;
		mix(&sig, ((uint64_t)(uint32_t)abs.x << 32) | (uint32_t)abs.y);
		mix(&sig, ((uint64_t)(uint32_t)abs.width << 32) | (uint32_t)abs.height);
		mix(&sig, (uint64_t)(o->wlr_output->scale * 1000) << 2 | solid << 1 | from_backdrop);
		if (!b->dirty && sig == b->sig) {
			continue;
		}
		b->sig = sig;
		b->dirty = false;
		worked = true;
		bool ok = false;
		if (from_backdrop) {
			ok = blur_backdrop(b, o, bd, abs);
		} else if (!solid && comp.software) {
			int64_t t = now_ns();
			ok = blur_cpu(b, o, abs);
			int64_t done = now_ns();
			if (ok) {
				note_cost(b, o, done - t, done);
			}
		} else if (!solid) {
			ok = blur_gpu(b, o, abs, stop);
			if (!ok && !cfg.gpu_broken) {
				wlr_log(WLR_ERROR, "luxcomp: gles2 blur failed, solid material from now on");
				cfg.gpu_broken = true;
			}
		}
		if (!ok) {
			paint_solid(b, o);
		}
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

/* LUXCOMP_STATS: cas celeho snimku (prepocet + vykresleni) */
void
blur_frame_time(struct output *o, int64_t ns, bool worked)
{
	if (!cfg.stats || wl_list_empty(&blurs)) {
		return;
	}
	cfg.frames++;
	cfg.over += ns > SLOW_NS;
	cfg.sum_ns += ns;
	if (ns > cfg.max_ns) {
		cfg.max_ns = ns;
	}
	if (cfg.frames % 120 == 0) {
		fprintf(stderr, "luxcomp: blur stats tier %ld frames %d max %.2f ms avg %.2f ms over 8 ms %d, "
			"updates %d max %.2f ms avg %.2f ms, fallbacks %d\n", (long)luxcomp_blur_tier(), cfg.frames,
			cfg.max_ns / 1e6, cfg.sum_ns / 1e6 / cfg.frames, cfg.over, cfg.updates, cfg.blur_max_ns / 1e6,
			cfg.updates ? cfg.blur_sum_ns / 1e6 / cfg.updates : 0.0, cfg.fallbacks);
		cfg.frames = cfg.updates = cfg.over = 0;
		cfg.max_ns = cfg.sum_ns = cfg.blur_max_ns = cfg.blur_sum_ns = 0;
	}
}

/* ---- material pod obdelnikem okna (luxcomp_view_set_material) ---- */

/* Pozadavek se jen ulozi; uzel vznika az s dekoraci okna (deco_update -> blur_view_update), aby byl
 * pod kopiemi zaoblenych rohu klienta, ktere deco_create taky dava na spodek stromu */
void
luxcomp_view_set_material(int64_t id, const char *name, int64_t x, int64_t y, int64_t w, int64_t h)
{
	struct view *v = view_by_id(id);
	if (!v) {
		return;
	}
	if (!name || !*name || strlen(name) >= sizeof(v->material_name) || w <= 0 || h <= 0) {
		blur_destroy(v->material);
		v->material = NULL;
		v->material_name[0] = '\0';
		return;
	}
	if (v->material && strcmp(v->material->material, name)) {
		blur_destroy(v->material);
		v->material = NULL;
	}
	strcpy(v->material_name, name);
	v->material_box = (struct wlr_box){ x, y, w, h };
	if (v->deco) {
		deco_update(v->deco);
	}
}

/* Obdelnik oriznuty na geometrii okna; rohy obdelniku, ktere lezi v zaoblenych rozich okna
 * (@rounded = CORNER_* okna), dostanou stejny polomer, ostatni jsou ostre */
void
blur_view_update(struct view *v, int radius, int rounded)
{
	if (!v->material_name[0]) {
		return;
	}
	struct wlr_box geo = { 0, 0, view_width(v), view_height(v) }, box;
	if (!wlr_box_intersection(&box, &v->material_box, &geo)) {
		box = (struct wlr_box){ 0 };
	}
	if (!v->material) {
		v->material = blur_create(v->body, v->material_name, 0);
		v->material->stop = &v->tree->node;
		v->material->flat = true;
	}
	struct blur *b = v->material;
	int corners = 0;
	bool left = box.x == 0, top = box.y == 0;
	bool right = box.x + box.width == geo.width, bottom = box.y + box.height == geo.height;
	corners |= top && left ? CORNER_TL : 0;
	corners |= top && right ? CORNER_TR : 0;
	corners |= bottom && right ? CORNER_BR : 0;
	corners |= bottom && left ? CORNER_BL : 0;
	corners &= rounded;
	if (!corners) {
		radius = 0;
	}
	if (corners != b->corners || radius != b->radius) {
		b->corners = corners;
		b->radius = radius;
		b->dirty = true;
	}
	blur_set_box(b, box);
}
