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
struct wlr_buffer;
struct _cairo_surface;
struct wlr_surface;
struct wlr_xdg_popup;
struct wlr_xwayland_surface;
struct wlr_session_lock_v1;
struct wlr_ext_image_capture_source_v1;

enum grab_mode { GRAB_NONE, GRAB_MOVE, GRAB_RESIZE };

/* prvni polozka struktur, na ktere ukazuje node->data ve scene */
enum node_kind { KIND_VIEW = 1, KIND_LAYER };

struct layer {
	int kind;
	struct wlr_layer_surface_v1 *surface;
	struct wlr_scene_layer_surface_v1 *scene;
	struct output *output;
	struct wl_listener map, unmap, commit, destroy, new_popup;
};

struct output {
	struct wl_list link;
	int64_t id;
	struct wlr_output *wlr_output;
	struct wlr_scene_output *scene_output;
	struct wlr_box usable;
	bool lock_shown;		/* rendered a frame with the lock cover */
	bool head_enabled, head_published;
	int last_x, last_y;	/* last state sent through wlr-output-management */
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
	struct wlr_xdg_toplevel *toplevel;	/* exactly one of toplevel and xsurface is set */
	struct wlr_xwayland_surface *xsurface;
	struct wlr_scene_tree *tree;	/* at the content top-left */
	struct wlr_scene_tree *surface_tree;	/* NULL for an X11 window without a wl_surface */
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
	/* xwayland.c */
	struct wl_listener x_associate, x_dissociate, x_configure, x_activate, x_decorations;
	/* foreign.c: handles for the Dock, they exist while the view is mapped */
	struct wlr_foreign_toplevel_handle_v1 *ftl;
	struct wlr_ext_foreign_toplevel_handle_v1 *ext;
	struct wlr_output *ftl_output;
	struct wlr_ext_image_capture_source_v1 *capture;
	struct wl_listener ftl_activate, ftl_minimize, ftl_maximize, ftl_fullscreen,
		ftl_close, capture_destroy;
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
	struct wlr_scene_tree *layer_bg, *layer_bottom, *views, *above, *unmanaged,
		*layer_top, *fullscreen, *layer_overlay, *lock_tree;
	struct wlr_scene_rect *background;
	const char *socket;

	struct wl_list outputs, views_list, workspaces, keybinds, keyboards;
	struct workspace *default_ws;

	struct wlr_xdg_shell *xdg_shell;
	struct wlr_layer_shell_v1 *layer_shell;
	struct wlr_xdg_decoration_manager_v1 *deco_mgr;
	struct wlr_output_manager_v1 *output_mgr;
	bool software;
	bool virtual_input_open;	/* LUXCOMP_VIRTUAL_INPUT: virtual input for every unsandboxed client */
	char **privileged;		/* executables allowed to bind privileged globals */
	size_t n_privileged;
	struct wlr_security_context_manager_v1 *security;
	struct wlr_xdg_activation_v1 *activation;
	struct wlr_idle_notifier_v1 *idle;
	struct wlr_idle_inhibit_manager_v1 *inhibit;
	struct wlr_foreign_toplevel_manager_v1 *ftl_mgr;
	struct wlr_ext_foreign_toplevel_list_v1 *ext_list;
	struct wlr_xwayland *xwayland;
	struct wlr_compositor *compositor;
	struct wl_listener activate, new_token, new_inhibitor, toplevel_capture,
		new_lock, lock_surface, lock_unlock, lock_destroy, xwayland_surface,
		xwayland_ready;

	/* lock.c: locked stays true when the locker dies, until a new locker unlocks */
	bool locked;
	struct wlr_session_lock_v1 *lock;
	bool lock_sent;
	struct wlr_scene_rect *lock_cover;
	uint32_t lock_color;
	struct wl_listener new_output, new_toplevel, new_popup, new_layer_surface,
		new_decoration, new_input, output_mgr_apply, output_mgr_test,
		new_virtual_keyboard, new_virtual_pointer;

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
	int grab_frames;		/* LUXCOMP_STATS: render times while dragging */
	int64_t grab_render_max_ns, grab_render_sum_ns;

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
void popup_attach(struct wlr_xdg_popup *popup, struct wlr_scene_tree *parent_tree,
		struct wlr_scene_tree *holder);
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
void deco_hover(struct deco *deco, int part);	/* NULL = pointer is not over a title bar */
struct wlr_buffer *cairo_buffer_create(int width, int height, struct _cairo_surface **surface);

/* shadow.c: window shadow drawn from shared pre-blurred 9-slice textures */
struct shadow;
struct shadow *shadow_create(struct wlr_scene_tree *parent);
void shadow_destroy(struct shadow *shadow);
/* frame = window incl. title bar, relative to parent; size 0 hides the shadow */
void shadow_update(struct shadow *shadow, struct wlr_box frame, int size, int radius,
	uint32_t argb, int scale);

/* view.c, shared with xwayland.c */
struct view *view_create(void);
void view_map_common(struct view *v);
void view_unmap_common(struct view *v);
void view_destroy_common(struct view *v);
struct wlr_surface *view_surface(struct view *v);
int view_width(struct view *v);
int view_height(struct view *v);
struct view *view_from_surface(struct wlr_surface *surface);
bool view_shown(struct view *v);
void tree_track(struct wlr_scene_tree **tree);

/* foreign.c */
void foreign_init(void);
void foreign_map(struct view *v);
void foreign_unmap(struct view *v);
void foreign_update(struct view *v);

/* lock.c */
void lock_init(void);
void lock_frame_done(struct output *o);

/* idle.c: idle-notify, idle-inhibit and xdg-activation */
void idle_init(void);
void idle_activity(void);
void idle_update(void);
const char *idle_shell_token(void);

/* security.c */
void security_init(void);
void security_mark(struct wl_global *global, int level);
bool client_privileged(struct wl_client *client);
enum { GLOBAL_SANDBOX_DENIED = 1, GLOBAL_PRIVILEGED = 2, GLOBAL_VIRTUAL_INPUT = 3 };

/* xwayland.c */
void xwayland_finish(void);

/* workspace.c */
struct workspace *workspace_by_id(int64_t id);
struct workspace *workspace_create(void);
void workspaces_frame_done(int64_t frame_ns);

#endif
