/* Jadro: zivotni cyklus, smycka udalosti, vystupy a layer-shell */
#define _GNU_SOURCE
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <wlr/backend.h>
#include <wlr/backend/headless.h>
#include <wlr/backend/multi.h>
#include <wlr/render/allocator.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_data_control_v1.h>
#include <wlr/types/wlr_data_device.h>
#include <wlr/types/wlr_ext_data_control_v1.h>
#include <wlr/types/wlr_ext_image_capture_source_v1.h>
#include <wlr/types/wlr_ext_image_copy_capture_v1.h>
#include <wlr/types/wlr_fractional_scale_v1.h>
#include <wlr/types/wlr_layer_shell_v1.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_output_management_v1.h>
#include <wlr/types/wlr_presentation_time.h>
#include <wlr/types/wlr_primary_selection_v1.h>
#include <wlr/types/wlr_scene.h>
#include <wlr/types/wlr_screencopy_v1.h>
#include <wlr/types/wlr_single_pixel_buffer_v1.h>
#include <wlr/types/wlr_subcompositor.h>
#include <wlr/types/wlr_viewporter.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/types/wlr_xdg_output_v1.h>
#include <wlr/util/log.h>
#include "internal.h"

struct comp comp;


void
emit(int64_t event, int64_t id, int64_t a, int64_t b, int64_t c)
{
	if (comp.emit_fn) {
		comp.emit_fn(comp.user, event, id, a, b, c);
	}
}

/* ---- vystupy ---- */

struct output *
output_by_id(int64_t id)
{
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		if (o->id == id) {
			return o;
		}
	}
	return NULL;
}

struct output *
output_at(double x, double y)
{
	struct wlr_output *wo = wlr_output_layout_output_at(comp.layout, x, y);
	return wo ? wo->data : NULL;
}

/* Frame callbacky podle primarniho vystupu bufferu povrchu. wlr_scene_output_send_frame_done()
 * je posila jen na "frame pacing" vystup povrchu a ten wlroots vynuluje, kdyz kterakoli kopie
 * povrchu ve scene neni nikde videt. Pruh mezi zaoblenymi rohy (deco.c) je takova kopie: okno na
 * celou obrazovku, maximalizovane nebo s dolnim okrajem zakrytym by pak na snimek cekalo navzdy
 * (zamrzly greeter, okna bez prekresleni). */
struct frame_done {
	struct wlr_scene_output *scene_output;
	struct timespec *when;
};

static void
send_frame_done(struct wlr_scene_buffer *buffer, int sx, int sy, void *data)
{
	struct frame_done *fd = data;
	struct wlr_scene_surface *ss = wlr_scene_surface_try_from_buffer(buffer);
	if (ss && buffer->primary_output == fd->scene_output) {
		wlr_surface_send_frame_done(ss->surface, fd->when);
	}
}

static void
output_enable(struct wlr_output *wo)
{
	struct wlr_output_state state;
	wlr_output_state_init(&state);
	wlr_output_state_set_enabled(&state, true);
	struct wlr_output_mode *mode = wlr_output_preferred_mode(wo);
	const char *custom = getenv("LUXCOMP_OUTPUT_MODE");
	int w, h;
	if (mode) {
		wlr_output_state_set_mode(&state, mode);
	} else if (custom && sscanf(custom, "%dx%d", &w, &h) == 2) {
		/* headless a vnoreny backend nemaji rezimy; velikost pro testy a okno */
		wlr_output_state_set_custom_mode(&state, w, h, 0);
	}
	if (!wlr_output_commit_state(wo, &state)) {
		/* rezim neprosel (napr. VM bez daneho rozliseni): zkusit bez nej */
		wlr_output_state_finish(&state);
		wlr_output_state_init(&state);
		wlr_output_state_set_enabled(&state, true);
		wlr_output_commit_state(wo, &state);
	}
	wlr_output_state_finish(&state);
}

/* ---- hold: obraz pred startem (splash Plymouthu) zustava do prvniho snimku klienta ----
 * wlroots prebira rozsviceny CRTC s jeho rezimem a nic na nem nemeni, dokud nekdo necommitne. Drzeny
 * vystup tedy dal ukazuje posledni snimek splashe; prvni commit uz nese snimek s klientem (greeter),
 * bez prazdneho cerneho bufferu modesetu a bez pozadi sceny mezi tim. */

static void
client_buffer(struct wlr_scene_buffer *buffer, int sx, int sy, void *data)
{
	if (wlr_scene_surface_try_from_buffer(buffer)) {
		*(bool *)data = true;
	}
}

static void
hold_release(bool by_client)
{
	comp.hold = false;
	comp.hold_by_client = by_client;
	if (comp.hold_timer) {
		wl_event_source_remove(comp.hold_timer);
		comp.hold_timer = NULL;
	}
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		if (o->wlr_output->enabled) {
			o->hold_wait = true;
			comp.hold_pending++;
			wlr_output_schedule_frame(o->wlr_output);
		}
	}
	if (comp.hold_pending == 0) {
		emit(LUXCOMP_EV_HOLD_END, 0, by_client, 0, 0);
	}
}

