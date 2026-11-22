/*
 * Animace oken (otevreni, zavreni, minimalizace do Docku, obnoveni).
 *
 * Scena wlroots neumi zmensit cely strom, takze se zmensuji jeho uzly: poloha kazdeho uzlu pod korenem
 * i velikost bufferu krat meritko, koren posunuty tak, aby stred okna zustal na miste. Klient muze behem
 * animace commitnout (nova velikost, podpovrch, popup); co se od posledniho kroku zmenilo, je nova
 * vychozi hodnota. Ulozene uzly se jen porovnavaji s tim, co je ve strome, nikdy se na ne nesaha.
 * Zavirane a minimalizovane okno je kopie posledniho obrazu (zamcene buffery), ktera vstup nebere:
 * kliky jdou hned na to, co je pod ni. Otevirane a obnovene okno je zive a vstup bere.
 * Krok pred vykreslenim kazdeho snimku vystupu; meni se jen uzly okna, scena tedy prekresli jen jeho
 * oblast. Pixman: zmensovani bez filtru (nearest), dva pomale snimky za sebou animace dokonci.
 */
#define _GNU_SOURCE
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wlr/types/wlr_buffer.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/util/log.h>
#include "internal.h"

/* snimek pomalejsi nez tohle dvakrat za sebou: animace skoci na konec (radeji skok nez trhani) */
#define SLOW_FRAME_NS 12000000

struct saved {
	struct wlr_scene_node *node;	/* jen k porovnani, muze uz byt uvolneny */
	int x, y, w, h;			/* vychozi hodnoty */
	int ax, ay, aw, ah;		/* naposledy nastavene animaci */
	float opacity, a_opacity;
	enum wlr_scale_filter_mode filter;
};

struct anim {
	struct wl_list link;
	int kind;
	struct view *view;		/* zive okno (OPEN, RESTORE), jinak NULL */
	struct wlr_scene_tree *root;	/* strom okna nebo kopie obrazu */
	int base_x, base_y;		/* poloha kopie (zive okno ma v->x, v->y) */
	double cx, cy;			/* stred okna v souradnicich korene */
	double dx, dy;			/* posun stredu do cile (Dock) */
	int64_t start_ns, duration_ns;
	struct saved *saved;
	int n_saved, cap_saved;
	struct wl_listener destroy;
	int frames;
	int64_t render_max_ns;
};

/* krivky jako cubic-bezier(x1, y1, x2, y2) */
struct curve { double x1, y1, x2, y2; };

struct kind {
	double scale_from, scale_to, alpha_from, alpha_to;
	bool to_target, from_target;	/* do cile (minimalizace) / z cile (obnoveni) */
	struct curve scale, x, y, alpha;
};

/* Hodnoty z picom.conf LuxOS 1.0.x (animace oken pod X11, commit 82c1a813): otevreni a zavreni
 * kratke zvetseni/zmenseni o 10 % s prolnutim, minimalizace do Docku a obnoveni z nej */
static const struct kind kinds[] = {
	[LUXCOMP_ANIM_OPEN] = { 0.9, 1, 0, 1, false, false,
		{ 0.2, 0.8, 0.3, 1 }, { 0.2, 0.8, 0.3, 1 }, { 0.2, 0.8, 0.3, 1 }, { 0, 0, 0.4, 1 } },
	[LUXCOMP_ANIM_CLOSE] = { 1, 0.9, 1, 0, false, false,
		{ 0.4, 0, 1, 1 }, { 0.4, 0, 1, 1 }, { 0.4, 0, 1, 1 }, { 0.4, 0, 1, 1 } },
	[LUXCOMP_ANIM_MINIMIZE] = { 1, 0.06, 1, 0, true, false,
		{ 0.4, 0, 0.6, 1 }, { 0.4, 0, 0.6, 1 }, { 0.5, 0, 0.9, 0.6 }, { 0.6, 0, 1, 1 } },
	[LUXCOMP_ANIM_RESTORE] = { 0.06, 1, 0, 1, false, true,
		{ 0.2, 0.8, 0.3, 1 }, { 0.2, 0.8, 0.3, 1 }, { 0.1, 0.5, 0.4, 1 }, { 0, 0, 0.4, 1 } },
};
#define KINDS ((int)(sizeof(kinds) / sizeof(kinds[0])))

static struct wl_list anims = { &anims, &anims };
static int64_t duration_ms[KINDS];
static double time_scale = 1;	/* LUXCOMP_ANIM_SCALE: zpomaleni pro snimky v testech */
static int slow_frames;

static int64_t
now_ns(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000000000LL + t.tv_nsec;
}

