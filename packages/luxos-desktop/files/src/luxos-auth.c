/*
 * LuxOS - overeni pro zamek obrazovky na Waylandu (luxos-lock) mimo jeho proces: PAM a jeho moduly
 * tak nikdy nebezi v programu, ktery kresli a cte klavesnici.
 *
 *   luxos-auth password      sluzba PAM luxos-lock, heslo prijde rourou
 *   luxos-auth fingerprint   sluzba luxos-lock-fingerprint, jen otisk prstu (pam_fprintd)
 *
 * Uzivatel je vzdy ten, kdo program spustil (getuid), nikdy z argumentu. Jeden proces = jeden pokus.
 * Na stdout jdou radky (bez hesla):
 *   info TEXT | error TEXT | prompt TEXT | result ok|fail|unavail CISLO_PAM
 * Na stdin po kazdem "prompt" prijde jeden ramec: delka (uint32, poradi bajtu stroje) a heslo.
 * Heslo neni v argv, prostredi ani logu; buffer je zamceny v RAM (mlock) a po predani PAM se prepise
 * nulami. Odpoved PAM uvolni modul sam (pam_unix ji prepise). Proces nejde ladit ani vypsat (dumpable 0).
 * Na vysledek se ceka tak dlouho, jak urci PAM (pam_faildelay/pam_unix po chybe ~2 s) - program sam
 * nic neporovnava a spatne heslo nevraci rychleji nez spravne.
 *
 *     gcc -O2 -o luxos-auth luxos-auth.c -lpam
 */
#define _GNU_SOURCE
#include <errno.h>
#include <pwd.h>
#include <security/pam_appl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <unistd.h>

#define SECRET_MAX 1024

static char secret[SECRET_MAX];

/* jeden radek protokolu; ridici znaky ze zpravy PAM (vic radku) nahradi mezery */
static int say(const char *kind, const char *text)
{
    char line[512];
    int n = snprintf(line, sizeof line, "%s %s", kind, text ? text : "");
    if (n < 0)
        return -1;
    if ((size_t)n >= sizeof line - 1)
        n = sizeof line - 2;
    for (int i = 0; i < n; i++)
        if ((unsigned char)line[i] < 0x20 || line[i] == 0x7f)
            line[i] = ' ';
    line[n++] = '\n';
    for (int done = 0; done < n;) {
        ssize_t w = write(STDOUT_FILENO, line + done, (size_t)(n - done));
        if (w < 0 && errno == EINTR)
            continue;
        if (w <= 0)
            return -1;
        done += (int)w;
    }
    return 0;
}

static int read_full(void *buf, size_t size)
{
    size_t done = 0;
    while (done < size) {
        ssize_t r = read(STDIN_FILENO, (char *)buf + done, size - done);
        if (r < 0 && errno == EINTR)
            continue;
        if (r <= 0)
            return -1;
        done += (size_t)r;
    }
    return 0;
}

/* Ramec s heslem -> nova kopie pro PAM; nas buffer se hned smaze */
static char *read_secret(void)
{
    uint32_t len;
    char *copy = NULL;
    if (read_full(&len, sizeof len) < 0 || len >= SECRET_MAX)
        return NULL;
    if (read_full(secret, len) == 0) {
        secret[len] = 0;
        copy = strndup(secret, len);
    }
    explicit_bzero(secret, sizeof secret);
    return copy;
}

static void free_replies(struct pam_response *r, int n)
{
    for (int i = 0; i < n; i++) {
        if (r[i].resp) {
            explicit_bzero(r[i].resp, strlen(r[i].resp));
            free(r[i].resp);
        }
    }
    free(r);
}

static int conversation(int n, const struct pam_message **msg, struct pam_response **out, void *data)
{
    int password = *(int *)data;
    struct pam_response *r = calloc((size_t)n, sizeof *r);
    if (n <= 0 || !r) {
        free(r);
        return PAM_CONV_ERR;
    }
    for (int i = 0; i < n; i++) {
        switch (msg[i]->msg_style) {
        case PAM_PROMPT_ECHO_OFF:
        case PAM_PROMPT_ECHO_ON:
            /* otisk prstu heslo nechce; kdyby se modul ptal, pokus konci */
            if (!password || say("prompt", msg[i]->msg) < 0 || !(r[i].resp = read_secret())) {
                free_replies(r, n);
                return PAM_CONV_ERR;
            }
            break;
        case PAM_ERROR_MSG:
            say("error", msg[i]->msg);
            break;
        case PAM_TEXT_INFO:
            say("info", msg[i]->msg);
            break;
        default:
            free_replies(r, n);
            return PAM_CONV_ERR;
        }
    }
    *out = r;
    return PAM_SUCCESS;
}

int main(int argc, char **argv)
{
    int password;
    if (argc == 2 && strcmp(argv[1], "password") == 0)
        password = 1;
    else if (argc == 2 && strcmp(argv[1], "fingerprint") == 0)
        password = 0;
    else {
        fprintf(stderr, "usage: luxos-auth password|fingerprint\n");
        return 2;
    }
    /* zadny vypis pameti, ptrace ani core dump; heslo mimo swap */
    prctl(PR_SET_DUMPABLE, 0);
    setrlimit(RLIMIT_CORE, &(struct rlimit){0, 0});
    mlock(secret, sizeof secret);
    signal(SIGPIPE, SIG_IGN);

    struct passwd *pw = getpwuid(getuid());
    if (!pw || !pw->pw_name) {
        say("result", "error 0");
        return 2;
    }
    struct pam_conv conv = {conversation, &password};
    pam_handle_t *pamh = NULL;
    int rc = pam_start(password ? "luxos-lock" : "luxos-lock-fingerprint", pw->pw_name, &conv, &pamh);
    if (rc == PAM_SUCCESS) {
        rc = pam_authenticate(pamh, 0);
        /* obnovit pristupove listky (Kerberos, AD) jako setrice obrazovky; vysledek nemeni odemceni */
        if (rc == PAM_SUCCESS)
            pam_setcred(pamh, PAM_REINITIALIZE_CRED);
        pam_end(pamh, rc);
    }
    explicit_bzero(secret, sizeof secret);
    char line[32];
    snprintf(line, sizeof line, "%s %d", rc == PAM_SUCCESS ? "ok" : rc == PAM_AUTHINFO_UNAVAIL ? "unavail" : "fail", rc);
    say("result", line);
    return rc == PAM_SUCCESS ? 0 : 1;
}
