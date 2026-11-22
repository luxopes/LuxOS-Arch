/*
 * Hry: pointer-constraints + relative-pointer (rozhlizeni mysi, i hry pod XWayland), keyboard-shortcuts-
 * inhibit (hra, VM a vzdalena plocha dostanou Super a spol.), tearing-control a adaptivni synchronizace
 * ve snimku vystupu, content-type, drm-lease (VR helmy), gamma-control, linux-drm-syncobj (explicitni
 * synchronizace, NVIDIA) a dmabuf feedback sceny (klient dostane formaty pro primy scanout).
 *
 * Celoobrazovkove okno navrchu vystupu (output_fullscreen) je kandidat na primy scanout: bez dekorace,
 * stinu, zaobleni a materialu nad nim zbude ve scene jediny buffer a wlr_scene ho posle primo na
 * obrazovku. Efekty (deco.c, blur.c, animace) se proto u nej musi vypnout, viz output_fullscreen().
 */
#include <math.h>
#include <stdlib.h>
#include <wlr/backend.h>
#include <wlr/render/swapchain.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/types/wlr_content_type_v1.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_drm_lease_v1.h>
#include <wlr/types/wlr_gamma_control_v1.h>
#include <wlr/types/wlr_keyboard_shortcuts_inhibit_v1.h>
#include <wlr/types/wlr_linux_dmabuf_v1.h>
#include <wlr/types/wlr_linux_drm_syncobj_v1.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_pointer_constraints_v1.h>
#include <wlr/types/wlr_relative_pointer_v1.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_tearing_control_v1.h>
#include <wlr/util/log.h>
#include <wlr/util/region.h>
#include <xkbcommon/xkbcommon.h>
#include "internal.h"

static struct {
	struct wlr_pointer_constraints_v1 *constraints;
	struct wlr_relative_pointer_manager_v1 *relative;
	struct wlr_keyboard_shortcuts_inhibit_manager_v1 *inhibit;
	struct wlr_tearing_control_manager_v1 *tearing;
	struct wlr_content_type_manager_v1 *content;
	struct wlr_drm_lease_v1_manager *lease;
	struct wlr_pointer_constraint_v1 *active;
	/* Super+Esc: zkratky kompozitoru zpet pro tento povrch, dokud ma klavesnici */
	struct wlr_surface *suspended;
	double dx, dy;		/* posun kurzoru posledniho pohybu po omezeni (gaming_pointer_focus) */
	struct wl_listener new_constraint, new_inhibitor, focus_change, lease_request;
} g;

struct constraint {
	struct wlr_pointer_constraint_v1 *c;
	struct wl_listener set_region, commit, destroy;
};

struct inhibitor {
	struct wl_listener destroy;
};

/* ---- celoobrazovkove okno ---- */

/* Okno na cele obrazovce navrchu vystupu (luxwm ho da do vrstvy FULLSCREEN, jen kdyz je zamerene);
 * pod zamkem neni navrchu nic */
struct view *
output_fullscreen(struct output *o)
{
	if (comp.locked) {
		return NULL;
	}
	struct wlr_box out;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &out);
	struct view *v;
	wl_list_for_each(v, &comp.views_list, link) {
		if (v->layer != LUXCOMP_LAYER_FULLSCREEN || !view_shown(v) || !view_surface(v)
				|| !luxcomp_view_get(v->id, LUXCOMP_VIEW_FULLSCREEN)) {
			continue;
		}
		struct wlr_box box = { v->x, v->y, view_width(v), view_height(v) }, hit;
		if (wlr_box_intersection(&hit, &box, &out)) {
			return v;
		}
	}
	return NULL;
}

/* Uzel pod vrstvou celoobrazovkovych oken je zakryty, kdyz celoobrazovkove okno pokryva cely vystup:
 * material listy nebo Docku pod hrou se nemusi prepocitavat */
