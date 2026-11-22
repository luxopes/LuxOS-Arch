/*
 * Prechod po prihlaseni jako luxos-session-cover --login v X11 (LuxOS 1.0.5): posledni snimek prihlasovaci
 * obrazovky (ztmavena tapeta bez formulare, ulozi ho luxos-greeter) a pres nej tenky bar prubehu jako pri
 * startu systemu (Plymouth, 220x6) na miste pole pro heslo. Bar se plni podle fazi relace
 * (luxcomp_cover_stage) a nikdy nestoji; az je plocha nakreslena, zakryti se behem 280 ms rozplyne do hotove
 * plochy (pruhlednost (1 - t)^2 jako 14 kroku v X11). Vstup jde skrz (input.c hit_test).
 */
#define _GNU_SOURCE
#include <cairo.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <wlr/interfaces/wlr_buffer.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/util/log.h>
#include "internal.h"

/* luxos-session-cover.c */
#define BAR_W 220
#define BAR_H 6
#define BAR_FADE_IN_MS 250
#define BAR_TAU_MS 300.0		/* jak rychle vypln dobiha k cili */
#define BAR_FINISH_TAU_MS 70.0		/* hotovo: rychle do konce */
#define BAR_CREEP_MS 2500.0		/* v kazde fazi se pomalu blizi k dalsi */
#define BAR_STAGES 5			/* start, spravce oken, plocha a lista, plocha vykreslena, hotovo */
#define FRAME_MAX_SIDE 16384

static const double bar_level[BAR_STAGES] = { 0.04, 0.30, 0.55, 0.80, 1.0 };

static struct {
	struct wlr_scene_rect *rect;
	struct wlr_scene_buffer *frame;	/* snimek greeteru, NULL = jen barva */
	struct wlr_scene_buffer *bar;	/* NULL = bez baru */
	float color[4];
	double time_scale;
	int64_t start_ns;		/* luxcomp_cover_stage(0): od kdy se meri faze baru */
	double stage_at[BAR_STAGES];	/* ms od startu, 0 = jeste ne */
	double fill, last_ms;
	int64_t fade_start, fade_ns;	/* fade_ns 0 = nerozplyva se */
	int frames;
	int64_t render_max_ns;
} cover;

static int64_t
now_ns(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000000000LL + t.tv_nsec;
}

/* Hlavni vystup: prvni pripojeny (greeter je pres celou obrazovku na nem) */
static struct output *
primary(void)
{
	if (wl_list_empty(&comp.outputs)) {
		return NULL;
	}
	struct output *o = wl_container_of(comp.outputs.next, o, link);
	return o;
}

/* Cil vyplne v case t: uroven posledni dosazene faze a pomale priblizovani k dalsi */
static double
bar_goal(double t, int *last)
{
	int k = 0;
	for (int i = 1; i < BAR_STAGES; i++) {
		if (cover.stage_at[i] > 0 && cover.stage_at[i] <= t) {
			k = i;
		}
	}
	*last = k;
	if (k == BAR_STAGES - 1) {
		return 1.0;
	}
	double since = t - (k ? cover.stage_at[k] : 0);
	double a = bar_level[k], next = bar_level[k + 1];
	return a + (next - a) * 0.85 * (1.0 - exp(-since / BAR_CREEP_MS));
}

/* Zaobleny obdelnik s pulkruhy na koncich */
static void
rounded_path(cairo_t *cr, double x, double w, double h)
{
	double r = h / 2;
	cairo_new_path(cr);
	cairo_arc(cr, x + w - r, r, r, -M_PI / 2, M_PI / 2);
	cairo_arc(cr, x + r, r, r, M_PI / 2, 3 * M_PI / 2);
	cairo_close_path(cr);
}

/* Draha (tlumena bila) a vypln (bar-fill Plymouthu) posunuta tak, ze jeji kulaty konec je v miste postupu */
static struct wlr_buffer *
bar_draw(int w, int h, double fw)
{
	cairo_surface_t *s;
	struct wlr_buffer *buffer = cairo_buffer_create(w, h, &s);
	cairo_t *cr = cairo_create(s);
	cairo_set_operator(cr, CAIRO_OPERATOR_SOURCE);
	cairo_set_source_rgba(cr, 0, 0, 0, 0);
	cairo_paint(cr);
	cairo_set_operator(cr, CAIRO_OPERATOR_OVER);
	rounded_path(cr, 0, w, h);
	cairo_set_source_rgba(cr, 1, 1, 1, 0.22);
	cairo_fill_preserve(cr);
	cairo_clip(cr);
	rounded_path(cr, fw - w, w, h);
	cairo_set_source_rgba(cr, 0xee / 255.0, 0xf4 / 255.0, 1.0, 0.95);
	cairo_fill(cr);
	cairo_destroy(cr);
	cairo_surface_flush(s);
	return buffer;
}

