/*
 * LuxOS - pojistka proti fork bombe (luxos-forkguard, systemova sluzba luxos-forkguard.service).
 *
 * Fork bomba (":(){ :|:& };:") nebo skript, ktery se nekontrolovane vetvi, vytvori tisice procesu za
 * sekundu. Kazdy stoji 0,25 MB (bash -c: 4000 procesu = 1,0 GB, z toho tabulky stranek 240 MB a slab
 * 165 MB, ktere nejdou odlozit do swapu) az 0,83 MB (napsana v interaktivnim lsh), namereno ve VM. Bez
 * zasahu takova bomba mimo chraneny panel Terminalu (stare okno, xfce4-terminal, spoustec, skript
 * z plochy) vycerpala RAM i zram a pocitac zamrzl tak, ze pomohl jen tvrdy restart. earlyoom (luxos-tweaks) tu nepomuze:
 * ukoncuje jeden nejvetsi proces (prohlizec, Steam), procesy bomby jsou malinke a hned se doplni.
 *
 * Tato pojistka hlida skupiny procesu (cgroup) uzivatelu v /sys/fs/cgroup/user.slice:
 *  - normalne jen 2 male soubory za sekundu (pids.current a pids.events cele user.slice) a udalost
 *    inotify, kdyz kdekoli pod user.slice nekdo narazi na limit procesu (zasah do ~0,1 s);
 *  - kdyz uzivatele maji aspon MIN procesu a zaroven nekdo narazil na limit procesu (pids.events),
 *    procesu rychle pribyva nebo dochazi pamet, projde skupiny a hleda bombu: aspon MIN procesu
 *    se stejnym jmenem (comm), ktere tvori vetsinu sve skupiny a z nichz aspon ctvrtina ma rodice
 *    stejneho jmena (proces se vetvi sam) - beznou praci (make -j, "sleep &" ve smycce, prohlizec,
 *    hry, kontejnery) to nesplni, ta ma ruzna jmena nebo malo procesu;
 *  - skupinu zmrazi (cgroup.freeze - bomba se uz nemuze dal vetvit), ukonci (SIGKILL) procesy toho
 *    jmena, jejichz rodic ma stejne jmeno nebo uz skoncil, a skupinu zase rozmrazi. Shell, ze ktereho
 *    byla bomba spustena (rodic je terminal), zustane - panel i okno funguji dal. Kdyz se ve stejne
 *    skupine bomba do 60 s obnovi (prikaz, ktery se vetvi sam ve smycce), ukonci uz vsechny procesy
 *    toho jmena;
 *  - posle signal cz.luxos.ForkGuard.Stopped (jmeno, pocet, UID) na systemovou sbernici - luxos-hub
 *    ukaze upozorneni. Procesy roota se nikdy neukoncuji.
 * Bezi s OOMScoreAdjust=-1000 a pamet ma zamcenou (mlockall), aby fungovala i pri plne pameti; bez
 * fork() a bez alokaci ve smycce. Kdyby skoncila se zmrazenou skupinou, pri dalsim startu ji rozmrazi
 * (/run/luxos-forkguard/frozen).
 *
 * Proc C a ne LSL: smycka musi bezet pri vycerpane pameti bez alokaci a bez behoveho prostredi
 * (mlockall, pevne buffery) - LSL zatim nema zaruku behu bez alokaci/GC ani mlockall.
 *
 * Prostredi pro testy: LUXOS_FORKGUARD_MIN (vychozi 500), LUXOS_FORKGUARD_ROOT (jina skupina nez
 * /sys/fs/cgroup/user.slice), LUXOS_FORKGUARD_INTERVAL_MS (vychozi 1000).
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <poll.h>
#include <sys/inotify.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <systemd/sd-bus.h>
#include <time.h>
#include <unistd.h>

#define STATE_FILE "/run/luxos-forkguard/frozen"
#define MAX_COMMS 64
#define MAX_DEPTH 10

static const char *root = "/sys/fs/cgroup/user.slice";
static long min_procs = 500;
static long interval_ms = 1000;
static char frozen_cg[PATH_MAX];   /* skupina, kterou prave drzime zmrazenou */

