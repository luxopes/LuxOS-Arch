/* Vnitrni stav libluxcomp; ven jde jen luxcomp.h */
#ifndef LUXCOMP_INTERNAL_H
#define LUXCOMP_INTERNAL_H

#include <stdbool.h>
#include <stdint.h>
#include <sys/types.h>
#include <wayland-server-core.h>
#include <pixman.h>
#include <wlr/util/box.h>
#include "luxcomp.h"

struct wlr_scene_tree;
struct wlr_scene_rect;
struct wlr_scene_node;
struct wlr_buffer;
struct _cairo_surface;
struct wlr_surface;
struct wlr_xwayland_surface;
struct wlr_session_lock_v1;
struct wlr_session;
struct wlr_ext_image_capture_source_v1;
struct xkb_keymap;

enum grab_mode { GRAB_NONE, GRAB_MOVE, GRAB_RESIZE };

struct blur;
#define BLUR_SET_MAX 8
struct blur_set {
	char material[16];	/* "" = bez materialu; "popups" = jen popupy plochy (nabidka plochy) */
	int radius;
	struct blur *blur[BLUR_SET_MAX];
};

/* prvni polozka struktur, na ktere ukazuje node->data ve scene */
enum node_kind { KIND_VIEW = 1, KIND_LAYER };

struct layer {
	int kind;
	struct wlr_layer_surface_v1 *surface;
	struct wlr_scene_layer_surface_v1 *scene;
	struct output *output;
	struct blur_set blur;		/* jmenny prostor "nazev@material[:polomer]" */
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
	bool mirror;			/* shows another output (same origin), own layers hidden */
	bool held;			/* luxcomp_hold: still shows what was there before (boot splash) */
	bool hold_wait;			/* the first frame after the hold is not on screen yet */
	int last_x, last_y;	/* last state sent through wlr-output-management */
	struct wl_listener frame, request_state, destroy, present;
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
	struct wlr_scene_tree *body;	/* content + rounded bottom corners (deco.c), what a window capture shows */
	struct wlr_scene_tree *surface_tree;	/* NULL for an X11 window without a wl_surface */
	struct workspace *workspace;
	int layer;
	int x, y;
	bool mapped, visible, decorated;
	bool compact;		/* luxcomp_view_set_compact(): lower title bar */
	struct deco *deco;
	char *badge;		/* luxcomp_view_set_badge(), drawn by deco.c */
	char *app_id_override, *title_override;	/* luxcomp_view_set_names() */
	int last_w, last_h;	/* size of the last VIEW_MAP/VIEW_SIZE */
	/* luxcomp_view_set_material(): blurred backdrop under a rectangle of the content (blur.c) */
	struct blur *material;
	char material_name[16];		/* "" = none */
	struct wlr_box material_box;	/* window geometry coordinates, clipped to the window when shown */
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
	struct wlr_box icon_box;	/* Dock icon (foreign-toplevel set_rectangle), layout coordinates */
	struct wl_listener ftl_activate, ftl_minimize, ftl_maximize, ftl_fullscreen,
		ftl_close, ftl_rectangle, capture_destroy;
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
	struct wlr_scene_tree *layer_hidden;	/* layer surfaces of mirrored outputs */
	struct wlr_scene_tree *cover;		/* luxcomp_cover(): over everything but the lock, no input */
	struct wlr_scene_rect *background;
	const char *socket;

	struct wl_list outputs, views_list, workspaces, keybinds, keyboards;
	struct workspace *default_ws;

