# LuxOS - klik na hodiny v liste: bezici luxos-hub (SIGUSR2) nebo Kalendar na pozadi (SIGUSR1) jen prepne okno
# (v LSL bez shellu a procesu cat/grep/kill: klik reaguje za 1 ms)
load env, fd
load luxos_sys

SIGUSR1 = 10
SIGUSR2 = 12

runtime = env.get("XDG_RUNTIME_DIR", "")
if runtime == "":
    runtime = "/tmp"
end
pid = ""
safe:
    pid = fd.read_text(runtime + "/luxos-calendar.pid").strip()
end
if pid != "":
    cmdline = ""
    safe:
        cmdline = fd.read_text("/proc/" + pid + "/cmdline")
    end
    signal = 0
    if cmdline.find("luxos-hub") >= 0:
        signal = SIGUSR2
    elif cmdline.find("luxos-calendar") >= 0:
        signal = SIGUSR1
    end
    if signal != 0:
        if luxos_sys.kill(Int(pid), signal) == 0:
            call exit(0)
        end
        call exit(1)
    end
end
call luxos_sys.exec(["luxos-calendar"])
call exit(127)
