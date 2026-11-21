/* Spolecny jazyk scenaru pro wlt-input (Wayland) a wlt-qmp (VM) */
#ifndef WLT_SCEN_H
#define WLT_SCEN_H

enum { BTN_L, BTN_R, BTN_M };

struct scen_ops {
	void (*move)(void *ctx, double x, double y);
	void (*button)(void *ctx, int btn, int down);
	/* name = jmeno klavesy (xkb keysym: a, Return, Escape, ctrl, ...) */
	int (*key)(void *ctx, const char *name, int down);
	int (*text)(void *ctx, const char *s);
	void (*flush)(void *ctx);
	/* kolecko: kroky, kladne = dolu */
	void (*scroll)(void *ctx, int steps);
};

/* Provede jeden radek scenare; vraci 0, nebo -1 s hlaskou na stderr */
int scen_line(const struct scen_ops *ops, void *ctx, char *line);
/* Radky z argv (kazdy argument jeden prikaz) nebo ze stdin, kdyz je argc 0 */
int scen_run(const struct scen_ops *ops, void *ctx, int argc, char **argv);
void scen_sleep(double sec);
double scen_now(void);

#endif
