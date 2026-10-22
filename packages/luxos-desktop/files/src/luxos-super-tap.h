/*
 * luxos-super-tap.h - rozpoznani samotneho tuknuti na klavesu Super (otevre Launchpad).
 *
 * Ciste stavove funkce bez Xlib, aby je slo testovat (tests/test_luxos_menubar.py
 * je prelozi s malym harnessem). Pouziva luxos-menubar s udalostmi XInput2 raw.
 *
 * Tuknuti = stisk Super_L/Super_R, kdyz neni drzena zadna jina klavesa, a jeho uvolneni
 * do SUPER_TAP_MS bez stisku jine klavesy nebo tlacitka mysi mezi tim. Super+klavesa,
 * Super+klik/kolecko (presun okna, zoom) ani drzeni Super proto Launchpad nikdy neotevrou.
 */
#ifndef LUXOS_SUPER_TAP_H
#define LUXOS_SUPER_TAP_H

#include <string.h>

#define SUPER_TAP_MS 400            /* nejdelsi tuknuti */
#define SUPER_TAP_DEBOUNCE_MS 250   /* dve spusteni nejdriv po tolika ms */

enum { TAP_KEY_PRESS, TAP_KEY_RELEASE, TAP_BUTTON };

struct super_tap {
    unsigned char down[32];         /* bitmapa drzenych klaves (keycode 0..255, jako XQueryKeymap) */
    int armed;                      /* keycode stisknute Super, ktera muze byt tuknutim; 0 = nic */
    long long since;                /* cas stisku Super (ms) */
    long long last_fire;            /* cas posledniho spusteni (ms) */
    int fired;                      /* last_fire plati */
};

static inline int tap_is_down(const struct super_tap *t, int kc)
{
    return kc > 0 && kc < 256 && (t->down[kc >> 3] >> (kc & 7)) & 1;
}

static inline void tap_set_down(struct super_tap *t, int kc, int on)
{
    if (kc <= 0 || kc >= 256)
        return;
    if (on)
        t->down[kc >> 3] |= (unsigned char)(1 << (kc & 7));
    else
        t->down[kc >> 3] &= (unsigned char)~(1 << (kc & 7));
}

/* Drzi se jina klavesa nez kc? */
static inline int tap_other_down(const struct super_tap *t, int kc)
{
    for (int i = 1; i < 256; i++)
        if (i != kc && tap_is_down(t, i))
            return 1;
    return 0;
}

/* Prevzit skutecny stav klaves ze serveru (XQueryKeymap) - opravi ztracene uvolneni */
static inline void super_tap_sync(struct super_tap *t, const char keys[32])
{
    memcpy(t->down, keys, 32);
}

/*
 * Jedna udalost: type = TAP_KEY_PRESS / TAP_KEY_RELEASE / TAP_BUTTON, keycode klavesy,
 * is_super = klavesa je Super_L/Super_R, now = monotonni cas v ms.
 * Vraci 1, kdyz se ma otevrit Launchpad.
 */
static inline int super_tap_event(struct super_tap *t, int type, int keycode, int is_super, long long now)
{
    if (type == TAP_BUTTON) {
        t->armed = 0;
        return 0;
    }
    if (type == TAP_KEY_PRESS) {
        if (tap_is_down(t, keycode) && keycode == t->armed)
            return 0;               /* automaticke opakovani drzene Super */
        tap_set_down(t, keycode, 1);
        if (is_super && !tap_other_down(t, keycode)) {
            t->armed = keycode;
            t->since = now;
        } else {
            t->armed = 0;           /* jina klavesa (Super+E, Ctrl+Super, ...) */
        }
        return 0;
    }
    /* TAP_KEY_RELEASE */
    tap_set_down(t, keycode, 0);
    if (keycode != t->armed) {
        t->armed = 0;
        return 0;
    }
    t->armed = 0;
    if (now - t->since > SUPER_TAP_MS || now < t->since)
        return 0;                   /* Super se drzela dlouho */
    if (t->fired && now - t->last_fire < SUPER_TAP_DEBOUNCE_MS)
        return 0;
    t->last_fire = now;
    t->fired = 1;
    return 1;
}

#endif
