/*
 * luxcomp-demo - nejmensi politika nad libluxcomp na zkouseni jadra (skutecna politika bude
 * luxwm v LSL). Umisteni do stredu / volneho mista / kaskady, zamereni klikem, presun za
 * zahlavi, semafor, Alt+Tab, Ctrl+Left/Right mezi dvema plochami s prejezdem, celoobrazovkove
 * okno nad listou.
 *
 * Prikazy na stdin (testy bez vstupnich zarizeni): "slide", "slide-left", "focus-next", "fullscreen",
 * "spawn PRIKAZ", "list", "quit". Stdin a luxcomp_fd() hlida poll(), stejne jako to bude
 * delat smycka GLib v LSL.
 */
#define _POSIX_C_SOURCE 200809L
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "luxcomp.h"

#define CASCADE 28

static int64_t ws[2], current, bind_tab, bind_left, bind_right, bind_close, bind_grave;

static int64_t
vget(int64_t v, int64_t p)
{
	return luxcomp_view_get(v, p);
}

static int
overlaps(int64_t self, int x, int y, int w, int h)
{
	for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
		if (o == self || !vget(o, LUXCOMP_VIEW_VISIBLE)
				|| vget(o, LUXCOMP_VIEW_WORKSPACE) != vget(self, LUXCOMP_VIEW_WORKSPACE)) {
			continue;
		}
		int ox = vget(o, LUXCOMP_VIEW_X), oy = vget(o, LUXCOMP_VIEW_Y) - vget(o, LUXCOMP_VIEW_DECO_TOP);
		int ow = vget(o, LUXCOMP_VIEW_W), oh = vget(o, LUXCOMP_VIEW_H) + vget(o, LUXCOMP_VIEW_DECO_TOP);
		if (x < ox + ow && ox < x + w && y < oy + oh && oy < y + h) {
			return 1;
		}
	}
	return 0;
}

/* stred, kdyz je volny, jinak kaskada od nejvyssiho okna stejne aplikace */
static void
place(int64_t v)
{
	int64_t out = luxcomp_output_at(luxcomp_cursor_x(), luxcomp_cursor_y());
	int ux = luxcomp_output_get(out, LUXCOMP_OUT_USABLE_X);
	int uy = luxcomp_output_get(out, LUXCOMP_OUT_USABLE_Y);
	int uw = luxcomp_output_get(out, LUXCOMP_OUT_USABLE_W);
	int uh = luxcomp_output_get(out, LUXCOMP_OUT_USABLE_H);
	int top = vget(v, LUXCOMP_VIEW_DECO_TOP);
	int w = vget(v, LUXCOMP_VIEW_W), h = vget(v, LUXCOMP_VIEW_H) + top;
	int x = ux + (uw - w) / 2, y = uy + (uh - h) / 2;
	if (y < uy) {
		y = uy;
	}
	if (getenv("DEMO_DEBUG")) {
		fprintf(stderr, "place %ld out=%ld usable %d,%d %dx%d size %dx%d overlap=%d\n",
			(long)v, (long)out, ux, uy, uw, uh, w, h, overlaps(v, x, y, w, h));
	}
	if (overlaps(v, x, y, w, h)) {
		/* volne misto: prvni pozice v mrizce bez prekryti */
		for (int gy = uy; gy + h <= uy + uh; gy += 32) {
			for (int gx = ux; gx + w <= ux + uw; gx += 32) {
				if (!overlaps(v, gx, gy, w, h)) {
					luxcomp_view_move(v, gx, gy + top);
					return;
				}
			}
		}
		const char *app = luxcomp_view_app_id(v);
		for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
			const char *oapp = luxcomp_view_app_id(o);
			if (o != v && app && oapp && !strcmp(app, oapp)) {
				x = vget(o, LUXCOMP_VIEW_X) + CASCADE;
				y = vget(o, LUXCOMP_VIEW_Y) - vget(o, LUXCOMP_VIEW_DECO_TOP) + CASCADE;
				break;
			}
		}
		if (x + w > ux + uw) x = ux;
		if (y + h > uy + uh) y = uy;
	}
	luxcomp_view_move(v, x, y + top);
}

static void
focus(int64_t v)
{
	luxcomp_view_raise(v);
	luxcomp_view_focus(v);
	/* zamerene celoobrazovkove okno je nad listou, ostatni ne */
	for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
		if (vget(o, LUXCOMP_VIEW_FULLSCREEN)) {
			luxcomp_view_set_layer(o, o == v ? LUXCOMP_LAYER_FULLSCREEN : LUXCOMP_LAYER_NORMAL);
		}
	}
}

