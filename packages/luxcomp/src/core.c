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
#include <wlr/render/allocator.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_cursor_shape_v1.h>
#include <wlr/types/wlr_data_device.h>
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

static void
output_frame(struct wl_listener *listener, void *data)
{
	struct output *o = wl_container_of(listener, o, frame);
	struct timespec t0, t1;
	clock_gettime(CLOCK_MONOTONIC, &t0);
	wlr_scene_output_commit(o->scene_output, NULL);
	clock_gettime(CLOCK_MONOTONIC, &t1);
	workspaces_frame_done((t1.tv_sec - t0.tv_sec) * 1000000000LL
		+ (t1.tv_nsec - t0.tv_nsec));
	wlr_scene_output_send_frame_done(o->scene_output, &t1);
}

/* Aktualni rozlozeni pro wlr-output-management (wlr-randr, nastaveni monitoru, harness testu) */
static void
output_config_update(void)
{
	struct wlr_output_configuration_v1 *config = wlr_output_configuration_v1_create();
	struct output *o;
	wl_list_for_each(o, &comp.outputs, link) {
		struct wlr_output_configuration_head_v1 *head =
			wlr_output_configuration_head_v1_create(config, o->wlr_output);
		struct wlr_box box;
		wlr_output_layout_get_box(comp.layout, o->wlr_output, &box);
		head->state.x = box.x;
		head->state.y = box.y;
	}
	wlr_output_manager_v1_set_configuration(comp.output_mgr, config);
}