bool
node_under_fullscreen(struct wlr_scene_node *node, struct output *o)
{
	struct view *v = output_fullscreen(o);
	struct wlr_box out;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &out);
	if (!v || v->x > out.x || v->y > out.y || v->x + view_width(v) < out.x + out.width
			|| v->y + view_height(v) < out.y + out.height) {
		return false;
	}
	while (node->parent && node->parent != &comp.scene->tree) {
		node = &node->parent->node;
	}
	struct wlr_scene_node *n;
	wl_list_for_each(n, &comp.scene->tree.children, link) {
		if (n == &comp.fullscreen->node) {
			return false;
		}
		if (n == node) {
			return true;
		}
	}
	return false;
}

/* ---- snimek vystupu: tearing a adaptivni synchronizace ---- */

static bool
wants_tearing(struct output *o, struct view *fs)
{
	return fs && o->tearing && wlr_tearing_control_manager_v1_surface_hint_from_surface(g.tearing,
		view_surface(fs)) == WP_TEARING_CONTROL_V1_PRESENTATION_HINT_ASYNC;
}

/* Misto wlr_scene_output_commit(): navic async page flip pro hru, ktera o nej pozada, a VRR podle
 * nastaveni vystupu (vychozi jen pod celoobrazovkovym oknem: promenna frekvence na plose blika) */
bool
gaming_output_commit(struct output *o)
{
	struct wlr_output *wo = o->wlr_output;
	if (!wlr_scene_output_needs_frame(o->scene_output) && !o->night_dirty) {
		return true;
	}
	struct view *fs = output_fullscreen(o);
	bool vrr = o->vrr == LUXCOMP_VRR_ALWAYS || (o->vrr == LUXCOMP_VRR_FULLSCREEN && fs);
	bool vrr_change = wo->adaptive_sync_supported && o->vrr_refused != vrr
		&& vrr != (wo->adaptive_sync_status == WLR_OUTPUT_ADAPTIVE_SYNC_ENABLED);
	struct wlr_output_state state;
	wlr_output_state_init(&state);
	if (vrr_change) {
		wlr_output_state_set_adaptive_sync_enabled(&state, vrr);
	}
	bool ok = wlr_scene_output_build_state(o->scene_output, &state, NULL);
	if (ok) {
		night_apply(o, &state);
		state.tearing_page_flip = wants_tearing(o, fs);
		if (state.tearing_page_flip && !wlr_output_test_state(wo, &state)) {
			state.tearing_page_flip = false;
		}
		ok = wlr_output_commit_state(wo, &state);
		if (!ok && vrr_change) {
			/* monitor nebo ovladac VRR odmitl: snimek bez nej a znovu az po zmene nastaveni */
			o->vrr_refused = vrr;
			state.committed &= ~WLR_OUTPUT_STATE_ADAPTIVE_SYNC_ENABLED;
			ok = wlr_output_commit_state(wo, &state);
		}
	}
	o->scanout = ok && state.buffer && wo->swapchain && !wlr_swapchain_has_buffer(wo->swapchain, state.buffer);
	o->torn = ok && state.tearing_page_flip;
	wlr_output_state_finish(&state);
	return ok;
}

/* ---- omezeni ukazatele a relativni pohyb ---- */

static void
constraint_deactivate(void)
{
	struct wlr_pointer_constraint_v1 *c = g.active;
	if (!c) {
		return;
	}
	g.active = NULL;
	/* zamceny ukazatel: kurzor se objevi tam, kde ho hra naposledy ukazovala */
	if (c->type == WLR_POINTER_CONSTRAINT_V1_LOCKED && c->current.cursor_hint.enabled
			&& comp.seat->pointer_state.focused_surface == c->surface) {
		double ox = comp.cursor->x - comp.seat->pointer_state.sx;
		double oy = comp.cursor->y - comp.seat->pointer_state.sy;
		wlr_cursor_warp(comp.cursor, NULL, ox + c->current.cursor_hint.x, oy + c->current.cursor_hint.y);
	}
	wlr_pointer_constraint_v1_send_deactivated(c);
}

/* wlroots pocita oblast az pri commitu povrchu a staticke okno Xwayland po zamceni necommitne: do te doby
 * plati cela vstupni oblast povrchu (oblast bez set_region) */
static const pixman_region32_t *
constraint_region(struct wlr_pointer_constraint_v1 *c)
{
	return pixman_region32_not_empty(&c->region) ? &c->region : &c->surface->input_region;
}