static void
focus_next(void)
{
	/* nejvyssi je zamerene; vezmi nejnizsi viditelne na aktualni plose */
	int64_t last = 0;
	for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
		if (vget(o, LUXCOMP_VIEW_VISIBLE) && vget(o, LUXCOMP_VIEW_WORKSPACE) == ws[current]) {
			last = o;
		}
	}
	if (last) {
		focus(last);
	}
}

static void
focus_top(void)
{
	for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
		if (vget(o, LUXCOMP_VIEW_VISIBLE) && vget(o, LUXCOMP_VIEW_WORKSPACE) == ws[current]) {
			focus(o);
			return;
		}
	}
	luxcomp_view_focus(0);
}

/* poloha pred celou obrazovkou (demo si pamatuje jen jedno okno) */
static int64_t saved_view, saved_x, saved_y, saved_w, saved_h;

static void
set_fullscreen(int64_t v, int on)
{
	int64_t out = vget(v, LUXCOMP_VIEW_OUTPUT);
	luxcomp_view_set_state(v, LUXCOMP_STATE_FULLSCREEN, on);
	if (on) {
		saved_view = v;
		saved_x = vget(v, LUXCOMP_VIEW_X);
		saved_y = vget(v, LUXCOMP_VIEW_Y);
		saved_w = vget(v, LUXCOMP_VIEW_W);
		saved_h = vget(v, LUXCOMP_VIEW_H);
		luxcomp_view_move(v, luxcomp_output_get(out, LUXCOMP_OUT_X),
			luxcomp_output_get(out, LUXCOMP_OUT_Y));
		luxcomp_view_resize(v, luxcomp_output_get(out, LUXCOMP_OUT_W),
			luxcomp_output_get(out, LUXCOMP_OUT_H));
		luxcomp_view_set_layer(v, LUXCOMP_LAYER_FULLSCREEN);
	} else if (saved_view == v) {
		luxcomp_view_resize(v, saved_w, saved_h);
		luxcomp_view_move(v, saved_x, saved_y);
		luxcomp_view_set_layer(v, LUXCOMP_LAYER_NORMAL);
	}
}

/* nova lista (exkluzivni zona): okna nesmi zustat pod ni */
static void
keep_below_bar(int64_t out)
{
	int uy = luxcomp_output_get(out, LUXCOMP_OUT_USABLE_Y);
	for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
		int top = vget(o, LUXCOMP_VIEW_DECO_TOP);
		if (!vget(o, LUXCOMP_VIEW_FULLSCREEN) && vget(o, LUXCOMP_VIEW_Y) - top < uy) {
			luxcomp_view_move(o, vget(o, LUXCOMP_VIEW_X), uy + top);
		}
	}
}

static void
slide(int dir)
{
	int next = (current + 1) % 2;
	luxcomp_workspace_slide(ws[current], ws[next], dir, 420);
	current = next;
}

static void
on_event(void *user, int64_t ev, int64_t id, int64_t a, int64_t b, int64_t c)
{
	printf("event %ld id=%ld %ld %ld %ld\n", (long)ev, (long)id, (long)a, (long)b, (long)c);
	fflush(stdout);
	switch (ev) {
	case LUXCOMP_EV_VIEW_NEW:
		luxcomp_view_set_workspace(id, ws[current]);
		break;
	case LUXCOMP_EV_VIEW_MAP:
		place(id);
		focus(id);
		break;
	case LUXCOMP_EV_VIEW_UNMAP:
		focus_top();
		break;
	case LUXCOMP_EV_BUTTON:
		if (!b || !id) {
			break;
		}
		focus(id);
		if (c == LUXCOMP_PART_TITLE) {
			luxcomp_view_begin_move(id);
		} else if (c == LUXCOMP_PART_CLOSE) {
			luxcomp_view_close(id);
		} else if (c == LUXCOMP_PART_MINIMIZE) {
			luxcomp_view_set_visible(id, 0);
			focus_top();
		}
		break;
	case LUXCOMP_EV_VIEW_REQUEST:
		if (a == LUXCOMP_REQ_MOVE) {
			luxcomp_view_begin_move(id);
		} else if (a == LUXCOMP_REQ_RESIZE) {
			luxcomp_view_begin_resize(id, b);
		} else if (a == LUXCOMP_REQ_FULLSCREEN) {
			set_fullscreen(id, b);
		}
		break;
	case LUXCOMP_EV_KEYBIND:
		if (id == bind_tab || id == bind_grave) {
			focus_next();
		} else if (id == bind_left) {
			slide(-1);
		} else if (id == bind_right) {
			slide(1);
		} else if (id == bind_close) {
			for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
				if (vget(o, LUXCOMP_VIEW_FOCUSED)) {
					luxcomp_view_close(o);
				}
			}
		}
		break;
	case LUXCOMP_EV_OUTPUT_USABLE:
		keep_below_bar(id);
		break;
	case LUXCOMP_EV_SLIDE_DONE:
		focus_top();
		break;
	}
}

