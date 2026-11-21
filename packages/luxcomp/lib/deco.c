/*
 * Zahlavi oken kreslene kompozitorem (semafor vlevo, nazev uprostred), stin, obrys a zaoblene dolni
 * rohy. Barvy a rozmery nastavuje politika pres luxcomp_theme_set(); vychozi hodnoty nize jsou
 * svetly vzhled LuxOS (luxos_tokens TITLEBAR). Rozmery jsou stejne jako u zahlavi GTK (luxos-themes),
 * aby okno s vlastnim zahlavim a okno se zahlavim kompozitoru vypadala stejne.
 *
 * Barva zahlavi navazuje na obsah okna: jednobarevny neutralni horni radek klienta (tmavy terminal =
 * tmave zahlavi), jinak svetla nebo tmava barva podle jasu klienta, u neznameho klienta barva motivu.
 */
#define _GNU_SOURCE
#include <cairo.h>
#include <drm_fourcc.h>
#include <math.h>
#include <pango/pangocairo.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wlr/interfaces/wlr_buffer.h>
#include <wlr/render/wlr_texture.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_xdg_shell.h>
#include "internal.h"

/* [0] neaktivni, [1] aktivni okno; u inkoustu [0] svetle, [1] tmave zahlavi; [0] bezne, [1] nizke zahlavi */
static struct {
	int title_height[2], inset[2], radius, button, spacing;
	int shadow_size[2], shadow_offset[2];
	uint32_t bg[2], bg_light, bg_dark, text[2][2], button_inactive[2], ring[2], shadow[2];
	uint32_t close, minimize, maximize, separator, glyph, accent, border;
	char *font;
} theme = {
	.title_height = { 38, 30 },
	.inset = { 20, 14 },
	.radius = 12,
	.button = 12,
	.spacing = 8,
	.shadow_size = { 24, 40 },
	.shadow_offset = { -1, -1 },
	.bg = { 0xfff2f2f7, 0xfff2f2f7 },
	.bg_light = 0xfff2f2f7,
	.bg_dark = 0xff21242b,
	.text = { { 0x731d1d2b, 0xff1d1d2b }, { 0x73f4f4fa, 0xfff4f4fa } },
	.button_inactive = { 0x38000000, 0x38ffffff },
	.ring = { 0x1a000000, 0x1affffff },
	.shadow = { 0x2e000000, 0x59000000 },
	.close = 0xffff5f57,
	.minimize = 0xfffebc2e,
	.maximize = 0xff28c840,
	.glyph = 0xb33c140a,
	.accent = 0xff3d7bff,
	.border = 0x33000000,
};

struct deco {
	struct view *view;
	struct wlr_scene_buffer *node;
	struct shadow *shadow, *outline;
	/* zaoblene dolni rohy: obsah oriznuty nad dolnim pruhem, pruh mezi rohy (druhy strom
	 * stejneho povrchu) a dva rohy jako kopie pixelu klienta s maskou */
	struct wlr_scene_tree *strip;
	struct wlr_surface *strip_surface;
	struct wlr_scene_buffer *corner[2];
	struct wlr_buffer *held[3];	/* zobrazene buffery: zahlavi, rohy (show_buffer) */
	struct wlr_box corner_geo;
	int corner_px;
	/* poskozeni povrchu plati pro posledni commit a zustava, dokud neprijde dalsi: commit (seq), jehoz
	 * poskozeni uz rohy a vzorkovani zahlavi zpracovaly, jinak by kazde deco_update cetlo pixely znovu
	 * a casovac vzorkovani se natahoval porad dokola (5x za sekundu u kazdeho okna) */
	uint32_t corner_seq, sample_seq;
	bool rounded;
	int width, height, scale, hover;
	bool active, square, compact;
	bool ssd;		/* false = the client draws its title bar: only shadow and corners */
	char *title;
	/* barva klienta pod zahlavim (0 = neznama), cteni nejvys 5x za sekundu, posledni zmena casovacem */
	uint32_t client_bg;
	struct wlr_box sampled_geo;
	int64_t sampled_ms;
	struct wl_event_source *sample_timer;
};

static struct deco *hovered;

/* Scena buffer po nahrani do GPU (gles2) pusti a necha si jen texturu, material (blur.c) pak zahlavi a rohy
 * okna pod plochou nevidi. Proto zobrazeny buffer drzime sami; s pixman to dela textura sama. */
