/*
 * Zahlavi oken kreslene kompozitorem (semafor vlevo, nazev uprostred), stin a zaoblene dolni rohy.
 * Barvy a rozmery nastavuje politika pres luxcomp_theme_set(); vychozi hodnoty nize jsou
 * svetly vzhled LuxOS a pozdeji je prepisi tokeny navrhu (WP-4).
 */
#define _GNU_SOURCE
#include <cairo.h>
#include <drm_fourcc.h>
#include <math.h>
#include <pango/pangocairo.h>
#include <stdlib.h>
#include <string.h>
#include <wlr/interfaces/wlr_buffer.h>
#include <wlr/render/wlr_texture.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_xdg_shell.h>
#include "internal.h"

static struct {
	int title_height, radius, button, spacing;
	int shadow_size[2];
	uint32_t bg[2], text[2], shadow[2];
	uint32_t close, minimize, maximize, button_inactive, separator, glyph;
	char *font;
} theme = {
	.title_height = 28,
	.radius = 10,
	.button = 12,
	.spacing = 8,
	.shadow_size = { 24, 40 },
	.bg = { 0xffe8e8e8, 0xfff6f6f6 },	/* [0] neaktivni, [1] aktivni */
	.text = { 0xff6e6e6e, 0xff3c3c3c },
	.shadow = { 0x2e000000, 0x59000000 },
	.close = 0xffff5f57,
	.minimize = 0xfffebc2e,
	.maximize = 0xff28c840,
	.button_inactive = 0xffcfcfcf,
	.separator = 0x26000000,
	.glyph = 0xb33c140a,
};

struct deco {
	struct view *view;
	struct wlr_scene_buffer *node;
	struct shadow *shadow;
	/* zaoblene dolni rohy: obsah oriznuty nad dolnim pruhem, pruh mezi rohy (druhy strom
	 * stejneho povrchu) a dva rohy jako kopie pixelu klienta s maskou */
	struct wlr_scene_tree *strip;
	struct wlr_surface *strip_surface;
	struct wlr_scene_buffer *corner[2];
	struct wlr_box corner_geo;
	int corner_px;
	bool rounded;
	int width, height, scale, hover;
	bool active, square;
	char *title;
};

static struct deco *hovered;

/* ---- wlr_buffer nad pameti cairo ---- */

struct cairo_buffer {
	struct wlr_buffer base;
	cairo_surface_t *surface;
};

