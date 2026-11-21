"""Co je noveho: novinky aktualni verze LuxOS (data z luxos-branding v pracovni kopii)."""


def shots(s):
    exe = s.lslc("luxos-desktop/files/lsl/luxos-whats-new.lsl")
    s.launch([exe], env={"LUXOS_WHATS_NEW_DIR": s.src("luxos-branding/files/whats-new"),
                         "LUXOS_VERSION_FILE": s.src("luxos-branding/files/version")})
    win = s.window(cls="luxos-whats-new", size=None)
    s.sleep(0.5)
    s.capture("1", win)
