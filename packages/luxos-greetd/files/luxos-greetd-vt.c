/*
 * LuxOS - greetd (LD_PRELOAD v luxos-greetd.service): dokud bezi splash Plymouthu, VT neprepinat do textoveho rezimu.
 *
 * greetd pri startu a pred kazdou relaci nastavi VT na KD_TEXT. Prechod z grafickeho do textoveho rezimu jadro
 * bere jako navrat textove konzole a jeji framebuffer vynuti na displej i pres DRM mastera (vyjimka pro Xorg
 * v drm_fb_helper_set_par). Splash tak zmizel pod cernou konzoli driv, nez luxwm --hold mohl prevzit jeho obraz
 * (1,6-2,5 s cerne mezi splashem a prihlasenim). VT zustava v grafickem rezimu Plymouthu; logind ho pri
 * TakeControl nastavi stejne a po konci relace vrati textovy. Po konci Plymouthu se greetd chova beze zmeny.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <linux/kd.h>
#include <stdarg.h>
#include <sys/ioctl.h>
#include <unistd.h>

int
ioctl(int fd, unsigned long request, ...)
{
	static int (*real)(int, unsigned long, ...);
	va_list ap;
	va_start(ap, request);
	void *arg = va_arg(ap, void *);
	va_end(ap);
	if (!real) {
		real = (int (*)(int, unsigned long, ...))dlsym(RTLD_NEXT, "ioctl");
	}
	if (request == KDSETMODE && (unsigned long)arg == KD_TEXT && access("/run/plymouth/pid", F_OK) == 0) {
		return 0;
	}
	return real(fd, request, arg);
}