static void
cbuf_destroy(struct wlr_buffer *b)
{
	struct cairo_buffer *cb = wl_container_of(b, cb, base);
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
button_x(int i)
{
	return theme.spacing + i * (theme.button + theme.spacing);
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

/* Znacka aplikace v sandboxu: tlumeny text na jemnem podkladu se zaoblenymi rohy u praveho okraje. Vraci sirku
 * vyhrazenou od okraje (nazev zustava uprostred okna). Zkracuje se, aby nezasahla do semaforu. */
static int
draw_badge(cairo_t *cr, struct deco *d, const char *text, int w, int h)
{
	PangoLayout *layout = pango_cairo_create_layout(cr);
	PangoFontDescription *font = pango_font_description_from_string(
		theme.font ? theme.font : "Inter Semi-Bold 10");
	pango_font_description_set_size(font, pango_font_description_get_size(font) * 4 / 5);
	pango_layout_set_font_description(layout, font);
	pango_font_description_free(font);
	pango_layout_set_text(layout, text, -1);
	pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
	pango_layout_set_single_paragraph_mode(layout, true);
	int pad = 6, max_w = w / 2 - button_x(3) - 2 * pad;
	if (max_w < 16) {
		g_object_unref(layout);
		return 0;
	}
	pango_layout_set_width(layout, max_w * PANGO_SCALE);
	int tw, th;
	pango_layout_get_pixel_size(layout, &tw, &th);
	double bh = th + 4, bw = tw + 2 * pad, x = w - theme.spacing - bw, y = (h - bh) / 2, r = bh / 2;
	cairo_new_sub_path(cr);
	cairo_arc(cr, x + r, y + r, r, M_PI / 2, 1.5 * M_PI);
	cairo_arc(cr, x + bw - r, y + r, r, 1.5 * M_PI, M_PI / 2);
	cairo_close_path(cr);
	set_color(cr, theme.separator);
	cairo_fill(cr);
	set_color(cr, theme.text[0]);
	cairo_move_to(cr, x + pad, (h - th) / 2.0);
	pango_cairo_show_layout(cr, layout);
	g_object_unref(layout);
	return w - (int)x + theme.spacing;
}

/* Kresli se v pixelech vystupu (meritko), scena buffer zmensi na logickou velikost */
static struct wlr_buffer *
render(struct deco *d)
{
	int w = d->width, h = theme.title_height, r = d->square ? 0 : theme.radius, k = d->scale;
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
	set_color(cr, theme.bg[d->active]);
	cairo_fill(cr);
	set_color(cr, theme.separator);
	cairo_rectangle(cr, 0, h - 1, w, 1);
	cairo_fill(cr);

	uint32_t colors[3] = { theme.close, theme.minimize, theme.maximize };
	for (int i = 0; i < 3; i++) {
		int part = LUXCOMP_PART_CLOSE + i;
		double cx = button_x(i) + theme.button / 2.0, cy = h / 2.0;
		/* neaktivni okno: sedy semafor, pod ukazatelem barva i znak */
		set_color(cr, d->active || d->hover == part ? colors[i] : theme.button_inactive);
		cairo_arc(cr, cx, cy, theme.button / 2.0, 0, 2 * M_PI);
		cairo_fill(cr);
		if (d->hover == part) {
			draw_glyph(cr, part, cx, cy);
		}
	}

	int reserved = button_x(3);
	const char *badge = d->view->badge;
	if (badge && w > 2 * reserved) {
		reserved = MAX(reserved, draw_badge(cr, d, badge, w, h));
	}
	if (d->title && *d->title) {
		int max_w = w - 2 * reserved;
		if (max_w > 20) {
			PangoLayout *layout = pango_cairo_create_layout(cr);
			PangoFontDescription *font = pango_font_description_from_string(
				theme.font ? theme.font : "Inter Semi-Bold 10");
			pango_layout_set_font_description(layout, font);
			pango_font_description_free(font);
			pango_layout_set_text(layout, d->title, -1);
			pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
			pango_layout_set_width(layout, max_w * PANGO_SCALE);
			pango_layout_set_single_paragraph_mode(layout, true);
			int tw, th;
			pango_layout_get_pixel_size(layout, &tw, &th);
			set_color(cr, theme.text[d->active]);
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
		wlr_scene_buffer_set_buffer(d->node, NULL);
		return;
	}
	struct wlr_buffer *b = render(d);
	wlr_scene_buffer_set_buffer(d->node, b);
	wlr_buffer_drop(b);
	wlr_scene_buffer_set_dest_size(d->node, d->width, theme.title_height);
	wlr_scene_node_set_position(&d->node->node, 0, -theme.title_height);
	/* nepruhledna cast zahlavi: scena pod ni nekresli (stin, okna pod oknem) */
	pixman_region32_t opaque;
	int r = d->square ? 0 : theme.radius;
	pixman_region32_init_rect(&opaque, 0, r, d->width,
		(theme.bg[d->active] >> 24) == 0xff ? theme.title_height - r : 0);
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
		wlr_scene_buffer_set_buffer(d->corner[i], buffer);
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
	wlr_surface_get_effective_damage(s, &damage);
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
	d->shadow = shadow_create(view->tree);
	d->width = -1;
	deco_update(d);
	return d;
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
	wlr_scene_node_destroy(&d->node->node);
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
	wlr_scene_node_set_enabled(&d->node->node, !fullscreen);
	int width = view_width(v), height = view_height(v), scale = output_scale();
	bool active = comp.focused == v;
	bool square = fullscreen || luxcomp_view_get(id, LUXCOMP_VIEW_MAXIMIZED);
	const char *title = luxcomp_view_title(id) ? luxcomp_view_title(id) : "";
	bool same = width == d->width && height == d->height && active == d->active
		&& square == d->square && scale == d->scale;
	d->square = square;
	corners_update(d);
	if (same && d->title && !strcmp(title, d->title)) {
		return;
	}
	d->width = width;
	d->height = height;
	d->active = active;
	d->scale = scale;
	free(d->title);
	d->title = strdup(title);
	redraw(d);
	int t = theme.title_height;
	shadow_update(d->shadow, (struct wlr_box){ 0, -t, width, height + t },
		square ? 0 : theme.shadow_size[active], theme.radius, theme.shadow[active], scale);
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
	double cy = -theme.title_height / 2.0;
	for (int i = 0; i < 3; i++) {
		double cx = button_x(i) + theme.button / 2.0;
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
deco_height(void)
{
	return theme.title_height;
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
			deco_update(v->deco);
		}
	}
}

void
luxcomp_theme_set(int64_t prop, int64_t value)
{
	uint32_t c = value;
	switch (prop) {
	case LUXCOMP_THEME_TITLE_HEIGHT: theme.title_height = value; break;
	case LUXCOMP_THEME_CORNER_RADIUS: theme.radius = value; break;
	case LUXCOMP_THEME_BUTTON_SIZE: theme.button = value; break;
	case LUXCOMP_THEME_BUTTON_SPACING: theme.spacing = value; break;
	case LUXCOMP_THEME_BG_ACTIVE: theme.bg[1] = c; break;
	case LUXCOMP_THEME_BG_INACTIVE: theme.bg[0] = c; break;
	case LUXCOMP_THEME_TEXT_ACTIVE: theme.text[1] = c; break;
	case LUXCOMP_THEME_TEXT_INACTIVE: theme.text[0] = c; break;
	case LUXCOMP_THEME_CLOSE: theme.close = c; break;
	case LUXCOMP_THEME_MINIMIZE: theme.minimize = c; break;
	case LUXCOMP_THEME_MAXIMIZE: theme.maximize = c; break;
	case LUXCOMP_THEME_BUTTON_INACTIVE: theme.button_inactive = c; break;
	case LUXCOMP_THEME_SEPARATOR: theme.separator = c; break;
	case LUXCOMP_THEME_GLYPH: theme.glyph = c; break;
	case LUXCOMP_THEME_SHADOW_ACTIVE: theme.shadow[1] = c; break;
	case LUXCOMP_THEME_SHADOW_INACTIVE: theme.shadow[0] = c; break;
	case LUXCOMP_THEME_SHADOW_ACTIVE_SIZE: theme.shadow_size[1] = value; break;
	case LUXCOMP_THEME_SHADOW_INACTIVE_SIZE: theme.shadow_size[0] = value; break;
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