/* Omezeni plati pro povrch pod ukazatelem jen v zamerenem okne: hra v pozadi nesmi chytit
 * kurzor, ktery pres ni jen projede */
void
gaming_pointer_update(void)
{
	struct wlr_surface *s = comp.seat->pointer_state.focused_surface;
	struct wlr_pointer_constraint_v1 *c = NULL;
	if (s && !comp.locked && comp.grab == GRAB_NONE && comp.focused
			&& view_from_surface(s) == comp.focused) {
		c = wlr_pointer_constraints_v1_constraint_for_surface(g.constraints, s, comp.seat);
	}
	if (c == g.active) {
		return;
	}
	/* aktivuje se, az ukazatel vjede do oblasti */
	if (c && !pixman_region32_contains_point(constraint_region(c), floor(comp.seat->pointer_state.sx),
			floor(comp.seat->pointer_state.sy), NULL)) {
		c = NULL;
	}
	constraint_deactivate();
	if (c) {
		g.active = c;
		wlr_pointer_constraint_v1_send_activated(c);
	}
}

void
gaming_pointer_motion(uint32_t time_msec, double *dx, double *dy, double udx, double udy)
{
	wlr_relative_pointer_manager_v1_send_relative_motion(g.relative, comp.seat,
		(uint64_t)time_msec * 1000, *dx, *dy, udx, udy);
	struct wlr_pointer_constraint_v1 *c = g.active;
	if (!c) {
		return;
	}
	double sx = comp.seat->pointer_state.sx, sy = comp.seat->pointer_state.sy, x, y;
	if (c->type == WLR_POINTER_CONSTRAINT_V1_LOCKED
			|| !wlr_region_confine(constraint_region(c), sx, sy, sx + *dx, sy + *dy, &x, &y)) {
		*dx = *dy = 0;
	} else {
		*dx = x - sx;
		*dy = y - sy;
	}
	g.dx = *dx;
	g.dy = *dy;
}

/* Aktivni omezeni drzi ukazatel na svem povrchu: zaoblene rohy okna (kopie pixelu, ne povrch), oznameni
 * ani jine okno pod kurzorem ho hre neseberou */
bool
gaming_pointer_focus(struct wlr_surface **surface, double *sx, double *sy)
{
	struct wlr_pointer_constraint_v1 *c = g.active;
	if (!c || comp.locked || comp.seat->pointer_state.focused_surface != c->surface) {
		return false;
	}
	*surface = c->surface;
	*sx = comp.seat->pointer_state.sx + g.dx;
	*sy = comp.seat->pointer_state.sy + g.dy;
	g.dx = g.dy = 0;
	return true;
}

int64_t
luxcomp_pointer_constraint(void)
{
	if (!g.active) {
		return 0;
	}
	return g.active->type == WLR_POINTER_CONSTRAINT_V1_LOCKED ? 1 : 2;
}

/* oblast omezeni plati az commitem povrchu (Xwayland zamyka bez dalsiho pohybu mysi) */
static void
constraint_changed(struct wl_listener *listener, void *data)
{
	if (!g.active) {
		gaming_pointer_update();
	}
}

static void
constraint_destroy(struct wl_listener *listener, void *data)
{
	struct constraint *con = wl_container_of(listener, con, destroy);
	if (g.active == con->c) {
		g.active = NULL;
	}
	wl_list_remove(&con->set_region.link);
	wl_list_remove(&con->commit.link);
	wl_list_remove(&con->destroy.link);
	free(con);
}

static void
new_constraint(struct wl_listener *listener, void *data)
{
	struct constraint *con = calloc(1, sizeof(*con));
	con->c = data;
	con->set_region.notify = constraint_changed;
	wl_signal_add(&con->c->events.set_region, &con->set_region);
	con->commit.notify = constraint_changed;
	wl_signal_add(&con->c->surface->events.commit, &con->commit);
	con->destroy.notify = constraint_destroy;
	wl_signal_add(&con->c->events.destroy, &con->destroy);
	gaming_pointer_update();
}

/* ---- keyboard-shortcuts-inhibit ---- */