static void
show_buffer(struct wlr_scene_buffer *node, struct wlr_buffer **held, struct wlr_buffer *buffer)
{
	wlr_scene_buffer_set_buffer(node, buffer);
	if (*held) {
		wlr_buffer_unlock(*held);
	}
	*held = buffer ? wlr_buffer_lock(buffer) : NULL;
}

/* ---- wlr_buffer nad pameti cairo ---- */

struct cairo_buffer {
	struct wlr_buffer base;
	cairo_surface_t *surface;
};

static void
cbuf_destroy(struct wlr_buffer *b)
{
	struct cairo_buffer *cb = wl_container_of(b, cb, base);
	wlr_buffer_finish(b);
	cairo_surface_destroy(cb->surface);
	free(cb);
}

static bool
cbuf_begin(struct wlr_buffer *b, uint32_t flags, void **data, uint32_t *format,
		size_t *stride)
{
	struct cairo_buffer *cb = wl_container_of(b, cb, base);
	if (flags & WLR_BUFFER_DATA_PTR_ACCESS_WRITE) {
		return false;
	}
	*data = cairo_image_surface_get_data(cb->surface);
	*format = DRM_FORMAT_ARGB8888;
	*stride = cairo_image_surface_get_stride(cb->surface);
	return true;
}

static void
cbuf_end(struct wlr_buffer *b)
{
}

static const struct wlr_buffer_impl cbuf_impl = {
	.destroy = cbuf_destroy,
	.begin_data_ptr_access = cbuf_begin,
	.end_data_ptr_access = cbuf_end,
};

struct wlr_buffer *
cairo_buffer_create(int w, int h, cairo_surface_t **surface)
{
	struct cairo_buffer *cb = calloc(1, sizeof(*cb));
	wlr_buffer_init(&cb->base, &cbuf_impl, w, h);
	cb->surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h);
	*surface = cb->surface;
	return &cb->base;
}

/* ---- kresleni zahlavi ---- */

static void
set_color(cairo_t *cr, uint32_t argb)
{
	cairo_set_source_rgba(cr, (argb >> 16 & 0xff) / 255.0, (argb >> 8 & 0xff) / 255.0,
		(argb & 0xff) / 255.0, (argb >> 24) / 255.0);
}

static int
title_height(struct deco *d)
{
	return theme.title_height[d->view->compact];
}

/* Stred i-teho svetla semaforu */
static double
button_cx(struct deco *d, int i)
{
	return theme.inset[d->view->compact] + i * (theme.button + theme.spacing);
}

/* Okraj za semaforem: odtud muze zacit znacka a nazev */
static int
lights_end(struct deco *d)
{
	return lround(button_cx(d, 2) + theme.button / 2.0);
}

static double
luminance(uint32_t argb)
{
	return (0.2126 * (argb >> 16 & 0xff) + 0.7152 * (argb >> 8 & 0xff) + 0.0722 * (argb & 0xff)) / 255;
}

static uint32_t
bar_color(struct deco *d)
{
	return d->client_bg ? d->client_bg : theme.bg[d->active];
}

/* Inkoust podle jasu zahlavi: 1 = tmave zahlavi */
static int
ink(struct deco *d)
{
	return luminance(bar_color(d)) < 0.5;
}

/* Znak na semaforu pod ukazatelem jako v tematu X11 (luxos_tokens light_svg): x, -, + */
static void
draw_glyph(cairo_t *cr, int part, double cx, double cy)
{
	double b = theme.button, a = b * 0.25;
	set_color(cr, theme.glyph);
	cairo_set_line_width(cr, b / 8.5);
	cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
	if (part == LUXCOMP_PART_CLOSE) {
		a = b * 0.21;
		cairo_move_to(cr, cx - a, cy - a);
		cairo_line_to(cr, cx + a, cy + a);
		cairo_move_to(cr, cx + a, cy - a);
		cairo_line_to(cr, cx - a, cy + a);
	} else {
		cairo_move_to(cr, cx - a, cy);
		cairo_line_to(cr, cx + a, cy);
		if (part == LUXCOMP_PART_MAXIMIZE) {
			cairo_move_to(cr, cx, cy - a);
			cairo_line_to(cr, cx, cy + a);
		}
	}
	cairo_stroke(cr);
}

static PangoLayout *
title_layout(cairo_t *cr, const char *text, int px)
{
	PangoLayout *layout = pango_cairo_create_layout(cr);
	PangoFontDescription *font = pango_font_description_from_string(
		theme.font ? theme.font : "Inter Semi-Bold 13px");
	if (px) {
		pango_font_description_set_absolute_size(font, px * PANGO_SCALE);
	}
	pango_layout_set_font_description(layout, font);
	pango_font_description_free(font);
	pango_layout_set_text(layout, text, -1);
	pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
	pango_layout_set_single_paragraph_mode(layout, true);
	return layout;
}

