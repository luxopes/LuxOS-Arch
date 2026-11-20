/*
 * Vyber rendereru, ktery funguje vsude.
 *
 * Automaticky vyber wlroots zkousi gles2 a vulkan a na pixman prejde jen bez render node.
 * Ve VM bez 3D (virtio-gpu bez virgl, vmwgfx bez 3D) nebo jen s llvmpipe render node existuje,
 * gles2 softwarovy ovladac odmitne a kompozitor by skoncil s cernou obrazovkou. Proto 3D
 * zjistujeme sami, gles2 zkousime jen kdyz ma sanci, jinak pixman se softwarovym kurzorem
 * (hardwarovy kurzor ve VM casto ukazuje vedle). WLR_RENDERER ma prednost, ale pri selhani
 * taky spadne na pixman.
 */
#define _GNU_SOURCE
#include "internal.h"
#include <dirent.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <virtgpu_drm.h>
#include <vmwgfx_drm.h>
#include <wlr/backend.h>
#include <wlr/render/allocator.h>
#include <wlr/render/gles2.h>
#include <wlr/render/pixman.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/util/log.h>
#include <xf86drm.h>

static bool
any_render_node(void)
{
	DIR *dir = opendir("/dev/dri");
	if (!dir) {
		return false;
	}
	bool found = false;
	struct dirent *de;
	while ((de = readdir(dir))) {
		if (!strncmp(de->d_name, "renderD", 7)) {
			found = true;
			break;
		}
	}
	closedir(dir);
	return found;
}

/* Proc 3D nejde pouzit, NULL = gles2 ma smysl zkusit */
static const char *
no_3d_reason(int drm_fd)
{
	if (drm_fd < 0) {
		/* headless/vnoreny: render node si wlroots otevre sam */
		return any_render_node() ? NULL : "no DRM render node";
	}

	char *render_node = drmGetRenderDeviceNameFromFd(drm_fd);
	if (!render_node) {
		/* bochs-drm (QEMU std VGA), simpledrm, cirrus... */
		return "no DRM render node";
	}
	free(render_node);

	drmVersion *version = drmGetVersion(drm_fd);
	if (!version) {
		return NULL;
	}
	const char *reason = NULL;
	if (!strcmp(version->name, "virtio_gpu")) {
		uint64_t has_3d = 0;
		struct drm_virtgpu_getparam param = {
			.param = VIRTGPU_PARAM_3D_FEATURES,
			.value = (uintptr_t)&has_3d,
		};
		if (drmIoctl(drm_fd, DRM_IOCTL_VIRTGPU_GETPARAM, &param) || !has_3d) {
			reason = "virtio-gpu without virgl";
		}
	} else if (!strcmp(version->name, "vmwgfx")) {
		struct drm_vmw_getparam_arg arg = { .param = DRM_VMW_PARAM_3D };
		if (drmCommandWriteRead(drm_fd, DRM_VMW_GET_PARAM, &arg, sizeof(arg))
				|| !arg.value) {
			reason = "vmwgfx without 3D";
		}
	}
	drmFreeVersion(version);
	return reason;
}

static const char *
renderer_name(struct wlr_renderer *renderer)
{
	if (wlr_renderer_is_gles2(renderer)) {
		return "gles2";
	}
	if (wlr_renderer_is_pixman(renderer)) {
		return "pixman";
	}
	return "vulkan";
}

static bool
create_allocator(struct wlr_backend *backend, struct wlr_renderer *renderer,
		struct wlr_allocator **allocator)
{
	*allocator = wlr_allocator_autocreate(backend, renderer);
	if (!*allocator) {
		wlr_log(WLR_ERROR, "luxcomp: no allocator for the %s renderer",
			renderer_name(renderer));
		wlr_renderer_destroy(renderer);
		return false;
	}
	return true;
}

struct wlr_renderer *
renderer_create(struct wlr_backend *backend, struct wlr_allocator **allocator,
		bool *software_out)
{
	bool software;
	struct wlr_renderer *renderer = NULL;
	const char *reason = NULL;
	const char *forced = getenv("WLR_RENDERER");

	if (forced && *forced) {
		renderer = wlr_renderer_autocreate(backend);
		if (renderer && create_allocator(backend, renderer, allocator)) {
			goto done;
		}
		if (!strcmp(forced, "pixman")) {
			return NULL;
		}
		reason = "the renderer from WLR_RENDERER failed";
	} else {
		reason = no_3d_reason(wlr_backend_get_drm_fd(backend));
		if (!reason) {
			/* jen gles2: vulkan neni otestovany a llvmpipe wlroots odmitne */
			setenv("WLR_RENDERER", "gles2", 1);
			renderer = wlr_renderer_autocreate(backend);
			unsetenv("WLR_RENDERER");
			if (renderer && create_allocator(backend, renderer, allocator)) {
				goto done;
			}
			reason = "no usable 3D driver (gles2 failed)";
		}
	}

	renderer = wlr_pixman_renderer_create();
	if (!renderer || !create_allocator(backend, renderer, allocator)) {
		return NULL;
	}
done:
	software = wlr_renderer_is_pixman(renderer);
	if (software) {
		setenv("WLR_NO_HARDWARE_CURSORS", "1", 1);
	}
	/* WLR_ERROR, aby volba byla v kazdem logu */
	wlr_log(WLR_ERROR, "luxcomp: renderer %s%s%s%s%s", renderer_name(renderer),
		software ? " + software cursor" : "",
		reason ? " (" : forced && *forced ? " (WLR_RENDERER)" : "",
		reason ? reason : "", reason ? ")" : "");
	*software_out = software;
	return renderer;
}
