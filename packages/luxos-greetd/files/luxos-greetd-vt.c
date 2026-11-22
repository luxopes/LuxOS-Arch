/*
 * LuxOS - greetd (LD_PRELOAD v luxos-greetd.service): VT bez textove konzole mezi splashem a prihlasenim a mezi
 * prihlasenim a relaci.
 *
 * greetd pri startu a pred kazdou relaci nastavi VT na KD_TEXT. Prechod z grafickeho do textoveho rezimu jadro
 * bere jako navrat textove konzole a jeji framebuffer vynuti na displej i pres DRM mastera (vyjimka pro Xorg
 * v drm_fb_helper_set_par). Splash tak zmizel pod cernou konzoli driv, nez luxwm --hold mohl prevzit jeho obraz
 * (1,6-2,5 s cerne mezi splashem a prihlasenim). Dokud bezi Plymouth, VT zustava v jeho grafickem rezimu; logind
 * ho pri TakeControl nastavi stejne a po konci relace vrati textovy.
 *
 * Prihlaseni: luxos-greeter ulozi posledni snimek (FRAME) a luxwm --greeter pred koncem prepne na HANDOFF_VT,
 * ktery tu pri startu greetd dostane graficky rezim - prepnuti obraz nemeni (fbcon na grafickem VT nekresli
 * a rezim framebufferu je stejny). Z VT v grafickem rezimu s VT_AUTO jadro neprepne (ceka na aplikaci, ktera
 * ho kresli), proto VT_PROCESS: hlavni proces greetd prepnuti potvrzuje signalem. Jadro pri prepnuti vrati na
 * displej framebuffer textove konzole (fbdev emulace DRM) - po prichodu na HANDOFF_VT do nej tu jde snimek
 * greeteru (zapis do /dev/fb0 dokud ma displej DRM master, emulace na displej neprenese). Konec greeteru pak logind vrati VT 1 do textoveho rezimu jen v pameti (neni
 * zobrazeny) a pred relaci ho tu greetd misto KD_TEXT dostane graficky: navrat na VT 1 nic nenakresli a luxwm
 * relace prevezme rozsviceny vystup se snimkem greeteru (luxwm --intro). Jinak se greetd chova beze zmeny.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/kd.h>
#include <linux/vt.h>
#include <pwd.h>
#include <signal.h>
#include <stdarg.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* testy (test_luxos_greetd_vt.py) prekladaji s vlastni cestou snimku a uzivatelem */
#ifndef FRAME
#define FRAME "/run/luxos-greeter/login-frame"
#endif
#ifndef GREETER_USER
#define GREETER_USER "greeter"
#endif
#define FRAME_MAX_AGE_S 20
#define HANDOFF_TTY "/dev/tty12"	/* luxwm.lsl HANDOFF_VT */

static int (*real_ioctl)(int, unsigned long, ...);
static int handoff_fd = -1;
static uid_t greeter_uid = (uid_t)-1;

/* Snimek zapisuje neprivilegovany greeter, cte ho root: jen obycejny soubor uzivatele greeter (ne odkaz, ne FIFO),
 * cerstvy a presne tak velky, jak rika hlavicka. Vraci otevreny popisovac nebo -1; w, h, len z hlavicky. Bezi
 * i v obsluze signalu: jen open/fstat/read/close a cas. */