/* posledni zasah - pro opakovanou bombu ve stejne skupine */
static char last_cg[PATH_MAX], last_comm[16];
static double last_time;

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void sleep_ms(long ms)
{
    struct timespec ts = {ms / 1000, (ms % 1000) * 1000000L};
    while (nanosleep(&ts, &ts) < 0 && errno == EINTR) {}
}

/* cely maly soubor do buf (ukonceny nulou); delka nebo -1 */
static ssize_t read_small(const char *path, char *buf, size_t size)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buf, size - 1);
    close(fd);
    if (n < 0) return -1;
    buf[n] = 0;
    return n;
}

static int write_small(const char *path, const char *s)
{
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = write(fd, s, strlen(s));
    close(fd);
    return n == (ssize_t)strlen(s) ? 0 : -1;
}

/* cislo ze souboru; s klicem ("max" v pids.events) hodnota na radku "klic N"; "max" -> LLONG_MAX */
static long long read_num(const char *dir, const char *file, const char *key)
{
    char path[PATH_MAX], buf[512];
    snprintf(path, sizeof path, "%s/%s", dir, file);
    if (read_small(path, buf, sizeof buf) < 0) return -1;
    char *p = buf;
    if (key) {
        size_t kl = strlen(key);
        for (p = buf; p && *p; p = strchr(p, '\n') ? strchr(p, '\n') + 1 : NULL)
            if (!strncmp(p, key, kl) && p[kl] == ' ') break;
        if (!p || !*p) return -1;
        p += kl + 1;
    }
    if (!strncmp(p, "max", 3)) return LLONG_MAX;
    return strtoll(p, NULL, 10);
}

/* jmeno (comm), stav a rodic procesu z /proc/PID/stat; 0 = OK */
static int proc_stat(long pid, char comm[16], char *state, long *ppid)
{
    char path[64], buf[1024];
    snprintf(path, sizeof path, "/proc/%ld/stat", pid);
    if (read_small(path, buf, sizeof buf) < 0) return -1;
    char *l = strchr(buf, '('), *r = strrchr(buf, ')');
    if (!l || !r || r < l || r[1] != ' ') return -1;
    size_t n = r - l - 1;
    if (n > 15) n = 15;
    memcpy(comm, l + 1, n);
    comm[n] = 0;
    if (state) *state = r[2];
    if (ppid) *ppid = strtol(r + 4, NULL, 10);
    return 0;
}

static uid_t proc_uid(long pid)
{
    char path[64];
    struct stat st;
    snprintf(path, sizeof path, "/proc/%ld", pid);
    return stat(path, &st) == 0 ? st.st_uid : 0;
}

/* Prochazeni cgroup.procs po castech (pevny buffer, bez alokaci). cb vraci 0 = pokracovat. */
typedef int (*pid_cb)(long pid, void *data);
static void for_each_pid(const char *cg, pid_cb cb, void *data)
{
    char path[PATH_MAX];
    static char buf[65536];
    snprintf(path, sizeof path, "%s/cgroup.procs", cg);
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return;
    size_t keep = 0;
    for (;;) {
        ssize_t n = read(fd, buf + keep, sizeof buf - 1 - keep);
        if (n <= 0) break;
        size_t len = keep + n;
        size_t start = 0;
        for (size_t i = 0; i < len; i++) {
            if (buf[i] != '\n') continue;
            buf[i] = 0;
            long pid = strtol(buf + start, NULL, 10);
            start = i + 1;
            if (pid > 0 && cb(pid, data)) { close(fd); return; }
        }
        keep = len - start;
        memmove(buf, buf + start, keep);
    }
    close(fd);
}

