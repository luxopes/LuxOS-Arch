/*
 * LuxOS - stav klavesnice zamykaci obrazovky bez GTK a X (Caps Lock, rozlozeni, hlasky),
 * aby sel testovat samostatne (tests/test-lock-kbd.c). Viz luxos-lock-kbd.c.
 */
#ifndef SRC_LUXOS_LOCK_KBD_H_
#define SRC_LUXOS_LOCK_KBD_H_

#include <glib.h>

G_BEGIN_DECLS

/* Caps Lock z uzamcenych modifikatoru XKB (XkbStateRec.locked_mods, LockMask) */
gboolean lux_kbd_caps_from_mods (guint locked_mods);

/* skupina XKB omezena na pocet rozlozeni (0 pri zadnem) */
int lux_kbd_group_index (int group, int n_layouts);

/* dalsi rozlozeni pri prepnuti (kliknuti na rozlozeni) */
int lux_kbd_next_group (int group, int n_layouts);

/* stitek rozlozeni: "CZ", "US"; varianta jen kdyz je stejne rozlozeni vickrat ("CZ qwerty") */
char *lux_kbd_label (char **layouts, char **variants, int group);

/* rozlozeni pod polem pro heslo ukazat jen pri vic nez jednom (jinak neni co splest) */
gboolean lux_kbd_show_layout (int n_layouts);

/* anglicky klic hlasky po spatnem hesle (preklad pres luxos-i18n) */
const char *lux_kbd_failed_text (gboolean caps_lock_on);

/* probuzeni z uspani mezi dvema okamziky: realny cas uplynul o vic nez monotonni (ten
   v uspani stoji) - hodnoty v mikrosekundach (g_get_real_time, g_get_monotonic_time) */
gboolean lux_kbd_slept (gint64 real_before, gint64 mono_before, gint64 real_now, gint64 mono_now);

G_END_DECLS

#endif /* SRC_LUXOS_LOCK_KBD_H_ */