static int
hold_timeout(void *data)
{
	comp.hold_timer = NULL;
	if (comp.hold) {
		hold_release(false);
	}
	return 0;
}

/* Az kdyz je prvni snimek po hold opravdu na obrazovce, smi splash skoncit (jeho framebuffer zmizi) */
static void
hold_presented(struct output *o)
{
	o->hold_wait = false;
	if (--comp.hold_pending == 0) {
		emit(LUXCOMP_EV_HOLD_END, 0, comp.hold_by_client, 0, 0);
	}
}

static void
output_present(struct wl_listener *listener, void *data)
{
	struct output *o = wl_container_of(listener, o, present);
	const struct wlr_output_event_present *event = data;
	if (o->hold_wait && event->presented) {
		hold_presented(o);
	}
}

/* Prvni commit drzeneho vystupu: jen novy buffer ve stavajicim rezimu (plynula vymena). Kdyz to ovladac
 * odmitne (rezim splashe nejde prevzit bez modesetu), modeset ve stejnem rezimu, uz s hotovym snimkem. */
static bool
held_output_commit(struct output *o)
{
	struct wlr_output *wo = o->wlr_output;
	struct wlr_output_state state;
	wlr_output_state_init(&state);
	bool ok = wlr_scene_output_build_state(o->scene_output, &state, NULL);
	if (ok && !wlr_output_commit_state(wo, &state)) {
		if (wo->current_mode) {
			wlr_output_state_set_mode(&state, wo->current_mode);
		} else {
			wlr_output_state_set_custom_mode(&state, wo->width, wo->height, wo->refresh);
		}
		ok = wlr_output_commit_state(wo, &state);
	}
	wlr_output_state_finish(&state);
	if (!ok) {
		/* stav splashe nejde prevzit vubec: normalni zapnuti (kratce cerna) a snimek hned potom */
		output_enable(wo);
		wlr_output_schedule_frame(wo);
	}
	o->held = false;
	return ok;
}

static void
output_frame(struct wl_listener *listener, void *data)
{
	struct output *o = wl_container_of(listener, o, frame);
	if (comp.hold) {
		bool client = false;
		wlr_scene_output_for_each_buffer(o->scene_output, client_buffer, &client);
		if (client) {
			hold_release(true);
		} else if (o->held) {
			return;	/* splash zustava; vystup zhasnuty pri startu kresli normalne */
		}
	}
	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	decos_frame();
	bool blurred = blur_output_frame(o);
	bool done = o->held ? held_output_commit(o) : wlr_scene_output_commit(o->scene_output, NULL);
	clock_gettime(CLOCK_MONOTONIC, &t1);
	int64_t render_ns = (t1.tv_sec - t0.tv_sec) * 1000000000LL + (t1.tv_nsec - t0.tv_nsec);
	blur_frame_time(o, render_ns, blurred);
	if (done) {
		lock_frame_done(o);
		if (comp.grab != GRAB_NONE) {
			comp.grab_frames++;
			comp.grab_render_sum_ns += render_ns;
			if (render_ns > comp.grab_render_max_ns) {
				comp.grab_render_max_ns = render_ns;
			}
		}
	}
	workspaces_frame_done(render_ns);
	wlr_scene_output_for_each_buffer(o->scene_output, send_frame_done,
		&(struct frame_done){ o->scene_output, &t1 });
}

/* Aktualni rozlozeni pro wlr-output-management (wlr-randr, nastaveni monitoru, harness testu).
 * @skip vynecha znovu zapnute vystupy (viz output_config_update). */
static void
output_config_publish(bool skip)
{
	struct wlr_output_configuration_v1 *config = wlr_output_configuration_v1_create();
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		if (skip && o->wlr_output->enabled && !o->head_enabled) {
			continue;
		}
		struct wlr_output_configuration_head_v1 *head =
			wlr_output_configuration_head_v1_create(config, o->wlr_output);
		struct wlr_box box;
		wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
		if (!wlr_box_empty(&box)) {
			o->last_x = box.x;
			o->last_y = box.y;
		}
		/* vypnuty vystup nabizi posledni polohu, wlr-randr --on ho vrati na stejne misto */
		head->state.x = o->last_x;
		head->state.y = o->last_y;
	}
	wlr_output_manager_v1_set_configuration(comp.output_mgr, config);
}

/* wlroots 0.20.2 posle virtualni rezim (vystup bez rezimu: headless, vnoreny) znovu zapnute hlave
 * jen kdyz ho nema zadny klient; klient, ktery se pripojil, kdyz byl vystup vypnuty, pak shodi
 * kompozitor (assert v head_send_state). Znovu zapnuty vystup proto nejdriv z konfigurace
 * vypustime a pak pridame jako novou hlavu. Oprava: packages/wlroots0.20/output-management-custom-mode.patch */
