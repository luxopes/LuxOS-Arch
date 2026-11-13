# lsl: internal-abi
load gtk
load glib
load json
load time
load icon_ui
load icon_native
load icon_model
load icon_render

dialog_action = {"mode": "", "step": 0, "folder": "", "name": "", "response": -6, "labels": []}

function respond_dialog():
    node = __lsl_qbe_call0(__lsl_symbol("gtk_window_list_toplevels"))
    first = node
    found = 0
    while node:
        widget = __lsl_qbe_load64(node)
        if __lsl_qbe_call2(__lsl_symbol("g_type_check_instance_is_a"), icon_native.ptr(widget), __lsl_qbe_call0(__lsl_symbol("gtk_dialog_get_type"))) != 0 and gtk.widget_get_visible(widget):
            found = widget
        end
        node = __lsl_qbe_load64(node + 8)
    end
    call __lsl_qbe_call1(__lsl_symbol("g_list_free"), icon_native.ptr(first))
    if not found:
        dialog_action["step"] += 1
        return dialog_action["step"] < 20
    end
    if dialog_action["mode"] == "file" and not dialog_action.get("prepared", False):
        call __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_current_folder"), icon_native.ptr(found), icon_native.cstr(dialog_action["folder"]))
        call __lsl_qbe_call2(__lsl_symbol("gtk_file_chooser_set_current_name"), icon_native.ptr(found), icon_native.cstr(dialog_action["name"]))
        dialog_action["prepared"] = True
        return True
    end
    dialog_action["labels"] = []
    for response in [-6, -2, -3, -5]:
        button = __lsl_qbe_call2(__lsl_symbol("gtk_dialog_get_widget_for_response"), icon_native.ptr(found), icon_native.ptr(response))
        if button:
            dialog_action["labels"].append(glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_button_get_label"), icon_native.ptr(button))))
        end
    end
    call __lsl_qbe_call2(__lsl_symbol("gtk_dialog_response"), icon_native.ptr(found), icon_native.ptr(dialog_action["response"]))
    return False
end

function prepare_dialog(mode, folder="", name="", response=-3):
    dialog_action["mode"] = mode
    dialog_action["folder"] = folder
    dialog_action["name"] = name
    dialog_action["response"] = response
    dialog_action["step"] = 0
    dialog_action["prepared"] = False
    call glib.timeout_add(200, respond_dialog)
end

function pump(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        call glib.pump()
        call time.sleep(0.005)
    end
end

function event_for(widget, kind):
    event = __lsl_qbe_call1(__lsl_symbol("gdk_event_new"), kind)
    window = __lsl_qbe_call1(__lsl_symbol("g_object_ref"), icon_native.ptr(gtk.widget_get_window(widget)))
    call __lsl_qbe_store64(icon_native.ptr(event) + 8, icon_native.ptr(window))
    return event
end

function key_event(state, key, modifiers=4):
    event = event_for(state["window"], 8)
    call __lsl_qbe_store32(icon_native.ptr(event) + 24, modifiers)
    call __lsl_qbe_store32(icon_native.ptr(event) + 28, key)
    result = icon_native.buffer(8)
    call __lsl_qbe_call4(__lsl_symbol("g_signal_emit_by_name"), icon_native.ptr(state["window"]), icon_native.cstr("key-press-event"), icon_native.ptr(event), icon_native.data(result))
    call __lsl_qbe_call1(__lsl_symbol("gdk_event_free"), icon_native.ptr(event))
end

function pointer_event(state, kind, signal, x, y):
    event = event_for(state["canvas"], kind)
    call __lsl_qbe_store64(icon_native.ptr(event) + 24, __lsl_float_bits(Float(x)))
    call __lsl_qbe_store64(icon_native.ptr(event) + 32, __lsl_float_bits(Float(y)))
    call __lsl_qbe_store32(icon_native.ptr(event) + 48, 256)
    if kind != 3:
        call __lsl_qbe_store32(icon_native.ptr(event) + 52, 1)
    end
    result = icon_native.buffer(8)
    call __lsl_qbe_call4(__lsl_symbol("g_signal_emit_by_name"), icon_native.ptr(state["canvas"]), icon_native.cstr(signal), icon_native.ptr(event), icon_native.data(result))
    call __lsl_qbe_call1(__lsl_symbol("gdk_event_free"), icon_native.ptr(event))
end

call gtk.init()
locale = "en"
if arg_count() > 2:
    locale = arg(2)
end
state = icon_ui.new_window("", locale)
call gtk.window_resize(state["window"], 1360, 900)
call pump(0.8)
call icon_native.screenshot(state["window"], arg(1) + "/wide.png")
call gtk.window_resize(state["window"], 1000, 760)
call pump(0.4)
call icon_native.screenshot(state["window"], arg(1) + "/narrow.png")
call gtk.window_resize(state["window"], 1360, 900)
call pump(0.3)
report = {"initial_layers": len(state["project"]["layers"]), "selected": state["selected"], "allocated": gtk.widget_get_allocation(state["canvas"]), "heading": gtk.label_get_text(state["properties_heading"])}
rect = state["canvas_rect"]
cx = rect[0] + rect[2] / 2.0
cy = rect[1] + rect[2] / 2.0
drag_x = icon_ui.selected(state)["x"]
call pointer_event(state, 4, "button-press-event", cx, cy)
call pointer_event(state, 3, "motion-notify-event", cx + 15.0, cy + 12.0)
call pointer_event(state, 7, "button-release-event", cx + 15.0, cy + 12.0)
report["drag_signal"] = icon_ui.selected(state)["x"] > drag_x
call gtk.button_clicked(state["undo_button"])
report["drag_undo"] = icon_ui.selected(state)["x"] == drag_x
original_x = icon_ui.selected(state)["x"]
call gtk.spin_button_set_value(state["fields"]["x"], original_x + 25)
report["property_signal"] = icon_ui.selected(state)["x"] == original_x + 25
call gtk.button_clicked(state["undo_button"])
report["undo_signal"] = icon_ui.selected(state)["x"] == original_x
call gtk.button_clicked(state["redo_button"])
report["redo_signal"] = icon_ui.selected(state)["x"] == original_x + 25
call gtk.combo_box_set_active(state["fields"]["glyph"], 1)
report["glyph_signal"] = icon_ui.selected(state)["glyph"] == "spark"
call icon_ui.set_color(state["fields"]["color"], "#234567")
call __lsl_qbe_call2(__lsl_symbol("g_signal_emit_by_name"), icon_native.ptr(state["fields"]["color"]), icon_native.cstr("color-set"))
report["color_signal"] = icon_ui.selected(state)["color"] == "#234567"
call icon_ui.add_layer(state, "text")
call gtk.entry_set_text(state["fields"]["text"], "Test české ikony")
report["text_signal"] = icon_ui.selected(state)["text"] == "Test české ikony"
call key_event(state, 100)
report["duplicate_shortcut"] = len(state["project"]["layers"]) == 5
call key_event(state, 122)
report["undo_shortcut"] = len(state["project"]["layers"]) == 4
state["path"] = arg(1) + "/edited.luxicon"
call gtk.button_clicked(state["save_button"])
report["save_signal"] = icon_model.open_project(state["path"])["layers"][3]["text"] == "Test české ikony"
report["save_clean"] = not icon_ui.dirty(state)
call prepare_dialog("file", arg(1), "dialog-saved.luxicon")
report["save_as_dialog"] = icon_ui.save_as(state, 0)
report["save_as_file"] = icon_model.open_project(arg(1) + "/dialog-saved.luxicon")["layers"][3]["text"] == "Test české ikony"
call prepare_dialog("file", arg(1), "dialog-export.png")
call icon_ui.export_file(state, "png")
report["export_dialog"] = icon_model.file_size(arg(1) + "/dialog-export.png") > 100
call gtk.spin_button_set_value(state["fields"]["x"], icon_ui.selected(state)["x"] + 1)
call prepare_dialog("question", "", "", -6)
report["close_cancel"] = not icon_ui.confirm_discard(state) and state["alive"]
report["close_labels"] = dialog_action["labels"]
call prepare_dialog("question", "", "", -3)
report["close_save"] = icon_ui.confirm_discard(state) and not icon_ui.dirty(state)
call icon_render.render_png(state["project"], arg(1) + "/edited.png", 256)
call pump(0.2)
handler_count = len(glib.handlers)
for index in rang(12):
    call icon_ui.select_layer(state, state["project"]["layers"][index % 4]["id"])
    call pump(0.015)
end
report["handler_growth"] = len(glib.handlers) - handler_count
call icon_ui.open_path(state, state["path"])
report["roundtrip"] = len(state["project"]["layers"]) == 4 and not icon_ui.dirty(state)
print json.encode(report)
call gtk.window_resize(state["window"], 1000, 760)
call pump(0.5)
call icon_native.screenshot(state["window"], arg(1) + "/edited-narrow.png")
call gtk.widget_destroy(state["window"])
call pump(0.1)
