# lsl: internal-abi
# lsl: link libgtksourceview-4.so.0 libgtk-3.so.0 libgdk-3.so.0 libgdk_pixbuf-2.0.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
load glib
waiting = {"job": None}

function ptr(value):
    return __lsl_unbox_int(value)
end

function cstr(value):
    return __lsl_address(value) + 16
end

function cell(length=16):
    return __lsl_byte_zeros(length)
end

function data(value):
    return __lsl_qbe_load64(__lsl_address(value) + 24)
end

function env(name, fallback=""):
    address = __lsl_qbe_call1(__lsl_symbol("getenv"), cstr(name))
    if address == 0:
        return fallback
    end
    return glib.from_c(address)
end

function exists(path):
    return __lsl_qbe_call2(__lsl_symbol("g_file_test"), cstr(path), 18) != 0
end

function directory(path):
    return __lsl_qbe_call2(__lsl_symbol("g_file_test"), cstr(path), 4) != 0
end

function symlink(path):
    return __lsl_qbe_call2(__lsl_symbol("g_file_test"), cstr(path), 2) != 0
end

function mkdir(path):
    return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("mkdir"), cstr(path), 493)) == 0
end

function mkdirs(path):
    if symlink(path):
        Error(ProjectError: "A project directory must not be a symbolic link: " + path)
    end
    if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("g_mkdir_with_parents"), cstr(path), 493)) != 0:
        Error(ProjectError: "Cannot create directory: " + path)
    end
end

function canonical(path):
    raw = __lsl_qbe_call2(__lsl_symbol("realpath"), cstr(path), 0)
    if raw == 0:
        Error(ProjectError: "Directory does not exist: " + path)
    end
    result = glib.from_c(raw)
    call __lsl_qbe_call1(__lsl_symbol("free"), raw)
    return result
end

function program(name):
    return glib.take_c(__lsl_qbe_call1(__lsl_symbol("g_find_program_in_path"), cstr(name)))
end

function rename(source, target):
    return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("rename"), cstr(source), cstr(target))) == 0
end

function chmod(path, mode):
    return __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("chmod"), cstr(path), ptr(mode))) == 0
end

function unlink(path):
    return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("unlink"), cstr(path))) == 0
end

function now():
    return __lsl_qbe_call0(__lsl_symbol("g_get_monotonic_time")) / 1000000.0
end

function digest(text):
    return glib.take_c(__lsl_qbe_call3(__lsl_symbol("g_compute_checksum_for_string"), 2, cstr(text), __lsl_text_byte_length(text)))
end

function confined_directory(root, relative):
    cursor = root
    for component in relative.split("/"):
        cursor += "/" + component
        if symlink(cursor):
            Error(ProjectError: "Project directories must not be symbolic links: " + cursor)
        end
        if not directory(cursor):
            if exists(cursor) or not mkdir(cursor):
                Error(ProjectError: "Cannot create a project directory: " + cursor)
            end
        end
    end
    if not canonical(cursor).startswith(root + "/"):
        Error(ProjectError: "Project directories must stay inside the project.")
    end
    return cursor
end

function log_tail(path):
    handle = __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("open"), cstr(path), 655360))
    if handle < 0:
        return ""
    end
    total = __lsl_qbe_call3(__lsl_symbol("lseek"), ptr(handle), 0, 2)
    start = max(0, total - 65536)
    call __lsl_qbe_call3(__lsl_symbol("lseek"), ptr(handle), ptr(start), 0)
    bytes = cell(65536)
    count = __lsl_qbe_call3(__lsl_symbol("read"), ptr(handle), data(bytes), 65536)
    call __lsl_qbe_call1(__lsl_symbol("close"), ptr(handle))
    if count <= 0:
        return ""
    end
    return __lsl_text_from_bytes(bytes, 0, count)
end

