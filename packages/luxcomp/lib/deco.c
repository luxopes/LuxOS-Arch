/*
 * Zahlavi oken kreslene kompozitorem (semafor vlevo, nazev uprostred).
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
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_xdg_shell.h>
#include "internal.h"

static struct {
	int title_height, radius, button, spacing;
	uint32_t bg[2], text[2], close, minimize, maximize, button_inactive, separator;
	char *font;
} theme = {
	.title_height = 28,
	.radius = 10,
	.button = 12,
	.spacing = 8,
	.bg = { 0xffe8e8e8, 0xfff6f6f6 },	/* [0] neaktivni, [1] aktivni */
	.text = { 0xffa0a0a0, 0xff3c3c3c },
	.close = 0xffff5f57,
	.minimize = 0xfffebc2e,
	.maximize = 0xff28c840,
	.button_inactive = 0xffcfcfcf,
	.separator = 0x26000000,
};

struct deco {
	struct view *view;
	struct wlr_scene_buffer *node;
	int width;
	bool active;
	char *title;
};

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

/* ---- kresleni ---- */

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

static struct wlr_buffer *
render(struct deco *d)
{
	int w = d->width, h = theme.title_height, r = theme.radius;
	struct cairo_buffer *cb = calloc(1, sizeof(*cb));
	wlr_buffer_init(&cb->base, &cbuf_impl, w, h);
	cb->surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h);
	cairo_t *cr = cairo_create(cb->surface);

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
		set_color(cr, d->active ? colors[i] : theme.button_inactive);
		cairo_arc(cr, button_x(i) + theme.button / 2.0, h / 2.0, theme.button / 2.0,
			0, 2 * M_PI);
		cairo_fill(cr);
	}

	if (d->title && *d->title) {
		int reserved = button_x(3);
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
	cairo_surface_flush(cb->surface);
	return &cb->base;
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
	wlr_scene_node_set_position(&d->node->node, 0, -theme.title_height);
}

struct deco *
deco_create(struct view *view)
{
	struct deco *d = calloc(1, sizeof(*d));
	d->view = view;
	d->node = wlr_scene_buffer_create(view->tree, NULL);
	d->width = -1;
	deco_update(d);
	return d;
}

void
deco_destroy(struct deco *d)
{
	wlr_scene_node_destroy(&d->node->node);
	free(d->title);
	free(d);
}

/* Prekresli jen kdyz se zmenilo, co je videt (commit chodi kazdy snimek klienta) */
void
deco_update(struct deco *d)
{
	int64_t id = d->view->id;
	wlr_scene_node_set_enabled(&d->node->node, !luxcomp_view_get(id, LUXCOMP_VIEW_FULLSCREEN));
	int width = view_width(d->view);
	bool active = comp.focused == d->view;
	const char *title = luxcomp_view_title(id) ? luxcomp_view_title(id) : "";
	if (width == d->width && active == d->active && d->title && !strcmp(title, d->title)) {
		return;
	}
	d->width = width;
	d->active = active;
	free(d->title);
	d->title = strdup(title);
	redraw(d);
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

int
deco_height(void)
{
	return theme.title_height;
}

static void
redraw_all(void)
{
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (v->deco) {
			v->deco->width = -1;
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
