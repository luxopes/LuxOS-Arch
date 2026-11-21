/*
 * LuxOS - LD_PRELOAD pro snimky X11 zamku a prihlaseni (tests/lock/x11_goldens.py): pevne hodiny,
 * rizeny monotonni cas a napodobeny libpam. Zamek se nikdy neoveruje skutecnym heslem.
 *
 *   LUXOS_FAKE_EPOCH=sekundy     time(), gettimeofday() a CLOCK_REALTIME stoji na tomto okamziku
 *   LUXOS_FAKE_MONO=soubor       CLOCK_MONOTONIC = monotonni cas pri prvnim dotazu + mikrosekundy ze souboru
 *                                (test jimi posouva animace po presnych krocich; bez souboru skutecny cas)
 *   LUXOS_FAKE_PAM_INFO=text     PAM_TEXT_INFO pred vyzvou k heslu (otisk prstu); vyzva az po
 *                                LUXOS_FAKE_PAM_INFO_WAIT sekundach (jako ctecka cekajici na prst)
 *   LUXOS_FAKE_PAM_ERROR=text    PAM_ERROR_MSG po spatnem hesle (pam_faillock)
 * Spravne heslo je "luxos".
 *
 *     gcc -shared -fPIC -O2 -o x11-fake.so x11-fake.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <security/pam_appl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static int (*real_clock_gettime) (clockid_t, struct timespec *);
static long long mono_base = -1;

static long long
epoch (void) {
    const char *e = getenv ("LUXOS_FAKE_EPOCH");
    return e && *e ? atoll (e) : -1;
}

static long long
mono_offset (void) {
    const char *path = getenv ("LUXOS_FAKE_MONO");
    char buf[32];
    int fd, n;
    if (!path || !*path || (fd = open (path, O_RDONLY | O_CLOEXEC)) < 0)
        return -1;
    n = read (fd, buf, sizeof buf - 1);
    close (fd);
    if (n <= 0)
        return -1;
    buf[n] = '\0';
    return atoll (buf);
}

int
clock_gettime (clockid_t id, struct timespec *ts) {
    long long e, off;
    if (!real_clock_gettime)
        real_clock_gettime = dlsym (RTLD_NEXT, "clock_gettime");
    if ((id == CLOCK_REALTIME || id == CLOCK_REALTIME_COARSE) && (e = epoch ()) >= 0) {
        ts->tv_sec = e;
        ts->tv_nsec = 0;
        return 0;
    }
    if (id == CLOCK_MONOTONIC || id == CLOCK_MONOTONIC_COARSE || id == CLOCK_MONOTONIC_RAW || id == CLOCK_BOOTTIME) {
        struct timespec r;
        int rc = real_clock_gettime (CLOCK_MONOTONIC, &r);
        long long now = (long long) r.tv_sec * 1000000 + r.tv_nsec / 1000;
        if (rc == 0 && (off = mono_offset ()) >= 0) {
            if (mono_base < 0)
                mono_base = now;
            now = mono_base + off;
            ts->tv_sec = now / 1000000;
            ts->tv_nsec = (now % 1000000) * 1000;
            return 0;
        }
    }
    return real_clock_gettime (id, ts);
}

time_t
time (time_t *t) {
    struct timespec ts;
    clock_gettime (CLOCK_REALTIME, &ts);
    if (t)
        *t = ts.tv_sec;
    return ts.tv_sec;
}

int
gettimeofday (struct timeval *tv, void *tz) {
    struct timespec ts;
    clock_gettime (CLOCK_REALTIME, &ts);
    if (tv) {
        tv->tv_sec = ts.tv_sec;
        tv->tv_usec = ts.tv_nsec / 1000;
    }
    return 0;
}

/* ---- napodobeny libpam (jako packages/xfce4-screensaver/tests/fake-pam.c) ---- */
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

static void
say (pam_handle_t *pamh, int style, const char *text) {
    struct pam_message m = { style, text };
    const struct pam_message *mp = &m;
    struct pam_response *r = NULL;
    pamh->conv.conv (1, &mp, &r, pamh->conv.appdata_ptr);
    if (r) {
        free (r->resp);
        free (r);
    }
}

int
pam_authenticate (pam_handle_t *pamh, int flags) {
    struct pam_message m = { PAM_PROMPT_ECHO_OFF, "Password: " };
    const struct pam_message *mp = &m;
    struct pam_response *r = NULL;
    const char *info = getenv ("LUXOS_FAKE_PAM_INFO"), *err = getenv ("LUXOS_FAKE_PAM_ERROR");
    int ok;
    if (info && *info) {
        say (pamh, PAM_TEXT_INFO, info);
        if (getenv ("LUXOS_FAKE_PAM_INFO_WAIT"))
            sleep (atoi (getenv ("LUXOS_FAKE_PAM_INFO_WAIT")));
    }
    if (pamh->conv.conv (1, &mp, &r, pamh->conv.appdata_ptr) != PAM_SUCCESS || r == NULL)
        return PAM_CONV_ERR;
    ok = r->resp != NULL && strcmp (r->resp, "luxos") == 0;
    free (r->resp);
    free (r);
    if (!ok && err && *err)
        say (pamh, PAM_ERROR_MSG, err);
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
