/*
 * GPU klient pro luxwm (test_luxwm_gaming.py, PRIME offload): okno xdg-shell kreslene pres EGL/GLES2
 * na Waylandu, N snimku jednolitou barvou. Vypisuje "renderer GL_RENDERER", "frames N" a konci.
 * Vykresleny buffer jde do kompozitoru pres linux-dmabuf (NVIDIA offload: kopie pro GPU kompozitoru).
 *
 *   egl-probe [--frames N] [--color RRGGBB]
 * Hlavicky GLES2 nejsou potreba: par funkci pres eglGetProcAddress.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>
#include <wayland-egl.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include "xdg-shell-client-protocol.h"

#define GL_COLOR_BUFFER_BIT 0x4000
#define GL_RENDERER 0x1F01

static struct wl_compositor *compositor;
static struct xdg_wm_base *wm_base;
static int configured, width = 320, height = 240;

static void
global(void *data, struct wl_registry *r, uint32_t name, const char *iface, uint32_t version)
{
	if (!strcmp(iface, wl_compositor_interface.name)) {
		compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
	} else if (!strcmp(iface, xdg_wm_base_interface.name)) {
		wm_base = wl_registry_bind(r, name, &xdg_wm_base_interface, 1);
	}
}

static void global_remove(void *data, struct wl_registry *r, uint32_t name) {}
static const struct wl_registry_listener registry_listener = { global, global_remove };
static void ping(void *data, struct xdg_wm_base *b, uint32_t serial) { xdg_wm_base_pong(b, serial); }
static const struct xdg_wm_base_listener wm_listener = { ping };

static void
surface_configure(void *data, struct xdg_surface *s, uint32_t serial)
{
	xdg_surface_ack_configure(s, serial);
	configured = 1;
}

static const struct xdg_surface_listener surface_listener = { surface_configure };
static void top_configure(void *d, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *s) {}
static void top_close(void *d, struct xdg_toplevel *t) { exit(0); }
static const struct xdg_toplevel_listener top_listener = { top_configure, top_close };

int
main(int argc, char **argv)
{
	int frames = 30;
	unsigned color = 0x20c040;
	for (int i = 1; i + 1 < argc; i++) {
		if (!strcmp(argv[i], "--frames")) {
			frames = atoi(argv[++i]);
		} else if (!strcmp(argv[i], "--color")) {
			color = strtoul(argv[++i], NULL, 16);
		}
	}
	struct wl_display *dpy = wl_display_connect(NULL);
	if (!dpy) {
		fprintf(stderr, "egl-probe: no wayland display\n");
		return 1;
	}
	wl_registry_add_listener(wl_display_get_registry(dpy), &registry_listener, NULL);
	wl_display_roundtrip(dpy);
	xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
	struct wl_surface *surface = wl_compositor_create_surface(compositor);
	struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
	xdg_surface_add_listener(xs, &surface_listener, NULL);
	struct xdg_toplevel *top = xdg_surface_get_toplevel(xs);
	xdg_toplevel_add_listener(top, &top_listener, NULL);
	xdg_toplevel_set_title(top, "egl");
	xdg_toplevel_set_app_id(top, "egl-probe");
	wl_surface_commit(surface);
	while (!configured && wl_display_dispatch(dpy) >= 0) {
	}

	PFNEGLGETPLATFORMDISPLAYEXTPROC get_display =
		(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
	EGLDisplay egl = get_display(EGL_PLATFORM_WAYLAND_KHR, dpy, NULL);
	if (!eglInitialize(egl, NULL, NULL)) {
		fprintf(stderr, "egl-probe: eglInitialize failed 0x%x\n", eglGetError());
		return 1;
	}
	eglBindAPI(EGL_OPENGL_ES_API);
	EGLint attrs[] = { EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
		EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_NONE };
	EGLConfig config;
	EGLint n = 0;
	if (!eglChooseConfig(egl, attrs, &config, 1, &n) || n < 1) {
		fprintf(stderr, "egl-probe: no EGL config\n");
		return 1;
	}
	EGLint ctx_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
	EGLContext ctx = eglCreateContext(egl, config, EGL_NO_CONTEXT, ctx_attrs);
	struct wl_egl_window *win = wl_egl_window_create(surface, width, height);
	EGLSurface es = eglCreateWindowSurface(egl, config, (EGLNativeWindowType)win, NULL);
	if (!eglMakeCurrent(egl, es, es, ctx)) {
		fprintf(stderr, "egl-probe: eglMakeCurrent failed 0x%x\n", eglGetError());
		return 1;
	}
	void (*clear_color)(float, float, float, float) = (void (*)(float, float, float, float))eglGetProcAddress("glClearColor");
	void (*clear)(unsigned) = (void (*)(unsigned))eglGetProcAddress("glClear");
	const char *(*get_string)(unsigned) = (const char *(*)(unsigned))eglGetProcAddress("glGetString");
	printf("renderer %s\n", get_string(GL_RENDERER));
	fflush(stdout);
	int done = 0;
	for (; done < frames; done++) {
		clear_color((color >> 16 & 0xff) / 255.0f, (color >> 8 & 0xff) / 255.0f, (color & 0xff) / 255.0f, 1);
		clear(GL_COLOR_BUFFER_BIT);
		if (!eglSwapBuffers(egl, es)) {
			fprintf(stderr, "egl-probe: eglSwapBuffers failed 0x%x\n", eglGetError());
			break;
		}
	}
	printf("frames %d\n", done);
	fflush(stdout);
	/* okno nechat videt pro snimek obrazovky, test proces ukonci */
	while (wl_display_dispatch(dpy) >= 0) {
	}
	return 0;
}