static int
frame_open(unsigned *w, unsigned *h, unsigned *len)
{
	if (greeter_uid == (uid_t)-1) {
		return -1;
	}
	int fd = open(FRAME, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
	struct stat st;
	char head[64];
	struct timespec now;
	if (fd < 0) {
		return -1;
	}
	clock_gettime(CLOCK_REALTIME, &now);
	ssize_t n = fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_uid == greeter_uid
		&& now.tv_sec - st.st_mtime <= FRAME_MAX_AGE_S && now.tv_sec - st.st_mtime >= -5
		? read(fd, head, sizeof(head) - 1) : -1;
	*w = *h = *len = 0;
	if (n > 10 && !memcmp(head, "LUXFRAME1 ", 10)) {
		head[n] = 0;
		char *p = head + 10;
		while (*p >= '0' && *p <= '9' && *w < 100000) *w = *w * 10 + (unsigned)(*p++ - '0');
		if (*p == ' ') p++;
		while (*p >= '0' && *p <= '9' && *h < 100000) *h = *h * 10 + (unsigned)(*p++ - '0');
		*len = *p == '\n' ? (unsigned)(p + 1 - head) : 0;
	}
	if (!*len || !*w || !*h || st.st_size != (off_t)*len + (off_t)*w * *h * 4) {
		close(fd);
		return -1;
	}
	return fd;
}

static int
handoff(void)
{
	unsigned w, h, len;
	int fd = frame_open(&w, &h, &len);
	if (fd < 0) {
		return 0;
	}
	close(fd);
	return 1;
}

#ifdef GREETD_VT_TEST
int luxos_greetd_vt_frame_ok(void) { return handoff(); }
void luxos_greetd_vt_init(void) { struct passwd *pw = getpwnam(GREETER_USER); greeter_uid = pw ? pw->pw_uid : (uid_t)-1; }
#endif

/* "LUXFRAME1 <w> <h>\n" + BGRx (luxos-greeter) do framebufferu konzole, jen 32 bitu XRGB stejne velikosti. Bezi
 * v obsluze signalu: jen open/read/pwrite/ioctl a buffer na zasobniku. */
static void
show_frame(void)
{
	/* velke kusy: co nejdriv cely obraz (displej uz framebuffer ukazuje) */
	static char chunk[1 << 20];
	unsigned w, h, len;
	int in = frame_open(&w, &h, &len);
	int out = in >= 0 ? open("/dev/fb0", O_WRONLY | O_CLOEXEC) : -1;
	struct fb_var_screeninfo var;
	struct fb_fix_screeninfo fix;
	if (out < 0 || real_ioctl(out, FBIOGET_VSCREENINFO, &var) != 0 || real_ioctl(out, FBIOGET_FSCREENINFO, &fix) != 0) {
		len = 0;
	}
	if (len && w == var.xres && h == var.yres && var.bits_per_pixel == 32 && var.red.offset == 16
			&& w * 4 <= sizeof(chunk) && fix.line_length >= w * 4) {
		/* radky po celych kusech; framebuffer s vetsi roztec radku po radcich */
		unsigned rows = fix.line_length == w * 4 ? sizeof(chunk) / (w * 4) : 1;
		for (unsigned y = 0; y < h; y += rows) {
			unsigned n = y + rows > h ? h - y : rows;
			size_t size = (size_t)n * w * 4;
			if (pread(in, chunk, size, len + (off_t)y * w * 4) != (ssize_t)size
					|| pwrite(out, chunk, size, (off_t)y * fix.line_length) != (ssize_t)size) {
				break;
			}
		}
	}
	if (in >= 0) close(in);
	if (out >= 0) close(out);
}

/* Jadro chce potvrzeni odchodu z VT a prichodu na nej */
static void
vt_signal(int sig)
{
	int saved = errno;
	if (sig == SIGRTMAX - 1) {
		real_ioctl(handoff_fd, VT_RELDISP, 1);
	} else {
		if (handoff()) {
			show_frame();
		}
		real_ioctl(handoff_fd, VT_RELDISP, VT_ACKACQ);
	}
	errno = saved;
}

/* Jen hlavni proces greetd: LD_PRELOAD maji i pracovnici (--session-worker) a ExecStartPre/Post jednotky
 * (plymouth, luxos-greetd-splash) - VT_PROCESS by si vzal proces, ktery hned skonci, a jadro by pak z VT
 * neprepnulo */
static int
main_process(void)
{
	char cmd[256] = "";
	int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
	ssize_t n = fd >= 0 ? read(fd, cmd, sizeof(cmd) - 1) : -1;
	if (fd >= 0) {
		close(fd);
	}
	if (n <= 0 || strcmp(program_invocation_short_name, "greetd")) {
		return 0;
	}
	for (ssize_t i = 0; i < n; i += strlen(cmd + i) + 1) {
		if (!strcmp(cmd + i, "--session-worker")) {
			return 0;
		}
	}
	return 1;
}

/* Prazdny VT pro predani obrazovky: graficky rezim a VT_PROCESS, popisovac zustava otevreny po celou dobu greetd */
__attribute__((constructor)) static void
prepare_handoff_vt(void)
{
	real_ioctl = (int (*)(int, unsigned long, ...))dlsym(RTLD_NEXT, "ioctl");
	if (geteuid() != 0) {
		return;
	}
	/* jednou tady: getpwnam neni pro obsluhu signalu; bez uzivatele greeter zadne predani */
	struct passwd *pw = getpwnam(GREETER_USER);
	greeter_uid = pw ? pw->pw_uid : (uid_t)-1;
	if (!main_process()) {
		return;
	}
	handoff_fd = open(HANDOFF_TTY, O_RDWR | O_NOCTTY | O_CLOEXEC);
	if (handoff_fd < 0) {
		return;
	}
	struct sigaction sa = { .sa_handler = vt_signal, .sa_flags = SA_RESTART };
	sigemptyset(&sa.sa_mask);
	sigaction(SIGRTMAX - 1, &sa, NULL);
	sigaction(SIGRTMAX - 2, &sa, NULL);
	struct vt_mode vm = { .mode = VT_PROCESS, .relsig = SIGRTMAX - 1, .acqsig = SIGRTMAX - 2 };
	if (real_ioctl(handoff_fd, VT_SETMODE, &vm) == 0) {
		real_ioctl(handoff_fd, KDSETMODE, KD_GRAPHICS);
	} else {
		close(handoff_fd);
		handoff_fd = -1;
	}
}

int
ioctl(int fd, unsigned long request, ...)
{
	va_list ap;
	va_start(ap, request);
	void *arg = va_arg(ap, void *);
	va_end(ap);
	if (!real_ioctl) {
		real_ioctl = (int (*)(int, unsigned long, ...))dlsym(RTLD_NEXT, "ioctl");
	}
	if (request == KDSETMODE && (unsigned long)arg == KD_TEXT) {
		if (access("/run/plymouth/pid", F_OK) == 0) {
			return 0;
		}
		if (handoff()) {
			return real_ioctl(fd, request, KD_GRAPHICS);
		}
	}
	return real_ioctl(fd, request, arg);
}
