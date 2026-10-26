#!/usr/bin/env python3
"""LuxOS - laborator AD: overeni pres PAM bez terminalu (UVNITR VM klienta, jako root).

  pam-auth.py SLUZBA UZIVATEL [--acct] [--chauthtok]   hesla na stdin (1. radek, pri zmene dalsi radky)

Vypise PAM_SUCCESS / chybu PAM a zpravy modulu (pam_sss: "Authenticated with cached credentials",
"Password expired", ...). Navratovy kod 0 = uspech. Jen pro testy v laboratori (libpam pres ctypes).
"""
import ctypes
import ctypes.util
import sys

libpam = ctypes.CDLL(ctypes.util.find_library("pam"))
libc = ctypes.CDLL(ctypes.util.find_library("c"))
libc.calloc.restype = ctypes.c_void_p
libc.strdup.restype = ctypes.c_void_p
libc.strdup.argtypes = [ctypes.c_char_p]
libpam.pam_strerror.restype = ctypes.c_char_p


class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class PamResponse(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(PamMessage)),
                        ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)


class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV), ("appdata_ptr", ctypes.c_void_p)]


answers = [line.rstrip("\n") for line in sys.stdin]


def conv(n, msgs, resp, _data):
    arr = libc.calloc(n, ctypes.sizeof(PamResponse))
    out = ctypes.cast(arr, ctypes.POINTER(PamResponse))
    for i in range(n):
        m = msgs[i].contents
        text = (m.msg or b"").decode(errors="replace")
        if m.msg_style in (1, 2):          # PAM_PROMPT_ECHO_OFF / ON
            print(f"prompt: {text}")
            out[i].resp = libc.strdup((answers.pop(0) if answers else "").encode())
        else:
            print(f"message: {text}")
    resp[0] = out
    return 0


def main():
    service, user = sys.argv[1], sys.argv[2]
    handle = ctypes.c_void_p()
    pc = PamConv(CONV(conv), None)
    rc = libpam.pam_start(service.encode(), user.encode(), ctypes.byref(pc), ctypes.byref(handle))
    if rc == 0 and "--acct" not in sys.argv:
        rc = libpam.pam_authenticate(handle, 0)
    if rc == 0:
        rc = libpam.pam_acct_mgmt(handle, 0)
    if rc == 12 and "--chauthtok" in sys.argv:          # PAM_NEW_AUTHTOK_REQD
        print("result: new password required")
        rc = libpam.pam_chauthtok(handle, 0x20)          # PAM_CHANGE_EXPIRED_AUTHTOK
    print("result:", libpam.pam_strerror(handle, rc).decode())
    libpam.pam_end(handle, rc)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