static double
bezier(struct curve c, double x)
{
	double s = x;
	for (int i = 0; i < 8; i++) {
		double bx = 3 * c.x1 * s * (1 - s) * (1 - s) + 3 * c.x2 * s * s * (1 - s) + s * s * s;
		double dx = 3 * c.x1 * (1 - s) * (1 - 3 * s) + 3 * c.x2 * s * (2 - 3 * s) + 3 * s * s;
		if (fabs(dx) < 1e-6) {
			break;
		}
		s -= (bx - x) / dx;
		s = s < 0 ? 0 : s > 1 ? 1 : s;
	}
	return 3 * c.y1 * s * (1 - s) * (1 - s) + 3 * c.y2 * s * s * (1 - s) + s * s * s;
}

static bool
no_input(struct wlr_scene_buffer *buffer, double *sx, double *sy)
{
	return false;
}

static struct saved *
saved_for(struct anim *a, struct wlr_scene_node *node)
{
	for (int i = 0; i < a->n_saved; i++) {
		if (a->saved[i].node == node) {
			return &a->saved[i];
		}
	}
	if (a->n_saved == a->cap_saved) {
		a->cap_saved = a->cap_saved ? a->cap_saved * 2 : 16;
		a->saved = realloc(a->saved, a->cap_saved * sizeof(*a->saved));
	}
	struct saved *s = &a->saved[a->n_saved++];
	*s = (struct saved){ .node = node, .x = node->x, .y = node->y, .ax = node->x, .ay = node->y };
	if (node->type == WLR_SCENE_NODE_BUFFER) {
		struct wlr_scene_buffer *b = wlr_scene_buffer_from_node(node);
		s->w = s->aw = b->dst_width;
		s->h = s->ah = b->dst_height;
		s->opacity = s->a_opacity = b->opacity;
		s->filter = b->filter_mode;
	} else if (node->type == WLR_SCENE_NODE_RECT) {
		struct wlr_scene_rect *r = wlr_scene_rect_from_node(node);
		s->w = s->aw = r->width;
		s->h = s->ah = r->height;
	}
	return s;
}

/* Velikost bufferu bez dest size, jako ji pocita scena */
static void
buffer_size(struct wlr_scene_buffer *b, int *w, int *h)
{
	*w = *h = 0;
	if (b->buffer) {
		*w = b->buffer->width;
		*h = b->buffer->height;
		if (b->transform & WL_OUTPUT_TRANSFORM_90) {
			int t = *w;
			*w = *h;
			*h = t;
		}
	}
}

/* Uzly pod stromem: meritko s, pruhlednost alpha; s = 1, alpha = 1 a restore vrati vychozi hodnoty */
static void
apply_tree(struct anim *a, struct wlr_scene_tree *tree, double s, double alpha, bool restore)
{
	struct wlr_scene_node *n;
	wl_list_for_each(n, &tree->children, link) {
		struct saved *sv = saved_for(a, n);
		if (n->x != sv->ax || n->y != sv->ay) {
			sv->x = n->x;
			sv->y = n->y;
		}
		sv->ax = restore ? sv->x : lround(sv->x * s);
		sv->ay = restore ? sv->y : lround(sv->y * s);
		wlr_scene_node_set_position(n, sv->ax, sv->ay);
		if (n->type == WLR_SCENE_NODE_TREE) {
			apply_tree(a, wlr_scene_tree_from_node(n), s, alpha, restore);
		} else if (n->type == WLR_SCENE_NODE_BUFFER) {
			struct wlr_scene_buffer *b = wlr_scene_buffer_from_node(n);
			if (b->dst_width != sv->aw || b->dst_height != sv->ah) {
				sv->w = b->dst_width;
				sv->h = b->dst_height;
			}
			if (b->opacity != sv->a_opacity) {
				sv->opacity = b->opacity;
			}
			if (restore) {
				sv->aw = sv->w;
				sv->ah = sv->h;
				sv->a_opacity = sv->opacity;
				wlr_scene_buffer_set_filter_mode(b, sv->filter);
			} else {
				int w = sv->w, h = sv->h;
				if (w <= 0 || h <= 0) {
					buffer_size(b, &w, &h);
				}
				/* aspon 1 px: dest size 0 znamena "velikost bufferu" */
				sv->aw = w > 0 ? fmax(1, lround(w * s)) : 0;
				sv->ah = h > 0 ? fmax(1, lround(h * s)) : 0;
				sv->a_opacity = sv->opacity * alpha;
				if (comp.software) {
					wlr_scene_buffer_set_filter_mode(b, WLR_SCALE_FILTER_NEAREST);
				}
			}
			wlr_scene_buffer_set_dest_size(b, sv->aw, sv->ah);
			wlr_scene_buffer_set_opacity(b, sv->a_opacity);
		} else if (n->type == WLR_SCENE_NODE_RECT) {
			struct wlr_scene_rect *r = wlr_scene_rect_from_node(n);
			if (r->width != sv->aw || r->height != sv->ah) {
				sv->w = r->width;
				sv->h = r->height;
			}
			sv->aw = restore ? sv->w : lround(sv->w * s);
			sv->ah = restore ? sv->h : lround(sv->h * s);
			wlr_scene_rect_set_size(r, sv->aw, sv->ah);
		}
	}
}

