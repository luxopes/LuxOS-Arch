# LuxOS - klik na Ovladaci centrum v liste: bezici luxos-hub jen prepne okno (okamzite), jinak ho spusti
# (v LSL bez shellu a procesu cat/grep/kill: klik reaguje za 1 ms)
load env, fd
load luxos_sys

SIGUSR1 = 10

runtime = env.get("XDG_RUNTIME_DIR", "")
if runtime == "":
    runtime = "/tmp"
end
pid = ""
safe:
    pid = fd.read_text(runtime + "/luxos-control-center.pid").strip()
end
if pid != "":
    cmdline = ""
    safe:
        cmdline = fd.read_text("/proc/" + pid + "/cmdline")
    end
    if cmdline.find("luxos-hub") >= 0 or cmdline.find("luxos-control-center") >= 0:
        if luxos_sys.kill(Int(pid), SIGUSR1) == 0:
            call exit(0)
        end
        call exit(1)
    end
end
call luxos_sys.exec(["luxos-control-center"])
call exit(127)
