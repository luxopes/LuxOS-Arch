/*
 * LuxOS - vzhled zamykaciho dialogu xfce4-screensaver jako zamykaci obrazovka luxos-greeter.
 * Viz luxos-lock-ui.c.
 */
#ifndef SRC_LUXOS_LOCK_UI_H_
#define SRC_LUXOS_LOCK_UI_H_

#include <gtk/gtk.h>

G_BEGIN_DECLS

typedef struct _LuxLock LuxLock;
typedef void (*LuxLockFunc) (gpointer data);

/* preklad z /usr/share/luxos/i18n/<jazyk>.tsv (luxos-i18n), jinak anglicky text */
const char *lux_tr (const char *text);

/* widgety z xfce4-screensaver-dialog.ui; plug_widget = GtkPlug dialogu */
LuxLock *lux_lock_new (GtkBuilder *builder,
                       GtkWidget *plug_widget);
/* rozmery podle monitoru, tapeta, styl (az po nastaveni vlastnosti dialogu) */
void lux_lock_setup (LuxLock *ll,
                     gint monitor_index);
void lux_lock_free (LuxLock *ll);

/* tlacitko ve spodni rade: "switch" (prepnout uzivatele), "logout" */
GtkWidget *lux_lock_get_button (LuxLock *ll,
                                const char *key);
/* vic uzivatelu s prihlasenim (tlacitko Prepnout uzivatele jen pak) */
gboolean lux_lock_multi_user (void);

/* klid (hodiny) -> prihlaseni; zpet s funkci po dokonceni animace */
void lux_lock_enter (LuxLock *ll);
void lux_lock_leave (LuxLock *ll,
                     LuxLockFunc done,
                     gpointer data);

/* PAM: vyzva, zprava, odeslana odpoved, neuspech */
void lux_lock_set_prompt (LuxLock *ll,
                          const char *text,
                          gboolean secret);
void lux_lock_pam_message (LuxLock *ll,
                           const char *text,
                           gboolean is_error);
void lux_lock_checking (LuxLock *ll);
void lux_lock_auth_failed (LuxLock *ll,
                           const char *message);

void lux_lock_hint (LuxLock *ll,
                    const char *text,
                    gboolean error);
void lux_lock_update_caps (LuxLock *ll,
                           gboolean on);
void lux_lock_set_status_message (LuxLock *ll,
                                  const char *text);

G_END_DECLS

#endif /* SRC_LUXOS_LOCK_UI_H_ */
