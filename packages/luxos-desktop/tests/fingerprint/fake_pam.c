/* LuxOS - testovaci PAM modul (bez hlavicek libpam-dev): napodobi pam_fprintd nebo pam_unix.
 *   auth ... fake_pam.so finger    -> chovani podle FAKE_FP: match | nomatch | unavail
 *   auth ... fake_pam.so password  -> vyzva "Password: ", spravne heslo je "secret"
 *   auth ... fake_pam.so faillock preauth|authsucc  -> pam_faillock: FAKE_LOCKED=1 = ucet zamceny
 *   auth ... fake_pam.so nologin   -> pam_nologin: FAKE_NOLOGIN=1 = /etc/nologin existuje
 *   auth ... fake_pam.so shells    -> pam_shells: FAKE_BADSHELL=1 = shell neni v /etc/shells
 * Kazde volani zapise do souboru FAKE_LOG (je-li nastaven) radek "finger" / "password" /
 * "preauth" / "authsucc" / "nologin" / "shells". */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct pam_handle pam_handle_t;
struct pam_message { int msg_style; const char *msg; };
struct pam_response { char *resp; int resp_retcode; };
struct pam_conv {
    int (*conv)(int, const struct pam_message **, struct pam_response **, void *);
    void *appdata_ptr;
};
extern int pam_get_item(const pam_handle_t *, int, const void **);

#define PAM_SUCCESS 0
#define PAM_AUTH_ERR 7
#define PAM_AUTHINFO_UNAVAIL 9
#define PAM_CONV 5
#define PAM_PROMPT_ECHO_OFF 1
#define PAM_ERROR_MSG 3
#define PAM_TEXT_INFO 4

static int say(pam_handle_t *h, int style, const char *text, char **answer)
{
    const struct pam_conv *c = NULL;
    struct pam_message m = { style, text };
    const struct pam_message *mp = &m;
    struct pam_response *r = NULL;
    if (pam_get_item(h, PAM_CONV, (const void **)&c) != PAM_SUCCESS || !c)
        return -1;
    if (c->conv(1, &mp, &r, c->appdata_ptr) != PAM_SUCCESS)
        return -1;
    if (answer)
        *answer = (r && r->resp) ? strdup(r->resp) : NULL;
    if (r) { free(r->resp); free(r); }
    return 0;
}

static void note(const char *what)
{
    const char *p = getenv("FAKE_LOG");
    FILE *f;
    if (p && (f = fopen(p, "a"))) { fprintf(f, "%s\n", what); fclose(f); }
}

static int env_on(const char *name)
{
    const char *v = getenv(name);
    return v && strcmp(v, "1") == 0;
}

int pam_sm_authenticate(pam_handle_t *h, int flags, int argc, const char **argv)
{
    (void)flags;
    if (argc > 1 && strcmp(argv[0], "faillock") == 0) {
        note(argv[1]);
        if (strcmp(argv[1], "preauth") == 0 && env_on("FAKE_LOCKED")) {
            say(h, PAM_ERROR_MSG, "The account is locked due to 20 failed logins.", NULL);
            return PAM_AUTH_ERR;
        }
        return PAM_SUCCESS;
    }
    if (argc > 0 && strcmp(argv[0], "nologin") == 0) {
        note("nologin");
        return env_on("FAKE_NOLOGIN") ? PAM_AUTH_ERR : PAM_SUCCESS;
    }
    if (argc > 0 && strcmp(argv[0], "shells") == 0) {
        note("shells");
        return env_on("FAKE_BADSHELL") ? PAM_AUTH_ERR : PAM_SUCCESS;
    }
    if (argc > 0 && strcmp(argv[0], "finger") == 0) {
        const char *mode = getenv("FAKE_FP");
        note("finger");
        if (!mode || strcmp(mode, "unavail") == 0)
            return PAM_AUTHINFO_UNAVAIL;
        say(h, PAM_TEXT_INFO, "Place your finger on the fingerprint reader", NULL);
        if (strcmp(mode, "match") == 0)
            return PAM_SUCCESS;
        say(h, PAM_ERROR_MSG, "Failed to match fingerprint", NULL);
        return PAM_AUTH_ERR;
    }
    char *pw = NULL;
    int ok;
    note("password");
    if (say(h, PAM_PROMPT_ECHO_OFF, "Password: ", &pw) != 0)
        return PAM_AUTH_ERR;
    ok = pw && strcmp(pw, "secret") == 0;
    free(pw);
    return ok ? PAM_SUCCESS : PAM_AUTH_ERR;
}

int pam_sm_setcred(pam_handle_t *h, int flags, int argc, const char **argv)
{
    (void)h; (void)flags; (void)argc; (void)argv;
    return PAM_SUCCESS;
}