static void
output_config_update(void)
{
	bool reenabled = false;
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		reenabled |= o->wlr_output->enabled && !o->head_enabled && o->head_published;
	}
	if (reenabled) {
		output_config_publish(true);
	}
	output_config_publish(false);
	wl_list_for_each(o, &comp.outputs, link) {
		o->head_enabled = o->wlr_output->enabled;
		o->head_published = true;
	}
}

static bool
output_config_commit(struct wlr_output_configuration_v1 *config, bool test)
{
	struct wlr_output_configuration_head_v1 *head;
	wl_list_for_each(head, &config->heads, link) {
		struct wlr_output *wo = head->state.output;
		struct wlr_output_state state;
		wlr_output_state_init(&state);
		wlr_output_head_v1_state_apply(&head->state, &state);
		bool ok = test ? wlr_output_test_state(wo, &state) : wlr_output_commit_state(wo, &state);
		wlr_output_state_finish(&state);
		if (!ok) {
			return false;
		}
	}
	return true;
}

static void
output_config_apply(struct wlr_output_configuration_v1 *config, bool test)
{
	/* nejdriv test vsech hlav: neprijatelny rezim jednoho monitoru nesmi nechat ostatni
	 * napul prepnute (nastaveni monitoru posila celou konfiguraci najednou) */
	bool ok = output_config_commit(config, true) && (test || output_config_commit(config, false));
	struct wlr_output_configuration_head_v1 *head;
	wl_list_for_each(head, &config->heads, link) {
		struct wlr_output *wo = head->state.output;
		if (!ok || test || !wo->data) {
			continue;
		}
		struct output *o = wo->data;
		if (head->state.enabled) {
			bool placed = wlr_output_layout_get(comp.layout, wo) != NULL;
			struct wlr_output_layout_output *lo =
				wlr_output_layout_add(comp.layout, wo, head->state.x, head->state.y);
			if (!placed && lo) {
				wlr_scene_output_layout_add_output(comp.scene_layout, lo, o->scene_output);
			}
		} else {
			/* vypnuty vystup nesmi drzet misto v rozlozeni (kurzor, umisteni oken) */
			wlr_output_layout_remove(comp.layout, wo);
		}
	}
	if (ok) {
		wlr_output_configuration_v1_send_succeeded(config);
	} else {
		wlr_output_configuration_v1_send_failed(config);
	}
	wlr_output_configuration_v1_destroy(config);
	if (ok && !test) {
		layers_arrange_all();
		output_config_update();
	}
}

static void
output_mgr_apply(struct wl_listener *listener, void *data)
{
	output_config_apply(data, false);
}

static void
output_mgr_test(struct wl_listener *listener, void *data)
{
	output_config_apply(data, true);
}

static void
output_request_state(struct wl_listener *listener, void *data)
{
	struct output *o = wl_container_of(listener, o, request_state);
	const struct wlr_output_event_request_state *event = data;
	wlr_output_commit_state(o->wlr_output, event->state);
	layers_arrange(o);
	output_config_update();
}

static void
output_destroy(struct wl_listener *listener, void *data)
{
	struct output *o = wl_container_of(listener, o, destroy);
	emit(LUXCOMP_EV_OUTPUT_REMOVE, o->id, 0, 0, 0);
	layers_close(o);
	wl_list_remove(&o->frame.link);
	wl_list_remove(&o->request_state.link);
	wl_list_remove(&o->destroy.link);
	wl_list_remove(&o->present.link);
	wl_list_remove(&o->link);
	if (o->hold_wait) {
		hold_presented(o);
	}
	free(o);
	layers_arrange_all();
	output_config_update();
}

static void
new_output(struct wl_listener *listener, void *data)
{
	struct wlr_output *wo = data;
	if (!wlr_output_init_render(wo, comp.allocator, comp.renderer)) {
		return;
	}

	/* hold: rozsviceny vystup (splash) si necha rezim i obraz, prvni commit az se snimkem klienta */
	bool held = comp.hold && wo->enabled && wo->width > 0 && wo->height > 0;
	if (!held) {
		output_enable(wo);
	}

	struct output *o = calloc(1, sizeof(*o));
	o->id = ++comp.next_id;
	o->wlr_output = wo;
	o->held = held;
	wo->data = o;
	o->frame.notify = output_frame;
	wl_signal_add(&wo->events.frame, &o->frame);
	o->request_state.notify = output_request_state;
	wl_signal_add(&wo->events.request_state, &o->request_state);
	o->destroy.notify = output_destroy;
	wl_signal_add(&wo->events.destroy, &o->destroy);
	o->present.notify = output_present;
	wl_signal_add(&wo->events.present, &o->present);
	wl_list_insert(comp.outputs.prev, &o->link);

	struct wlr_output_layout_output *lo = wlr_output_layout_add_auto(comp.layout, wo);
	o->scene_output = wlr_scene_output_create(comp.scene, wo);
	wlr_scene_output_layout_add_output(comp.scene_layout, lo, o->scene_output);
	layers_arrange(o);
	output_config_update();
	emit(LUXCOMP_EV_OUTPUT_ADD, o->id, wo->width, wo->height, 0);
}

