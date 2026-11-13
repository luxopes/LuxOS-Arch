load studio_native as native
load json
load glib
call glib.unbuffered()
if arg_count() > 2:
    job = native.spawn_logged(["/usr/bin/sleep", "10"], arg(1), arg(1) + "/child.log")
    print job["pid"]
    result = native.wait(job)
    print json.encode({"status": result, "pid": job["pid"]})
else:
started = native.now()
leaks = []
for index in rang(30):
    job = native.spawn_logged(["/usr/bin/sleep", "10"], arg(1), arg(1) + "/child.log")
    pid = job["pid"]
    call native.stop(job)
    call native.dispose(job)
    if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("kill"), native.ptr(pid), 0)) == 0:
        leaks.append(pid)
    end
end
print json.encode({"seconds": native.now() - started, "leaks": leaks})
end