static void
root_position(struct anim *a, int *x, int *y)
{
	*x = a->view ? a->view->x : a->base_x;
	*y = a->view ? a->view->y : a->base_y;
}

static void
anim_free(struct anim *a)
{
	wl_list_remove(&a->link);
	wl_list_remove(&a->destroy.link);
	if (!a->view) {
		wlr_scene_node_destroy(&a->root->node);
	}
	free(a->saved);
	free(a);
}

static void
anim_finish(struct anim *a)
{
	if (getenv("LUXCOMP_STATS")) {
		wlr_log(WLR_ERROR, "luxcomp: anim %d %d frames, slowest render %.2f ms",
			a->kind, a->frames, a->render_max_ns / 1e6);
	}
	if (a->view) {
		int x, y;
		root_position(a, &x, &y);
		wlr_scene_node_set_position(&a->root->node, x, y);
		apply_tree(a, a->root, 1, 1, true);
	}
	anim_free(a);
}

static void
anim_root_destroy(struct wl_listener *listener, void *data)
{
	struct anim *a = wl_container_of(listener, a, destroy);
	/* okno zaniklo behem animace: jeho strom uz neexistuje */
	a->view = NULL;
	a->root = NULL;
	wl_list_remove(&a->link);
	wl_list_remove(&a->destroy.link);
	free(a->saved);
	free(a);
}

static void
anim_step(struct anim *a, int64_t now)
{
	const struct kind *k = &kinds[a->kind];
	double p = a->duration_ns > 0 ? (double)(now - a->start_ns) / a->duration_ns : 1;
	p = p < 0 ? 0 : p;
	if (p >= 1) {
		anim_finish(a);
		return;
	}
	double s = k->scale_from + (k->scale_to - k->scale_from) * bezier(k->scale, p);
	double alpha = k->alpha_from + (k->alpha_to - k->alpha_from) * bezier(k->alpha, p);
	double fx = 0, fy = 0;	/* podil cesty do cile */
	if (k->to_target) {
		fx = bezier(k->x, p);
		fy = bezier(k->y, p);
	} else if (k->from_target) {
		fx = 1 - bezier(k->x, p);
		fy = 1 - bezier(k->y, p);
	}
	int x, y;
	root_position(a, &x, &y);
	wlr_scene_node_set_position(&a->root->node,
		lround(x + a->cx * (1 - s) + a->dx * fx), lround(y + a->cy * (1 - s) + a->dy * fy));
	apply_tree(a, a->root, s, alpha, false);
}

static struct anim *
anim_of_view(struct view *v)
{
	struct anim *a;
	wl_list_for_each(a, &anims, link) {
		if (a->view == v) {
			return a;
		}
	}
	return NULL;
}

/* Kopie obrazu okna: stejne buffery (zamcene), bez vstupu. Pri VIEW_UNMAP scena uz strom povrchu
 * vypnula (odmapovani), buffery v nem ale jeste jsou: uvnitr surface_tree se stav stromu nebere v uvahu. */
static void
copy_tree(struct wlr_scene_tree *dst, struct wlr_scene_tree *src, struct wlr_scene_tree *surface_tree,
	bool unmapped)
{
	struct wlr_scene_node *n;
	wl_list_for_each(n, &src->children, link) {
		bool tree = n->type == WLR_SCENE_NODE_TREE;
		if (!n->enabled && !(tree && (unmapped || (surface_tree && n == &surface_tree->node)))) {
			continue;
		}
		if (n->type == WLR_SCENE_NODE_TREE) {
			struct wlr_scene_tree *t = wlr_scene_tree_create(dst);
			wlr_scene_node_set_position(&t->node, n->x, n->y);
			struct wlr_scene_tree *child = wlr_scene_tree_from_node(n);
			copy_tree(t, child, surface_tree, unmapped || child == surface_tree);
		} else if (n->type == WLR_SCENE_NODE_BUFFER) {
			struct wlr_scene_buffer *b = wlr_scene_buffer_from_node(n);
			if (!b->buffer) {
				continue;
			}
			struct wlr_scene_buffer *c = wlr_scene_buffer_create(dst, b->buffer);
			c->point_accepts_input = no_input;
			wlr_scene_buffer_set_source_box(c, &b->src_box);
			wlr_scene_buffer_set_dest_size(c, b->dst_width, b->dst_height);
			wlr_scene_buffer_set_transform(c, b->transform);
			wlr_scene_buffer_set_opacity(c, b->opacity);
			wlr_scene_buffer_set_filter_mode(c, b->filter_mode);
			wlr_scene_node_set_position(&c->node, n->x, n->y);
		}
	}
}

