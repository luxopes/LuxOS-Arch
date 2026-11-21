/* wlt-qmp - QMP klient pro VM matici
 *   wlt-qmp SOCK exec JSON                     jeden prikaz, vypise odpoved
 *   wlt-qmp SOCK capture DIR FPS SEC           snimky screendump DIR/f0000.ppm.. a DIR/times.txt
 *   wlt-qmp SOCK input WxH [PRIKAZ..]          scenar (scen.c) pres input-send-event (usb-tablet)
 * Kazdy proces potrebuje vlastni QMP soket (QEMU obsluhuje na soketu jen jednoho klienta). */
#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include "scen.h"

static FILE *qin, *qout;
static int scr_w, scr_h;

/* odpoved = prvni radek s "return" nebo "error" (udalosti se preskakuji) */
static int qmp(const char *json, char *reply, size_t len)
{
	static char line[65536];
	fprintf(qout, "%s\n", json);
	fflush(qout);
	while (fgets(line, sizeof line, qin)) {
		if (strstr(line, "\"event\""))
			continue;
		if (reply)
			snprintf(reply, len, "%s", line);
		return strstr(line, "\"error\"") ? -1 : 0;
	}
	fprintf(stderr, "qmp: connection closed\n");
	exit(1);
}

static void qmp_connect(const char *path)
{
	struct sockaddr_un sa = { .sun_family = AF_UNIX };
	snprintf(sa.sun_path, sizeof sa.sun_path, "%s", path);
	int fd = socket(AF_UNIX, SOCK_STREAM, 0);
	if (fd < 0 || connect(fd, (struct sockaddr *)&sa, sizeof sa) < 0) {
		perror(path);
		exit(1);
	}
	qin = fdopen(fd, "r");
	qout = fdopen(dup(fd), "w");
	char greet[4096];
	if (!fgets(greet, sizeof greet, qin) || !strstr(greet, "QMP")) {
		fprintf(stderr, "qmp: no greeting\n");
		exit(1);
	}
	char r[4096];
	if (qmp("{\"execute\":\"qmp_capabilities\"}", r, sizeof r) < 0) {
		fprintf(stderr, "qmp: %s", r);
		exit(1);
	}
}

static void events(const char *ev)
{
	char buf[1024], r[4096];
	snprintf(buf, sizeof buf, "{\"execute\":\"input-send-event\",\"arguments\":{\"events\":[%s]}}", ev);
	if (qmp(buf, r, sizeof r) < 0)
		fprintf(stderr, "qmp: %s", r);
}

static void q_move(void *ctx, double x, double y)
{
	/* usb-tablet: absolutni osa 0..32767 pres celou obrazovku */
	char ev[256];
	int ax = (int)(x * 32767 / (scr_w - 1)), ay = (int)(y * 32767 / (scr_h - 1));
	ax = ax < 0 ? 0 : ax > 32767 ? 32767 : ax;
	ay = ay < 0 ? 0 : ay > 32767 ? 32767 : ay;
	snprintf(ev, sizeof ev, "{\"type\":\"abs\",\"data\":{\"axis\":\"x\",\"value\":%d}},"
		"{\"type\":\"abs\",\"data\":{\"axis\":\"y\",\"value\":%d}}", ax, ay);
	events(ev);
}

static void q_button(void *ctx, int btn, int down)
{
	static const char *names[] = { "left", "right", "middle" };
	char ev[128];
	snprintf(ev, sizeof ev, "{\"type\":\"btn\",\"data\":{\"down\":%s,\"button\":\"%s\"}}",
		down ? "true" : "false", names[btn]);
	events(ev);
}

static void q_scroll(void *ctx, int steps)
{
	const char *name = steps > 0 ? "wheel-down" : "wheel-up";
	char ev[128];
	for (int down = 1; down >= 0; down--) {
		snprintf(ev, sizeof ev, "{\"type\":\"btn\",\"data\":{\"down\":%s,\"button\":\"%s\"}}",
			down ? "true" : "false", name);
		events(ev);
	}
}