/* ---------- rozpoznani bomby ve skupine ---------- */
/* n = procesy toho jmena, self = z nich ty, jejichz rodic ma stejne jmeno (znak bomby: proces se
 * vetvi sam; "sleep &" ve smycce shellu nebo procesy predane systemd po skonceni rodice ho nemaji) */
typedef struct { char comm[16]; long n, self; } CommCount;
typedef struct { CommCount c[MAX_COMMS]; int used; long total; } Census;

static int census_cb(long pid, void *data)
{
    Census *cs = data;
    char comm[16], pcomm[16];
    long ppid;
    cs->total++;
    if (proc_stat(pid, comm, NULL, &ppid)) return 0;
    int self = ppid > 1 && !proc_stat(ppid, pcomm, NULL, NULL) && !strcmp(pcomm, comm);
    for (int i = 0; i < cs->used; i++)
        if (!strcmp(cs->c[i].comm, comm)) { cs->c[i].n++; cs->c[i].self += self; return 0; }
    if (cs->used < MAX_COMMS) {
        memcpy(cs->c[cs->used].comm, comm, 16);
        cs->c[cs->used].n = 1;
        cs->c[cs->used++].self = self;
    }
    return 0;
}

/* ---------- zastaveni bomby ---------- */
typedef struct { const char *comm; int all; long killed, spared; long uid_pid; } Stop;

static int stop_cb(long pid, void *data)
{
    Stop *s = data;
    char comm[16], pcomm[16], st;
    long ppid;
    if (proc_stat(pid, comm, &st, &ppid) || strcmp(comm, s->comm) || st == 'Z' || st == 'X') return 0;
    if (proc_uid(pid) == 0) return 0;   /* procesy roota nikdy */
    int victim = s->all || ppid <= 1;
    if (!victim) {
        /* rodic se stejnym jmenem (soucast bomby), skoncil nebo je to sirotek u systemd */
        victim = proc_stat(ppid, pcomm, NULL, NULL) || !strcmp(pcomm, comm) || !strcmp(pcomm, "systemd");
    }
    if (!victim) { s->spared++; return 0; }
    if (kill((pid_t)pid, SIGKILL) == 0) {
        s->killed++;
        if (!s->uid_pid) s->uid_pid = pid;
    }
    return 0;
}

