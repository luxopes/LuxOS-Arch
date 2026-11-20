/*
 * Stin okna. Rozmazani se pocita jednou: obdelnik se zaoblenymi rohy rozmazany do textury, ze ktere
 * se kresli 8 dilu (rohy 1:1, hrany roztazene z jednoho sloupce nebo radku, stred zakryva okno).
 * Textura je sdilena vsemi okny se stejnou velikosti stinu, polomerem, barvou a meritkem, takze
 * pod pixman stin stoji jen slozeni par obdelniku a pri presunu okna se nic nepocita.
 */
#define _GNU_SOURCE
#include <cairo.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <wlr/types/wlr_buffer.h>
#include <wlr/types/wlr_scene.h>
#include "internal.h"

struct shadow_texture {
	int size, radius, scale;
	uint32_t argb;
	struct wlr_buffer *buffer;
};

struct shadow {
	struct wlr_scene_tree *tree;
	struct wlr_scene_buffer *piece[8];
};

/* aktivni a neaktivni okno; vic kombinaci naraz neni */
static struct shadow_texture cache[2];
static int next;

/* Box blur radku nebo sloupce s nulami za okrajem; tri pruchody davaji temer gauss */
static void
blur_line(uint8_t *p, int n, int step, int r, uint8_t *tmp)
{
	int win = 2 * r + 1, sum = 0;
	for (int i = 0; i < n; i++) {
		tmp[i] = p[i * step];
	}
	for (int i = 0; i < r && i < n; i++) {
		sum += tmp[i];
	}
	for (int i = 0; i < n; i++) {
		if (i + r < n) {
			sum += tmp[i + r];
		}
		if (i - r - 1 >= 0) {
			sum -= tmp[i - r - 1];
		}
		p[i * step] = (sum + win / 2) / win;
	}
}

/* Strana textury v logickych px: roh siaha s ven a s + r dovnitr, uprostred 1 px rovne hrany */
static int
corner_size(int size, int radius)
{
	return 2 * size + radius;
}

static struct wlr_buffer *
render(int size, int radius, uint32_t argb, int scale)
{
	int n = (2 * corner_size(size, radius) + 1) * scale;
	int s = size * scale, r = radius * scale;
	cairo_surface_t *mask = cairo_image_surface_create(CAIRO_FORMAT_A8, n, n);
	cairo_t *cr = cairo_create(mask);
	cairo_new_path(cr);
	cairo_arc(cr, s + r, s + r, r, M_PI, 1.5 * M_PI);
	cairo_arc(cr, n - s - r, s + r, r, 1.5 * M_PI, 2 * M_PI);
	cairo_arc(cr, n - s - r, n - s - r, r, 0, 0.5 * M_PI);
	cairo_arc(cr, s + r, n - s - r, r, 0.5 * M_PI, M_PI);
	cairo_close_path(cr);
	cairo_fill(cr);
	cairo_destroy(cr);
	cairo_surface_flush(mask);

	uint8_t *a = cairo_image_surface_get_data(mask);
	int stride = cairo_image_surface_get_stride(mask);
	int br = s / 3 > 0 ? s / 3 : 1;
	uint8_t *tmp = malloc(n);
	for (int pass = 0; pass < 3; pass++) {
		for (int y = 0; y < n; y++) {
			blur_line(a + y * stride, n, 1, br, tmp);
		}
		for (int x = 0; x < n; x++) {
			blur_line(a + x, n, stride, br, tmp);
		}
	}
	free(tmp);

	cairo_surface_t *img;
	struct wlr_buffer *buffer = cairo_buffer_create(n, n, &img);
	uint32_t *px = (uint32_t *)cairo_image_surface_get_data(img);
	int pstride = cairo_image_surface_get_stride(img) / 4;
	uint32_t ca = argb >> 24, cr8 = argb >> 16 & 0xff, cg = argb >> 8 & 0xff, cb = argb & 0xff;
	for (int y = 0; y < n; y++) {
		for (int x = 0; x < n; x++) {
			uint32_t al = a[y * stride + x] * ca / 255;
			px[y * pstride + x] = al << 24 | (cr8 * al / 255) << 16
				| (cg * al / 255) << 8 | cb * al / 255;
		}
	}
	cairo_surface_mark_dirty(img);
	cairo_surface_destroy(mask);
	return buffer;
}

