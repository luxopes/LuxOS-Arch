/*
 * Testovaci harness pro luxos-super-tap.h (preklada tests/test_luxos_menubar.py).
 * Radky na stdin: "p KC S T" stisk, "r KC S T" uvolneni, "b T" tlacitko mysi,
 * "k KC..." stav klaves ze serveru (super_tap_sync); KC = keycode, S = 1 pro Super, T = cas v ms.
 * Pro kazdou udalost vypise 1 (otevrit Launchpad) nebo 0.
 */
#include <stdio.h>
#include <string.h>
#include "../../files/src/luxos-super-tap.h"

int main(void)
{
    struct super_tap t;
    char line[256];
    memset(&t, 0, sizeof t);
    while (fgets(line, sizeof line, stdin)) {
        int kc, sup;
        long long now;
        if (line[0] == 'k') {
            char keys[32] = {0};
            int off = 1, n;
            while (sscanf(line + off, "%d%n", &kc, &n) == 1) {
                keys[kc >> 3] |= (char)(1 << (kc & 7));
                off += n;
            }
            super_tap_sync(&t, keys);
        } else if (line[0] == 'b' && sscanf(line + 1, "%lld", &now) == 1) {
            printf("%d\n", super_tap_event(&t, TAP_BUTTON, 0, 0, now));
        } else if ((line[0] == 'p' || line[0] == 'r') && sscanf(line + 1, "%d %d %lld", &kc, &sup, &now) == 3) {
            printf("%d\n", super_tap_event(&t, line[0] == 'p' ? TAP_KEY_PRESS : TAP_KEY_RELEASE, kc, sup, now));
        }
    }
    return 0;
}