static void
inhibit_update(void)
{
	struct wlr_surface *focus = comp.seat->keyboard_state.focused_surface;
	if (g.suspended != focus) {
		g.suspended = NULL;
	}
	struct wlr_keyboard_shortcuts_inhibitor_v1 *i;
	wl_list_for_each(i, &g.inhibit->inhibitors, link) {
		bool on = i->surface == focus && !g.suspended && !comp.locked;
		if (on && !i->active) {
			wlr_keyboard_shortcuts_inhibitor_v1_activate(i);
		} else if (!on && i->active) {
			wlr_keyboard_shortcuts_inhibitor_v1_deactivate(i);
		}
	}
}

static struct wlr_keyboard_shortcuts_inhibitor_v1 *
focused_inhibitor(void)
{
	struct wlr_surface *focus = comp.seat->keyboard_state.focused_surface;
	struct wlr_keyboard_shortcuts_inhibitor_v1 *i;
	wl_list_for_each(i, &g.inhibit->inhibitors, link) {
		if (focus && i->surface == focus) {
			return i;
		}
	}
	return NULL;
}

bool
gaming_shortcuts_inhibited(void)
{
	struct wlr_keyboard_shortcuts_inhibitor_v1 *i = focused_inhibitor();
	return i && i->active;
}

/* Super+Esc vrati zkratky kompozitoru (a znovu je da hre), jako GNOME. Prepnuti konzole
 * (Ctrl+Alt+F1..F12) plati vzdy, kontroluje se pred zkratkami. */
bool
gaming_shortcut_escape(struct xkb_state *state, uint32_t keycode, uint32_t mods)
{
	if (mods != LUXCOMP_MOD_SUPER || !focused_inhibitor()
			|| xkb_state_key_get_one_sym(state, keycode) != XKB_KEY_Escape) {
		return false;
	}
	struct wlr_surface *focus = comp.seat->keyboard_state.focused_surface;
	g.suspended = g.suspended ? NULL : focus;
	/* inhibit_update() suspended pro zamereny povrch nemaze */
	struct wlr_keyboard_shortcuts_inhibitor_v1 *i = focused_inhibitor();
	if (g.suspended) {
		wlr_keyboard_shortcuts_inhibitor_v1_deactivate(i);
	} else {
		inhibit_update();
	}
	return true;
}

static void
inhibitor_destroy(struct wl_listener *listener, void *data)
{
	struct inhibitor *in = wl_container_of(listener, in, destroy);
	wl_list_remove(&in->destroy.link);
	free(in);
}

static void
new_inhibitor(struct wl_listener *listener, void *data)
{
	struct wlr_keyboard_shortcuts_inhibitor_v1 *i = data;
	struct inhibitor *in = calloc(1, sizeof(*in));
	in->destroy.notify = inhibitor_destroy;
	wl_signal_add(&i->events.destroy, &in->destroy);
	inhibit_update();
}

static void
focus_change(struct wl_listener *listener, void *data)
{
	inhibit_update();
	gaming_pointer_update();
}

/* ---- content-type, drm-lease ---- */

int
gaming_content_type(struct wlr_surface *surface)
{
	return surface ? (int)wlr_surface_get_content_type_v1(g.content, surface) : 0;
}

bool
gaming_tearing_hint(struct wlr_surface *surface)
{
	return surface && wlr_tearing_control_manager_v1_surface_hint_from_surface(g.tearing, surface)
		== WP_TEARING_CONTROL_V1_PRESENTATION_HINT_ASYNC;
}

/* xdg okno: zmena typu obsahu jde politice (necinnost pod celoobrazovkovym videem a hrou) */
void
gaming_view_commit(struct view *v)
{
	int type = gaming_content_type(view_surface(v));
	if (type != v->content_type) {
		v->content_type = type;
		emit(LUXCOMP_EV_VIEW_CONTENT_TYPE, v->id, type, 0, 0);
	}
}

static void
lease_request(struct wl_listener *listener, void *data)
{
	struct wlr_drm_lease_request_v1 *req = data;
	if (!wlr_drm_lease_request_v1_grant(req)) {
		wlr_drm_lease_request_v1_reject(req);
	}
}

