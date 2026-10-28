/* Nepretrzite snimani obrazovky a porovnani s referencnim snimkem (mimo vynechany obdelnik).
 *   diffcap OUTDIR SECONDS REF_MS X0 Y0 X1 Y1
 * V case REF_MS ulozi referencni snimek (napr. setric pred probuzenim), pak u kazdeho snimku zapise do
 * OUTDIR/diffs.log "t_ms podil" - podil bodu mimo obdelnik X0,Y0-X1,Y1 (hodiny), ktere se od reference
 * lisi o vic nez 40 (soucet kanalu). Ulozi reference.ppm a prvni 4 snimky s rozdilem >= 5 % po
 * referenci (diff-<t>.ppm) a kazdou vterinu sample-<t>.ppm. */
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/XShm.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/shm.h>
#include <time.h>

static long now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000L + t.tv_nsec / 1000000L;
}

static void save_ppm(const char *path, const unsigned char *data, int bpl, int w, int h)
{
    FILE *f = fopen(path, "wb");
    if (!f)
        return;
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int y = 0; y < h; y++) {
        const unsigned char *r = data + (size_t)y * bpl;
        for (int x = 0; x < w; x++) {
            fputc(r[x * 4 + 2], f);
            fputc(r[x * 4 + 1], f);
            fputc(r[x * 4], f);
        }
    }
    fclose(f);
}

int main(int argc, char **argv)
{
    if (argc < 8)
        return 2;
    const char *out = argv[1];
    double secs = atof(argv[2]);
    long ref_ms = atol(argv[3]);
    int bx0 = atoi(argv[4]), by0 = atoi(argv[5]), bx1 = atoi(argv[6]), by1 = atoi(argv[7]);
    Display *d = XOpenDisplay(NULL);
    if (!d)
        return 1;
    int s = DefaultScreen(d), w = DisplayWidth(d, s), h = DisplayHeight(d, s);
    XShmSegmentInfo si;
    XImage *im = XShmCreateImage(d, DefaultVisual(d, s), (unsigned)DefaultDepth(d, s), ZPixmap, NULL, &si,
                                 (unsigned)w, (unsigned)h);
    size_t size = (size_t)im->bytes_per_line * (size_t)im->height;
    si.shmid = shmget(IPC_PRIVATE, size, IPC_CREAT | 0600);
    si.shmaddr = im->data = shmat(si.shmid, 0, 0);
    si.readOnly = False;
    XShmAttach(d, &si);
    XSync(d, False);
    shmctl(si.shmid, IPC_RMID, 0);
    unsigned char *ref = NULL;
    char p[4096];
    snprintf(p, sizeof p, "%s/diffs.log", out);
    FILE *log = fopen(p, "w");
    if (!log)
        return 1;
    struct timespec rt;
    clock_gettime(CLOCK_REALTIME, &rt);
    fprintf(log, "# start %ld.%09ld\n", (long)rt.tv_sec, rt.tv_nsec);
    long t0 = now_ms();
    int saved = 0;
    while (now_ms() - t0 < secs * 1000) {
        XShmGetImage(d, RootWindow(d, s), im, 0, 0, AllPlanes);
        long t = now_ms() - t0;
        if (!ref) {
            if (t >= ref_ms) {
                ref = malloc(size);
                memcpy(ref, im->data, size);
                snprintf(p, sizeof p, "%s/reference.ppm", out);
                save_ppm(p, ref, im->bytes_per_line, w, h);
            }
            continue;
        }
        long diff = 0, tot = 0;
        for (int y = 0; y < h; y += 3) {
            const unsigned char *a = (unsigned char *)im->data + (size_t)y * im->bytes_per_line;
            const unsigned char *b = ref + (size_t)y * im->bytes_per_line;
            for (int x = 0; x < w; x += 3) {
                if (x >= bx0 && x < bx1 && y >= by0 && y < by1)
                    continue;
                int dd = abs(a[x * 4] - b[x * 4]) + abs(a[x * 4 + 1] - b[x * 4 + 1]) + abs(a[x * 4 + 2] - b[x * 4 + 2]);
                tot++;
                diff += dd > 40;
            }
        }
        double fr = tot ? (double)diff / tot : 0;
        fprintf(log, "%ld %.4f\n", t, fr);
        static long sample_at = 0;
        if (t >= sample_at) {           /* kazdou vterinu snimek pro kontrolu ocima */
            snprintf(p, sizeof p, "%s/sample-%05ld.ppm", out, t);
            save_ppm(p, (unsigned char *)im->data, im->bytes_per_line, w, h);
            sample_at = (t / 1000 + 1) * 1000;
        }
        if (fr >= 0.05 && saved < 4) {
            snprintf(p, sizeof p, "%s/diff-%05ld.ppm", out, t);
            save_ppm(p, (unsigned char *)im->data, im->bytes_per_line, w, h);
            saved++;
        }
    }
    fclose(log);
    return 0;
}