	struct wlr_xdg_shell *xdg_shell;
	struct wlr_layer_shell_v1 *layer_shell;
	struct wlr_xdg_decoration_manager_v1 *deco_mgr;
	struct wlr_server_decoration_manager *kde_deco_mgr;
	struct wl_listener new_kde_decoration;
	struct wlr_output_manager_v1 *output_mgr;
	bool software;
	/* luxcomp_hold: lit outputs are not touched until the first client frame */
	bool hold;
	int hold_pending;		/* outputs whose first frame after the hold is not on screen yet */
	bool hold_by_client;
	struct wl_event_source *hold_timer;
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
	struct wlr_session *session;	/* NULL without DRM (headless, nested) */
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
		cursor_axis, cursor_frame, request_cursor, request_shape, request_selection,
		request_primary, request_start_drag, start_drag;
	struct wlr_scene_tree *drag_icons;	/* drag-and-drop icons, above everything, follow the cursor */
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
	struct xkb_keymap *kb_keymap;	/* the keymap of physical keyboards */
	uint32_t kb_group;		/* active layout, the same on every keyboard */
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
void layers_arrange_all(void);
void layers_close(struct output *output);
void layers_init(void);
bool layer_on_demand(struct wlr_surface *surface);	/* mapped, keyboard_interactivity on_demand */

/* view.c */
void views_init(void);
struct view *view_by_id(int64_t id);
void view_update_enabled(struct view *view);

/* input.c */
void input_init(void);
void input_finish(void);
void seat_focus_surface(struct wlr_surface *surface);
void seat_enter_direct(struct wlr_surface *surface);
void cursor_rebase(void);
void cursor_busy_update(void);

/* deco.c */
struct deco;
struct deco *deco_create(struct view *view);
void deco_destroy(struct deco *deco);
void deco_update(struct deco *deco);		/* size, title, activation */
void deco_redraw(struct deco *deco);		/* unconditionally (badge) */
void deco_set_ssd(struct deco *deco, bool on);	/* server-side title bar or only shadow + corners (CSD) */
int deco_part_at(struct deco *deco, double x, double y);
bool deco_owns_node(struct deco *deco, struct wlr_scene_node *node);
int deco_height(struct deco *deco);		/* title bar of this view (normal or compact) */
void deco_hover(struct deco *deco, int part);	/* NULL = pointer is not over a title bar */
struct wlr_buffer *cairo_buffer_create(int width, int height, struct _cairo_surface **surface);

/* shadow.c: window shadow drawn from shared pre-blurred 9-slice textures */
struct shadow;
struct shadow *shadow_create(struct wlr_scene_tree *parent);
void shadow_destroy(struct shadow *shadow);
/* frame = window incl. title bar, relative to parent; size 0 hides the shadow; offset moves it
 * down; blur false = a sharp outline 1 px around the frame (size 1) */
void shadow_update(struct shadow *shadow, struct wlr_box frame, int size, int offset, int radius,
	uint32_t argb, int scale, bool blur);

/* blur.c: material (rozmazane pozadi a stin) pod plochami layer-shell a jejich popupy */

bool blur_parse_namespace(const char *ns, char material[16], int *radius);
struct blur *blur_create(struct wlr_scene_tree *parent, const char *material, int radius);
void blur_destroy(struct blur *blur);
void blur_set_box(struct blur *blur, struct wlr_box box);	/* v souradnicich parent */
bool blur_output_frame(struct output *o);		/* pred vykreslenim; true = neco prepocital */
void blur_frame_time(struct output *o, int64_t ns, bool worked);
/* obdelniky vstupni oblasti povrchu w x h (nejvys BLUR_SET_MAX) */
void blur_set_update(struct blur_set *set, struct wlr_scene_tree *parent, const pixman_region32_t *input,
	int width, int height);
void blur_set_clear(struct blur_set *set);
/* material okna (luxcomp_view_set_material); z deco_update: polomer rohu okna a ktere rohy jsou zaoblene
 * (1 levy horni, 2 pravy horni, 4 pravy dolni, 8 levy dolni) */
void blur_view_update(struct view *v, int radius, int rounded);

/* view.c, shared with xwayland.c */
struct view *view_create(void);
struct wlr_xdg_popup;
void popup_attach(struct wlr_xdg_popup *popup, struct wlr_scene_tree *parent_tree);
void view_map_common(struct view *v);
void kde_decoration_check(struct view *v);
void view_unmap_common(struct view *v);
void view_destroy_common(struct view *v);
struct wlr_surface *view_surface(struct view *v);
int view_width(struct view *v);
int view_height(struct view *v);
void view_size_changed(struct view *v);
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
bool launch_busy(void);			/* a started program has no window yet: busy pointer */
void launch_window_mapped(void);

/* security.c */
void security_init(void);
void security_mark(struct wl_global *global, int level);
bool client_privileged(struct wl_client *client);
bool pid_privileged(pid_t pid);
enum { GLOBAL_SANDBOX_DENIED = 1, GLOBAL_PRIVILEGED = 2, GLOBAL_VIRTUAL_INPUT = 3 };

/* xwayland.c */
void xwayland_finish(void);
void xwayland_root_cursor(void);

/* ipc.c */
void ipc_finish(void);

/* workspace.c */
struct workspace *workspace_by_id(int64_t id);
struct workspace *workspace_create(void);
void workspaces_frame_done(int64_t frame_ns);

/* anim.c */
void anim_init(void);
void anim_frame(void);			/* before rendering a frame */
void anim_frame_done(int64_t render_ns);

/* cover.c */
void cover_init(double time_scale);
bool cover_step(int64_t now_ns);		/* true = needs another frame */
void cover_frame_done(int64_t render_ns);

#endif