static void
cover_end(void)
{
	if (getenv("LUXCOMP_STATS") && cover.fade_ns) {
		wlr_log(WLR_ERROR, "luxcomp: cover fade %d frames, slowest render %.2f ms",
			cover.frames, cover.render_max_ns / 1e6);
	}
	cover.fade_ns = 0;
	wlr_scene_node_set_enabled(&comp.cover->node, false);
	if (cover.frame) {
		wlr_scene_node_destroy(&cover.frame->node);
		cover.frame = NULL;
	}
	if (cover.bar) {
		wlr_scene_node_destroy(&cover.bar->node);
		cover.bar = NULL;
	}
}

/* Pred kazdym snimkem: poloha snimku a baru na hlavnim vystupu, postup baru, rozplynuti. true = dalsi snimek */
bool
cover_step(int64_t now)
{
	if (!comp.cover->node.enabled) {
		return false;
	}
	double alpha = 1;
	if (cover.fade_ns) {
		double p = (double)(now - cover.fade_start) / cover.fade_ns;
		if (p >= 1) {
			cover_end();
			return false;
		}
		p = p < 0 ? 0 : p;
		alpha = (1 - p) * (1 - p);
	}
	float c[4] = { cover.color[0] * alpha, cover.color[1] * alpha, cover.color[2] * alpha,
		cover.color[3] * alpha };
	wlr_scene_rect_set_color(cover.rect, c);

	struct output *o = primary();
	if (!o) {
		return cover.fade_ns || cover.bar;
	}
	struct wlr_box box;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
	float scale = o->wlr_output->scale > 0 ? o->wlr_output->scale : 1;
	if (cover.frame) {
		wlr_scene_node_set_position(&cover.frame->node, box.x, box.y);
		wlr_scene_buffer_set_dest_size(cover.frame, box.width, box.height);
		wlr_scene_buffer_set_opacity(cover.frame, alpha);
		/* snimek pres jediny monitor: barva pod nim by pri rozplynuti ztmavila plochu navic */
		wlr_scene_node_set_enabled(&cover.rect->node, wl_list_length(&comp.outputs) > 1);
	}
	if (!cover.bar) {
		return cover.fade_ns;
	}

	/* rozmery jako bar_geometry() v X11 (pixely monitoru), na scenu v logickych bodech */
	int mw = o->wlr_output->width, mh = o->wlr_output->height;
	double u = fmax(0.55, mh / 1080.0);
	int k = (int)fmax(1, (int)(mh / 1080.0 + 0.5));
	int w = BAR_W * k, h = BAR_H * k;
	int x = mw / 2 - w / 2, y = mh - (int)(204 * u + 0.5) - h / 2;

	double t = (now - cover.start_ns) / 1e6 / cover.time_scale;
	int last;
	double goal = bar_goal(t, &last);
	double dt = cover.last_ms < 0 ? 0 : t - cover.last_ms;
	cover.last_ms = t;
	double tau = last == BAR_STAGES - 1 ? BAR_FINISH_TAU_MS : BAR_TAU_MS;
	if (goal > cover.fill) {
		cover.fill += (goal - cover.fill) * (1.0 - exp(-dt / tau));
	}
	double fw = fmax(h, cover.fill * w);
	struct wlr_buffer *buffer = bar_draw(w, h, fw);
	wlr_scene_buffer_set_buffer(cover.bar, buffer);
	wlr_buffer_drop(buffer);
	wlr_scene_buffer_set_dest_size(cover.bar, lround(w / scale), lround(h / scale));
	wlr_scene_node_set_position(&cover.bar->node, box.x + lround(x / scale), box.y + lround(y / scale));
	wlr_scene_buffer_set_opacity(cover.bar, alpha * fmin(1, t / BAR_FADE_IN_MS));
	return true;
}

void
cover_frame_done(int64_t render_ns)
{
	if (cover.fade_ns) {
		cover.frames++;
		if (render_ns > cover.render_max_ns) {
			cover.render_max_ns = render_ns;
		}
	}
}

static bool
no_input(struct wlr_scene_buffer *buffer, double *sx, double *sy)
{
	return false;
}

void
cover_init(double time_scale)
{
	cover.time_scale = time_scale;
	comp.cover = wlr_scene_tree_create(&comp.scene->tree);
	cover.rect = wlr_scene_rect_create(comp.cover, 32768, 32768, (float[4]){ 0, 0, 0, 1 });
	wlr_scene_node_set_position(&cover.rect->node, -16384, -16384);
	wlr_scene_node_set_enabled(&comp.cover->node, false);
}