static void
output_config_apply(struct wlr_output_configuration_v1 *config, bool test)
{
	bool ok = true;
	struct wlr_output_configuration_head_v1 *head;
	wl_list_for_each(head, &config->heads, link) {
		struct wlr_output *wo = head->state.output;
		struct wlr_output_state state;
		wlr_output_state_init(&state);
		wlr_output_head_v1_state_apply(&head->state, &state);
		ok = test ? wlr_output_test_state(wo, &state) : wlr_output_commit_state(wo, &state);
		wlr_output_state_finish(&state);
		if (!ok) {
			break;
		}
		if (!test && head->state.enabled && wo->data) {
			wlr_output_layout_add(comp.layout, wo, head->state.x, head->state.y);
			layers_arrange(wo->data);
		}
	}
	if (ok) {
		wlr_output_configuration_v1_send_succeeded(config);
	} else {
		wlr_output_configuration_v1_send_failed(config);
	}
	wlr_output_configuration_v1_destroy(config);
	if (!test) {
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
	wl_list_remove(&o->frame.link);
	wl_list_remove(&o->request_state.link);
	wl_list_remove(&o->destroy.link);
	wl_list_remove(&o->link);
	free(o);
	output_config_update();
}

static void
new_output(struct wl_listener *listener, void *data)
{
	struct wlr_output *wo = data;
	if (!wlr_output_init_render(wo, comp.allocator, comp.renderer)) {
		return;
	}

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

	struct output *o = calloc(1, sizeof(*o));
	o->id = ++comp.next_id;
	o->wlr_output = wo;
	wo->data = o;
	o->frame.notify = output_frame;
	wl_signal_add(&wo->events.frame, &o->frame);
	o->request_state.notify = output_request_state;
	wl_signal_add(&wo->events.request_state, &o->request_state);
	o->destroy.notify = output_destroy;
	wl_signal_add(&wo->events.destroy, &o->destroy);
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
	comp.backend = wlr_backend_autocreate(comp.loop, NULL);
	if (!comp.backend) {
		wlr_log(WLR_ERROR, "luxcomp: no backend");
		return -1;
	}
	comp.renderer = renderer_create(comp.backend, &comp.allocator, &comp.software);
	if (!comp.renderer) {
		return -1;
	}
	wlr_renderer_init_wl_display(comp.renderer, comp.display);

	wlr_compositor_create(comp.display, 6, comp.renderer);
	wlr_subcompositor_create(comp.display);
	wlr_data_device_manager_create(comp.display);
	wlr_primary_selection_v1_device_manager_create(comp.display);
	wlr_viewporter_create(comp.display);
	wlr_single_pixel_buffer_manager_v1_create(comp.display);
	wlr_fractional_scale_manager_v1_create(comp.display, 1);
	wlr_presentation_create(comp.display, comp.backend, 2);
	/* zachyceni obrazovky (grim); omezeni na shell LuxOS prijde se security-context */
	wlr_screencopy_manager_v1_create(comp.display);
	wlr_ext_image_copy_capture_manager_v1_create(comp.display, 1);
	wlr_ext_output_image_capture_source_manager_v1_create(comp.display, 1);

	comp.layout = wlr_output_layout_create(comp.display);
	wlr_xdg_output_manager_v1_create(comp.display, comp.layout);
	comp.output_mgr = wlr_output_manager_v1_create(comp.display);
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
	comp.layer_top = wlr_scene_tree_create(root);
	comp.fullscreen = wlr_scene_tree_create(root);
	comp.layer_overlay = wlr_scene_tree_create(root);
	comp.default_ws = workspace_create();

	views_init();
	layers_init();
	input_init();
	wlr_cursor_shape_manager_v1_create(comp.display, 1);

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
	wl_display_destroy_clients(comp.display);
	wl_list_remove(&comp.new_toplevel.link);
	wl_list_remove(&comp.new_popup.link);
	wl_list_remove(&comp.new_decoration.link);
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
	float color[4] = { (argb >> 16 & 0xff) / 255.0f, (argb >> 8 & 0xff) / 255.0f,
		(argb & 0xff) / 255.0f, (argb >> 24 & 0xff) / 255.0f };
	/* jednolita barva pod tapetou; vetsi nez jakekoli rozlozeni vystupu */
	if (!comp.background) {
		comp.background = wlr_scene_rect_create(comp.layer_bg, 32768, 32768, color);
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
	pid_t child = fork();
	if (child == 0) {
		setsid();
		sigset_t set;
		sigemptyset(&set);
		sigprocmask(SIG_SETMASK, &set, NULL);
		pid_t grandchild = fork();
		if (grandchild == 0) {
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
		const struct wlr_box *full, struct wlr_box *usable)
{
	struct wlr_scene_node *node;
	wl_list_for_each(node, &tree->children, link) {
		struct layer *l = node->data;
		if (l && l->output == o && l->surface->initialized) {
			wlr_scene_layer_surface_v1_configure(l->scene, full, usable);
		}
	}
}

void
layers_arrange(struct output *o)
{
	struct wlr_box full;
	wlr_output_layout_get_box(comp.layout, o->wlr_output, &full);
	struct wlr_box usable = full;
	/* exkluzivni zony v poradi od nejvyssi vrstvy, jako ostatni kompozitory */
	arrange_tree(o, comp.layer_overlay, &full, &usable);
	arrange_tree(o, comp.layer_top, &full, &usable);
	arrange_tree(o, comp.layer_bottom, &full, &usable);
	arrange_tree(o, comp.layer_bg, &full, &usable);
	if (!wlr_box_equal(&usable, &o->usable)) {
		o->usable = usable;
		emit(LUXCOMP_EV_OUTPUT_USABLE, o->id, 0, 0, 0);
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
	if (comp.layer_focus) {
		comp.layer_focus = NULL;
		luxcomp_view_focus(comp.focused ? comp.focused->id : 0);
	}
}

static void
layer_map(struct wl_listener *listener, void *data)
{
	struct layer *l = wl_container_of(listener, l, map);
	layers_arrange(l->output);
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
	layers_arrange(l->output);
	layer_update_focus();
	cursor_rebase();
}

static void
layer_commit(struct wl_listener *listener, void *data)
{
	struct layer *l = wl_container_of(listener, l, commit);
	struct wlr_layer_surface_v1 *s = l->surface;
	if (!s->initialized) {
		return;
	}
	if (s->current.committed & WLR_LAYER_SURFACE_V1_STATE_LAYER) {
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
	wl_list_remove(&l->destroy.link);
	free(l);
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
	l->map.notify = layer_map;
	wl_signal_add(&s->surface->events.map, &l->map);
	l->unmap.notify = layer_unmap;
	wl_signal_add(&s->surface->events.unmap, &l->unmap);
	l->commit.notify = layer_commit;
	wl_signal_add(&s->surface->events.commit, &l->commit);
	l->destroy.notify = layer_destroy;
	wl_signal_add(&s->events.destroy, &l->destroy);
}

void
layers_init(void)
{
	comp.layer_shell = wlr_layer_shell_v1_create(comp.display, 4);
	comp.new_layer_surface.notify = new_layer_surface;
	wl_signal_add(&comp.layer_shell->events.new_surface, &comp.new_layer_surface);
}