/* ---- API ---- */

int64_t
luxcomp_init(luxcomp_event_fn fn, void *user)
{
	wlr_log_init(getenv("LUXCOMP_DEBUG") ? WLR_DEBUG : WLR_ERROR, NULL);
	comp.emit_fn = fn;
	comp.user = user;
	comp.repeat_rate = 25;
	comp.repeat_delay = 600;
	wl_list_init(&comp.outputs);
	wl_list_init(&comp.views_list);
	wl_list_init(&comp.workspaces);
	wl_list_init(&comp.keybinds);
	wl_list_init(&comp.keyboards);

	comp.display = wl_display_create();
	comp.loop = wl_display_get_event_loop(comp.display);
	comp.backend = wlr_backend_autocreate(comp.loop, &comp.session);
	if (!comp.backend) {
		wlr_log(WLR_ERROR, "luxcomp: no backend");
		return -1;
	}
	comp.renderer = renderer_create(comp.backend, &comp.allocator, &comp.software);
	if (!comp.renderer) {
		return -1;
	}
	wlr_renderer_init_wl_display(comp.renderer, comp.display);

	security_init();
	comp.compositor = wlr_compositor_create(comp.display, 6, comp.renderer);
	wlr_subcompositor_create(comp.display);
	wlr_data_device_manager_create(comp.display);
	wlr_primary_selection_v1_device_manager_create(comp.display);
	wlr_viewporter_create(comp.display);
	wlr_single_pixel_buffer_manager_v1_create(comp.display);
	wlr_fractional_scale_manager_v1_create(comp.display, 1);
	wlr_presentation_create(comp.display, comp.backend, 2);
	/* zachyceni obrazovky a schranka pro shell (grim, Dock, historie schranky): jen allowlist */
	security_mark(wlr_screencopy_manager_v1_create(comp.display)->global, GLOBAL_PRIVILEGED);
	security_mark(wlr_ext_image_copy_capture_manager_v1_create(comp.display, 1)->global,
		GLOBAL_PRIVILEGED);
	security_mark(wlr_ext_output_image_capture_source_manager_v1_create(comp.display, 1)->global,
		GLOBAL_PRIVILEGED);
	security_mark(wlr_ext_data_control_manager_v1_create(comp.display, 1)->global,
		GLOBAL_PRIVILEGED);
	security_mark(wlr_data_control_manager_v1_create(comp.display)->global, GLOBAL_PRIVILEGED);

	comp.layout = wlr_output_layout_create(comp.display);
	wlr_xdg_output_manager_v1_create(comp.display, comp.layout);
	comp.output_mgr = wlr_output_manager_v1_create(comp.display);
	security_mark(comp.output_mgr->global, GLOBAL_PRIVILEGED);
	comp.output_mgr_apply.notify = output_mgr_apply;
	wl_signal_add(&comp.output_mgr->events.apply, &comp.output_mgr_apply);
	comp.output_mgr_test.notify = output_mgr_test;
	wl_signal_add(&comp.output_mgr->events.test, &comp.output_mgr_test);
	comp.new_output.notify = new_output;
	wl_signal_add(&comp.backend->events.new_output, &comp.new_output);

	comp.scene = wlr_scene_create();
	comp.scene_layout = wlr_scene_attach_output_layout(comp.scene, comp.layout);
	struct wlr_scene_tree *root = &comp.scene->tree;
	comp.layer_bg = wlr_scene_tree_create(root);
	comp.layer_bottom = wlr_scene_tree_create(root);
	comp.views = wlr_scene_tree_create(root);
	comp.above = wlr_scene_tree_create(root);
	comp.unmanaged = wlr_scene_tree_create(root);
	comp.layer_top = wlr_scene_tree_create(root);
	comp.fullscreen = wlr_scene_tree_create(root);
	comp.layer_overlay = wlr_scene_tree_create(root);
	comp.layer_hidden = wlr_scene_tree_create(root);
	wlr_scene_node_set_enabled(&comp.layer_hidden->node, false);
	comp.default_ws = workspace_create();

	views_init();
	layers_init();
	input_init();
	foreign_init();
	idle_init();
	lock_init();

	comp.socket = wl_display_add_socket_auto(comp.display);
	if (!comp.socket) {
		return -1;
	}
	setenv("WAYLAND_DISPLAY", comp.socket, 1);
	return 0;
}

const char *
luxcomp_socket(void)
{
	return comp.socket;
}

void
luxcomp_hold(int64_t timeout_ms)
{
	comp.hold = true;
	comp.hold_timer = wl_event_loop_add_timer(comp.loop, hold_timeout, NULL);
	wl_event_source_timer_update(comp.hold_timer, timeout_ms > 0 ? (int)timeout_ms : 1);
}

int64_t
luxcomp_start(void)
{
	return wlr_backend_start(comp.backend) ? 0 : -1;
}

int64_t
luxcomp_fd(void)
{
	return wl_event_loop_get_fd(comp.loop);
}

