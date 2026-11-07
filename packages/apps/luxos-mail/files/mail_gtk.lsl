# lsl: internal-abi
# lsl: link libgtk-3.so.0 libgdk-3.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# Posta LuxOS - doplnky GTK 3, ktere modul gtk ani luxos_gtk nemaji: GtkPaned, GtkTextView,
# vyber v GtkListBox, posuvnik, GtkSpinner, GtkStack. Nazvy = funkce GTK bez gtk_.

WRAP_WORD_CHAR = 3

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function flag(value):
    if value:
        return 1
    end
    return 0
end

function paned_new(orientation):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_paned_new"), ptr(orientation))
    end
end

function paned_pack1(paned, child, resize, shrink):
    unsafe:
        return __lsl_qbe_call4(__lsl_symbol("gtk_paned_pack1"), ptr(paned), ptr(child), flag(resize), flag(shrink))
    end
end

function paned_pack2(paned, child, resize, shrink):
    unsafe:
        return __lsl_qbe_call4(__lsl_symbol("gtk_paned_pack2"), ptr(paned), ptr(child), flag(resize), flag(shrink))
    end
end

function paned_set_position(paned, position):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_paned_set_position"), ptr(paned), ptr(position))
    end
end

function paned_get_position(paned):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_paned_get_position"), ptr(paned)))
    end
end

function text_view_new():
    unsafe:
        view = __lsl_qbe_call0(__lsl_symbol("gtk_text_view_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_editable"), view, 0)
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_cursor_visible"), view, 0)
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_wrap_mode"), view, 3)
        return view
    end
end

function text_view_set_margins(view, left, right, top, bottom):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_left_margin"), ptr(view), ptr(left))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_right_margin"), ptr(view), ptr(right))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_top_margin"), ptr(view), ptr(top))
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_bottom_margin"), ptr(view), ptr(bottom))
        return 0
    end
end

function text_view_set_text(view, text):
    unsafe:
        buffer = __lsl_qbe_call1(__lsl_symbol("gtk_text_view_get_buffer"), ptr(view))
        call __lsl_qbe_call3(__lsl_symbol("gtk_text_buffer_set_text"), buffer, cstr(text), -1)
        return 0
    end
end

function text_view_scroll_top(view):
    unsafe:
        buffer = __lsl_qbe_call1(__lsl_symbol("gtk_text_view_get_buffer"), ptr(view))
        iter = __lsl_byte_zeros(128)
        base = __lsl_qbe_load64(__lsl_address(iter) + 24)
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_buffer_get_start_iter"), buffer, base)
        call __lsl_qbe_call2(__lsl_symbol("gtk_text_buffer_place_cursor"), buffer, base)
        return 0
    end
end

function list_box_select_row(box, row):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_list_box_select_row"), ptr(box), ptr(row))
    end
end

function list_box_unselect_all(box):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_list_box_unselect_all"), ptr(box))
    end
end

function list_box_get_selected_row(box):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_list_box_get_selected_row"), ptr(box))
    end
end

function list_box_get_row_at_index(box, index):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_list_box_get_row_at_index"), ptr(box), ptr(index))
    end
end

function list_box_row_set_selectable(row, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_list_box_row_set_selectable"), ptr(row), flag(value))
    end
end

function list_box_row_set_activatable(row, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_list_box_row_set_activatable"), ptr(row), flag(value))
    end
end

function list_box_set_placeholder(box, widget):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_list_box_set_placeholder"), ptr(box), ptr(widget))
    end
end

function list_box_set_activate_on_single_click(box, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_list_box_set_activate_on_single_click"), ptr(box), flag(value))
    end
end

function scrolled_vadjustment(scrolled):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_scrolled_window_get_vadjustment"), ptr(scrolled))
    end
end

function adjustment_get_value(adj):
    unsafe:
        return Int(__lsl_qbe_fcall1(__lsl_symbol("gtk_adjustment_get_value"), ptr(adj)))
    end
end

function adjustment_set_value(adj, value):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_adjustment_set_value"), ptr(adj), Float(value))
    end
end

function spinner_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_spinner_new"))
    end
end

function spinner_set(spinner, active):
    unsafe:
        if active:
            return __lsl_qbe_call1(__lsl_symbol("gtk_spinner_start"), ptr(spinner))
        end
        return __lsl_qbe_call1(__lsl_symbol("gtk_spinner_stop"), ptr(spinner))
    end
end

function stack_new():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_stack_new"))
    end
end

function stack_add(stack, child, name):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_stack_add_named"), ptr(stack), ptr(child), cstr(name))
    end
end

function stack_show(stack, name):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_stack_set_visible_child_name"), ptr(stack), cstr(name))
    end
end

function widget_has_focus(widget):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_widget_has_focus"), ptr(widget)) != 0
    end
end

function window_get_focus(window):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_window_get_focus"), ptr(window))
    end
end

function is_entry(widget):
    unsafe:
        if ptr(widget) == 0:
            return False
        end
        return __lsl_qbe_call2(__lsl_symbol("g_type_check_instance_is_a"), ptr(widget), __lsl_qbe_call0(__lsl_symbol("gtk_entry_get_type"))) != 0
    end
end

function window_set_min_size(window, width, height):
    unsafe:
        return __lsl_qbe_call3(__lsl_symbol("gtk_widget_set_size_request"), ptr(window), ptr(width), ptr(height))
    end
end

function combo_box_set_active_id(combo, id):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_combo_box_set_active_id"), ptr(combo), cstr(id))
    end
end

function label_set_lines(label, lines):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_label_set_lines"), ptr(label), ptr(lines))
    end
end

function entry_set_input_purpose(entry, purpose):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_entry_set_input_purpose"), ptr(entry), ptr(purpose))
    end
end

# Prepinaci tlacitko bez popisku (jen ikona pres button_set_image, napr. oko u hesla)
function toggle_button_new_empty():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("gtk_toggle_button_new"))
    end
end

# Nabidka pod widgetem, pravy okraj zarovnany (tlacitko nabidky vpravo v liste; GdkGravity 9/3 = SE/NE)
function menu_popup_below(menu, widget):
    unsafe:
        return __lsl_qbe_call5(__lsl_symbol("gtk_menu_popup_at_widget"), ptr(menu), ptr(widget), 9, 3, 0)
    end
end

function menu_shell_select_first(menu):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_menu_shell_select_first"), ptr(menu), 1)
    end
end