/* Cil minimalizace: ikona v Docku (foreign-toplevel set_rectangle), jinak stred spodniho okraje
 * monitoru okna, kde Dock je */
static void
dock_point(struct view *v, double *x, double *y)
{
	if (v->icon_box.width > 0) {
		*x = v->icon_box.x + v->icon_box.width / 2.0;
		*y = v->icon_box.y + v->icon_box.height / 2.0;
		return;
	}
	struct output *o = output_at(v->x + view_width(v) / 2.0, v->y + view_height(v) / 2.0);
	if (!o && !wl_list_empty(&comp.outputs)) {
		o = wl_container_of(comp.outputs.next, o, link);
	}
	struct wlr_box box = { 0 };
	if (o) {
		wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
	}
	*x = box.x + box.width / 2.0;
	*y = box.y + box.height;
}

static void
schedule_frames(void)
{
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		wlr_output_schedule_frame(o->wlr_output);
	}
}

static void
anim_start(struct view *v, int kind)
{
	const struct kind *k = &kinds[kind];
	struct anim *old = anim_of_view(v);
	if (old) {
		anim_finish(old);
	}
	struct anim *a = calloc(1, sizeof(*a));
	a->kind = kind;
	bool live = kind == LUXCOMP_ANIM_OPEN || kind == LUXCOMP_ANIM_RESTORE;
	if (live) {
		a->view = v;
		a->root = v->tree;
	} else {
		a->root = wlr_scene_tree_create(v->tree->node.parent);
		wlr_scene_node_place_above(&a->root->node, &v->tree->node);
		a->base_x = v->x;
		a->base_y = v->y;
		copy_tree(a->root, v->tree, v->surface_tree, false);
		wlr_scene_node_set_position(&a->root->node, v->x, v->y);
	}
	/* stred ramu okna vcetne zahlavi */
	int top = v->deco ? deco_height(v->deco) : 0;
	a->cx = view_width(v) / 2.0;
	a->cy = (view_height(v) - top) / 2.0;
	if (k->to_target || k->from_target) {
		double tx, ty;
		dock_point(v, &tx, &ty);
		a->dx = tx - (v->x + a->cx);
		a->dy = ty - (v->y + a->cy);
	}
	a->start_ns = now_ns();
	a->duration_ns = duration_ms[kind] * 1000000.0 * time_scale;
	a->destroy.notify = anim_root_destroy;
	wl_signal_add(&a->root->node.events.destroy, &a->destroy);
	wl_list_insert(&anims, &a->link);
	anim_step(a, a->start_ns);
	schedule_frames();
}

/* ---- snimky ---- */

void
anim_frame(void)
{
	int64_t now = now_ns();
	struct anim *a, *tmp;
	wl_list_for_each_safe(a, tmp, &anims, link) {
		anim_step(a, now);
	}
	bool cover = cover_step(now);
	if (!wl_list_empty(&anims) || cover) {
		schedule_frames();
	}
}

void
anim_frame_done(int64_t render_ns)
{
	cover_frame_done(render_ns);
	if (wl_list_empty(&anims)) {
		slow_frames = 0;
		return;
	}
	struct anim *a, *tmp;
	wl_list_for_each(a, &anims, link) {
		a->frames++;
		if (render_ns > a->render_max_ns) {
			a->render_max_ns = render_ns;
		}
	}
	slow_frames = render_ns > SLOW_FRAME_NS ? slow_frames + 1 : 0;
	if (slow_frames >= 2) {
		wl_list_for_each_safe(a, tmp, &anims, link) {
			anim_finish(a);
		}
		slow_frames = 0;
	}
}

void
anim_init(void)
{
	const char *scale = getenv("LUXCOMP_ANIM_SCALE");
	if (scale && atof(scale) > 0) {
		time_scale = atof(scale);
	}
	cover_init(time_scale);
}

/* ---- API ---- */

void
luxcomp_anim_set(int64_t kind, int64_t ms)
{
	if (kind > 0 && kind < KINDS) {
		duration_ms[kind] = ms > 0 ? ms : 0;
	}
}

void
luxcomp_view_animate(int64_t id, int64_t kind)
{
	struct view *v = view_by_id(id);
	if (!v || kind <= 0 || kind >= KINDS || duration_ms[kind] <= 0 || !v->workspace->shown) {
		return;
	}
	/* zavreni prichazi s VIEW_UNMAP: okno uz je skryte, ale buffery jeste ma */
	bool shown = kind == LUXCOMP_ANIM_CLOSE ? v->visible : v->mapped && v->visible;
	if (!shown) {
		return;
	}
	anim_start(v, kind);
}
