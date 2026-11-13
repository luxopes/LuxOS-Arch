# lsl: internal-abi
# lsl: link libgtk-3.so.0 libgdk-3.so.0 libgdk_pixbuf-2.0.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0 libcairo.so.2
# Small native GTK bridge. Signal records follow the owning GObject lifetime.
load gtk
load glib

owners = []
retired = []
jobs = []
idle_record = 0
idle_pending = False
language = "en"

function set_language(value):
    global language
    language = value
end

function tr(english, czech):
    if language == "cs":
        return czech
    end
    return english
end

function ptr(value):
    return __lsl_unbox_int(value)
end

function cstr(value):
    return __lsl_address(value) + 16
end

function buffer(size):
    return __lsl_byte_zeros(size)
end

function data(value):
    return __lsl_qbe_load64(__lsl_address(value) + 24)
end

function release(record):
    for item in glib.handlers.copy():
        if __lsl_address(item) == record:
            call glib.handlers.remove(item)
        end
    end
end

function drain():
    global idle_pending, jobs, retired
    idle_pending = False
    old = retired
    retired = []
    for owner in old:
        for record in owner["records"]:
            call release(record)
        end
        call owners.remove(owner)
    end
    pending = jobs
    jobs = []
    for job in pending:
        call job[0](job[1])
    end
    return False
end

function schedule():
    global idle_record, idle_pending
    if not idle_record:
        idle_record = glib.record_new(drain, 0)
    end
    if not idle_pending:
        idle_pending = True
        call __lsl_qbe_call4(__lsl_symbol("g_idle_add_full"), 200, glib.callback_first(), ptr(idle_record), 0)
    end
end

function defer(handler, state):
    jobs.append([handler, state])
    call schedule()
end

function finalized(owner, object):
    owner["widget"] = 0
    retired.append(owner)
    call schedule()
end

function connect(widget, signal, handler, state=None, argument_count=0):
    owner = None
    for item in owners:
        if item["widget"] == widget:
            owner = item
        end
    end
    if owner == None:
        owner = {"widget": widget, "records": []}
        owners.append(owner)
        weak = glib.record_bound(finalized, 1, owner)
        owner["records"].append(weak)
        call __lsl_qbe_call3(__lsl_symbol("g_object_weak_ref"), ptr(widget), glib.callback_first(), ptr(weak))
    end
    record = glib.record_bound(handler, argument_count + 1, state)
    owner["records"].append(record)
    return __lsl_qbe_call6(__lsl_symbol("g_signal_connect_data"), ptr(widget), cstr(signal), glib.callback_first(), ptr(record), 0, 2)
end

function children(container):
    result = []
    node = __lsl_qbe_call1(__lsl_symbol("gtk_container_get_children"), ptr(container))
    first = node
    while node != 0:
        result.append(__lsl_qbe_load64(node))
        node = __lsl_qbe_load64(node + 8)
    end
    if first:
        call __lsl_qbe_call1(__lsl_symbol("g_list_free"), first)
    end
    return result
end

function clear(container):
    for child in children(container):
        call gtk.widget_destroy(child)
    end
end

function align(label, alignment):
    # GTK takes float, while the raw call ABI supports double. GValue converts.
    value = buffer(24)
    call __lsl_qbe_call2(__lsl_symbol("g_value_init"), data(value), 60)
    call __lsl_qbe_call2(__lsl_symbol("g_value_set_double"), data(value), Float(alignment))
    call __lsl_qbe_call3(__lsl_symbol("g_object_set_property"), ptr(label), cstr("xalign"), data(value))
    call __lsl_qbe_call1(__lsl_symbol("g_value_unset"), data(value))
end

function left(label):
    call align(label, 0.0)
end

function unref(object):
    if object:
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(object))
    end
end

function choose(parent, title, action=0, name=""):
    accept = tr("Open", "Otevřít")
    if action == 1:
        accept = tr("Save", "Uložit")
    elif action == 2:
        accept = tr("Select", "Vybrat")
    end
    dialog = __lsl_qbe_call5(__lsl_symbol("gtk_file_chooser_native_new"), cstr(title), ptr(parent), ptr(action), cstr(accept), cstr(tr("Cancel", "Zrušit")))
    if action == 1:
        call __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_do_overwrite_confirmation"), ptr(dialog), 1)
        if name:
            call __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_current_name"), ptr(dialog), cstr(name))
        end
    end
    result = ""
    response = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_native_dialog_run"), ptr(dialog)))
    if response == -3:
        result = glib.take_c(__lsl_qbe_call1(__lsl_symbol("gtk_file_chooser_get_filename"), ptr(dialog)))
    end
    call __lsl_qbe_call1(__lsl_symbol("gtk_native_dialog_destroy"), ptr(dialog))
    call unref(dialog)
    return result
end

function message(parent, title, detail, question=False):
    dialog = __lsl_qbe_call0(__lsl_symbol("gtk_dialog_new"))
    call gtk.widget_add_class(dialog, "icon-studio")
    call gtk.window_set_title(dialog, title)
    call gtk.window_set_transient_for(dialog, parent)
    call gtk.window_set_modal(dialog, True)
    area = __lsl_qbe_call1(__lsl_symbol("gtk_dialog_get_content_area"), ptr(dialog))
    call gtk.container_set_border_width(area, 24)
    label = gtk.label_new(detail)
    call gtk.label_set_line_wrap(label, True)
    call gtk.label_set_max_width_chars(label, 55)
    call gtk.container_add(area, label)
    if question:
        call __lsl_qbe_call3(__lsl_symbol("gtk_dialog_add_button"), ptr(dialog), cstr(tr("Cancel", "Zrušit")), -6)
        call __lsl_qbe_call3(__lsl_symbol("gtk_dialog_add_button"), ptr(dialog), cstr(tr("Discard changes", "Zahodit změny")), -2)
        call __lsl_qbe_call3(__lsl_symbol("gtk_dialog_add_button"), ptr(dialog), cstr(tr("Save", "Uložit")), -3)
    else:
        call __lsl_qbe_call3(__lsl_symbol("gtk_dialog_add_button"), ptr(dialog), cstr("OK"), -5)
    end
    call gtk.widget_show_all(dialog)
    response = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_dialog_run"), ptr(dialog)))
    call gtk.widget_destroy(dialog)
    return response
end

function screenshot(window, path):
    pixbuf = __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_get_from_window"), ptr(gtk.widget_get_window(window)), 0, 0, ptr(gtk.widget_get_allocated_width(window)), ptr(gtk.widget_get_allocated_height(window)))
    if not pixbuf:
        return False
    end
    ok = __lsl_qbe_call5(__lsl_symbol("gdk_pixbuf_save"), ptr(pixbuf), cstr(path), cstr("png"), 0, 0) != 0
    call unref(pixbuf)
    return ok
end
