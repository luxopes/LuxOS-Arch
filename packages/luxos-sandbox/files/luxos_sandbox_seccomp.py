"""LuxOS Sandbox - generator seccomp filtru (klasicke BPF) pro bwrap --seccomp.

Bez zavislosti na libseccomp: program se sestavi primo jako pole instrukci
struct sock_filter {u16 code; u8 jt; u8 jf; u32 k;} a bwrap ho nacte z FD.
Filtr je jen pro x86_64; jina architektura (i386, x32) se rovnou odmitne.

Rezimy:
  run     - bezne spusteni aplikace
  install - pacman jako falesny root: navic povoli chroot (skriptlety)
            a volani chown*() predstiraji uspech (v jednouidovem user namespace
            nelze menit vlastnika na jine UID; soubory zustanou vlastnene uzivatelem)
"""
import struct
import sys

AUDIT_ARCH_X86_64 = 0xC000003E
X32_SYSCALL_BIT = 0x40000000

RET_KILL_PROCESS = 0x80000000
RET_ALLOW = 0x7FFF0000
RET_ERRNO = 0x00050000

EPERM, ENOSYS, EAFNOSUPPORT = 1, 38, 97

# BPF instrukce
LD_W_ABS = 0x20
JEQ_K = 0x15
JGE_K = 0x35
JSET_K = 0x45
RET_K = 0x06

# Offsety v struct seccomp_data
OFF_NR, OFF_ARCH = 0, 4
OFF_ARG0_LO, OFF_ARG1_LO = 16, 24

# Volani zakazana vzdy (EPERM). Cisla pro x86_64.
BLOCKED = {
    "ptrace": 101, "process_vm_readv": 310, "process_vm_writev": 311, "pidfd_getfd": 438,
    "kcmp": 312,
    "kexec_load": 246, "kexec_file_load": 320, "reboot": 169,
    "init_module": 175, "finit_module": 313, "delete_module": 176,
    "mount": 165, "umount2": 166, "pivot_root": 155, "move_mount": 429, "open_tree": 428,
    "open_tree_attr": 467, "fsopen": 430, "fsconfig": 431, "fsmount": 432, "fspick": 433,
    "mount_setattr": 442,
    "setns": 308,
    "keyctl": 250, "add_key": 248, "request_key": 249,
    "bpf": 321, "perf_event_open": 298, "userfaultfd": 323,
    "io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427,
    "fanotify_init": 300, "open_by_handle_at": 304, "name_to_handle_at": 303,
    "swapon": 167, "swapoff": 168, "acct": 163, "syslog": 103, "quotactl": 179, "quotactl_fd": 443,
    "lookup_dcookie": 212, "iopl": 172, "ioperm": 173, "modify_ldt": 154, "uselib": 134,
    "settimeofday": 164, "clock_settime": 227, "clock_adjtime": 305, "adjtimex": 159,
    "vhangup": 153, "nfsservctl": 180,
}
CHROOT = 161
CHOWN_FAMILY = (92, 93, 94, 260)          # chown, fchown, lchown, fchownat
NR_IOCTL, NR_CLONE, NR_UNSHARE, NR_CLONE3, NR_SOCKET = 16, 56, 272, 435, 41
CLONE_NEWUSER = 0x10000000
TIOCSTI, TIOCLINUX = 0x5412, 0x541C       # vkladani znaku do terminalu
# Neobvykle rodiny socketu (velka utocna plocha jadra, aplikace je nepotrebuji)
BLOCKED_AF = (3, 4, 5, 6, 8, 9, 11, 12, 15, 17, 21, 30, 31, 32, 33, 34, 35, 36, 37, 39, 40, 41, 42, 43, 44, 45)


def ins(code, k, jt=0, jf=0):
    return (code, jt, jf, k)


def ret(value):
    return ins(RET_K, value)


def build_program(mode="run"):
    """Vrati seznam instrukci (code, jt, jf, k); bloky s kontrolou argumentu konci vzdy ret."""
    if mode not in ("run", "install"):
        raise ValueError(mode)
    deny = RET_ERRNO | EPERM
    p = [
        ins(LD_W_ABS, OFF_ARCH),
        ins(JEQ_K, AUDIT_ARCH_X86_64, 1, 0),
        ret(RET_KILL_PROCESS),
        ins(LD_W_ABS, OFF_NR),
        ins(JGE_K, X32_SYSCALL_BIT, 0, 1),
        ret(deny),
    ]
    blocked = sorted(BLOCKED.values())
    if mode == "run":
        blocked.append(CHROOT)
    for nr in blocked:
        p += [ins(JEQ_K, nr, 0, 1), ret(deny)]
    if mode == "install":
        for nr in CHOWN_FAMILY:
            p += [ins(JEQ_K, nr, 0, 1), ret(RET_ERRNO | 0)]
    p += [ins(JEQ_K, NR_CLONE3, 0, 1), ret(RET_ERRNO | ENOSYS)]

    def arg_block(nr, body):
        # Blok: pokud nr nesedi, preskocit cele telo (telo vzdy konci ret)
        return [ins(JEQ_K, nr, 0, len(body))] + body

    newuser = [ins(LD_W_ABS, OFF_ARG0_LO), ins(JSET_K, CLONE_NEWUSER, 0, 1), ret(deny), ret(RET_ALLOW)]
    p += arg_block(NR_CLONE, newuser)
    p += arg_block(NR_UNSHARE, newuser)
    tty = [ins(LD_W_ABS, OFF_ARG1_LO),
           ins(JEQ_K, TIOCSTI, 0, 1), ret(deny),
           ins(JEQ_K, TIOCLINUX, 0, 1), ret(deny),
           ret(RET_ALLOW)]
    p += arg_block(NR_IOCTL, tty)
    sock = [ins(LD_W_ABS, OFF_ARG0_LO)]
    for af in BLOCKED_AF:
        sock += [ins(JEQ_K, af, 0, 1), ret(RET_ERRNO | EAFNOSUPPORT)]
    sock += [ret(RET_ALLOW)]
    p += arg_block(NR_SOCKET, sock)
    p += [ret(RET_ALLOW)]
    for code, jt, jf, _k in p:
        if jt > 255 or jf > 255:
            raise ValueError("BPF skok je prilis dlouhy")
    if len(p) > 4096:
        raise ValueError("BPF program je prilis dlouhy")
    return p


def to_bytes(program):
    return b"".join(struct.pack("<HBBI", c, jt, jf, k) for c, jt, jf, k in program)


def filter_bytes(mode="run"):
    return to_bytes(build_program(mode))


if __name__ == "__main__":
    # python3 luxos_sandbox_seccomp.py [run|install] > filtr.bpf
    sys.stdout.buffer.write(filter_bytes(sys.argv[1] if len(sys.argv) > 1 else "run"))