function spawn_logged(argv, cwd, logfile):
    setsid = program("setsid")
    if not setsid:
        Error(ToolError: "The setsid program is required (util-linux).")
    end
    command = [setsid] + argv
    vector = glib.cstr_array(command)
    handle = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("open"), cstr(logfile), 655937, 384))
    if handle < 0:
        Error(ProjectError: "Cannot write the build log: " + logfile)
    end
    pid = cell()
    problem = cell()
    ok = __lsl_qbe_call11(__lsl_symbol("g_spawn_async_with_fds"), cstr(cwd), glib.array_data(vector), 0, 2, 0, 0, data(pid), -1, ptr(handle), ptr(handle), data(problem))
    call __lsl_qbe_call1(__lsl_symbol("close"), ptr(handle))
    if ok == 0:
        raw = __lsl_qbe_load64(data(problem))
        message = "Unable to start the requested program."
        if raw != 0:
            message = glib.from_c(__lsl_qbe_load64(raw + 8))
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), raw)
        end
        Error(ToolError: message)
    end
    return {"pid": __lsl_qbe_s32(__lsl_qbe_load32(data(pid))), "log": logfile, "stopping": False, "deadline": 0.0}
end

function poll(job):
    if not job.get("pid"):
        return 0
    end
    status = cell()
    result = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("waitpid"), ptr(job["pid"]), data(status), 1))
    if result == 0:
        if job.get("stopping") and now() >= job["deadline"]:
            call signal_job(job, 9)
        end
        return None
    end
    call __lsl_qbe_call1(__lsl_symbol("g_spawn_close_pid"), ptr(job["pid"]))
    job["pid"] = 0
    if result < 0:
        return 127
    end
    raw = __lsl_qbe_load32(data(status))
    if raw & 127:
        return 128 + (raw & 127)
    end
    return (raw >> 8) & 255
end

function stop(job):
    if job and job.get("pid"):
        call signal_job(job, 15)
        job["stopping"] = True
        job["deadline"] = now() + 0.6
    end
end

function signal_job(job, signum):
    if job and job.get("pid"):
        result = __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("kill"), ptr(-job["pid"]), ptr(signum)))
        # A click on Stop can beat setsid(). That child is still ours, but
        # its process group does not exist yet; signal its positive PID.
        if result != 0:
            call __lsl_qbe_call2(__lsl_symbol("kill"), ptr(job["pid"]), ptr(signum))
        end
    end
end

function dispose(job):
    if not job or not job.get("pid"):
        return
    end
    call stop(job)
    deadline = now() + 0.7
    while now() < deadline:
        if poll(job) != None:
            return
        end
        call __lsl_qbe_call1(__lsl_symbol("g_usleep"), 10000)
    end
    if job.get("pid"):
        call signal_job(job, 9)
        status = cell()
        call __lsl_qbe_call3(__lsl_symbol("waitpid"), ptr(job["pid"]), data(status), 0)
        call __lsl_qbe_call1(__lsl_symbol("g_spawn_close_pid"), ptr(job["pid"]))
        job["pid"] = 0
    end
end

function wait(job):
    waiting["job"] = job
    interrupts = [glib.unix_signal_add(2, cancel_wait), glib.unix_signal_add(15, cancel_wait)]
    status = poll(job)
    while status == None:
        call glib.pump()
        call __lsl_qbe_call1(__lsl_symbol("g_usleep"), 20000)
        status = poll(job)
    end
    for source in interrupts:
        call glib.source_remove(source)
    end
    waiting["job"] = None
    return status
end

function cancel_wait():
    call stop(waiting["job"])
    return True
end

function connect(widget, signal, handler, state, count=0):
    record = glib.record_bound(handler, count + 1, state)
    return __lsl_qbe_call6(__lsl_symbol("g_signal_connect_data"), ptr(widget), cstr(signal), glib.callback_first(), ptr(record), 0, 2)
end

function text_buffer(view):
    return __lsl_qbe_call1(__lsl_symbol("gtk_text_view_get_buffer"), ptr(view))
end

function set_text(view, text):
    return __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_set_text"), ptr(text_buffer(view)), cstr(text), -1)
end

