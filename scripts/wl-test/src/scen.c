/* Prikazy scenare:
 *   move X Y | down [left|right|middle] | up [..] | click [..]
 *   drag X1 Y1 X2 Y2 [MS] [BTN] | key NAME[+NAME..] | keydown NAME | keyup NAME | type TEXT | sleep SEC
 *   echo TEXT (po odeslani predchozich prikazu vypise TEXT: synchronizace s trvale bezicim wlt-input)
 * Souradnice jsou pixely celeho rozvrzeni vystupu. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "scen.h"

double scen_now(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

void scen_sleep(double sec)
{
	if (sec <= 0)
		return;
	struct timespec ts = { (time_t)sec, (long)((sec - (time_t)sec) * 1e9) };
	nanosleep(&ts, NULL);
}

static int parse_btn(const char *s)
{
	if (!s || !strcmp(s, "left"))
		return BTN_L;
	if (!strcmp(s, "right"))
		return BTN_R;
	if (!strcmp(s, "middle"))
		return BTN_M;
	return -1;
}

static int combo(const struct scen_ops *ops, void *ctx, char *spec)
{
	char *names[8];
	int n = 0;
	for (char *t = strtok(spec, "+"); t && n < 8; t = strtok(NULL, "+"))
		names[n++] = t;
	for (int i = 0; i < n; i++)
		if (ops->key(ctx, names[i], 1) < 0)
			return -1;
	ops->flush(ctx);
	for (int i = n - 1; i >= 0; i--)
		ops->key(ctx, names[i], 0);
	ops->flush(ctx);
	return 0;
}

int scen_line(const struct scen_ops *ops, void *ctx, char *line)
{
	char *cmd = strtok(line, " \t\r\n");
	if (!cmd || cmd[0] == '#')
		return 0;
	char *a[6] = { 0 };
	int n = 0;
	if (!strcmp(cmd, "type")) {
		/* zbytek radku vcetne mezer */
		char *rest = strtok(NULL, "\r\n");
		if (!rest)
			return 0;
		int r = ops->text(ctx, rest);
		ops->flush(ctx);
		return r;
	}
	if (!strcmp(cmd, "echo")) {
		char *rest = strtok(NULL, "\r\n");
		ops->flush(ctx);
		printf("%s\n", rest ? rest : "");
		fflush(stdout);
		return 0;
	}
	while (n < 6 && (a[n] = strtok(NULL, " \t\r\n")))
		n++;

	if (!strcmp(cmd, "move") && n == 2) {
		ops->move(ctx, atof(a[0]), atof(a[1]));
	} else if ((!strcmp(cmd, "down") || !strcmp(cmd, "up") || !strcmp(cmd, "click")) && n <= 1) {
		int b = parse_btn(a[0]);
		if (b < 0)
			goto bad;
		if (cmd[0] != 'u')
			ops->button(ctx, b, 1);
		if (cmd[0] == 'c') {
			ops->flush(ctx);
			scen_sleep(0.03);
		}
		if (cmd[0] != 'd')
			ops->button(ctx, b, 0);
	} else if (!strcmp(cmd, "drag") && n >= 4) {
		double x1 = atof(a[0]), y1 = atof(a[1]), x2 = atof(a[2]), y2 = atof(a[3]);
		double ms = n > 4 ? atof(a[4]) : 500;
		int b = parse_btn(n > 5 ? a[5] : NULL);
		if (b < 0)
			goto bad;
		/* krok po ~8 ms jako skutecna mys */
		int steps = ms / 8 > 1 ? (int)(ms / 8) : 1;
		ops->move(ctx, x1, y1);
		ops->flush(ctx);
		scen_sleep(0.05);
		ops->button(ctx, b, 1);
		ops->flush(ctx);
		scen_sleep(0.05);
		double t0 = scen_now();
		for (int i = 1; i <= steps; i++) {
			ops->move(ctx, x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps);
			ops->flush(ctx);
			scen_sleep(t0 + ms / 1000.0 * i / steps - scen_now());
		}
		scen_sleep(0.05);
		ops->button(ctx, b, 0);
	} else if (!strcmp(cmd, "key") && n == 1) {
		return combo(ops, ctx, a[0]);
	} else if ((!strcmp(cmd, "keydown") || !strcmp(cmd, "keyup")) && n == 1) {
		/* drzeny modifikator pres vic prikazu (Alt+Tab+Tab) */
		if (ops->key(ctx, a[0], cmd[3] == 'd') < 0)
			return -1;
	} else if (!strcmp(cmd, "sleep") && n == 1) {
		ops->flush(ctx);
		scen_sleep(atof(a[0]));
		return 0;
	} else {
		goto bad;
	}
	ops->flush(ctx);
	return 0;
bad:
	fprintf(stderr, "bad command: %s\n", cmd);
	return -1;
}

int scen_run(const struct scen_ops *ops, void *ctx, int argc, char **argv)
{
	char buf[4096];
	if (argc > 0) {
		for (int i = 0; i < argc; i++) {
			snprintf(buf, sizeof buf, "%s", argv[i]);
			if (scen_line(ops, ctx, buf) < 0)
				return -1;
		}
		return 0;
	}
	while (fgets(buf, sizeof buf, stdin))
		if (scen_line(ops, ctx, buf) < 0)
			return -1;
	return 0;
}