static struct wlr_buffer *
texture(int size, int radius, uint32_t argb, int scale)
{
	for (int i = 0; i < 2; i++) {
		struct shadow_texture *c = &cache[i];
		if (c->buffer && c->size == size && c->radius == radius && c->argb == argb
				&& c->scale == scale) {
			return c->buffer;
		}
	}
	/* okna drzi starou texturu dal (zamek wlr_buffer), dokud se neprekresli */
	struct shadow_texture *t = &cache[next];
	next ^= 1;
	if (t->buffer) {
		wlr_buffer_drop(t->buffer);
	}
	*t = (struct shadow_texture){ size, radius, scale, argb, render(size, radius, argb, scale) };
	return t->buffer;
}

/* Stin nema byt cilem kliknuti, patri k oknu jen opticky */
static bool
no_input(struct wlr_scene_buffer *buffer, double *sx, double *sy)
{
	return false;
}

struct shadow *
shadow_create(struct wlr_scene_tree *parent)
{
	struct shadow *sh = calloc(1, sizeof(*sh));
	sh->tree = wlr_scene_tree_create(parent);
	wlr_scene_node_lower_to_bottom(&sh->tree->node);
	for (int i = 0; i < 8; i++) {
		sh->piece[i] = wlr_scene_buffer_create(sh->tree, NULL);
		sh->piece[i]->point_accepts_input = no_input;
		wlr_scene_buffer_set_filter_mode(sh->piece[i], WLR_SCALE_FILTER_NEAREST);
	}
	wlr_scene_node_set_enabled(&sh->tree->node, false);
	return sh;
}

void
shadow_destroy(struct shadow *sh)
{
	wlr_scene_node_destroy(&sh->tree->node);
	free(sh);
}

void
shadow_update(struct shadow *sh, struct wlr_box f, int size, int radius, uint32_t argb,
		int scale)
{
	bool on = size > 0 && (argb >> 24) > 0 && f.width > 0 && f.height > 0;
	wlr_scene_node_set_enabled(&sh->tree->node, on);
	if (!on) {
		return;
	}
	struct wlr_buffer *buffer = texture(size, radius, argb, scale);
	int c = corner_size(size, radius), n = 2 * c + 1;
	/* svetlo shora: stin posunuty dolu o ctvrtinu velikosti */
	int x0 = f.x - size, y0 = f.y - size + size / 4;
	int w = f.width + 2 * size, h = f.height + 2 * size;
	/* u maleho okna se rohy zkrati, aby se neprekryvaly */
	int cx = c < w / 2 ? c : w / 2, cy = c < h / 2 ? c : h / 2;
	/* hrany jen tak siroke, kolik je stinu vedle okna; zbytek by se kreslil pod nim */
	int t = size + size / 4, tx = t < cx ? t : cx, ty = t < cy ? t : cy;
	int ew = w - 2 * cx, eh = h - 2 * cy;
	struct { int sx, sy, sw, sh, x, y, w, h; } part[8] = {
		{ 0, 0, cx, cy, x0, y0, cx, cy },
		{ n - cx, 0, cx, cy, x0 + w - cx, y0, cx, cy },
		{ 0, n - cy, cx, cy, x0, y0 + h - cy, cx, cy },
		{ n - cx, n - cy, cx, cy, x0 + w - cx, y0 + h - cy, cx, cy },
		{ c, 0, 1, ty, x0 + cx, y0, ew, ty },
		{ c, n - ty, 1, ty, x0 + cx, y0 + h - ty, ew, ty },
		{ 0, c, tx, 1, x0, y0 + cy, tx, eh },
		{ n - tx, c, tx, 1, x0 + w - tx, y0 + cy, tx, eh },
	};
	for (int i = 0; i < 8; i++) {
		struct wlr_scene_buffer *p = sh->piece[i];
		wlr_scene_node_set_enabled(&p->node, part[i].w > 0 && part[i].h > 0);
		if (part[i].w <= 0 || part[i].h <= 0) {
			continue;
		}
		wlr_scene_buffer_set_buffer(p, buffer);
		wlr_scene_buffer_set_source_box(p, &(struct wlr_fbox){ part[i].sx * scale,
			part[i].sy * scale, part[i].sw * scale, part[i].sh * scale });
		wlr_scene_buffer_set_dest_size(p, part[i].w, part[i].h);
		wlr_scene_node_set_position(&p->node, part[i].x, part[i].y);
	}
}
