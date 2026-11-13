load studio_ui as studio
load studio_project as projects
load studio_native as native
load gtk
load glib
load json

function pump(seconds):
    until = native.now() + seconds
    while native.now() < until:
        call glib.pump()
        call __lsl_qbe_call1(__lsl_symbol("g_usleep"), 5000)
    end
end

function shot(window, path):
    native_window = gtk.widget_get_window(window)
    width = gtk.widget_get_allocated_width(window)
    height = gtk.widget_get_allocated_height(window)
    pixbuf = __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_get_from_window"), native.ptr(native_window), 0, 0, native.ptr(width), native.ptr(height))
    if pixbuf:
        call __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_save"), native.ptr(pixbuf), native.cstr(path), native.cstr("png"), 0, 0)
        call glib.object_unref(pixbuf)
    end
end

window = studio.new_window()
if arg_count() > 2:
    call gtk.window_resize(window, Int(arg(2)), 760)
end
call pump(0.8)
call shot(window, arg(1) + "/create.png")
project = projects.create(arg(1) + "/gui-project", "A fresh idea", "fresh-idea", "gtk")
call studio.update_project(project)
call studio.start_job("build")
deadline = native.now() + 30
while studio.ui["job"] and native.now() < deadline:
    call pump(0.05)
end
built = studio.ui["job"] == None and native.exists(project["path"] + "/build/fresh-idea")
call pump(0.15)
call shot(window, arg(1) + "/project.png")
original = readfile(project["path"] + "/src/main.lsl")
# editor ukazuje main.lsl; vlastni uprava se pred sestavenim ulozi sama
editor_text = native.get_text(studio.ui["editor"])
call native.set_text(studio.ui["editor"], editor_text + "\n# edited in App Studio\n")
call studio.save_current()
autosaved = readfile(project["path"] + "/src/main.lsl").endswith("# edited in App Studio\n")
call pump(0.2)
stale = not projects.build_ready(project)
rejected = False
try:
    call studio.start_job("run")
else:
    rejected = True
end
# chyba prekladu: lista s hlaskou a skok na radek v editoru
call writefile(project["path"] + "/src/main.lsl", "x = 1\nfunction broken(:\n")
call pump(0.3)
call studio.clicked("build", 0)
deadline = native.now() + 30
while studio.ui["job"] and native.now() < deadline:
    call pump(0.05)
end
call pump(0.2)
errors = studio.ui["errors"]
bar_visible = gtk.widget_get_visible(studio.ui["bar"])
call shot(window, arg(1) + "/error.png")
# Spustit = ulozit, sestavit a spustit
call writefile(project["path"] + "/src/main.lsl", original)
call pump(0.3)
call studio.clicked("run", 0)
deadline = native.now() + 30
while not (studio.ui["job"] and studio.ui["mode"] == "run") and native.now() < deadline:
    call pump(0.05)
end
ran = studio.ui["mode"] == "run" and studio.ui["job"] != None
pid = 0
if studio.ui["job"]:
    pid = studio.ui["job"]["pid"]
end
call pump(0.4)
# chyba az za behu (neznama promenna ve funkci): lista a radek jako u prekladu
call writefile(project["path"] + "/src/main.lsl", "function f():\n    return 1 + missing_value\nend\nprint f()\n")
call pump(0.3)
call studio.clicked("run", 0)
deadline = native.now() + 40
while not studio.ui["errors"] and native.now() < deadline:
    call pump(0.05)
end
runtime_errors = studio.ui["errors"]
runtime_bar = gtk.widget_get_visible(studio.ui["bar"])
call writefile(project["path"] + "/src/main.lsl", original)
call pump(0.3)
call studio.clicked("run", 0)
deadline = native.now() + 30
while not (studio.ui["job"] and studio.ui["mode"] == "run") and native.now() < deadline:
    call pump(0.05)
end
if studio.ui["job"]:
    pid = studio.ui["job"]["pid"]
end
call pump(0.4)
call studio.close(None, 0, window)
alive = pid != 0 and __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("kill"), native.ptr(pid), 0)) == 0
call gtk.widget_destroy(window)
call pump(0.1)
print json.encode({"built": built, "czech": studio.LANG_CS, "autosaved": autosaved, "stale_detected": stale, "stale_run_rejected": rejected, "errors": errors, "bar_visible": bar_visible, "ran": ran, "runtime_errors": runtime_errors, "runtime_bar": runtime_bar, "child_pid": pid, "child_alive_after_close": alive, "job": studio.ui["job"], "timer": studio.ui["timer"]})