/* Stit (12 px) znacky sandboxu */
static void
draw_shield(cairo_t *cr, double x, double y)
{
	cairo_move_to(cr, x + 6, y + 0.5);
	cairo_line_to(cr, x + 11, y + 2.5);
	cairo_curve_to(cr, x + 11, y + 7, x + 9, y + 10, x + 6, y + 11.5);
	cairo_curve_to(cr, x + 3, y + 10, x + 1, y + 7, x + 1, y + 2.5);
	cairo_close_path(cr);
	cairo_fill(cr);
}

/* Znacka aplikace v sandboxu za semaforem: stit a text v barve akcentu na jeho svetlem podkladu
 * (bezpecnostni udaj, proto hned vedle ovladani okna). Zkracuje se, aby nazvu nechala polovinu sirky.
 * Vraci pravy okraj znacky. */
static int
draw_badge(cairo_t *cr, struct deco *d, const char *text, int w, int h)
{
	int x = lights_end(d) + 18, pad = 7, glyph = 12, gap = 4;
	int max_w = w / 2 - x - 2 * pad - glyph - gap;
	if (max_w < 16) {
		return 0;
	}
	PangoLayout *layout = title_layout(cr, text, 11);
	pango_layout_set_width(layout, max_w * PANGO_SCALE);
	int tw, th;
	pango_layout_get_pixel_size(layout, &tw, &th);
	double bh = 18, bw = pad + glyph + gap + tw + pad, y = (h - bh) / 2, r = bh / 2;
	uint32_t accent = theme.accent & 0xffffff;
	cairo_new_sub_path(cr);
	cairo_arc(cr, x + r, y + r, r, M_PI / 2, 1.5 * M_PI);
	cairo_arc(cr, x + bw - r, y + r, r, 1.5 * M_PI, M_PI / 2);
	cairo_close_path(cr);
	set_color(cr, 0x26000000 | accent);
	cairo_fill(cr);
	set_color(cr, 0xff000000 | accent);
	draw_shield(cr, x + pad, (h - glyph) / 2.0);
	cairo_move_to(cr, x + pad + glyph + gap, (h - th) / 2.0);
	pango_cairo_show_layout(cr, layout);
	g_object_unref(layout);
	return x + bw;
}

/* Kresli se v pixelech vystupu (meritko), scena buffer zmensi na logickou velikost */
static struct wlr_buffer *
render(struct deco *d)
{
	int w = d->width, h = title_height(d), r = d->square ? 0 : theme.radius, k = d->scale;
	cairo_surface_t *surface;
	struct wlr_buffer *buffer = cairo_buffer_create(w * k, h * k, &surface);
	cairo_t *cr = cairo_create(surface);
	cairo_scale(cr, k, k);

	/* horni rohy zaoblene, dolni rovne (navazuje na obsah okna) */
	cairo_new_path(cr);
	cairo_arc(cr, r, r, r, M_PI, 1.5 * M_PI);
	cairo_arc(cr, w - r, r, r, 1.5 * M_PI, 2 * M_PI);
	cairo_line_to(cr, w, h);
	cairo_line_to(cr, 0, h);
	cairo_close_path(cr);
	set_color(cr, bar_color(d));
	cairo_fill(cr);
	if (theme.separator >> 24) {
		set_color(cr, theme.separator);
		cairo_rectangle(cr, 0, h - 1, w, 1);
		cairo_fill(cr);
	}

	/* neaktivni okno: tlumeny semafor s krouzkem (viditelny i na bilem), pri najeti na skupinu
	 * barvy a znaky na vsech trech jako v macOS */
	int dark = ink(d);
	uint32_t colors[3] = { theme.close, theme.minimize, theme.maximize };
	for (int i = 0; i < 3; i++) {
		int part = LUXCOMP_PART_CLOSE + i;
		double cx = button_cx(d, i), cy = h / 2.0, rr = theme.button / 2.0;
		if (d->active || d->hover) {
			set_color(cr, colors[i]);
			cairo_arc(cr, cx, cy, rr, 0, 2 * M_PI);
			cairo_fill(cr);
		} else {
			set_color(cr, theme.button_inactive[dark]);
			cairo_arc(cr, cx, cy, rr, 0, 2 * M_PI);
			cairo_fill(cr);
			set_color(cr, theme.ring[dark]);
			cairo_set_line_width(cr, 1);
			cairo_arc(cr, cx, cy, rr - 0.5, 0, 2 * M_PI);
			cairo_stroke(cr);
		}
		if (d->hover) {
			draw_glyph(cr, part, cx, cy);
		}
	}

	int reserved = lights_end(d) + theme.spacing;
	const char *badge = d->view->badge;
	if (badge && w > 2 * reserved) {
		reserved = MAX(reserved, draw_badge(cr, d, badge, w, h) + theme.spacing);
	}
	if (d->title && *d->title) {
		int max_w = w - 2 * reserved;
		if (max_w > 20) {
			PangoLayout *layout = title_layout(cr, d->title, 0);
			pango_layout_set_width(layout, max_w * PANGO_SCALE);
			int tw, th;
			pango_layout_get_pixel_size(layout, &tw, &th);
			set_color(cr, theme.text[dark][d->active]);
			cairo_move_to(cr, (w - tw) / 2, (h - th) / 2);
			pango_cairo_show_layout(cr, layout);
			g_object_unref(layout);
		}
	}
	cairo_destroy(cr);
	cairo_surface_flush(surface);
	return buffer;
}