function choose(parent, title, action, initial=""):
    dialog = __lsl_qbe_call5(__lsl_symbol("gtk_file_chooser_native_new"), cstr(title), ptr(parent), ptr(action), cstr("Select"), 0)
    if initial:
        call __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_current_folder"), ptr(dialog), cstr(initial))
    end
    response = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_native_dialog_run"), ptr(dialog)))
    path = ""
    if response == -3:
        path = glib.take_c(__lsl_qbe_call1(__lsl_symbol("gtk_file_chooser_get_filename"), ptr(dialog)))
    end
    call __lsl_qbe_call1(__lsl_symbol("gtk_native_dialog_destroy"), ptr(dialog))
    call glib.object_unref(dialog)
    return path
end

# --- editor zdrojoveho kodu (GtkSourceView 4) -------------------------------

# Editor LSL se zvyraznenim syntaxe (lsl.lang z Textoveho editoru LuxOS), cisly radku
# a odsazovanim po 4 mezerach; barvy podle svetleho/tmaveho rezimu (luxos-light/-dark).
function source_view(dark):
    buffer = __lsl_qbe_call1(__lsl_symbol("gtk_source_buffer_new"), 0)
    languages = __lsl_qbe_call0(__lsl_symbol("gtk_source_language_manager_get_default"))
    language = __lsl_qbe_call2(__lsl_symbol("gtk_source_language_manager_get_language"), ptr(languages), cstr("lsl"))
    if language:
        call __lsl_qbe_call2(__lsl_symbol("gtk_source_buffer_set_language"), ptr(buffer), ptr(language))
    end
    schemes = __lsl_qbe_call0(__lsl_symbol("gtk_source_style_scheme_manager_get_default"))
    names = ["luxos-light", "classic"]
    if dark:
        names = ["luxos-dark", "oblivion"]
    end
    for name in names:
        scheme = __lsl_qbe_call2(__lsl_symbol("gtk_source_style_scheme_manager_get_scheme"), ptr(schemes), cstr(name))
        if scheme:
            call __lsl_qbe_call2(__lsl_symbol("gtk_source_buffer_set_style_scheme"), ptr(buffer), ptr(scheme))
            break
        end
    end
    view = __lsl_qbe_call1(__lsl_symbol("gtk_source_view_new_with_buffer"), ptr(buffer))
    call glib.object_unref(buffer)
    call __lsl_qbe_call2(__lsl_symbol("gtk_source_view_set_show_line_numbers"), ptr(view), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_source_view_set_auto_indent"), ptr(view), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_source_view_set_insert_spaces_instead_of_tabs"), ptr(view), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_source_view_set_highlight_current_line"), ptr(view), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_monospace"), ptr(view), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_source_view_set_tab_width"), ptr(view), 4)
    call __lsl_qbe_call2(__lsl_symbol("gtk_source_view_set_indent_width"), ptr(view), 4)
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_left_margin"), ptr(view), 8)
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_top_margin"), ptr(view), 6)
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_bottom_margin"), ptr(view), 6)
    return view
end

function get_text(view):
    buffer = text_buffer(view)
    start = cell(96)
    stop = cell(96)
    call __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_get_bounds"), ptr(buffer), data(start), data(stop))
    return glib.take_c(__lsl_qbe_call4(__lsl_symbol("gtk_text_buffer_get_text"), ptr(buffer), data(start), data(stop), 1))
end

# Novy obsah souboru: bez kroku Zpet (otevreni souboru se nevraci) a jako neupraveny
function load_text(view, text):
    buffer = text_buffer(view)
    call __lsl_qbe_call1(__lsl_symbol("gtk_source_buffer_begin_not_undoable_action"), ptr(buffer))
    call set_text(view, text)
    call __lsl_qbe_call1(__lsl_symbol("gtk_source_buffer_end_not_undoable_action"), ptr(buffer))
    call set_modified(view, False)
    start = cell(96)
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_buffer_get_start_iter"), ptr(buffer), data(start))
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_buffer_place_cursor"), ptr(buffer), data(start))
end

function modified(view):
    return __lsl_qbe_call1(__lsl_symbol("gtk_text_buffer_get_modified"), ptr(text_buffer(view))) != 0
end

function set_modified(view, value):
    flag = 0
    if value:
        flag = 1
    end
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_buffer_set_modified"), ptr(text_buffer(view)), ptr(flag))
end

