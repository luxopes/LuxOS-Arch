/* Spolecny stav libluxos-wl (neni soucast API). */
#ifndef LWL_INTERNAL_H
#define LWL_INTERNAL_H

#include <stdbool.h>
#include <stddef.h>
#include <wayland-client.h>
#include "luxos-wl.h"

#define LWL_EXPORT __attribute__((visibility("default")))

struct lwl_output {
	struct wl_list link;
	int id;
	uint32_t global;
	struct wl_output *wl;
	char *name, *description;
	int x, y, width, height, scale;
	bool announced, dead;
};

struct lwl_state {
	struct wl_display *display;
	bool own;                       /* vlastni spojeni: rozesilame ho sami */
	struct wl_registry *registry;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct wl_seat *seat;
	uint32_t seat_caps;
	struct wl_list outputs;
	int next_id;

	/* globaly protokolu (verze: wl_proxy_get_version) */
	struct zwlr_foreign_toplevel_manager_v1 *wlr_toplevels;
	struct ext_foreign_toplevel_list_v1 *ext_toplevels;
	struct ext_session_lock_manager_v1 *lock_manager;
	struct ext_output_image_capture_source_manager_v1 *output_sources;
	struct ext_foreign_toplevel_image_capture_source_manager_v1 *toplevel_sources;
	struct ext_image_copy_capture_manager_v1 *copy_capture;
	struct ext_data_control_manager_v1 *data_control;
	struct zwp_virtual_keyboard_manager_v1 *vk_manager;
	struct zwlr_output_manager_v1 *output_manager;
	struct ext_idle_notifier_v1 *idle_notifier;
	uint32_t idle_notifier_version;
};

extern struct lwl_state lwl;

int lwl_new_id(void);
void lwl_emit(int kind, int handle, int a, int b);
void lwl_flush(void);
char *lwl_strdup(const char *text);
void lwl_set_string(char **slot, const char *text);
struct lwl_output *lwl_find_output(int id);
int lwl_shm_fd(size_t size);
uint32_t lwl_now_ms(void);

/* po protokolech: navazani globalu (je-li nas) a uklid */
bool lwl_toplevel_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
bool lwl_lock_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
bool lwl_capture_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
bool lwl_clipboard_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
bool lwl_vkbd_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
bool lwl_heads_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
bool lwl_idle_bind(struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
void lwl_clipboard_seat(void);
void lwl_lock_keyboard_update(void);
void lwl_sweep(void);
void lwl_toplevel_sweep(void);
void lwl_heads_sweep(void);
struct ext_foreign_toplevel_handle_v1 *lwl_toplevel_ext_handle(int id);
void lwl_toplevel_reset(void);
void lwl_lock_reset(void);
void lwl_capture_reset(void);
void lwl_clipboard_reset(void);
void lwl_vkbd_reset(void);
void lwl_heads_reset(void);
void lwl_idle_reset(void);

#endif