static void
redraw(struct deco *d)
{
	if (d->width <= 0) {
		show_buffer(d->node, &d->held[0], NULL);
		return;
	}
	struct wlr_buffer *b = render(d);
	show_buffer(d->node, &d->held[0], b);
	wlr_buffer_drop(b);
	int h = title_height(d);
	wlr_scene_buffer_set_dest_size(d->node, d->width, h);
	wlr_scene_node_set_position(&d->node->node, 0, -h);
	/* nepruhledna cast zahlavi: scena pod ni nekresli (stin, okna pod oknem) */
	pixman_region32_t opaque;
	int r = d->square ? 0 : theme.radius;
	pixman_region32_init_rect(&opaque, 0, r, d->width, (bar_color(d) >> 24) == 0xff ? h - r : 0);
	wlr_scene_buffer_set_opaque_region(d->node, &opaque);
	pixman_region32_fini(&opaque);
}

/* ---- zaoblene dolni rohy ---- */

static struct wlr_box
geometry(struct view *v)
{
	if (v->toplevel) {
		return v->toplevel->base->geometry;
	}
	return (struct wlr_box){ 0, 0, view_width(v), view_height(v) };
}

/* Strom korenoveho povrchu; wlr_scene_xdg_surface ma jako prvniho potomka strom povrchu, za nim
 * jsou nase popupy */
static struct wlr_scene_tree *
content_tree(struct view *v)
{
	if (!v->surface_tree || v->xsurface) {
		return v->surface_tree;
	}
	struct wlr_scene_node *first = wl_container_of(v->surface_tree->children.next, first, link);
	return wlr_scene_tree_from_node(first);
}

static bool
no_input(struct wlr_scene_buffer *buffer, double *sx, double *sy)
{
	return false;
}

/* Kopie rohu klienta (n x n px bufferu) s vyhlazenou maskou ctvrtkruhu; i = 0 levy, 1 pravy */
static bool
corner_read(struct deco *d, int i, struct wlr_texture *tex, int x, int y, int n)
{
	cairo_surface_t *img;
	struct wlr_buffer *buffer = cairo_buffer_create(n, n, &img);
	cairo_surface_flush(img);
	uint8_t *px = cairo_image_surface_get_data(img);
	int stride = cairo_image_surface_get_stride(img);
	bool ok = wlr_texture_read_pixels(tex, &(struct wlr_texture_read_pixels_options){
		.data = px, .format = DRM_FORMAT_ARGB8888, .stride = stride,
		.src_box = { x, y, n, n } });
	if (ok) {
		double cx = i ? 0 : n;	/* stred kruhu = vnitrni horni roh dlazdice */
		for (int py = 0; py < n; py++) {
			for (int qx = 0; qx < n; qx++) {
				double a = n + 0.5 - hypot(qx + 0.5 - cx, py + 0.5);
				if (a >= 1) {
					continue;
				}
				uint8_t *p = px + py * stride + qx * 4;
				for (int c = 0; c < 4; c++) {
					p[c] = a <= 0 ? 0 : p[c] * a;
				}
			}
		}
		cairo_surface_mark_dirty(img);
		show_buffer(d->corner[i], &d->held[1 + i], buffer);
	}
	wlr_buffer_drop(buffer);
	return ok;
}

