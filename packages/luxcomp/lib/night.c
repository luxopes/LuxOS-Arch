/* Nocni svetlo a softwarovy jas (luxcomp_set_night_light): gamma tabulka vystupu v KMS, kdyz ji vystup ma
 * (zadna prace navic pri vykreslovani, primy scanout zustava), jinak dva obdelniky nad celou scenou: teply
 * zavoj a cerne ztlumeni (VM, headless, displeje bez gamma tabulky). Klient gamma-control (gammastep,
 * wlsunset, kalibrace) ma na svem vystupu prednost. */
#include <math.h>
#include <stdlib.h>
#include <wlr/render/color.h>
#include <wlr/types/wlr_gamma_control_v1.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_scene.h>
#include "internal.h"

static struct {
	int kelvin;			/* 6500 = neutralni */
	int brightness;			/* 10..100 % */
	struct wl_listener set_gamma;
} night = { .kelvin = 6500, .brightness = 100 };

/* Bily bod cerneho telesa (aproximace Tannera Hellanda) vuci 6500 K */
static void
whitepoint(int kelvin, double rgb[3])
{
	double t = kelvin / 100.0;
	rgb[0] = t <= 66 ? 1.0 : 1.292936186 * pow(t - 60, -0.1332047592);
	rgb[1] = t <= 66 ? 0.390081579 * log(t) - 0.631841444 : 1.129890861 * pow(t - 60, -0.0755148492);
	rgb[2] = t >= 66 ? 1.0 : t <= 19 ? 0.0 : 0.543206789 * log(t - 10) - 1.196254089;
	static const double neutral[3] = { 1.0, 1.0, 0.98063 };	/* vzorec pro 6500 K */
	for (int i = 0; i < 3; i++) {
		rgb[i] = fmin(1.0, fmax(0.0, rgb[i] / neutral[i]));
	}
}

static bool
active(void)
{
	return night.kelvin < 6500 || night.brightness < 100;
}

static struct wlr_color_transform *
ramp(size_t size)
{
	double mul[3];
	whitepoint(night.kelvin, mul);
	uint16_t *lut = malloc(3 * size * sizeof(*lut));
	if (!lut) {
		return NULL;
	}
	for (size_t i = 0; i < size; i++) {
		double v = size > 1 ? (double)i / (size - 1) : 1.0;
		for (int c = 0; c < 3; c++) {
			lut[c * size + i] = (uint16_t)lround(v * mul[c] * night.brightness / 100.0 * 65535.0);
		}
	}
	struct wlr_color_transform *tr = wlr_color_transform_init_lut_3x1d(size, lut, lut + size, lut + 2 * size);
	free(lut);
	return tr;
}

static void
overlay_remove(struct output *o)
{
	if (o->night_tint) {
		wlr_scene_node_destroy(&o->night_tint->node);
		wlr_scene_node_destroy(&o->night_dim->node);
		o->night_tint = o->night_dim = NULL;
	}
}

/* Zrcadlene vystupy maji stejny obdelnik: zavoj jen jednou, jinak by se zdvojil */
static bool
covered_by_other(struct output *o, struct wlr_box *box)
{
	struct output *other;
	wl_list_for_each(other, &comp.outputs, link) {
		if (other == o) {
			return false;
		}
		struct wlr_box b;
		wlr_output_layout_get_box(comp.layout, other->wlr_output, &b);
		if (other->night_tint && wlr_box_equal(&b, box)) {
			return true;
		}
	}
	return false;
}

/* Prolinani barvy jen priblizne (nasobit scena neumi): bila dostane odstin bileho bodu s 60 % jeho sily,
 * tmave plochy zcervenaji nejvys o petinu. Ztlumeni cernou je presne. */
