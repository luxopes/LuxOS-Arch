/*
 * LuxOS - stav klavesnice zamykaci obrazovky bez GTK a X (Caps Lock, rozlozeni, hlasky).
 * Po probuzeni notebooku bylo spatne heslo casto jen kvuli zapnutemu Caps Locku nebo jinemu
 * rozlozeni; tady je logika, co a kdy ukazat, aby sla otestovat (tests/test-lock-kbd.c).
 */
#include <string.h>

#include "luxos-lock-kbd.h"

/* LockMask z X11/X.h (1 << 1); bez zavislosti na hlavickach X kvuli testum */
#define LUX_LOCK_MASK (1u << 1)

/* realny cas utekl o vic nez monotonni = system spal (rozdil pod 5 s je bezny posun hodin) */
#define LUX_SLEEP_GAP_US (5 * G_USEC_PER_SEC)

gboolean
lux_kbd_caps_from_mods (guint locked_mods) {
    return (locked_mods & LUX_LOCK_MASK) != 0;
}

int
lux_kbd_group_index (int group, int n_layouts) {
    if (n_layouts <= 0 || group < 0)
        return 0;
    return group % n_layouts;
}

int
lux_kbd_next_group (int group, int n_layouts) {
    if (n_layouts <= 1)
        return 0;
    return (lux_kbd_group_index (group, n_layouts) + 1) % n_layouts;
}

char *
lux_kbd_label (char **layouts, char **variants, int group) {
    int n = layouts ? (int) g_strv_length (layouts) : 0, i, dup = 0;
    const char *lay, *var;
    char *up, *label;
    if (n == 0)
        return g_strdup ("US");
    i = lux_kbd_group_index (group, n);
    lay = layouts[i] && *layouts[i] ? layouts[i] : "us";
    var = variants && (int) g_strv_length (variants) > i ? variants[i] : "";
    for (int j = 0; j < n; j++)
        dup += g_strcmp0 (layouts[j], layouts[i]) == 0;
    up = g_ascii_strup (lay, -1);
    label = dup > 1 && var && *var ? g_strdup_printf ("%s %s", up, var) : g_strdup (up);
    g_free (up);
    return label;
}

gboolean
lux_kbd_show_layout (int n_layouts) {
    return n_layouts > 1;
}

const char *
lux_kbd_failed_text (gboolean caps_lock_on) {
    return caps_lock_on ? "Incorrect password – Caps Lock is on" : "Incorrect password. Try again.";
}

gboolean
lux_kbd_slept (gint64 real_before, gint64 mono_before, gint64 real_now, gint64 mono_now) {
    if (real_before <= 0 || mono_before <= 0)
        return FALSE;
    return (real_now - real_before) - (mono_now - mono_before) > LUX_SLEEP_GAP_US;
}