static void
corners_off(struct deco *d)
{
	struct wlr_scene_tree *content = content_tree(d->view);
	if (content) {
		wlr_scene_subsurface_tree_set_clip(&content->node, NULL);
	}
	if (d->strip) {
		wlr_scene_node_set_enabled(&d->strip->node, false);
	}
	wlr_scene_node_set_enabled(&d->corner[0]->node, false);
	wlr_scene_node_set_enabled(&d->corner[1]->node, false);
	d->rounded = false;
	d->corner_px = 0;
}

/* Klient kresli az k okraji okna, kompozitor mu dolni rohy zaobli. Pixely rohu se ctou jen kdyz
 * je klient v rozich zmenil (poskozeni povrchu), u terminalu tedy skoro nikdy. Pri neobvyklem
 * povrchu (viewport, rotace) nebo kdyz texturu nejde cist, zustanou rohy ostre. */
static void
corners_update(struct deco *d)
{
	struct view *v = d->view;
	struct wlr_scene_tree *content = content_tree(v);
	struct wlr_surface *s = content ? view_surface(v) : NULL;
	struct wlr_texture *tex = s ? wlr_surface_get_texture(s) : NULL;
	struct wlr_box g = geometry(v);
	int r = theme.radius;
	if (d->strip && d->strip_surface != s) {
		wlr_scene_node_destroy(&d->strip->node);
	}
	if (d->square || !tex || r <= 0 || g.width < 2 * r || g.height < 2 * r
			|| s->current.viewport.has_src
			|| s->current.transform != WL_OUTPUT_TRANSFORM_NORMAL) {
		if (d->rounded) {
			corners_off(d);
		}
		return;
	}
	double f = (double)tex->width / s->current.width;
	int n = lround(r * f);
	int bx[2] = { lround(g.x * f), lround((g.x + g.width - r) * f) };
	int by = lround((g.y + g.height - r) * f);
	if (bx[0] < 0 || by < 0 || bx[1] + n > (int)tex->width || by + n > (int)tex->height) {
		if (d->rounded) {
			corners_off(d);
		}
		return;
	}

	bool moved = !d->rounded || !d->strip || n != d->corner_px
		|| !wlr_box_equal(&g, &d->corner_geo);
	pixman_region32_t damage;
	pixman_region32_init(&damage);
	if (s->current.seq != d->corner_seq) {
		wlr_surface_get_effective_damage(s, &damage);
		d->corner_seq = s->current.seq;
	}
	for (int i = 0; i < 2; i++) {
		pixman_box32_t box = { g.x + (i ? g.width - r : 0), g.y + g.height - r,
			g.x + (i ? g.width : r), g.y + g.height };
		if (moved || pixman_region32_contains_rectangle(&damage, &box) != PIXMAN_REGION_OUT) {
			if (!corner_read(d, i, tex, bx[i], by, n)) {
				pixman_region32_fini(&damage);
				corners_off(d);
				return;
			}
		}
	}
	pixman_region32_fini(&damage);
	if (!moved) {
		return;
	}

	if (!d->strip) {
		d->strip = wlr_scene_subsurface_tree_create(v->body, s);
		d->strip_surface = s;
		tree_track(&d->strip);
		wlr_scene_node_place_below(&d->strip->node, &v->surface_tree->node);
	}
	wlr_scene_node_set_enabled(&d->strip->node, true);
	wlr_scene_node_set_position(&d->strip->node, -g.x, -g.y);
	wlr_scene_subsurface_tree_set_clip(&d->strip->node, &(struct wlr_box){
		g.x + r, g.y + g.height - r, g.width - 2 * r, r });
	wlr_scene_subsurface_tree_set_clip(&content->node, &(struct wlr_box){
		g.x, g.y, g.width, g.height - r });
	for (int i = 0; i < 2; i++) {
		wlr_scene_node_set_enabled(&d->corner[i]->node, true);
		wlr_scene_buffer_set_dest_size(d->corner[i], r, r);
		wlr_scene_node_set_position(&d->corner[i]->node, i ? g.width - r : 0, g.height - r);
	}
	d->corner_geo = g;
	d->corner_px = n;
	d->rounded = true;
}

/* ---- barva zahlavi podle klienta ---- */

#define SAMPLE_POINTS 5
#define SAMPLE_GAP_MS 200

static int64_t
now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* Horni radek obsahu: pet bodu pres sirku. Jednobarevny a neutralni = barva zahlavi; pruhledny nebo
 * barevny (obrazek, znacka aplikace) = svetle nebo tmave zahlavi podle jasu; ruznobarevny = nezname. */
