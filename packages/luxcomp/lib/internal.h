/* Vnitrni stav libluxcomp; ven jde jen luxcomp.h */
#ifndef LUXCOMP_INTERNAL_H
#define LUXCOMP_INTERNAL_H

#include <stdbool.h>
#include <stdint.h>
#include <wayland-server-core.h>
#include <wlr/util/box.h>
#include "luxcomp.h"

struct wlr_scene_tree;
struct wlr_scene_rect;
struct wlr_scene_node;
struct wlr_surface;

enum grab_mode { GRAB_NONE, GRAB_MOVE, GRAB_RESIZE };

/* prvni polozka struktur, na ktere ukazuje node->data ve scene */
enum node_kind { KIND_VIEW = 1, KIND_LAYER };

struct layer {
	int kind;
	struct wlr_layer_surface_v1 *surface;
	struct wlr_scene_layer_surface_v1 *scene;
	struct output *output;
	struct wl_listener map, unmap, commit, destroy;
};

struct output {
	struct wl_list link;
	int64_t id;
	struct wlr_output *wlr_output;
	struct wlr_scene_output *scene_output;
	struct wlr_box usable;
	struct wl_listener frame, request_state, destroy;
};

struct workspace {
	struct wl_list link;
	int64_t id;
	struct wlr_scene_tree *tree;
	bool shown;
};

struct view {
	int kind;
	struct wl_list link;		/* comp.views, stacking order, top first */
	int64_t id;
	struct wlr_xdg_toplevel *toplevel;
	struct wlr_scene_tree *tree;	/* at the content top-left */
	struct wlr_scene_tree *surface_tree;
	struct workspace *workspace;
	int layer;
	int x, y;
	bool mapped, visible, decorated;
	struct deco *deco;
	struct wlr_xdg_toplevel_decoration_v1 *xdg_deco;
	struct wl_listener map, unmap, commit, destroy;
	struct wl_listener request_move, request_resize, request_maximize,
		request_fullscreen, request_minimize, set_title, set_app_id;
	struct wl_listener deco_request_mode, deco_destroy;
};

struct keybind {
	struct wl_list link;
	int64_t id;
	uint32_t mods;
	uint32_t keysym;	/* 0 when matched by keycode */
	uint32_t keycode;
};

struct comp {
	luxcomp_event_fn emit_fn;
	void *user;
	int64_t next_id;
	bool quit;

	struct wl_display *display;
	struct wl_event_loop *loop;
	struct wlr_backend *backend;
	struct wlr_renderer *renderer;
	struct wlr_allocator *allocator;
	struct wlr_output_layout *layout;
	struct wlr_scene *scene;
	struct wlr_scene_output_layout *scene_layout;
	/* stacking, bottom to top */
	struct wlr_scene_tree *layer_bg, *layer_bottom, *views, *above, *layer_top,
		*fullscreen, *layer_overlay;
	struct wlr_scene_rect *background;
	const char *socket;

	struct wl_list outputs, views_list, workspaces, keybinds, keyboards;
	struct workspace *default_ws;

	struct wlr_xdg_shell *xdg_shell;
	struct wlr_layer_shell_v1 *layer_shell;
	struct wlr_xdg_decoration_manager_v1 *deco_mgr;
	bool software;
	struct wl_listener new_output, new_toplevel, new_popup, new_layer_surface,
		new_decoration, new_input;

	struct wlr_seat *seat;
	struct wlr_cursor *cursor;
	struct wlr_xcursor_manager *cursor_mgr;
	struct wl_listener cursor_motion, cursor_motion_abs, cursor_button,
		cursor_axis, cursor_frame, request_cursor, request_selection,
		request_primary;
	struct view *focused;
	struct wlr_surface *layer_focus;	/* keyboard-interactive layer surface */
	bool binding_mods_held;		/* report modifier release after a binding */

	enum grab_mode grab;
	struct view *grab_view;
	double grab_x, grab_y;
	struct wlr_box grab_box;
	uint32_t grab_edges;

	char *kb_layout, *kb_variant, *kb_options;
	int repeat_rate, repeat_delay;
};

extern struct comp comp;

void emit(int64_t event, int64_t id, int64_t a, int64_t b, int64_t c);

/* renderer.c */
struct wlr_renderer *renderer_create(struct wlr_backend *backend,
	struct wlr_allocator **allocator, bool *software);

/* core.c */
struct output *output_by_id(int64_t id);
struct output *output_at(double x, double y);
void layers_arrange(struct output *output);
void layers_init(void);

/* view.c */
void views_init(void);
struct view *view_by_id(int64_t id);
void view_update_enabled(struct view *view);

/* input.c */
void input_init(void);
void input_finish(void);
void seat_focus_surface(struct wlr_surface *surface);
void cursor_rebase(void);

/* deco.c */
struct deco;
struct deco *deco_create(struct view *view);
void deco_destroy(struct deco *deco);
void deco_update(struct deco *deco);		/* size, title, activation */
int deco_part_at(struct deco *deco, double x, double y);
bool deco_owns_node(struct deco *deco, struct wlr_scene_node *node);
int deco_height(void);

/* workspace.c */
struct workspace *workspace_by_id(int64_t id);
struct workspace *workspace_create(void);
void workspaces_frame_done(int64_t frame_ns);

#endif