int64_t
luxcomp_dispatch(int64_t timeout_ms)
{
	if (comp.quit) {
		return -1;
	}
	wl_display_flush_clients(comp.display);
	if (wl_event_loop_dispatch(comp.loop, (int)timeout_ms) < 0) {
		return -1;
	}
	wl_display_flush_clients(comp.display);
	return comp.quit ? -1 : 0;
}

void
luxcomp_run(void)
{
	while (luxcomp_dispatch(-1) == 0) {
	}
}

void
luxcomp_quit(void)
{
	comp.quit = true;
}

void
luxcomp_destroy(void)
{
	xwayland_finish();
	ipc_finish();
	wl_display_destroy_clients(comp.display);
	wl_list_remove(&comp.toplevel_capture.link);
	wl_list_remove(&comp.activate.link);
	wl_list_remove(&comp.new_inhibitor.link);
	wl_list_remove(&comp.new_lock.link);
	wl_list_remove(&comp.new_toplevel.link);
	wl_list_remove(&comp.new_popup.link);
	wl_list_remove(&comp.new_decoration.link);
	wl_list_remove(&comp.new_kde_decoration.link);
	wl_list_remove(&comp.new_layer_surface.link);
	wl_list_remove(&comp.new_output.link);
	wl_list_remove(&comp.new_input.link);
	wl_list_remove(&comp.output_mgr_apply.link);
	wl_list_remove(&comp.output_mgr_test.link);
	wlr_backend_destroy(comp.backend);
	wlr_scene_node_destroy(&comp.scene->tree.node);
	input_finish();
	wlr_allocator_destroy(comp.allocator);
	wlr_renderer_destroy(comp.renderer);
	wl_display_destroy(comp.display);
}

void
luxcomp_set_background(int64_t argb)
{
	comp.lock_color = argb & 0xffffff;
	float color[4] = { (argb >> 16 & 0xff) / 255.0f, (argb >> 8 & 0xff) / 255.0f,
		(argb & 0xff) / 255.0f, (argb >> 24 & 0xff) / 255.0f };
	/* jednolita barva pod tapetou; vetsi nez jakekoli rozlozeni vystupu, i do zapornych souradnic
	 * (zrcadlo s jinym pomerem stran je kolem vzoru a pruhy po stranach maji stejnou barvu).
	 * Souradnice do +-32767: pixman pocita v pevne radove carce 16.16, vetsi obdelnik se nenakresli
	 * a rozbije poskozene oblasti (odebrana okna by zustala na obrazovce) */
	if (!comp.background) {
		comp.background = wlr_scene_rect_create(comp.layer_bg, 32768, 32768, color);
		wlr_scene_node_set_position(&comp.background->node, -16384, -16384);
		wlr_scene_node_lower_to_bottom(&comp.background->node);
	} else {
		wlr_scene_rect_set_color(comp.background, color);
	}
}

int64_t
luxcomp_software_rendering(void)
{
	return comp.software;
}

/* Dvojity fork: proces nezustane jako zombie a hostitelsky program nemusi resit SIGCHLD */
int64_t
luxcomp_spawn(const char *command)
{
	int fds[2];
	if (!command || pipe2(fds, O_CLOEXEC) < 0) {
		return -1;
	}
	/* okno spusteneho programu se smi zamerit (xdg-activation, puvod SHELL) */
	const char *token = idle_shell_token();
	pid_t child = fork();
	if (child == 0) {
		setsid();
		sigset_t set;
		sigemptyset(&set);
		sigprocmask(SIG_SETMASK, &set, NULL);
		pid_t grandchild = fork();
		if (grandchild == 0) {
			if (token) {
				setenv("XDG_ACTIVATION_TOKEN", token, 1);
				setenv("DESKTOP_STARTUP_ID", token, 1);
			}
			execl("/bin/sh", "/bin/sh", "-c", command, (char *)NULL);
			_exit(127);
		}
		ssize_t r = write(fds[1], &grandchild, sizeof(grandchild));
		(void)r;
		_exit(0);
	}
	close(fds[1]);
	pid_t pid = -1;
	if (child > 0) {
		waitpid(child, NULL, 0);
		if (read(fds[0], &pid, sizeof(pid)) != sizeof(pid)) {
			pid = -1;
		}
	}
	close(fds[0]);
	return pid;
}

int64_t
luxcomp_output_get(int64_t id, int64_t prop)
{
	struct output *o = output_by_id(id);
	if (!o) {
		return 0;
	}
	struct wlr_box box;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
	switch (prop) {
	case LUXCOMP_OUT_X: return box.x;
	case LUXCOMP_OUT_Y: return box.y;
	case LUXCOMP_OUT_W: return box.width;
	case LUXCOMP_OUT_H: return box.height;
	case LUXCOMP_OUT_USABLE_X: return o->usable.x;
	case LUXCOMP_OUT_USABLE_Y: return o->usable.y;
	case LUXCOMP_OUT_USABLE_W: return o->usable.width;
	case LUXCOMP_OUT_USABLE_H: return o->usable.height;
	case LUXCOMP_OUT_REFRESH_MHZ: return o->wlr_output->refresh;
	case LUXCOMP_OUT_SCALE_PCT: return (int64_t)(o->wlr_output->scale * 100 + 0.5);
	}
	return 0;
}