static uint32_t
sample_client(struct deco *d, struct wlr_texture *tex, struct wlr_surface *s, struct wlr_box g)
{
	double f = (double)tex->width / s->current.width;
	int y = lround(g.y * f), x0 = lround(g.x * f), n = lround(g.width * f);
	if (n < SAMPLE_POINTS || x0 < 0 || y < 0 || x0 + n > (int)tex->width || y >= (int)tex->height) {
		return 0;
	}
	uint32_t *row = malloc(n * 4);
	bool ok = wlr_texture_read_pixels(tex, &(struct wlr_texture_read_pixels_options){
		.data = row, .format = DRM_FORMAT_ARGB8888, .stride = n * 4,
		.src_box = { x0, y, n, 1 } });
	/* nepravidelne rozestupy: pravidelny vzor (pruhy, mrizka) nesmi vyjit jako jedna barva */
	static const int at[SAMPLE_POINTS] = { 7, 23, 51, 68, 89 };
	uint32_t px[SAMPLE_POINTS];
	for (int i = 0; ok && i < SAMPLE_POINTS; i++) {
		px[i] = row[at[i] * n / 100];
	}
	free(row);
	if (!ok) {
		return 0;
	}
	int lo[4] = { 255, 255, 255, 255 }, hi[4] = { 0 };
	for (int i = 0; i < SAMPLE_POINTS; i++) {
		for (int c = 0; c < 4; c++) {
			int v = px[i] >> (8 * c) & 0xff;
			lo[c] = MIN(lo[c], v);
			hi[c] = MAX(hi[c], v);
		}
	}
	for (int c = 0; c < 4; c++) {
		if (hi[c] - lo[c] > 4) {
			return 0;
		}
	}
	/* pixely jsou premultiplikovane */
	uint32_t a = px[0] >> 24, rgb[3];
	if (a == 0) {
		return 0;
	}
	for (int c = 0; c < 3; c++) {
		rgb[c] = MIN(255u, (px[0] >> (16 - 8 * c) & 0xff) * 255 / a);
	}
	uint32_t color = 0xff000000 | rgb[0] << 16 | rgb[1] << 8 | rgb[2];
	int chroma = MAX(rgb[0], MAX(rgb[1], rgb[2])) - MIN(rgb[0], MIN(rgb[1], rgb[2]));
	if (a < 250 || chroma > 24) {
		return luminance(color) < 0.5 ? theme.bg_dark : theme.bg_light;
	}
	return color;
}

static void
sample_update(struct deco *d, bool force)
{
	struct view *v = d->view;
	struct wlr_scene_tree *content = content_tree(v);
	struct wlr_surface *s = content ? view_surface(v) : NULL;
	struct wlr_texture *tex = s ? wlr_surface_get_texture(s) : NULL;
	if (!tex || s->current.viewport.has_src || s->current.transform != WL_OUTPUT_TRANSFORM_NORMAL) {
		return;
	}
	struct wlr_box g = geometry(v);
	if (!force && wlr_box_equal(&g, &d->sampled_geo)) {
		/* jen kdyz se horni radek zmenil (prepnuti tmaveho rezimu), video nahore nevycerpa GPU */
		if (s->current.seq == d->sample_seq) {
			return;
		}
		d->sample_seq = s->current.seq;
		pixman_region32_t damage;
		pixman_region32_init(&damage);
		wlr_surface_get_effective_damage(s, &damage);
		pixman_box32_t top = { g.x, g.y, g.x + g.width, g.y + 1 };
		bool hit = pixman_region32_contains_rectangle(&damage, &top) != PIXMAN_REGION_OUT;
		pixman_region32_fini(&damage);
		if (!hit) {
			return;
		}
		int64_t wait = d->sampled_ms + SAMPLE_GAP_MS - now_ms();
		if (wait > 0) {
			wl_event_source_timer_update(d->sample_timer, wait);
			return;
		}
	}
	d->sampled_geo = g;
	d->sampled_ms = now_ms();
	d->sample_seq = s->current.seq;
	uint32_t color = sample_client(d, tex, s, g);
	if (color != d->client_bg) {
		d->client_bg = color;
		d->width = -1;	/* prekreslit */
	}
}

static int
sample_later(void *data)
{
	struct deco *d = data;
	if (d->ssd) {
		sample_update(d, true);
		deco_update(d);
	}
	return 0;
}

/* ---- zivotni cyklus ---- */