/* jmena xkb -> qcode QEMU; pismena, cislice a f1.. jsou stejna */
static const char *qcode(const char *name)
{
	static const char *map[][2] = {
		{ "ctrl", "ctrl" }, { "control_l", "ctrl" }, { "alt", "alt" }, { "alt_l", "alt" },
		{ "shift", "shift" }, { "shift_l", "shift" }, { "super", "meta_l" }, { "super_l", "meta_l" },
		{ "logo", "meta_l" }, { "escape", "esc" }, { "esc", "esc" }, { "return", "ret" },
		{ "enter", "ret" }, { "ret", "ret" }, { "space", "spc" }, { "spc", "spc" }, { "tab", "tab" },
		{ "backspace", "backspace" }, { "delete", "delete" }, { "up", "up" }, { "down", "down" },
		{ "left", "left" }, { "right", "right" }, { "home", "home" }, { "end", "end" },
		{ "minus", "minus" }, { "period", "dot" }, { "comma", "comma" }, { "slash", "slash" },
	};
	static char low[32];
	size_t i;
	for (i = 0; name[i] && i < sizeof low - 1; i++)
		low[i] = tolower((unsigned char)name[i]);
	low[i] = 0;
	for (i = 0; i < sizeof map / sizeof map[0]; i++)
		if (!strcmp(low, map[i][0]))
			return map[i][1];
	if ((strlen(low) == 1 && isalnum((unsigned char)low[0])) || (low[0] == 'f' && isdigit((unsigned char)low[1])))
		return low;
	return NULL;
}

static int q_key(void *ctx, const char *name, int down)
{
	const char *q = qcode(name);
	if (!q) {
		fprintf(stderr, "unknown key: %s\n", name);
		return -1;
	}
	char ev[160];
	snprintf(ev, sizeof ev, "{\"type\":\"key\",\"data\":{\"down\":%s,\"key\":{\"type\":\"qcode\",\"data\":\"%s\"}}}",
		down ? "true" : "false", q);
	events(ev);
	return 0;
}

static int q_text(void *ctx, const char *s)
{
	for (; *s; s++) {
		char k[2] = { (char)tolower((unsigned char)*s), 0 };
		int up = isupper((unsigned char)*s);
		const char *name = *s == ' ' ? "space" : *s == '.' ? "period" : *s == '-' ? "minus" : k;
		if (up)
			q_key(ctx, "shift", 1);
		if (q_key(ctx, name, 1) < 0)
			return -1;
		q_key(ctx, name, 0);
		if (up)
			q_key(ctx, "shift", 0);
		scen_sleep(0.02);
	}
	return 0;
}

static void q_flush(void *ctx) {}

static const struct scen_ops ops = { q_move, q_button, q_key, q_text, q_flush, q_scroll };

static int capture(const char *dir, double fps, double sec)
{
	char path[4096], cmd[4200], r[4096];
	mkdir(dir, 0755);
	snprintf(path, sizeof path, "%s/times.txt", dir);
	FILE *times = fopen(path, "w");
	if (!times) {
		perror(path);
		return 1;
	}
	int n = (int)(fps * sec), got = 0, late = 0;
	double t0 = scen_now();
	for (int i = 0; i < n; i++) {
		double target = t0 + i / fps, now = scen_now();
		if (now > target + 1 / fps) {
			/* screendump nestiha - snimek vynechat, at casova osa sedi */
			late++;
			continue;
		}
		scen_sleep(target - now);
		snprintf(path, sizeof path, "%s/f%04d.ppm", dir, got);
		snprintf(cmd, sizeof cmd, "{\"execute\":\"screendump\",\"arguments\":{\"filename\":\"%s\"}}", path);
		double ts = scen_now();
		if (qmp(cmd, r, sizeof r) < 0) {
			fprintf(stderr, "screendump: %s", r);
			return 1;
		}
		fprintf(times, "f%04d.ppm %.4f %.4f\n", got, ts - t0, scen_now() - ts);
		got++;
	}
	fclose(times);
	double el = scen_now() - t0;
	printf("frames=%d skipped=%d seconds=%.2f fps=%.1f\n", got, late, el, got / el);
	return 0;
}

int main(int argc, char **argv)
{
	if (argc < 3) {
		fprintf(stderr, "usage: wlt-qmp SOCK exec JSON | capture DIR FPS SEC | input WxH [CMD..]\n");
		return 2;
	}
	qmp_connect(argv[1]);
	if (!strcmp(argv[2], "exec") && argc == 4) {
		char r[65536];
		int rc = qmp(argv[3], r, sizeof r);
		fputs(r, stdout);
		return rc < 0;
	}
	if (!strcmp(argv[2], "capture") && argc == 6)
		return capture(argv[3], atof(argv[4]), atof(argv[5]));
	if (!strcmp(argv[2], "input") && argc >= 4 && sscanf(argv[3], "%dx%d", &scr_w, &scr_h) == 2)
		return scen_run(&ops, NULL, argc - 4, argv + 4) < 0;
	fprintf(stderr, "bad arguments\n");
	return 2;
}