static void
schedule_frames(void)
{
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		wlr_output_schedule_frame(o->wlr_output);
	}
}

/* ---- API ---- */

void
luxcomp_cover(int64_t argb)
{
	cover.color[3] = (argb >> 24 & 0xff) / 255.0f;
	cover.color[0] = (argb >> 16 & 0xff) / 255.0f * cover.color[3];
	cover.color[1] = (argb >> 8 & 0xff) / 255.0f * cover.color[3];
	cover.color[2] = (argb & 0xff) / 255.0f * cover.color[3];
	cover.fade_ns = 0;
	if (!(argb >> 24 & 0xff)) {
		cover_end();
		return;
	}
	wlr_scene_rect_set_color(cover.rect, cover.color);
	wlr_scene_node_set_enabled(&cover.rect->node, true);
	wlr_scene_node_set_enabled(&comp.cover->node, true);
	schedule_frames();
}

/* "LUXFRAME1 <w> <h>\n" + w*h*4 bajtu BGRx (cairo RGB24 na little-endian), jako login-frame.raw v X11.
 * Otevreny soubor za hlavickou, NULL = chybi, je starsi nez max_age_s nebo nesedi velikost. */
static FILE *
frame_open(const char *path, int64_t max_age_s, unsigned *w, unsigned *h)
{
	struct stat st;
	if (!path || stat(path, &st) != 0 || time(NULL) - st.st_mtime > max_age_s
			|| time(NULL) - st.st_mtime < -5) {
		return NULL;
	}
	FILE *f = fopen(path, "rb");
	if (f && fscanf(f, "LUXFRAME1 %u %u", w, h) == 2 && fgetc(f) == '\n' && *w && *h
			&& *w <= FRAME_MAX_SIDE && *h <= FRAME_MAX_SIDE
			&& st.st_size - ftell(f) == (off_t)*w * *h * 4) {
		return f;
	}
	if (f) {
		fclose(f);
	}
	return NULL;
}

int64_t
luxcomp_cover_frame(const char *path, int64_t max_age_s)
{
	unsigned w = 0, h = 0;
	FILE *f = frame_open(path, max_age_s, &w, &h);
	if (!f) {
		return 0;
	}
	cairo_surface_t *s;
	struct wlr_buffer *buffer = cairo_buffer_create(w, h, &s);
	unsigned char *data = cairo_image_surface_get_data(s);
	int stride = cairo_image_surface_get_stride(s);
	bool ok = true;
	for (unsigned y = 0; y < h && ok; y++) {
		unsigned char *row = data + (size_t)y * stride;
		ok = fread(row, 4, w, f) == w;
		for (unsigned x = 0; x < w; x++) {
			row[x * 4 + 3] = 0xff;
		}
	}
	cairo_surface_mark_dirty(s);
	fclose(f);
	if (!ok) {
		wlr_buffer_drop(buffer);
		wlr_log(WLR_ERROR, "luxcomp: bad cover frame %s", path);
		return 0;
	}
	if (cover.frame) {
		wlr_scene_node_destroy(&cover.frame->node);
	}
	cover.frame = wlr_scene_buffer_create(comp.cover, buffer);
	cover.frame->point_accepts_input = no_input;
	wlr_buffer_drop(buffer);
	if (cover.bar) {
		wlr_scene_node_raise_to_top(&cover.bar->node);
	}
	return 1;
}

void
luxcomp_cover_stage(int64_t stage)
{
	if (stage == 0) {
		cover.start_ns = now_ns();
		memset(cover.stage_at, 0, sizeof(cover.stage_at));
		cover.fill = 0;
		cover.last_ms = -1;
		if (!cover.bar) {
			cover.bar = wlr_scene_buffer_create(comp.cover, NULL);
			cover.bar->point_accepts_input = no_input;
		}
		schedule_frames();
		return;
	}
	if (stage >= BAR_STAGES || !cover.bar) {
		return;
	}
	double t = (now_ns() - cover.start_ns) / 1e6 / cover.time_scale;
	for (int i = 1; i <= stage; i++) {
		if (cover.stage_at[i] <= 0) {
			cover.stage_at[i] = t > 0 ? t : 1;
		}
	}
}

void
luxcomp_cover_fade(int64_t ms)
{
	if (!comp.cover->node.enabled) {
		return;
	}
	luxcomp_cover_stage(BAR_STAGES - 1);	/* bar dobehne do konce behem rozplynuti */
	if (ms <= 0) {
		cover_end();
		return;
	}
	cover.fade_start = now_ns();
	cover.fade_ns = ms * 1000000.0 * cover.time_scale;
	cover.frames = 0;
	cover.render_max_ns = 0;
	schedule_frames();
}


