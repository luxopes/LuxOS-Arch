/*
 * LuxOS - napodobeny libpam pro testy zamykaciho dialogu (LD_PRELOAD): testy nikdy neoveruji
 * skutecne heslo uzivatele ani nepocitaji neuspechy v pam_faillock.
 * Spravne heslo je "luxos" (nebo LUXOS_FAKE_PAM_PASSWORD); LUXOS_FAKE_PAM_LOG = soubor, kam se
 * zapise kazde prijate (testovaci) heslo.
 *
 *     gcc -shared -fPIC -o fake-pam.so fake-pam.c
 */
#include <security/pam_appl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct pam_handle {
    struct pam_conv conv;
    char *user;
    const void *items[32];
};

int
pam_start (const char *service, const char *user, const struct pam_conv *conv, pam_handle_t **pamh) {
    pam_handle_t *h = calloc (1, sizeof *h);
    h->conv = *conv;
    h->user = strdup (user ? user : "user");
    *pamh = h;
    return PAM_SUCCESS;
}

int
pam_end (pam_handle_t *pamh, int status) {
    if (pamh) {
        free (pamh->user);
        free (pamh);
    }
    return PAM_SUCCESS;
}

int
pam_set_item (pam_handle_t *pamh, int type, const void *item) {
    if (type >= 0 && type < 32)
        pamh->items[type] = item;
    return PAM_SUCCESS;
}

int
pam_get_item (const pam_handle_t *pamh, int type, const void **item) {
    *item = type == PAM_USER ? pamh->user : (type >= 0 && type < 32 ? pamh->items[type] : NULL);
    return PAM_SUCCESS;
}

int
pam_fail_delay (pam_handle_t *pamh, unsigned int usec) {
    return PAM_SUCCESS;
}

int
pam_authenticate (pam_handle_t *pamh, int flags) {
    struct pam_message m = { PAM_PROMPT_ECHO_OFF, "Password: " };
    const struct pam_message *mp = &m;
    struct pam_response *r = NULL;
    const char *want = getenv ("LUXOS_FAKE_PAM_PASSWORD");
    int ok;
    if (pamh->conv.conv (1, &mp, &r, pamh->conv.appdata_ptr) != PAM_SUCCESS || r == NULL)
        return PAM_CONV_ERR;
    ok = r->resp != NULL && strcmp (r->resp, want && *want ? want : "luxos") == 0;
    if (getenv ("LUXOS_FAKE_PAM_LOG")) {
        FILE *f = fopen (getenv ("LUXOS_FAKE_PAM_LOG"), "a");
        if (f) {
            fprintf (f, "%s\n", r->resp ? r->resp : "");
            fclose (f);
        }
    }
    free (r->resp);
    free (r);
    return ok ? PAM_SUCCESS : PAM_AUTH_ERR;
}

int
pam_acct_mgmt (pam_handle_t *pamh, int flags) {
    return PAM_SUCCESS;
}

int
pam_setcred (pam_handle_t *pamh, int flags) {
    return PAM_SUCCESS;
}

const char *
pam_strerror (pam_handle_t *pamh, int errnum) {
    return errnum == PAM_SUCCESS ? "Success" : "Authentication failure";
}
