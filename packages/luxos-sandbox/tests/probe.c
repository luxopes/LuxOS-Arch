/* LuxOS Sandbox - testovaci sonda (staticky prelozena, bezi uvnitr sandboxu).
 *
 *   probe ptrace PID            PTRACE_ATTACH na proces
 *   probe ptrace-self-child     fork + PTRACE_ATTACH na vlastniho potomka
 *   probe connect IP PORT       TCP spojeni (IPv4)
 *   probe unix PATH             spojeni na unix socket (cesta)
 *   probe abstract NAME         spojeni na abstraktni unix socket (@NAME)
 *   probe syscalls              zkusi zakazana volani a vypise vysledky
 *
 * Vystup: "OK" nebo "FAIL <errno-nazev>" (pro syscalls jeden radek na volani).
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/keyctl.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/ptrace.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>

static int report(const char *what, long r) {
    if (what) printf("%s ", what);
    if (r >= 0) { printf("OK\n"); return 0; }
    printf("FAIL %s\n", strerrorname_np(errno) ? strerrorname_np(errno) : "?");
    return 1;
}

static int do_unix(const char *name, int abstract) {
    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    if (s < 0) return report(NULL, -1);
    struct sockaddr_un a = {.sun_family = AF_UNIX};
    socklen_t len;
    if (abstract) {
        a.sun_path[0] = 0;
        strncpy(a.sun_path + 1, name, sizeof(a.sun_path) - 2);
        len = offsetof(struct sockaddr_un, sun_path) + 1 + strlen(name);
    } else {
        strncpy(a.sun_path, name, sizeof(a.sun_path) - 1);
        len = sizeof(a);
    }
    return report(NULL, connect(s, (struct sockaddr *)&a, len));
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    const char *cmd = argv[1];
    if (!strcmp(cmd, "ptrace") && argc == 3)
        return report(NULL, ptrace(PTRACE_ATTACH, atoi(argv[2]), 0, 0));
    if (!strcmp(cmd, "ptrace-self-child")) {
        pid_t c = fork();
        if (c == 0) { pause(); _exit(0); }
        int r = report(NULL, ptrace(PTRACE_ATTACH, c, 0, 0));
        kill(c, SIGKILL);
        waitpid(c, NULL, 0);
        return r;
    }
    if (!strcmp(cmd, "connect") && argc == 4) {
        int s = socket(AF_INET, SOCK_STREAM, 0);
        if (s < 0) return report(NULL, -1);
        struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(atoi(argv[3]))};
        inet_pton(AF_INET, argv[2], &a.sin_addr);
        struct timeval tv = {.tv_sec = 5};
        setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
        return report(NULL, connect(s, (struct sockaddr *)&a, sizeof(a)));
    }
    if (!strcmp(cmd, "unix") && argc == 3) return do_unix(argv[2], 0);
    if (!strcmp(cmd, "abstract") && argc == 3) return do_unix(argv[2], 1);
    if (!strcmp(cmd, "syscalls")) {
        int bad = 0;
        bad += !report("unshare(CLONE_NEWUSER)", unshare(CLONE_NEWUSER));
        bad += !report("unshare(CLONE_NEWNS)", unshare(CLONE_NEWNS));
        bad += !report("mount(tmpfs)", mount("none", "/tmp", "tmpfs", 0, NULL));
        bad += !report("umount2(/proc)", umount2("/proc", MNT_DETACH));
        bad += !report("chroot(/)", chroot("/"));
        bad += !report("keyctl", syscall(SYS_keyctl, KEYCTL_GET_KEYRING_ID, KEY_SPEC_SESSION_KEYRING, 0));
        bad += !report("bpf", syscall(SYS_bpf, 0, NULL, 0));
        bad += !report("perf_event_open", syscall(SYS_perf_event_open, NULL, 0, -1, -1, 0));
        bad += !report("userfaultfd", syscall(SYS_userfaultfd, 0));
        bad += !report("kexec_load", syscall(SYS_kexec_load, 0, 0, NULL, 0));
        bad += !report("init_module", syscall(SYS_init_module, NULL, 0, ""));
        bad += !report("setns", syscall(SYS_setns, 0, 0));
        bad += !report("io_uring_setup", syscall(SYS_io_uring_setup, 1, NULL));
        bad += !report("open_tree", syscall(SYS_open_tree, AT_FDCWD, "/", 0));
        char c = 'x';
        bad += !report("ioctl(TIOCSTI)", ioctl(0, TIOCSTI, &c));
        bad += !report("socket(AF_PACKET)", socket(17, SOCK_RAW, 0));
        bad += !report("socket(AF_VSOCK)", socket(40, SOCK_STREAM, 0));
        printf("ALLOWED %d\n", bad);
        return bad ? 1 : 0;
    }
    fprintf(stderr, "usage\n");
    return 2;
}
