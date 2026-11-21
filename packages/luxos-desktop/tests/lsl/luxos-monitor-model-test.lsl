# Test luxos_monitor_model.lsl bez displeje (test_luxos_monitor.py): radky "ok NAZEV" / "FAIL NAZEV ...".
# Argument: docasna slozka pro soubory.
load luxos_monitor_model as m

failures = 0
tmp = args[1]

function expect(name, got, want):
    global failures
    if got == want:
        print "ok " + name
    else:
        failures += 1
        print "FAIL " + name + " got " + String(got) + " want " + String(want)
    end
    return 0
end

function names(groups, key, desc):
    return [item[1]["name"] for item in m.sort_groups(groups, key, desc)]
end

groups = {"a": {"name": "Firefox", "cpu": 2.0, "mem": 900}, "b": {"name": "code", "cpu": 9.0, "mem": 300},
    "c": {"name": "Bash", "cpu": 2.0, "mem": 950}, "d": {"name": "zed", "cpu": 0.0, "mem": 300}}
# shoda procesoru -> rozhodne pamet
call expect("cpu-desc", names(groups, "cpu", True), ["code", "Bash", "Firefox", "zed"])
call expect("cpu-asc", names(groups, "cpu", False), ["zed", "Firefox", "Bash", "code"])
call expect("mem-desc", names(groups, "mem", True), ["Bash", "Firefox", "code", "zed"])
call expect("mem-asc", names(groups, "mem", False)[:2], ["zed", "code"])
call expect("name-asc", names(groups, "name", False), ["Bash", "code", "Firefox", "zed"])
call expect("name-desc", names(groups, "name", True), ["zed", "Firefox", "code", "Bash"])
call expect("empty", m.sort_groups({}, "cpu", True), [])

# zapamatovana volba
conf = tmp + "/config/luxos/monitor.conf"
call expect("sort-default", m.load_sort(conf), ["cpu", True])
call m.save_sort(conf, "mem", False)
call expect("sort-saved", m.load_sort(conf), ["mem", False])
call expect("sort-file", readfile(conf), "{\"sort\": \"mem\", \"descending\": false}")
call writefile(conf, "{rozbite")
call expect("sort-broken", m.load_sort(conf), ["cpu", True])
call writefile(conf, "{\"sort\": \"pid\"}")
call expect("sort-unknown", m.load_sort(conf), ["cpu", True])
call writefile(conf, "{\"sort\": \"name\"}")
call expect("sort-name-default-asc", m.load_sort(conf), ["name", False])
call writefile(conf, "[1, 2]")
call expect("sort-not-object", m.load_sort(conf), ["cpu", True])

# bezici VM: guest (900) je uz v user (1000); celkem 1000+100 idle, ne 2000
call writefile(tmp + "/stat", "cpu  1000 0 0 100 0 0 0 0 900 0\ncpu0 1000 0 0 100 0 0 0 0 900 0\ncpu1 1 0 0 1 0 0 0 0 0 0\nintr 5\n")
call expect("cpu-guest", m.read_cpu(tmp + "/stat"), [1100, 100])
call expect("cpu-count", m.cpu_count(tmp + "/stat"), 2)
call expect("cpu-missing", m.read_cpu(tmp + "/nothing"), [0, 0])
call writefile(tmp + "/meminfo", "MemTotal:       16000000 kB\nMemFree:         1000000 kB\nMemAvailable:    6000000 kB\n")
call expect("mem", m.read_mem(tmp + "/meminfo"), [10000000 * 1024, 16000000 * 1024])
call writefile(tmp + "/meminfo2", "MemTotal:       1000 kB\nMemFree:         250 kB\n")
call expect("mem-no-available", m.read_mem(tmp + "/meminfo2"), [750 * 1024, 1000 * 1024])
call writefile(tmp + "/dev", "Inter-|   Receive\n face |bytes\n    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n  eth0: 1000 10 0 0 0 0 0 0 200 3 0 0 0 0 0 0\nwlan0:   50 1 0 0 0 0 0 0 7 1 0 0 0 0 0 0\n")
call expect("net", m.read_net(tmp + "/dev"), [1050, 207])
call mkdir(tmp + "/block")
call mkdir(tmp + "/block/sda")
call mkdir(tmp + "/block/sda/device")
call writefile(tmp + "/diskstats", "   8       0 sda 10 0 100 0 5 0 40 0 0 0 0\n   8       1 sda1 10 0 100 0 5 0 40 0 0 0 0\n   7       0 loop0 1 0 8 0 0 0 0 0 0 0 0\n")
call expect("disk-io", m.read_disk_io(tmp + "/diskstats", tmp + "/block"), (100 + 40) * 512)

# /proc/PID/stat: jmeno se zavorkami a mezerou
stat = "4242 (Web Content (x)) S 4200 4242 4242 0 -1 4194560 0 0 0 0 150 50 0 0 20 0 1 0 100 1000000 2560 0 0"
call expect("stat", m.parse_stat(stat), ["Web Content (x)", 4200, 200, 2560])
call expect("stat-bad", m.parse_stat("garbage"), None)
call expect("program-script", m.program("python3", "/usr/bin/python3" + chr(0) + "/usr/bin/luxos-router" + chr(0)), "luxos-router")
call expect("program-flag", m.program("python3", "python3" + chr(0) + "-c" + chr(0) + "x" + chr(0)), "python3")
call expect("program-plain", m.program("firefox", "/usr/lib/firefox/firefox" + chr(0) + "-new" + chr(0)), "firefox")
call expect("program-kernel", m.program("kworker/0:1", ""), "kworker/0:1")

# texty
call expect("bytes-b", m.human_bytes(512, False, ","), "512 B")
call expect("bytes-kb", m.human_bytes(1500, False, ","), "1,5 KB")
call expect("bytes-mb", m.human_bytes(250000000, False, "."), "250 MB")
call expect("bytes-gb-rate", m.human_bytes(6442450944, True, "."), "6.4 GB/s")
call expect("bytes-round-up", m.human_bytes(99960, False, "."), "100.0 KB")
call expect("fixed", [m.fixed(37.4, 0, ","), m.fixed(2.5, 1, ","), m.fixed(12.26, 1, ".")], ["37", "2,5", "12.3"])
if failures > 0:
    exit(1)
end