static void
overlay_update(struct output *o)
{
	struct wlr_box box;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
	if (!active() || o->client_gamma || wlr_box_empty(&box) || covered_by_other(o, &box)) {
		overlay_remove(o);
		return;
	}
	double mul[3];
	whitepoint(night.kelvin, mul);
	const float strength = 0.6f;
	float a = strength * (float)(1.0 - mul[2]);
	/* premultiplied; bila po prolnuti: 1, 1 - strength * (1 - g), 1 - a */
	float tint[4] = { a, fmaxf(0.0f, a - strength * (float)(1.0 - mul[1])), 0, a };
	float dim[4] = { 0, 0, 0, 1.0f - night.brightness / 100.0f };
	if (!o->night_tint) {
		o->night_tint = wlr_scene_rect_create(comp.night, box.width, box.height, tint);
		o->night_dim = wlr_scene_rect_create(comp.night, box.width, box.height, dim);
	}
	struct wlr_scene_rect *rects[2] = { o->night_tint, o->night_dim };
	for (int i = 0; i < 2; i++) {
		wlr_scene_rect_set_color(rects[i], i ? dim : tint);
		wlr_scene_rect_set_size(rects[i], box.width, box.height);
		wlr_scene_node_set_position(&rects[i]->node, box.x, box.y);
		wlr_scene_node_set_enabled(&rects[i]->node, (i ? dim : tint)[3] > 0.0f);
	}
	/* nad zamkem i zakrytim po prihlaseni, ktere se vytvori pozdeji */
	wlr_scene_node_raise_to_top(&comp.night->node);
}

/* Pred snimkem vystupu (zavoj sleduje polohu a velikost vystupu; zmeny nic nestoji) */
void
night_frame(struct output *o)
{
	if (o->night_overlay) {
		overlay_update(o);
	}
}

/* Po wlr_scene_output_build_state(): gamma tabulka jen pri zmene (prepnuti, zapnuti vystupu, konec klienta
 * gamma-control, ktery ji scena nastavi zpet na vychozi) */
void
night_apply(struct output *o, struct wlr_output_state *state)
{
	if (!o->night_dirty) {
		return;
	}
	o->night_dirty = false;
	/* vychozi tabulku nastavujeme, jen kdyz jsme predtim dali vlastni: bez noci se gamma vystupu nedotykame */
	if (o->night_overlay || o->client_gamma || (!active() && !o->night_lut)) {
		return;
	}
	struct wlr_color_transform *tr = active() ? ramp(wlr_output_get_gamma_size(o->wlr_output)) : NULL;
	struct wlr_output_state test = {0};
	wlr_output_state_copy(&test, state);
	wlr_output_state_set_color_transform(&test, tr);
	if (wlr_output_test_state(o->wlr_output, &test)) {
		wlr_output_state_set_color_transform(state, tr);
		o->night_lut = tr != NULL;
	} else if (tr) {
		/* ovladac tabulku odmitl: zavoj od pristiho snimku */
		o->night_overlay = true;
		wlr_output_schedule_frame(o->wlr_output);
	}
	wlr_output_state_finish(&test);
	wlr_color_transform_unref(tr);
}

void
night_output_changed(struct output *o)
{
	o->night_dirty = true;
	wlr_output_schedule_frame(o->wlr_output);
}

void
night_output_init(struct output *o)
{
	o->night_overlay = wlr_output_get_gamma_size(o->wlr_output) == 0;
	night_output_changed(o);
}

void
night_output_destroy(struct output *o)
{
	overlay_remove(o);
}

static void
set_gamma(struct wl_listener *listener, void *data)
{
	const struct wlr_gamma_control_manager_v1_set_gamma_event *event = data;
	struct output *o = event->output->data;
	if (o) {
		o->client_gamma = event->control != NULL;
		night_output_changed(o);
	}
}

void
night_init(struct wlr_gamma_control_manager_v1 *gamma)
{
	comp.night = wlr_scene_tree_create(&comp.scene->tree);
	night.set_gamma.notify = set_gamma;
	wl_signal_add(&gamma->events.set_gamma, &night.set_gamma);
}

void
night_finish(void)
{
	wl_list_remove(&night.set_gamma.link);
}

void
luxcomp_set_night_light(int64_t kelvin, int64_t brightness)
{
	night.kelvin = kelvin <= 0 ? 6500 : (int)fmax(1000, fmin(6500, kelvin));
	night.brightness = (int)fmax(10, fmin(100, brightness));
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		night_output_changed(o);
	}
}

int64_t
luxcomp_night_light_mode(int64_t output)
{
	struct output *o = output_by_id(output);
	if (!o || !active() || o->client_gamma) {
		return 0;
	}
	return o->night_overlay ? 2 : 1;
}