# Oznaci radek (od 1) a posune na nej editor - skok na chybu prekladu
function select_line(view, line):
    buffer = text_buffer(view)
    count = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_text_buffer_get_line_count"), ptr(buffer)))
    line = max(1, min(line, count))
    start = cell(96)
    stop = cell(96)
    call __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_get_iter_at_line"), ptr(buffer), data(start), ptr(line - 1))
    call __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_get_iter_at_line"), ptr(buffer), data(stop), ptr(line - 1))
    call __lsl_qbe_call1(__lsl_symbol("gtk_text_iter_forward_to_line_end"), data(stop))
    call __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_select_range"), ptr(buffer), data(start), data(stop))
    mark = __lsl_qbe_call1(__lsl_symbol("gtk_text_buffer_get_insert"), ptr(buffer))
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_scroll_mark_onscreen"), ptr(view), ptr(mark))
    call __lsl_qbe_call1(__lsl_symbol("gtk_widget_grab_focus"), ptr(view))
end

# Tmavy rezim podle motivu GTK (WhiteSur-Dark, Adwaita-dark, ...)
function dark_theme():
    settings = __lsl_qbe_call0(__lsl_symbol("gtk_settings_get_default"))
    if settings == 0:
        return False
    end
    value = cell(24)
    call __lsl_qbe_call2(__lsl_symbol("g_value_init"), data(value), 64)
    call __lsl_qbe_call3(__lsl_symbol("g_object_get_property"), ptr(settings), cstr("gtk-theme-name"), data(value))
    name = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_value_get_string"), data(value)))
    call __lsl_qbe_call1(__lsl_symbol("g_value_unset"), data(value))
    return "dark" in name.lower()
end

# --- nabidka v hlavicce ---------------------------------------------------------

function menu_new():
    return __lsl_qbe_call0(__lsl_symbol("gtk_menu_new"))
end

function menu_item(menu, title, handler, bound):
    item = __lsl_qbe_call1(__lsl_symbol("gtk_menu_item_new_with_label"), cstr(title))
    call __lsl_qbe_call2(__lsl_symbol("gtk_menu_shell_append"), ptr(menu), ptr(item))
    call connect(item, "activate", handler, bound)
    return item
end

function menu_separator(menu):
    item = __lsl_qbe_call0(__lsl_symbol("gtk_separator_menu_item_new"))
    call __lsl_qbe_call2(__lsl_symbol("gtk_menu_shell_append"), ptr(menu), ptr(item))
end

function menu_item_set_label(item, title):
    call __lsl_qbe_call2(__lsl_symbol("gtk_menu_item_set_label"), ptr(item), cstr(title))
end

function menu_button(icon, menu):
    button = __lsl_qbe_call0(__lsl_symbol("gtk_menu_button_new"))
    image = __lsl_qbe_call2(__lsl_symbol("gtk_image_new_from_icon_name"), cstr(icon), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_button_set_image"), ptr(button), ptr(image))
    call __lsl_qbe_call1(__lsl_symbol("gtk_widget_show_all"), ptr(menu))
    call __lsl_qbe_call2(__lsl_symbol("gtk_menu_button_set_popup"), ptr(button), ptr(menu))
    return button
end

function paned(vertical):
    orientation = 0
    if vertical:
        orientation = 1
    end
    return __lsl_qbe_call1(__lsl_symbol("gtk_paned_new"), ptr(orientation))
end

function paned_pack(widget, first, second):
    call __lsl_qbe_call4(__lsl_symbol("gtk_paned_pack1"), ptr(widget), ptr(first), 1, 0)
    call __lsl_qbe_call4(__lsl_symbol("gtk_paned_pack2"), ptr(widget), ptr(second), 0, 0)
end

function header_set(header, title, subtitle):
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_title"), ptr(header), cstr(title))
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_subtitle"), ptr(header), cstr(subtitle))
end

function open_uri_folder(path):
    program_path = program("xdg-open")
    if program_path:
        call glib.spawn([program_path, path])
    end
end
