/*
 * LuxOS - testy stavu klavesnice zamykaci obrazovky (luxos-lock-kbd.c).
 *
 *     gcc -o test-lock-kbd tests/test-lock-kbd.c luxos-lock-kbd.c -I. $(pkg-config --cflags --libs glib-2.0)
 *     ./test-lock-kbd
 */
#include <glib.h>

#include "luxos-lock-kbd.h"

static void
test_caps (void) {
    /* LockMask = 1 << 1; Shift (1), NumLock (Mod2 = 1 << 4) ani skupina Caps Lock nejsou */
    g_assert_false (lux_kbd_caps_from_mods (0));
    g_assert_true (lux_kbd_caps_from_mods (1u << 1));
    g_assert_false (lux_kbd_caps_from_mods (1u << 0));
    g_assert_false (lux_kbd_caps_from_mods (1u << 4));
    g_assert_true (lux_kbd_caps_from_mods ((1u << 1) | (1u << 4)));
}

static void
test_failed_text (void) {
    g_assert_cmpstr (lux_kbd_failed_text (TRUE), ==, "Incorrect password – Caps Lock is on");
    g_assert_cmpstr (lux_kbd_failed_text (FALSE), ==, "Incorrect password. Try again.");
}

static void
test_label (void) {
    char *one[] = { "us", NULL };
    char *two[] = { "us", "cz", NULL };
    char *dup[] = { "cz", "cz", "us", NULL };
    char *dupv[] = { "", "qwerty", "", NULL };
    char *empty[] = { NULL };
    char *l;

    l = lux_kbd_label (one, NULL, 0);
    g_assert_cmpstr (l, ==, "US");
    g_free (l);
    l = lux_kbd_label (two, NULL, 1);
    g_assert_cmpstr (l, ==, "CZ");
    g_free (l);
    /* skupina mimo rozsah (stary stav serveru) se zalomi, nespadne */
    l = lux_kbd_label (two, NULL, 3);
    g_assert_cmpstr (l, ==, "CZ");
    g_free (l);
    l = lux_kbd_label (two, NULL, -1);
    g_assert_cmpstr (l, ==, "US");
    g_free (l);
    /* stejne rozlozeni dvakrat: rozlisit variantou */
    l = lux_kbd_label (dup, dupv, 1);
    g_assert_cmpstr (l, ==, "CZ qwerty");
    g_free (l);
    l = lux_kbd_label (dup, dupv, 0);
    g_assert_cmpstr (l, ==, "CZ");
    g_free (l);
    l = lux_kbd_label (dup, dupv, 2);
    g_assert_cmpstr (l, ==, "US");
    g_free (l);
    /* kratsi seznam variant */
    l = lux_kbd_label (dup, NULL, 1);
    g_assert_cmpstr (l, ==, "CZ");
    g_free (l);
    l = lux_kbd_label (empty, NULL, 0);
    g_assert_cmpstr (l, ==, "US");
    g_free (l);
    l = lux_kbd_label (NULL, NULL, 0);
    g_assert_cmpstr (l, ==, "US");
    g_free (l);
}

static void
test_groups (void) {
    g_assert_cmpint (lux_kbd_group_index (0, 2), ==, 0);
    g_assert_cmpint (lux_kbd_group_index (1, 2), ==, 1);
    g_assert_cmpint (lux_kbd_group_index (2, 2), ==, 0);
    g_assert_cmpint (lux_kbd_group_index (1, 0), ==, 0);
    g_assert_cmpint (lux_kbd_group_index (-3, 2), ==, 0);
    g_assert_cmpint (lux_kbd_next_group (0, 2), ==, 1);
    g_assert_cmpint (lux_kbd_next_group (1, 2), ==, 0);
    g_assert_cmpint (lux_kbd_next_group (2, 3), ==, 0);
    g_assert_cmpint (lux_kbd_next_group (5, 3), ==, 0);
    g_assert_cmpint (lux_kbd_next_group (0, 1), ==, 0);
    g_assert_cmpint (lux_kbd_next_group (0, 0), ==, 0);
}

static void
test_show_layout (void) {
    g_assert_false (lux_kbd_show_layout (0));
    g_assert_false (lux_kbd_show_layout (1));
    g_assert_true (lux_kbd_show_layout (2));
    g_assert_true (lux_kbd_show_layout (4));
}

static void
test_slept (void) {
    const gint64 s = G_USEC_PER_SEC, r0 = 1700000000 * s, m0 = 1000 * s;
    /* bez predchoziho mereni nic */
    g_assert_false (lux_kbd_slept (0, 0, r0, m0));
    /* bezny chod: oba casy stejne */
    g_assert_false (lux_kbd_slept (r0, m0, r0 + 1 * s, m0 + 1 * s));
    g_assert_false (lux_kbd_slept (r0, m0, r0 + 60 * s, m0 + 60 * s));
    /* drobny posun hodin (NTP) ne */
    g_assert_false (lux_kbd_slept (r0, m0, r0 + 4 * s, m0 + 1 * s));
    /* hodiny vracene zpet ne */
    g_assert_false (lux_kbd_slept (r0, m0, r0 - 3600 * s, m0 + 1 * s));
    /* uspani na 10 minut: monotonni cas stal */
    g_assert_true (lux_kbd_slept (r0, m0, r0 + 600 * s, m0 + 1 * s));
    g_assert_true (lux_kbd_slept (r0, m0, r0 + 7 * s, m0 + 1 * s));
}

int
main (int argc, char **argv) {
    g_test_init (&argc, &argv, NULL);
    g_test_add_func ("/lock-kbd/caps", test_caps);
    g_test_add_func ("/lock-kbd/failed-text", test_failed_text);
    g_test_add_func ("/lock-kbd/label", test_label);
    g_test_add_func ("/lock-kbd/groups", test_groups);
    g_test_add_func ("/lock-kbd/show-layout", test_show_layout);
    g_test_add_func ("/lock-kbd/slept", test_slept);
    return g_test_run ();
}