const char *
luxcomp_output_name(int64_t id)
{
	struct output *o = output_by_id(id);
	return o ? o->wlr_output->name : NULL;
}

int64_t
luxcomp_output_at(int64_t x, int64_t y)
{
	struct output *o = output_at(x, y);
	return o ? o->id : 0;
}

static void
find_headless(struct wlr_backend *backend, void *data)
{
	if (wlr_backend_is_headless(backend)) {
		*(struct wlr_backend **)data = backend;
	}
}

/* Pripojeni a odpojeni monitoru v testech (jen headless backend, skutecne monitory se tim nedaji
 * odpojit): nastaveni monitoru a lista se tak daji vyzkouset bez hardwaru. */
int64_t
luxcomp_test_output_add(int64_t width, int64_t height)
{
	struct wlr_backend *headless = NULL;
	if (wlr_backend_is_multi(comp.backend)) {
		wlr_multi_for_each_backend(comp.backend, find_headless, &headless);
	} else if (wlr_backend_is_headless(comp.backend)) {
		headless = comp.backend;
	}
	if (!headless || width <= 0 || height <= 0 || width > 16384 || height > 16384) {
		return 0;
	}
	struct wlr_output *wo = wlr_headless_add_output(headless, width, height);
	return wo && wo->data ? ((struct output *)wo->data)->id : 0;
}

void
luxcomp_test_output_remove(int64_t id)
{
	struct output *o = output_by_id(id);
	if (o && wlr_output_is_headless(o->wlr_output)) {
		wlr_output_destroy(o->wlr_output);
	}
}

/* ---- layer-shell (lista, Dock, tapeta, spoustec) ---- */

static struct wlr_scene_tree *
layer_tree(enum zwlr_layer_shell_v1_layer layer)
{
	switch (layer) {
	case ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND: return comp.layer_bg;
	case ZWLR_LAYER_SHELL_V1_LAYER_BOTTOM: return comp.layer_bottom;
	case ZWLR_LAYER_SHELL_V1_LAYER_TOP: return comp.layer_top;
	default: return comp.layer_overlay;
	}
}

static void
arrange_tree(struct output *o, struct wlr_scene_tree *tree,
		const struct wlr_box *full, struct wlr_box *usable, bool exclusive)
{
	struct wlr_scene_node *node, *tmp;
	wl_list_for_each_safe(node, tmp, &tree->children, link) {
		struct layer *l = node->data;
		if (!l || l->output != o || !l->surface->initialized
				|| (l->surface->current.exclusive_zone > 0) != exclusive) {
			continue;
		}
		/* zrcadlo kresli lista a Dock vychoziho monitoru; vlastni vrstvy schovane, at se
		 * pruhledna lista nekresli dvakrat pres sebe */
		struct wlr_scene_tree *parent = o->mirror ? comp.layer_hidden : layer_tree(l->surface->current.layer);
		if (node->parent != parent) {
			wlr_scene_node_reparent(node, parent);
		}
		wlr_scene_layer_surface_v1_configure(l->scene, full, usable);
	}
}

/* Zrcadleny vystup = jiny zapnuty vystup ma stejny stred (nebo starsim zapisem stejny pocatek) a je mensi
 * (pri shode drivejsi v seznamu). Nastaveni monitoru zrcadli umistenim vystupu pres sebe
 * (wlr-output-management zrcadleni nezna); mensi vystup je vzor, vetsi ukazuje jeho obsah a pri jinem
 * pomeru stran ho ma uprostred s cernymi pruhy po stranach. */
static bool
same_place(const struct wlr_box *a, const struct wlr_box *b)
{
	return (a->x == b->x && a->y == b->y)
		|| (abs(2 * a->x + a->width - 2 * b->x - b->width) <= 2
			&& abs(2 * a->y + a->height - 2 * b->y - b->height) <= 2);
}

static struct output *
mirror_source(struct output *o, const struct wlr_box *box)
{
	bool before = true;
	struct output *p;
	wl_list_for_each(p, &comp.outputs, link) {
		if (p == o) {
			before = false;
			continue;
		}
		struct wlr_box b;
		wlr_output_layout_get_box(comp.layout, p->wlr_output, &b);
		if (wlr_box_empty(&b) || !same_place(&b, box)) {
			continue;
		}
		int64_t area = (int64_t)b.width * b.height, own = (int64_t)box->width * box->height;
		if (area < own || (area == own && before)) {
			return p;
		}
	}
	return NULL;
}

