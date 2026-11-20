/* libluxos-wl: ploche API klienta Waylandu pro shell LuxOS (luxos_wl.lsl).
 *
 * Jedno spojeni na proces: vlastni (lwl_connect), nebo to, ktere uz ma GTK
 * (lwl_attach s gdk_wayland_display_get_wl_display) - klient shellu v GTK tak
 * ma jediny soket. Objekty jsou cisla (handly), ktera se nikdy nepouziji znovu;
 * stary handle je neskodny (gettery vrati 0 nebo "").
 *
 * Vsechny udalosti jdou jedinou obsluhou cb(user, kind, handle, a, b). Sbiraji
 * se behem rozesilani libwayland a doruci se az potom, obsluha tedy smi volat
 * cokoli z lwl_*. Konci-li objekt (zavrene okno, odebrany vystup), je citelny
 * jeste behem sve udalosti LWL_*_CLOSED/REMOVED a hned po ni se uvolni.
 *
 * Texty z getteru patri knihovne a plati do zmeny objektu; volajici si je kopiruje.
 */
#ifndef LUXOS_WL_H
#define LUXOS_WL_H

#include <stdint.h>

struct wl_display;

typedef void (*lwl_handler)(void *user, int kind, int handle, int a, int b);

enum lwl_event {
	LWL_OUTPUT_NEW = 1,         /* handle = vystup */
	LWL_OUTPUT_REMOVED,
	LWL_TOPLEVEL_NEW,           /* wlr-foreign-toplevel-management, po prvnim done */
	LWL_TOPLEVEL_CHANGED,
	LWL_TOPLEVEL_CLOSED,
	LWL_LIST_TOPLEVEL_NEW,      /* ext-foreign-toplevel-list */
	LWL_LIST_TOPLEVEL_CHANGED,
	LWL_LIST_TOPLEVEL_CLOSED,
	LWL_LOCKED,                 /* ext-session-lock: kompozitor ukazuje jen nase zamykaci plochy */
	LWL_LOCK_FINISHED,          /* zamek odmitnut nebo ukoncen kompozitorem */
	LWL_SURFACE_CONFIGURE,      /* handle = zamykaci plocha, a = sirka, b = vyska; nakreslit a commit */
	LWL_KEY,                    /* a = keysym, b = znak Unicode (0 = zadny); stisk na nasi plose.
	                               S lwl_lock_secret(1): znak jde jen do hesla v knihovne, a = 0 (znak)
	                               nebo keysym ostatnich klaves, b = delka hesla ve znacich */
	LWL_CAPTURE_READY,          /* handle = snimek, a = sirka, b = vyska */
	LWL_CAPTURE_FAILED,         /* a = duvod (failure_reason ext_image_copy_capture_frame_v1) nebo -1 */
	LWL_CLIPBOARD_CHANGED,      /* a = 1 primarni vyber, 0 schranka; b = 1 nabizi text */
	LWL_CLIPBOARD_CANCELLED,    /* nas vyber nahradil jiny; a = primarni */
	LWL_CLIPBOARD_DATA,         /* handle = pozadavek, a = delka, b = 0 ok / -1 chyba */
	LWL_HEAD_NEW,               /* hlava wlr-output-management */
	LWL_HEAD_CHANGED,
	LWL_HEAD_REMOVED,
	LWL_OUTPUT_CONFIG_RESULT,   /* a = 1 pouzito, 0 chyba, 2 zruseno */
	LWL_IDLE,                   /* handle = hlidani necinnosti */
	LWL_RESUMED,
	LWL_DISCONNECTED,           /* kompozitor skoncil */
	LWL_KEYBOARD,               /* zamek: handle = plocha s fokusem, a = Caps Lock, b = skupina (rozlozeni) */
};

/* bity stavu okna */
#define LWL_STATE_ACTIVATED  1
#define LWL_STATE_MAXIMIZED  2
#define LWL_STATE_MINIMIZED  4
#define LWL_STATE_FULLSCREEN 8

void lwl_set_handler(lwl_handler cb, void *user);
/* Navazat jen vyjmenovane globaly (nazvy rozhrani oddelene carkou), NULL = vsechny; plati pro dalsi
 * connect/attach. Plocha tak nedrzi napr. zwlr_output_manager_v1 (wlroots 0.20.2 pak pada pri zapnuti vystupu). */
void lwl_bind_only(const char *interfaces);
int lwl_connect(const char *name);
int lwl_attach(struct wl_display *display);
void lwl_disconnect(void);
int lwl_roundtrip(void);
int lwl_has(const char *interface);

int lwl_output_count(void);
int lwl_output_at(int index);
const char *lwl_output_name(int output);
const char *lwl_output_description(int output);
int lwl_output_x(int output);
int lwl_output_y(int output);
int lwl_output_width(int output);
int lwl_output_height(int output);
int lwl_output_scale(int output);

int lwl_toplevel_count(int list);
int lwl_toplevel_at(int list, int index);
const char *lwl_toplevel_app_id(int toplevel);
const char *lwl_toplevel_title(int toplevel);
const char *lwl_toplevel_identifier(int toplevel);
int lwl_toplevel_state(int toplevel);
int lwl_toplevel_activate(int toplevel);
int lwl_toplevel_set_minimized(int toplevel, int on);
int lwl_toplevel_set_maximized(int toplevel, int on);
int lwl_toplevel_close(int toplevel);

int lwl_lock(void);
int lwl_lock_surface(int output);
int lwl_unlock(void);
int lwl_lock_secret(int on);
int lwl_lock_secret_length(void);
void lwl_lock_secret_clear(void);
int lwl_lock_secret_write(int fd);
int lwl_lock_caps(void);
int lwl_lock_layout(void);
int lwl_lock_layout_count(void);
const char *lwl_lock_layout_code(int group);
int lwl_surface_width(int surface);
int lwl_surface_height(int surface);
void *lwl_surface_begin(int surface);
int lwl_surface_commit(int surface);

int lwl_capture_output(int output, int cursor);
int lwl_capture_toplevel(int list_toplevel, int cursor);
void *lwl_capture_data(int capture);
int lwl_capture_stride(int capture);
int lwl_capture_format(int capture);
void lwl_capture_free(int capture);

int lwl_clipboard_set(const char *text, int primary);
const char *lwl_clipboard_mime_types(int primary);
int lwl_clipboard_request(const char *mime, int primary);
const char *lwl_clipboard_data(int request);
void lwl_clipboard_free(int request);

int lwl_type(const char *text);

int lwl_head_count(void);
int lwl_head_at(int index);
const char *lwl_head_name(int head);
const char *lwl_head_description(int head);
int lwl_head_enabled(int head);
int lwl_head_x(int head);
int lwl_head_y(int head);
int lwl_head_width(int head);
int lwl_head_height(int head);
int lwl_head_refresh(int head);
int lwl_head_scale(int head);
int lwl_head_transform(int head);
int lwl_head_mode_count(int head);
int lwl_head_mode(int head, int index, int field);
int lwl_output_config_begin(void);
int lwl_output_config_head(int head, int enabled, int width, int height, int refresh,
	int x, int y, int transform, int scale);
int lwl_output_config_apply(int test_only);

int lwl_idle_watch(int timeout_ms);
int lwl_idle_watch_full(int timeout_ms, int input_only);
void lwl_idle_release(int watch);

#endif
