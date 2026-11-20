/*
 * LuxOS - napodobeny libpam pro testy luxos-auth / luxos-lock (LD_PRELOAD do luxos-auth): testy nikdy
 * neoveruji skutecne heslo ani nesahaji na pam_faillock systemu.
 *
 *   sluzba luxos-lock              heslo; spravne je "luxos" (nebo FAKE_PAM_PASSWORD)
 *   sluzba luxos-lock-fingerprint  FAKE_FP: none (bez ctecky, hned chyba), match / nomatch (vyzva,
 *                                  pak ceka na soubor FAKE_FP_TOUCH = prilozeny prst)
 * Faillock jako pam_faillock s nastavenim LuxOS: FAKE_TALLY = soubor s casy chyb, FAKE_DENY (20),
 * FAKE_INTERVAL (30 s), FAKE_UNLOCK (60 s). Pri zamceni zpravy jako pam_faillock a chyba bez pokusu.
 * FAKE_LOG = soubor, kam jde radek za kazde volani ("auth SLUZBA HESLO", testovaci hesla).
 * FAKE_DELAY_MS = cekani po spatnem hesle (pam_faildelay).
 *
 *     gcc -shared -fPIC -o fake-pam.so fake-pam.c
 */
#define _GNU_SOURCE
#include <security/pam_appl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

struct pam_handle {
    struct pam_conv conv;
    char service[64];
    char user[64];
};

static long env_num(const char *name, long def)
{
    const char *v = getenv(name);
    return v && *v ? atol(v) : def;
}

static void note(const char *what, const char *service, const char *text)
{
    const char *path = getenv("FAKE_LOG");
    FILE *f = path ? fopen(path, "a") : NULL;
    if (f) {
        fprintf(f, "%s %s %s\n", what, service, text ? text : "");
        fclose(f);
    }
}

static int say(pam_handle_t *h, int style, const char *text, char **answer)
{
    struct pam_message m = {style, text};
    const struct pam_message *mp = &m;
    struct pam_response *r = NULL;
    if (h->conv.conv(1, &mp, &r, h->conv.appdata_ptr) != PAM_SUCCESS)
        return -1;
    if (answer)
        *answer = r && r->resp ? strdup(r->resp) : NULL;
    if (r) {
        free(r->resp);
        free(r);
    }
    return 0;
}

/* casy chyb v souboru; vraci pocet chyb v okne FAKE_INTERVAL a cas posledni */
static int tally(time_t now, time_t *last)
{
    const char *path = getenv("FAKE_TALLY");
    FILE *f = path ? fopen(path, "r") : NULL;
    long t;
    int n = 0;
    *last = 0;
    if (!f)
        return 0;
    while (fscanf(f, "%ld", &t) == 1) {
        if (now - t <= env_num("FAKE_INTERVAL", 30))
            n++;
        *last = t;
    }
    fclose(f);
    return n;
}

static void tally_add(time_t now, int reset)
{
    const char *path = getenv("FAKE_TALLY");
    FILE *f = path ? fopen(path, reset ? "w" : "a") : NULL;
    if (!f)
        return;
    if (!reset)
        fprintf(f, "%ld\n", (long)now);
    fclose(f);
}

static int locked_out(pam_handle_t *h)
{
    time_t last, now = time(NULL);
    long unlock = env_num("FAKE_UNLOCK", 60);
    if (tally(now, &last) < env_num("FAKE_DENY", 20) || now - last >= unlock)
        return 0;
    char text[128];
    say(h, PAM_ERROR_MSG, "The account is locked due to 20 failed logins.", NULL);
    snprintf(text, sizeof text, "(%ld minutes left to unlock)", (unlock - (now - last) + 59) / 60);
    say(h, PAM_ERROR_MSG, text, NULL);
    return 1;
}

static int fingerprint(pam_handle_t *h)
{
    const char *mode = getenv("FAKE_FP");
    const char *touch = getenv("FAKE_FP_TOUCH");
    note("auth", h->service, mode);
    if (!mode || strcmp(mode, "none") == 0 || !touch)
        return PAM_AUTH_ERR;
    say(h, PAM_TEXT_INFO, "Place your finger on the fingerprint reader", NULL);
    for (int i = 0; i < 600 && access(touch, F_OK) != 0; i++)
        usleep(50000);
    if (access(touch, F_OK) != 0)
        return PAM_AUTH_ERR;
    unlink(touch);
    if (strcmp(mode, "match") == 0)
        return PAM_SUCCESS;
    say(h, PAM_ERROR_MSG, "Failed to match fingerprint", NULL);
    return PAM_AUTH_ERR;
}

int pam_start(const char *service, const char *user, const struct pam_conv *conv, pam_handle_t **pamh)
{
    pam_handle_t *h = calloc(1, sizeof *h);
    h->conv = *conv;
    snprintf(h->service, sizeof h->service, "%s", service);
    snprintf(h->user, sizeof h->user, "%s", user ? user : "");
    *pamh = h;
    return PAM_SUCCESS;
}

int pam_end(pam_handle_t *pamh, int status)
{
    (void)status;
    free(pamh);
    return PAM_SUCCESS;
}

int pam_authenticate(pam_handle_t *h, int flags)
{
    (void)flags;
    if (locked_out(h))
        return PAM_AUTH_ERR;
    if (strcmp(h->service, "luxos-lock-fingerprint") == 0) {
        int rc = fingerprint(h);
        if (rc == PAM_SUCCESS)
            tally_add(time(NULL), 1);
        return rc;
    }
    if (strcmp(h->service, "luxos-lock") != 0)
        return PAM_AUTH_ERR;
    char *answer = NULL;
    if (say(h, PAM_PROMPT_ECHO_OFF, "Password: ", &answer) < 0 || !answer)
        return PAM_CONV_ERR;
    const char *want = getenv("FAKE_PAM_PASSWORD");
    int ok = strcmp(answer, want && *want ? want : "luxos") == 0;
    note("auth", h->service, answer);
    free(answer);
    if (ok) {
        tally_add(time(NULL), 1);
        return PAM_SUCCESS;
    }
    tally_add(time(NULL), 0);
    usleep((useconds_t)env_num("FAKE_DELAY_MS", 0) * 1000);
    return PAM_AUTH_ERR;
}

int pam_setcred(pam_handle_t *h, int flags)
{
    (void)flags;
    note("setcred", h->service, "");
    return PAM_SUCCESS;
}

int pam_set_item(pam_handle_t *h, int type, const void *item)
{
    (void)h; (void)type; (void)item;
    return PAM_SUCCESS;
}

int pam_get_item(const pam_handle_t *h, int type, const void **item)
{
    *item = type == PAM_USER ? h->user : NULL;
    return PAM_SUCCESS;
}

int pam_fail_delay(pam_handle_t *h, unsigned int usec)
{
    (void)h; (void)usec;
    return PAM_SUCCESS;
}

const char *pam_strerror(pam_handle_t *h, int errnum)
{
    (void)h;
    return errnum == PAM_SUCCESS ? "Success" : "Authentication failure";
}