struct deco *
deco_create(struct view *view)
{
	struct deco *d = calloc(1, sizeof(*d));
	d->view = view;
	d->node = wlr_scene_buffer_create(view->tree, NULL);
	for (int i = 0; i < 2; i++) {
		d->corner[i] = wlr_scene_buffer_create(view->body, NULL);
		d->corner[i]->point_accepts_input = no_input;
		wlr_scene_node_lower_to_bottom(&d->corner[i]->node);
		wlr_scene_node_set_enabled(&d->corner[i]->node, false);
	}
	/* poradi zdola: stin, obrys, okno */
	d->outline = shadow_create(view->tree);
	d->shadow = shadow_create(view->tree);
	d->sample_timer = wl_event_loop_add_timer(comp.loop, sample_later, d);
	d->ssd = view->decorated;
	d->width = -1;
	deco_update(d);
	return d;
}

void
deco_set_ssd(struct deco *d, bool on)
{
	if (d->ssd != on) {
		d->ssd = on;
		d->width = -1;
		deco_update(d);
	}
}

void
deco_destroy(struct deco *d)
{
	if (hovered == d) {
		hovered = NULL;
	}
	if (d->rounded) {
		corners_off(d);
	}
	if (d->strip) {
		wlr_scene_node_destroy(&d->strip->node);
	}
	wlr_scene_node_destroy(&d->corner[0]->node);
	wlr_scene_node_destroy(&d->corner[1]->node);
	shadow_destroy(d->shadow);
	shadow_destroy(d->outline);
	wl_event_source_remove(d->sample_timer);
	wlr_scene_node_destroy(&d->node->node);
	for (int i = 0; i < 3; i++) {
		if (d->held[i]) {
			wlr_buffer_unlock(d->held[i]);
		}
	}
	free(d->title);
	free(d);
}

/* Zahlavi a stin se kresli v meritku nejvetsiho vystupu, na mensich je scena zmensi */
static int
output_scale(void)
{
	double max = 1;
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		if (o->wlr_output->enabled && o->wlr_output->scale > max) {
			max = o->wlr_output->scale;
		}
	}
	return ceil(max);
}

/* Prekresli jen kdyz se zmenilo, co je videt (commit chodi kazdy snimek klienta) */
void
deco_update(struct deco *d)
{
	struct view *v = d->view;
	int64_t id = v->id;
	bool fullscreen = luxcomp_view_get(id, LUXCOMP_VIEW_FULLSCREEN);
	wlr_scene_node_set_enabled(&d->node->node, d->ssd && !fullscreen);
	int width = view_width(v), height = view_height(v), scale = output_scale();
	bool active = comp.focused == v;
	bool square = fullscreen || luxcomp_view_get(id, LUXCOMP_VIEW_MAXIMIZED);
	const char *title = luxcomp_view_title(id) ? luxcomp_view_title(id) : "";
	bool same = width == d->width && height == d->height && active == d->active
		&& square == d->square && scale == d->scale && v->compact == d->compact;
	d->square = square;
	corners_update(d);
	if (d->ssd) {
		sample_update(d, false);
		same = same && d->width == width;
	}
	if (same && d->title && !strcmp(title, d->title)) {
		return;
	}
	d->width = width;
	d->height = height;
	d->active = active;
	d->scale = scale;
	d->compact = v->compact;
	free(d->title);
	d->title = strdup(title);
	/* okno s vlastnim zahlavim (GTK headerbar): stin kolem geometrie okna (bez okraju pro stin
	 * klienta), zahlavi nekreslit */
	int t = 0;
	if (d->ssd) {
		redraw(d);
		t = title_height(d);
	}
	struct wlr_box frame = { 0, -t, width, height + t };
	int size = theme.shadow_size[active], offset = theme.shadow_offset[active];
	shadow_update(d->shadow, frame, square ? 0 : size, offset < 0 ? size / 4 : offset, theme.radius,
		theme.shadow[active], scale, true);
	shadow_update(d->outline, frame, square ? 0 : 1, 0, theme.radius, theme.border, scale, false);
}

bool
deco_owns_node(struct deco *d, struct wlr_scene_node *node)
{
	return node == &d->node->node;
}

/* x, y relativne k levemu hornimu rohu obsahu okna (zahlavi ma y < 0) */
int
deco_part_at(struct deco *d, double x, double y)
{
	double cy = -title_height(d) / 2.0;
	for (int i = 0; i < 3; i++) {
		double cx = button_cx(d, i);
		/* zasahova plocha o pul mezery vetsi nez kolecko */
		double reach = (theme.button + theme.spacing) / 2.0;
		if (fabs(x - cx) <= reach && fabs(y - cy) <= reach) {
			return LUXCOMP_PART_CLOSE + i;
		}
	}
	return LUXCOMP_PART_TITLE;
}