void
layers_arrange(struct output *o)
{
	struct wlr_box full;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &full);
	struct wlr_box usable = full;
	o->mirror = !wlr_box_empty(&full) && mirror_source(o, &full);
	/* nejdriv exkluzivni zony (od nejvyssi vrstvy, jako ostatni kompozitory), pak ostatni plochy uvnitr
	 * zbyle plochy: vyskakovaci okna listy a Ovladaci centrum ve vrstve overlay jsou pod listou (vrstva
	 * top), ne pres ni */
	struct wlr_scene_tree *trees[] = { comp.layer_overlay, comp.layer_top, comp.layer_bottom,
		comp.layer_bg, comp.layer_hidden };
	for (int pass = 1; pass >= 0; pass--) {
		for (size_t i = 0; i < sizeof(trees) / sizeof(*trees); i++) {
			arrange_tree(o, trees[i], &full, &usable, pass);
		}
	}
	if (o->mirror || wlr_box_empty(&full)) {
		usable = full;
	}
	if (!wlr_box_equal(&usable, &o->usable)) {
		o->usable = usable;
		emit(LUXCOMP_EV_OUTPUT_USABLE, o->id, 0, 0, 0);
	}
}

/* Odpojeny monitor: jeho vrstvy zavrit (klient dostane closed), jinak by drzely ukazatel na vystup */
void
layers_close(struct output *o)
{
	struct wlr_scene_tree *trees[] = { comp.layer_overlay, comp.layer_top, comp.layer_bottom,
		comp.layer_bg, comp.layer_hidden };
	for (size_t i = 0; i < sizeof(trees) / sizeof(*trees); i++) {
		struct wlr_scene_node *node, *tmp;
		wl_list_for_each_safe(node, tmp, &trees[i]->children, link) {
			struct layer *l = node->data;
			if (l && l->output == o) {
				l->output = NULL;
				wlr_layer_surface_v1_destroy(l->surface);
			}
		}
	}
}

void
layers_arrange_all(void)
{
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		layers_arrange(o);
	}
}

static void
layer_update_focus(void)
{
	/* klavesnici dostane nejvyssi zobrazena vrstva s exkluzivni interaktivitou */
	struct wlr_scene_tree *trees[] = { comp.layer_overlay, comp.layer_top };
	for (size_t i = 0; i < 2; i++) {
		struct wlr_scene_node *node;
		wl_list_for_each_reverse(node, &trees[i]->children, link) {
			struct layer *l = node->data;
			if (l && l->surface->surface->mapped
					&& l->surface->current.keyboard_interactive
					== ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE) {
				comp.layer_focus = l->surface->surface;
				seat_focus_surface(comp.layer_focus);
				return;
			}
		}
	}
	/* vrstva na pozadani (klikem) si klavesnici necha, dokud je videt a na pozadani zustava; mapovani
	 * jine vrstvy (oznameni, lista) ji nebere */
	if (comp.layer_focus && !layer_on_demand(comp.layer_focus)) {
		comp.layer_focus = NULL;
		luxcomp_view_focus(comp.focused ? comp.focused->id : 0);
	}
}

bool
layer_on_demand(struct wlr_surface *surface)
{
	struct wlr_layer_surface_v1 *ls = surface ? wlr_layer_surface_v1_try_from_wlr_surface(surface) : NULL;
	return ls && ls->surface->mapped
		&& ls->current.keyboard_interactive == ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_ON_DEMAND;
}

static void
layer_map(struct wl_listener *listener, void *data)
{
	struct layer *l = wl_container_of(listener, l, map);
	if (l->output) {
		layers_arrange(l->output);
	}
	/* vyskakovaci okna listy a Ovladaci centrum (on demand nad okny) dostanou klavesnici hned po zobrazeni:
	 * Esc a ztrata fokusu je zaviraji jako na X11; Dock, lista a plocha jsou bez klavesnice nebo pod okny */
	struct wlr_layer_surface_v1 *s = l->surface;
	if (s->current.keyboard_interactive == ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_ON_DEMAND
			&& s->current.layer >= ZWLR_LAYER_SHELL_V1_LAYER_TOP && !comp.locked) {
		comp.layer_focus = s->surface;
		seat_focus_surface(comp.layer_focus);
	}
	layer_update_focus();
	cursor_rebase();
}

static void
layer_unmap(struct wl_listener *listener, void *data)
{
	struct layer *l = wl_container_of(listener, l, unmap);
	if (comp.layer_focus == l->surface->surface) {
		comp.layer_focus = NULL;
		luxcomp_view_focus(comp.focused ? comp.focused->id : 0);
	}
	if (l->output) {
		layers_arrange(l->output);
	}
	layer_update_focus();
	cursor_rebase();
}

static void
layer_commit(struct wl_listener *listener, void *data)
{
	struct layer *l = wl_container_of(listener, l, commit);
	struct wlr_layer_surface_v1 *s = l->surface;
	if (l->blur.material[0] && strcmp(l->blur.material, "popups")) {
		blur_set_update(&l->blur, l->scene->tree, &s->surface->current.input,
			s->surface->current.width, s->surface->current.height);
	}
	if (!s->initialized || !l->output) {
		return;
	}
	if ((s->current.committed & WLR_LAYER_SURFACE_V1_STATE_LAYER) && !l->output->mirror) {
		wlr_scene_node_reparent(&l->scene->tree->node, layer_tree(s->current.layer));
	}
	if (s->initial_commit || s->current.committed) {
		layers_arrange(l->output);
	}
	if (s->current.committed & WLR_LAYER_SURFACE_V1_STATE_KEYBOARD_INTERACTIVITY) {
		layer_update_focus();
	}
}