static void set_frozen(const char *cg, int on)
{
    char path[PATH_MAX];
    snprintf(path, sizeof path, "%s/cgroup.freeze", cg);
    if (on) {
        /* zaznam pro pripad, ze by sluzba skoncila drive, nez skupinu rozmrazi */
        int fd = open(STATE_FILE, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        if (fd >= 0) { ssize_t r = write(fd, cg, strlen(cg)); (void)r; close(fd); }
        snprintf(frozen_cg, sizeof frozen_cg, "%s", cg);
        write_small(path, "1");
    } else {
        write_small(path, "0");
        frozen_cg[0] = 0;
        unlink(STATE_FILE);
    }
}

static void wait_frozen(const char *cg)
{
    char path[PATH_MAX], buf[256];
    snprintf(path, sizeof path, "%s/cgroup.events", cg);
    for (int i = 0; i < 500; i++) {   /* nejvys ~1 s */
        if (read_small(path, buf, sizeof buf) > 0 && strstr(buf, "frozen 1")) return;
        sleep_ms(2);
    }
}

static void notify(const char *comm, long count, uid_t uid)
{
    sd_bus *bus = NULL;
    if (sd_bus_open_system(&bus) < 0) return;
    sd_bus_emit_signal(bus, "/cz/luxos/ForkGuard", "cz.luxos.ForkGuard", "Stopped", "suu", comm,
                       (uint32_t)(count > 0xffffffffL ? 0xffffffffL : count), (uint32_t)uid);
    sd_bus_flush(bus);
    sd_bus_flush_close_unref(bus);
}

static void stop_bomb(const char *cg, const char *comm, long count)
{
    double t = now_s();
    Stop s = {comm, !strcmp(cg, last_cg) && !strcmp(comm, last_comm) && t - last_time < 60, 0, 0, 0};
    set_frozen(cg, 1);
    wait_frozen(cg);
    /* zmrazena skupina se uz nevetvi; nekolik pruchodu pro procesy, ktere pribyly behem zmrazovani */
    for (int pass = 0; pass < 6; pass++) {
        long before = s.killed;
        for_each_pid(cg, stop_cb, &s);
        if (s.killed == before) break;
    }
    set_frozen(cg, 0);
    uid_t uid = s.uid_pid ? proc_uid(s.uid_pid) : 0;
    if (!uid) {   /* proces uz skoncil - UID z cesty .../user-UID.slice/... */
        const char *u = strstr(cg, "/user-");
        if (u) uid = (uid_t)strtoul(u + 6, NULL, 10);
    }
    fprintf(stderr, "luxos-forkguard: stopped %ld processes \"%s\" (%ld found%s, %ld spared) in %s\n",
            s.killed, comm, count, s.all ? ", repeated - all of them" : "", s.spared, cg + strlen("/sys/fs/cgroup"));
    if (s.killed) {   /* opakovani pocita jen skutecny zasah */
        snprintf(last_cg, sizeof last_cg, "%s", cg);
        memcpy(last_comm, comm, 16);
        last_time = now_s();
    }
    if (s.killed) notify(comm, s.killed, uid);
}

/* projde skupinu a jeji podskupiny s aspon min_procs procesy; 1 = zasah */
static int scan(const char *cg, int depth)
{
    long long cur = read_num(cg, "pids.current", NULL);
    if (cur < min_procs) return 0;
    Census cs = {.used = 0, .total = 0};
    for_each_pid(cg, census_cb, &cs);
    int best = -1;
    for (int i = 0; i < cs.used; i++)
        if (best < 0 || cs.c[i].n > cs.c[best].n) best = i;
    /* bomba: aspon min_procs procesu stejneho jmena, vetsina skupiny a aspon ctvrtina z nich ma rodice
     * stejneho jmena (vetvi se sama) */
    if (best >= 0 && cs.c[best].n >= min_procs && cs.c[best].n * 2 >= cs.total && cs.c[best].self * 4 >= min_procs) {
        char comm[16];
        memcpy(comm, cs.c[best].comm, 16);
        stop_bomb(cg, comm, cs.c[best].n);
        return 1;
    }
    if (depth >= MAX_DEPTH) return 0;
    DIR *d = opendir(cg);
    if (!d) return 0;
    int hit = 0;
    struct dirent *e;
    char sub[PATH_MAX];
    while ((e = readdir(d))) {
        if (e->d_type != DT_DIR || e->d_name[0] == '.') continue;
        if (snprintf(sub, sizeof sub, "%s/%s", cg, e->d_name) >= (int)sizeof sub) continue;
        hit |= scan(sub, depth + 1);
    }
    closedir(d);
    return hit;
}

static int memory_low(void)
{
    char buf[4096];
    if (read_small("/proc/meminfo", buf, sizeof buf) < 0) return 0;
    char *t = strstr(buf, "MemTotal:"), *a = strstr(buf, "MemAvailable:");
    if (!t || !a) return 0;
    long total = strtol(t + 9, NULL, 10), avail = strtol(a + 13, NULL, 10);
    return total > 0 && avail * 10 < total;
}

static void on_term(int sig)
{
    /* nikdy neskoncit se zmrazenou skupinou (jen async-signal-safe volani) */
    if (frozen_cg[0]) {
        char path[PATH_MAX];
        size_t n = strlen(frozen_cg);
        if (n + 15 < sizeof path) {
            memcpy(path, frozen_cg, n);
            memcpy(path + n, "/cgroup.freeze", 15);
            int fd = open(path, O_WRONLY);
            if (fd >= 0) { ssize_t r = write(fd, "0", 1); (void)r; close(fd); }
        }
        unlink(STATE_FILE);
    }
    _exit(sig == SIGTERM || sig == SIGINT ? 0 : 1);
}

int main(int argc, char **argv)
{
    const char *v;
    if ((v = getenv("LUXOS_FORKGUARD_ROOT")) && *v) root = v;
    if ((v = getenv("LUXOS_FORKGUARD_MIN")) && atol(v) > 0) min_procs = atol(v);
    if ((v = getenv("LUXOS_FORKGUARD_INTERVAL_MS")) && atol(v) > 0) interval_ms = atol(v);
    if (argc > 1 && (!strcmp(argv[1], "-h") || !strcmp(argv[1], "--help"))) {
        printf("luxos-forkguard - stops fork bombs in user sessions (system service luxos-forkguard.service)\n");
        return 0;
    }
    struct sigaction sa = {0};
    sa.sa_handler = on_term;
    int sigs[] = {SIGTERM, SIGINT, SIGHUP, SIGSEGV, SIGBUS, SIGABRT, SIGFPE};
    for (size_t i = 0; i < sizeof sigs / sizeof *sigs; i++) sigaction(sigs[i], &sa, NULL);

    /* skupina zmrazena predchozim behem, ktery nestihl rozmrazit */
    char prev[PATH_MAX];
    if (read_small(STATE_FILE, prev, sizeof prev) > 0 && !strncmp(prev, "/sys/fs/cgroup/", 15)) {
        set_frozen(prev, 0);
        fprintf(stderr, "luxos-forkguard: thawed %s left frozen by a previous run\n", prev);
    }
    unlink(STATE_FILE);
    if (mlockall(MCL_CURRENT | MCL_FUTURE) < 0) fprintf(stderr, "luxos-forkguard: mlockall: %s\n", strerror(errno));

    /* Narazeni na limit procesu kdekoli pod user.slice (panel Terminalu, relace, uzivatel) zmeni
     * pids.events korenove skupiny (hierarchicky) a jadro o tom posle udalost inotify - zasah pak
     * hned, ne az za interval. Rychly rust bez limitu zachyti kontrola kazdou sekundu. */
    char evpath[PATH_MAX];
    snprintf(evpath, sizeof evpath, "%s/pids.events", root);
    int ino = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    if (ino >= 0 && inotify_add_watch(ino, evpath, IN_MODIFY) < 0) { close(ino); ino = -1; }
    long long prev_cur = 0, prev_ev = read_num(root, "pids.events", "max");
    double last_full = 0;
    for (;;) {
        long long cur = read_num(root, "pids.current", NULL);
        long long ev = read_num(root, "pids.events", "max");
        int suspicious = 0;
        if (cur >= min_procs) {
            double t = now_s();
            suspicious = (ev > prev_ev) || (cur - prev_cur >= 200) || memory_low() ||
                         (cur >= 4 * min_procs && t - last_full >= 5);
            if (suspicious) last_full = t;
        }
        prev_cur = cur;
        prev_ev = ev;
        int hit = suspicious ? scan(root, 0) : 0;
        /* po zasahu a pri podezreni hned znovu (bomba muze byt ve vic skupinach), jinak klidovy interval
         * nebo udalost inotify (limit procesu) */
        static char evbuf[4096];
        if (hit || suspicious || ino < 0) {
            /* pevna pauza: udalosti limitu od beznych programu nesmi rozjet prochazeni stokrat za sekundu */
            sleep_ms(hit ? 100 : suspicious ? 250 : interval_ms);
            if (ino >= 0)
                while (read(ino, evbuf, sizeof evbuf) > 0) {}
        } else {
            struct pollfd pfd = {ino, POLLIN, 0};
            if (poll(&pfd, 1, (int)interval_ms) > 0)
                while (read(ino, evbuf, sizeof evbuf) > 0) {}
        }
    }
}