static void
command(char *line)
{
	line[strcspn(line, "\n")] = 0;
	if (!strcmp(line, "slide")) {
		slide(1);
	} else if (!strcmp(line, "slide-left")) {
		slide(-1);
	} else if (!strcmp(line, "focus-next")) {
		focus_next();
	} else if (!strcmp(line, "fullscreen")) {
		for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
			if (vget(o, LUXCOMP_VIEW_FOCUSED)) {
				set_fullscreen(o, !vget(o, LUXCOMP_VIEW_FULLSCREEN));
			}
		}
	} else if (!strncmp(line, "spawn ", 6)) {
		luxcomp_spawn(line + 6);
	} else if (!strcmp(line, "list")) {
		for (int64_t o = luxcomp_view_next(0); o; o = luxcomp_view_next(o)) {
			printf("view %ld app=%s title=%s %ldx%ld+%ld+%ld deco=%ld ws=%ld focused=%ld layer=%ld\n",
				(long)o, luxcomp_view_app_id(o), luxcomp_view_title(o),
				(long)vget(o, LUXCOMP_VIEW_W), (long)vget(o, LUXCOMP_VIEW_H),
				(long)vget(o, LUXCOMP_VIEW_X), (long)vget(o, LUXCOMP_VIEW_Y),
				(long)vget(o, LUXCOMP_VIEW_DECO_TOP), (long)vget(o, LUXCOMP_VIEW_WORKSPACE),
				(long)vget(o, LUXCOMP_VIEW_FOCUSED), (long)vget(o, LUXCOMP_VIEW_LAYER));
		}
		fflush(stdout);
	} else if (!strcmp(line, "quit")) {
		luxcomp_quit();
	}
}

/* allowlist privilegovanych protokolu jako luxwm (wlt ho predava v LUXWM_PRIVILEGED) */
static void
load_privileged(void)
{
	const char *path = getenv("LUXWM_PRIVILEGED");
	FILE *f = fopen(path ? path : "/usr/share/luxwm/privileged.conf", "r");
	char line[4096];
	while (f && fgets(line, sizeof(line), f)) {
		line[strcspn(line, "\n")] = '\0';
		if (line[0] == '/') {
			luxcomp_privileged_allow(line);
		}
	}
	if (f) {
		fclose(f);
	}
}

int
main(int argc, char *argv[])
{
	if (luxcomp_init(on_event, NULL) != 0) {
		fprintf(stderr, "luxcomp_init failed\n");
		return 1;
	}
	load_privileged();
	luxcomp_set_background(0xff35507a);
	ws[0] = luxcomp_workspace_new();
	ws[1] = luxcomp_workspace_new();
	luxcomp_workspace_show(ws[0], 1);
	bind_tab = luxcomp_bind_key(LUXCOMP_MOD_ALT, "Tab");
	bind_grave = luxcomp_bind_key(LUXCOMP_MOD_ALT, "code:49");
	bind_left = luxcomp_bind_key(LUXCOMP_MOD_CTRL, "Left");
	bind_right = luxcomp_bind_key(LUXCOMP_MOD_CTRL, "Right");
	bind_close = luxcomp_bind_key(LUXCOMP_MOD_ALT, "F4");
	if (luxcomp_start() != 0) {
		fprintf(stderr, "luxcomp_start failed\n");
		return 1;
	}
	printf("socket %s software=%ld\n", luxcomp_socket(), (long)luxcomp_software_rendering());
	fflush(stdout);
	for (int i = 1; i < argc; i++) {
		luxcomp_spawn(argv[i]);
	}

	struct pollfd fds[2] = {
		{ .fd = luxcomp_fd(), .events = POLLIN },
		{ .fd = STDIN_FILENO, .events = POLLIN },
	};
	char line[512];
	while (luxcomp_dispatch(0) == 0) {
		if (poll(fds, 2, -1) < 0) {
			continue;
		}
		if (fds[1].revents & POLLIN) {
			if (fgets(line, sizeof(line), stdin)) {
				command(line);
			} else {
				fds[1].fd = -1;		/* EOF: dal jen kompozitor */
			}
		}
	}
	luxcomp_destroy();
	return 0;
}