void
deco_hover(struct deco *d, int part)
{
	if (part < LUXCOMP_PART_CLOSE || part > LUXCOMP_PART_MAXIMIZE) {
		d = NULL;
		part = 0;
	}
	if (hovered && (hovered != d || hovered->hover != part)) {
		hovered->hover = 0;
		redraw(hovered);
	}
	hovered = d;
	if (d && d->hover != part) {
		d->hover = part;
		redraw(d);
	}
}

int
deco_height(struct deco *d)
{
	return title_height(d);
}

void
deco_redraw(struct deco *d)
{
	d->width = -1;
	deco_update(d);
}

static void
redraw_all(void)
{
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (v->deco) {
			v->deco->width = -1;
			v->deco->corner_px = 0;	/* polomer se mohl zmenit */
			v->deco->sampled_geo = (struct wlr_box){ 0 };	/* i barvy zahlavi */
			deco_update(v->deco);
		}
	}
}

void
luxcomp_theme_set(int64_t prop, int64_t value)
{
	uint32_t c = value;
	switch (prop) {
	case LUXCOMP_THEME_TITLE_HEIGHT: theme.title_height[0] = value; break;
	case LUXCOMP_THEME_TITLE_HEIGHT_COMPACT: theme.title_height[1] = value; break;
	case LUXCOMP_THEME_BUTTON_INSET: theme.inset[0] = value; break;
	case LUXCOMP_THEME_BUTTON_INSET_COMPACT: theme.inset[1] = value; break;
	case LUXCOMP_THEME_CORNER_RADIUS: theme.radius = value; break;
	case LUXCOMP_THEME_BUTTON_SIZE: theme.button = value; break;
	case LUXCOMP_THEME_BUTTON_SPACING: theme.spacing = value; break;
	case LUXCOMP_THEME_BG_ACTIVE: theme.bg[1] = c; break;
	case LUXCOMP_THEME_BG_INACTIVE: theme.bg[0] = c; break;
	case LUXCOMP_THEME_BG_LIGHT: theme.bg_light = c; break;
	case LUXCOMP_THEME_BG_DARK: theme.bg_dark = c; break;
	case LUXCOMP_THEME_TEXT_ACTIVE: theme.text[0][1] = c; break;
	case LUXCOMP_THEME_TEXT_INACTIVE: theme.text[0][0] = c; break;
	case LUXCOMP_THEME_DARK_TEXT_ACTIVE: theme.text[1][1] = c; break;
	case LUXCOMP_THEME_DARK_TEXT_INACTIVE: theme.text[1][0] = c; break;
	case LUXCOMP_THEME_CLOSE: theme.close = c; break;
	case LUXCOMP_THEME_MINIMIZE: theme.minimize = c; break;
	case LUXCOMP_THEME_MAXIMIZE: theme.maximize = c; break;
	case LUXCOMP_THEME_BUTTON_INACTIVE: theme.button_inactive[0] = c; break;
	case LUXCOMP_THEME_DARK_BUTTON_INACTIVE: theme.button_inactive[1] = c; break;
	case LUXCOMP_THEME_BUTTON_RING: theme.ring[0] = c; break;
	case LUXCOMP_THEME_DARK_BUTTON_RING: theme.ring[1] = c; break;
	case LUXCOMP_THEME_ACCENT: theme.accent = c; break;
	case LUXCOMP_THEME_BORDER: theme.border = c; break;
	case LUXCOMP_THEME_SEPARATOR: theme.separator = c; break;
	case LUXCOMP_THEME_GLYPH: theme.glyph = c; break;
	case LUXCOMP_THEME_SHADOW_ACTIVE: theme.shadow[1] = c; break;
	case LUXCOMP_THEME_SHADOW_INACTIVE: theme.shadow[0] = c; break;
	case LUXCOMP_THEME_SHADOW_ACTIVE_SIZE: theme.shadow_size[1] = value; break;
	case LUXCOMP_THEME_SHADOW_INACTIVE_SIZE: theme.shadow_size[0] = value; break;
	case LUXCOMP_THEME_SHADOW_ACTIVE_OFFSET: theme.shadow_offset[1] = value; break;
	case LUXCOMP_THEME_SHADOW_INACTIVE_OFFSET: theme.shadow_offset[0] = value; break;
	default: return;
	}
	redraw_all();
}

void
luxcomp_theme_set_font(const char *font)
{
	free(theme.font);
	theme.font = font && *font ? strdup(font) : NULL;
	redraw_all();
}