static void
layer_destroy(struct wl_listener *listener, void *data)
{
	struct layer *l = wl_container_of(listener, l, destroy);
	wl_list_remove(&l->map.link);
	wl_list_remove(&l->unmap.link);
	wl_list_remove(&l->commit.link);
	wl_list_remove(&l->new_popup.link);
	wl_list_remove(&l->destroy.link);
	blur_set_clear(&l->blur);
	free(l);
}

/* Menu vrstvy (nabidka plochy ve vrstve bottom) ve vlastnim strome ve vrstve overlay na miste vrstvy,
 * at ho nezakryji okna; strom zanikne s popupem */
struct popup_holder {
	struct wlr_scene_tree *tree;
	struct wlr_xdg_popup *popup;
	struct blur *blur;		/* nabidka plochy s materialem dostane material "menu" */
	struct wl_listener destroy, commit;
};

static void
popup_holder_destroy(struct wl_listener *listener, void *data)
{
	struct popup_holder *h = wl_container_of(listener, h, destroy);
	wl_list_remove(&h->destroy.link);
	if (h->blur) {
		wl_list_remove(&h->commit.link);
		blur_destroy(h->blur);
	}
	wlr_scene_node_destroy(&h->tree->node);
	free(h);
}

/* strom popupu zacina v rohu geometrie okna (stin GTK kolem nabidky je mimo) */
static void
popup_holder_commit(struct wl_listener *listener, void *data)
{
	struct popup_holder *h = wl_container_of(listener, h, commit);
	struct wlr_box g = h->popup->base->current.geometry;
	blur_set_box(h->blur, (struct wlr_box){ 0, 0, g.width, g.height });
}

static void
layer_new_popup(struct wl_listener *listener, void *data)
{
	struct layer *l = wl_container_of(listener, l, new_popup);
	struct wlr_xdg_popup *popup = data;
	struct popup_holder *h = calloc(1, sizeof(*h));
	h->tree = wlr_scene_tree_create(comp.layer_overlay);
	int lx = 0, ly = 0;
	wlr_scene_node_coords(&l->scene->tree->node, &lx, &ly);
	wlr_scene_node_set_position(&h->tree->node, lx, ly);
	h->popup = popup;
	h->destroy.notify = popup_holder_destroy;
	wl_signal_add(&popup->events.destroy, &h->destroy);
	popup_attach(popup, h->tree);
	if (l->blur.material[0] && popup->base->data) {
		char menu[16] = "menu";
		int radius = 0;
		blur_parse_namespace("@menu", menu, &radius);
		h->blur = blur_create(popup->base->data, menu, radius);
		h->commit.notify = popup_holder_commit;
		wl_signal_add(&popup->base->surface->events.commit, &h->commit);
	}
}

static void
new_layer_surface(struct wl_listener *listener, void *data)
{
	struct wlr_layer_surface_v1 *s = data;
	struct output *o = s->output ? s->output->data
		: output_at(comp.cursor->x, comp.cursor->y);
	if (!o && !wl_list_empty(&comp.outputs)) {
		o = wl_container_of(comp.outputs.next, o, link);
	}
	if (!o) {
		wlr_layer_surface_v1_destroy(s);
		return;
	}
	s->output = o->wlr_output;

	struct layer *l = calloc(1, sizeof(*l));
	l->kind = KIND_LAYER;
	l->surface = s;
	l->output = o;
	l->scene = wlr_scene_layer_surface_v1_create(layer_tree(s->pending.layer), s);
	l->scene->tree->node.data = l;
	s->data = l->scene->tree;	/* rodic pro popupy */
	blur_parse_namespace(s->namespace, l->blur.material, &l->blur.radius);
	l->map.notify = layer_map;
	wl_signal_add(&s->surface->events.map, &l->map);
	l->unmap.notify = layer_unmap;
	wl_signal_add(&s->surface->events.unmap, &l->unmap);
	l->commit.notify = layer_commit;
	wl_signal_add(&s->surface->events.commit, &l->commit);
	l->new_popup.notify = layer_new_popup;
	wl_signal_add(&s->events.new_popup, &l->new_popup);
	l->destroy.notify = layer_destroy;
	wl_signal_add(&s->events.destroy, &l->destroy);
}

void
layers_init(void)
{
	comp.layer_shell = wlr_layer_shell_v1_create(comp.display, 4);
	security_mark(comp.layer_shell->global, GLOBAL_SANDBOX_DENIED);
	comp.new_layer_surface.notify = new_layer_surface;
	wl_signal_add(&comp.layer_shell->events.new_surface, &comp.new_layer_surface);
}
