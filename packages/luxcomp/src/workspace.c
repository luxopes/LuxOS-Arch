/*
 * Plochy a jejich prejezd do strany (jako Spaces v macOS).
 *
 * Animace bezi v C, krok po kazdem vykreslenem snimku vystupu (synchronne s obnovou), aby
 * politika v LSL nemusela nic delat kazdy snimek. Krivka "ease" (cubic-bezier 0.25,0.1,0.25,1)
 * jako v xfwm4. Kdyz vykresleni snimku trva prilis dlouho (pixman na pomalem stroji), prejezd
 * se dokonci hned - radeji skok nez trhana animace.
 */
#define _GNU_SOURCE
#include <math.h>
#include <stdlib.h>
#include <time.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/util/log.h>
#include "internal.h"

/* polovina snimku pri 60 Hz; dva takove snimky za sebou = prejezd skoci na konec */
#define SLOW_FRAME_NS 8000000

static struct {
	struct workspace *from, *to;
	int dir, width;
	double from_start;	/* poloha "from" na zacatku (navazani na prerusenou animaci) */
	int64_t start_ns, duration_ns;
	int slow_frames;
	int frames;
	int64_t render_ns_max;
} slide;

static int64_t
now_ns(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec * 1000000000LL + t.tv_nsec;
}

/* cubic-bezier(0.25, 0.1, 0.25, 1): x(s) -> s Newtonem, vrati y(s) */
static double
ease(double x)
{
	const double x1 = 0.25, y1 = 0.1, x2 = 0.25, y2 = 1.0;
	double s = x;
	for (int i = 0; i < 8; i++) {
		double bx = 3 * x1 * s * (1 - s) * (1 - s) + 3 * x2 * s * s * (1 - s) + s * s * s;
		double dx = 3 * x1 * (1 - s) * (1 - 3 * s) + 3 * x2 * s * (2 - 3 * s) + 3 * s * s;
		if (fabs(dx) < 1e-6) {
			break;
		}
		s -= (bx - x) / dx;
		s = s < 0 ? 0 : s > 1 ? 1 : s;
	}
	return 3 * y1 * s * (1 - s) * (1 - s) + 3 * y2 * s * s * (1 - s) + s * s * s;
}

struct workspace *
workspace_by_id(int64_t id)
{
	struct workspace *ws;
	wl_list_for_each(ws, &comp.workspaces, link) {
		if (ws->id == id) {
			return ws;
		}
	}
	return NULL;
}

struct workspace *
workspace_create(void)
{
	struct workspace *ws = calloc(1, sizeof(*ws));
	ws->id = ++comp.next_id;
	ws->tree = wlr_scene_tree_create(comp.views);
	/* prvni plocha je videt, dalsi az na pokyn politiky */
	ws->shown = wl_list_empty(&comp.workspaces);
	wlr_scene_node_set_enabled(&ws->tree->node, ws->shown);
	wl_list_insert(comp.workspaces.prev, &ws->link);
	return ws;
}

static void
show(struct workspace *ws, bool on)
{
	ws->shown = on;
	wlr_scene_node_set_enabled(&ws->tree->node, on);
	wlr_scene_node_set_position(&ws->tree->node, 0, 0);
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (v->workspace == ws) {
			view_update_enabled(v);
		}
	}
}

static void
slide_finish(void)
{
	struct workspace *from = slide.from, *to = slide.to;
	if (getenv("LUXCOMP_STATS")) {
		wlr_log(WLR_ERROR, "luxcomp: slide %d frames, slowest render %.2f ms",
			slide.frames, slide.render_ns_max / 1e6);
	}
	slide.from = slide.to = NULL;
	if (from != to) {
		show(from, false);
	}
	show(to, true);
	emit(LUXCOMP_EV_SLIDE_DONE, to->id, 0, 0, 0);
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
slide_step(void)
{
	double target = -slide.dir * slide.width;
	double p = slide.duration_ns > 0
		? (double)(now_ns() - slide.start_ns) / slide.duration_ns : 1;
	if (p >= 1) {
		slide_finish();
		return;
	}
	double x = slide.from_start + (target - slide.from_start) * ease(p);
	wlr_scene_node_set_position(&slide.from->tree->node, lround(x), 0);
	wlr_scene_node_set_position(&slide.to->tree->node,
		lround(x + slide.dir * slide.width), 0);
	schedule_frames();
}

void
workspaces_frame_done(int64_t render_ns)
{
	if (!slide.to) {
		return;
	}
	slide.frames++;
	if (render_ns > slide.render_ns_max) {
		slide.render_ns_max = render_ns;
	}
	slide.slow_frames = render_ns > SLOW_FRAME_NS ? slide.slow_frames + 1 : 0;
	if (slide.slow_frames >= 2) {
		slide_finish();
		return;
	}
	slide_step();
}

/* ---- API ---- */

int64_t
luxcomp_workspace_new(void)
{
	return workspace_create()->id;
}

void
luxcomp_workspace_show(int64_t id, int64_t on)
{
	struct workspace *ws = workspace_by_id(id);
	if (ws) {
		show(ws, on);
	}
}

void
luxcomp_workspace_slide(int64_t from_id, int64_t to_id, int64_t dir, int64_t ms)
{
	struct workspace *from = workspace_by_id(from_id), *to = workspace_by_id(to_id);
	if (!from || !to || from == to) {
		return;
	}
	double from_start = 0;
	if (slide.to) {
		/* navazat: novy "from" je dosud prijizdejici plocha v aktualni poloze */
		if (slide.from != to) {
			show(slide.from, false);
		}
		from = slide.to;
		from_start = from->tree->node.x;
		slide.from = slide.to = NULL;
	}
	struct output *o = output_at(comp.cursor->x, comp.cursor->y);
	if (!o && !wl_list_empty(&comp.outputs)) {
		o = wl_container_of(comp.outputs.next, o, link);
	}
	int width = 0;
	if (o) {
		struct wlr_box box;
		wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
		width = box.width;
	}

	slide.from = from;
	slide.to = to;
	slide.dir = dir < 0 ? -1 : 1;
	slide.width = width;
	slide.from_start = from_start;
	slide.slow_frames = 0;
	slide.frames = 0;
	slide.render_ns_max = 0;
	slide.start_ns = now_ns();
	double distance = width ? fabs(-slide.dir * width - from_start) / width : 0;
	slide.duration_ns = ms > 0 ? (int64_t)(ms * 1000000.0 * distance) : 0;
	if (slide.duration_ns <= 0 || !width) {
		slide_finish();
		return;
	}
	wlr_scene_node_set_enabled(&to->tree->node, true);
	to->shown = true;
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (v->workspace == to) {
			view_update_enabled(v);
		}
	}
	slide_step();
}
