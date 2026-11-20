/*
 * ext-idle-notify-v1 (zamek a usporny rezim pri necinnosti), idle-inhibit (prehravac videa
 * brani necinnosti, jen dokud je jeho okno videt) a xdg-activation-v1 (tokeny: kdo smi
 * zamerit jine okno, rozhoduje politika podle puvodu tokenu).
 */
#include <stdlib.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_idle_inhibit_v1.h>
#include <wlr/types/wlr_idle_notify_v1.h>
#include <wlr/types/wlr_layer_shell_v1.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_xdg_activation_v1.h>
#include "internal.h"

/* znacka tokenu, ktere vytvoril sam kompozitor (luxcomp_spawn) */
static int shell_token;

void
idle_activity(void)
{
	wlr_idle_notifier_v1_notify_activity(comp.idle, comp.seat);
}

static bool
surface_visible(struct wlr_surface *surface)
{
	if (!surface->mapped) {
		return false;
	}
	struct view *v = view_from_surface(surface);
	if (v) {
		return view_shown(v);
	}
	/* vrstva (napr. prehravac na pozadi plochy) */
	return wlr_layer_surface_v1_try_from_wlr_surface(
		wlr_surface_get_root_surface(surface)) != NULL;
}

void
idle_update(void)
{
	if (!comp.inhibit) {
		return;
	}
	bool inhibited = false;
	struct wlr_idle_inhibitor_v1 *i;
	wl_list_for_each(i, &comp.inhibit->inhibitors, link) {
		if (surface_visible(i->surface)) {
			inhibited = true;
			break;
		}
	}
	wlr_idle_notifier_v1_set_inhibited(comp.idle, inhibited);
}

struct inhibitor {
	struct wlr_idle_inhibitor_v1 *inhibitor;
	struct wl_listener destroy, map, unmap;
};

static void
inhibitor_changed(struct wl_listener *listener, void *data)
{
	idle_update();
}

static void
inhibitor_destroy(struct wl_listener *listener, void *data)
{
	struct inhibitor *in = wl_container_of(listener, in, destroy);
	wl_list_remove(&in->destroy.link);
	wl_list_remove(&in->map.link);
	wl_list_remove(&in->unmap.link);
	/* knihovna ho ze seznamu vyradi az po teto udalosti */
	wl_list_remove(&in->inhibitor->link);
	wl_list_init(&in->inhibitor->link);
	free(in);
	idle_update();
}

static void
new_inhibitor(struct wl_listener *listener, void *data)
{
	struct wlr_idle_inhibitor_v1 *i = data;
	struct inhibitor *in = calloc(1, sizeof(*in));
	in->inhibitor = i;
	in->destroy.notify = inhibitor_destroy;
	wl_signal_add(&i->events.destroy, &in->destroy);
	in->map.notify = inhibitor_changed;
	wl_signal_add(&i->surface->events.map, &in->map);
	in->unmap.notify = inhibitor_changed;
	wl_signal_add(&i->surface->events.unmap, &in->unmap);
	idle_update();
}

/* ---- xdg-activation ---- */

static void
request_activate(struct wl_listener *listener, void *data)
{
	struct wlr_xdg_activation_v1_request_activate_event *e = data;
	struct view *v = view_from_surface(e->surface);
	if (!v || !v->mapped) {
		return;
	}
	int64_t origin = LUXCOMP_ORIGIN_CLIENT, from = 0;
	struct wlr_xdg_activation_token_v1 *t = e->token;
	if (t->data == &shell_token) {
		origin = LUXCOMP_ORIGIN_SHELL;
	} else if (t->surface && t->seat) {
		/* token navazany na vstup uzivatele (serial overila knihovna) */
		struct view *src = view_from_surface(t->surface);
		if (src) {
			origin = LUXCOMP_ORIGIN_VIEW;
			from = src->id;
		} else if (wlr_layer_surface_v1_try_from_wlr_surface(
				wlr_surface_get_root_surface(t->surface))) {
			origin = LUXCOMP_ORIGIN_SHELL;
		}
	}
	emit(LUXCOMP_EV_VIEW_REQUEST, v->id, LUXCOMP_REQ_ACTIVATE, origin, from);
}

/* Token pro program spusteny kompozitorem (XDG_ACTIVATION_TOKEN v luxcomp_spawn) */
const char *
idle_shell_token(void)
{
	struct wlr_xdg_activation_token_v1 *t = wlr_xdg_activation_token_v1_create(comp.activation);
	if (!t) {
		return NULL;
	}
	t->data = &shell_token;
	return wlr_xdg_activation_token_v1_get_name(t);
}

void
idle_init(void)
{
	comp.idle = wlr_idle_notifier_v1_create(comp.display);
	security_mark(comp.idle->global, GLOBAL_SANDBOX_DENIED);
	comp.inhibit = wlr_idle_inhibit_v1_create(comp.display);
	comp.new_inhibitor.notify = new_inhibitor;
	wl_signal_add(&comp.inhibit->events.new_inhibitor, &comp.new_inhibitor);
	comp.activation = wlr_xdg_activation_v1_create(comp.display);
	comp.activate.notify = request_activate;
	wl_signal_add(&comp.activation->events.request_activate, &comp.activate);
}