/* Displej "non-desktop" (VR helma) neni soucast plochy: nabidne se k pronajmu (SteamVR, Monado) */
bool
gaming_offer_output(struct wlr_output *wo)
{
	if (!wo->non_desktop) {
		return false;
	}
	if (g.lease) {
		wlr_drm_lease_v1_manager_offer_output(g.lease, wo);
	}
	return true;
}

/* ---- API ---- */

void
luxcomp_output_set(int64_t id, int64_t prop, int64_t value)
{
	struct output *o = output_by_id(id);
	if (!o) {
		return;
	}
	if (prop == LUXCOMP_OUT_VRR && value >= LUXCOMP_VRR_OFF && value <= LUXCOMP_VRR_ALWAYS) {
		o->vrr = value;
		o->vrr_refused = -1;
	} else if (prop == LUXCOMP_OUT_TEARING) {
		o->tearing = value != 0;
	}
	wlr_output_schedule_frame(o->wlr_output);
}

void
gaming_init(void)
{
	g.constraints = wlr_pointer_constraints_v1_create(comp.display);
	g.new_constraint.notify = new_constraint;
	wl_signal_add(&g.constraints->events.new_constraint, &g.new_constraint);
	g.relative = wlr_relative_pointer_manager_v1_create(comp.display);
	g.inhibit = wlr_keyboard_shortcuts_inhibit_v1_create(comp.display);
	g.new_inhibitor.notify = new_inhibitor;
	wl_signal_add(&g.inhibit->events.new_inhibitor, &g.new_inhibitor);
	g.focus_change.notify = focus_change;
	wl_signal_add(&comp.seat->keyboard_state.events.focus_change, &g.focus_change);
	g.tearing = wlr_tearing_control_manager_v1_create(comp.display, 1);
	g.content = wlr_content_type_manager_v1_create(comp.display, 1);

	/* nocni rezim a kalibrace (gammastep, wlsunset); mimo sandbox */
	struct wlr_gamma_control_manager_v1 *gamma = wlr_gamma_control_manager_v1_create(comp.display);
	wlr_scene_set_gamma_control_manager_v1(comp.scene, gamma);
	security_mark(gamma->global, GLOBAL_SANDBOX_DENIED);
	night_init(gamma);

	/* jen na DRM backendu; pronajem dava klientovi primo displej, proto ne v sandboxu */
	g.lease = wlr_drm_lease_v1_manager_create(comp.display, comp.backend);
	if (g.lease) {
		g.lease_request.notify = lease_request;
		wl_signal_add(&g.lease->events.request, &g.lease_request);
		struct wlr_drm_lease_device_v1 *dev;
		wl_list_for_each(dev, &g.lease->devices, link) {
			security_mark(dev->global, GLOBAL_SANDBOX_DENIED);
		}
	}

	/* dmabuf (GPU klienti, PRIME, gamescope) s feedbackem sceny: celoobrazovkova hra dostane formaty
	 * pro scanout. Pixman bez DRM zarizeni dmabuf neumi. */
	int drm_fd = wlr_renderer_get_drm_fd(comp.renderer);
	if (drm_fd >= 0 && wlr_renderer_get_texture_formats(comp.renderer, WLR_BUFFER_CAP_DMABUF)) {
		struct wlr_linux_dmabuf_v1 *dmabuf =
			wlr_linux_dmabuf_v1_create_with_renderer(comp.display, 5, comp.renderer);
		if (dmabuf) {
			wlr_scene_set_linux_dmabuf_v1(comp.scene, dmabuf);
		}
	}
	/* explicitni synchronizace (NVIDIA 555+, Mesa): jen kdyz ji umi renderer i backend */
	if (drm_fd >= 0 && comp.renderer->features.timeline && comp.backend->features.timeline) {
		wlr_linux_drm_syncobj_manager_v1_create(comp.display, 1, drm_fd);
	}
}

void
gaming_finish(void)
{
	wl_list_remove(&g.new_constraint.link);
	wl_list_remove(&g.new_inhibitor.link);
	wl_list_remove(&g.focus_change.link);
	night_finish();
	if (g.lease) {
		wl_list_remove(&g.lease_request.link);
	}
}
