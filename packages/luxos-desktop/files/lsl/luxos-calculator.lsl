# lsl: link libpango-1.0.so.0
# LuxOS Calculator - kalkulacka v barvach LuxOS (GTK 3), zakladni a vedecky rezim (drive Python).
#
# Pocita v desitkove aritmetice (0,1 + 0,2 = 0,3, luxos_calc), respektuje prednost operatoru a zavorky.
# Vedecky rezim (Ctrl+2, zpet Ctrl+1) pridava mocniny, odmocniny, logaritmy, goniometricke funkce
# (stupne/radiany), faktorial a konstanty. Klavesnice: cislice, + - * / ^ ( ), Enter, Backspace, Esc, %,
# Ctrl+C / Ctrl+V. Rezim se pamatuje v ~/.config/luxos/calculator ("basic" / "scientific").
load env, json, random
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_calc as calc
load luxos_testctl as testctl

MAX_DIGITS = 15
# nejvys znaku vlozeneho cisla (vic neni cislo pro kalkulacku)
MAX_PASTE = 200
CLIPBOARD = 69
# desetinny oddelovac z locale (gtk_init nastavi setlocale), tisice: uzka nedelitelna mezera pro carku,
# jinak carka
DEC = "."
GROUP = ","
CONFIG = glib.user_config_dir() + "/luxos/calculator"
OPS = {"+": "+", "-": "−", "*": "×", "/": "÷", "^": "^", "root": "ʸ√"}
# nejmensi pismo displeje; delsi priklad se pak zalamuje, nejvys MAX_LINES radku (zbytek zleva "…")
MIN_SIZE = 22
MAX_LINES = 4

CSS = "window.luxcalc { background-image: linear-gradient(165deg, @calc_bg_top, @calc_bg_bottom); }\n.calc-expr { color: @calc_dim; font-size: 15px; }\n.calc-value { color: @calc_fg; font-size: 46px; font-weight: 300; }\n.calc-preview { color: @calc_dim; font-size: 17px; }\nbutton.key {\n    border: none; border-radius: 16px; box-shadow: none; text-shadow: none;\n    background-image: none; background-color: @calc_key; color: @calc_fg;\n    font-size: 21px; min-height: 56px; min-width: 56px; padding: 0;\n    transition: background-color 120ms ease, opacity 120ms ease;\n}\nbutton.key:hover { background-color: @calc_key_hover; }\nbutton.key:active { background-color: @calc_key_active; }\nbutton.key.fn { background-color: @calc_fn; }\nbutton.key.fn:hover { background-color: @calc_fn_hover; }\nbutton.key.op { background-image: linear-gradient(180deg, #4d8dff, #5b4bff); color: white; font-size: 25px; }\nbutton.key.op:hover { background-image: linear-gradient(180deg, #62a0ff, #6d5eff); }\nbutton.key.op.selected { background-image: none; background-color: white; color: #4d5bff; }\nbutton.key.eq { background-image: linear-gradient(180deg, #ffbf57, #ff7a3c); color: white; font-size: 25px; }\nbutton.key.eq:hover { background-image: linear-gradient(180deg, #ffcb73, #ff8c52); }\nbutton.key.sci { font-size: 15px; min-width: 62px; background-color: alpha(@calc_fn, 0.55); }\nbutton.key.sci:hover { background-color: @calc_fn_hover; }\nbutton.key.sci.active { background-color: #5b6bff; color: white; }\nbutton.mode { border-radius: 999px; padding: 2px 10px; font-size: 12px; font-weight: 600;\n              background-image: none; background-color: alpha(@calc_fg, 0.08); color: @calc_fg; border: none; box-shadow: none; }\nbutton.mode:checked { background-color: #5b6bff; color: white; }\nbutton.mode:hover:not(:checked) { background-color: alpha(@calc_fg, 0.14); }\n"
DARK = "@define-color calc_bg_top #1d2145; @define-color calc_bg_bottom #0f1024;\n@define-color calc_fg #ffffff; @define-color calc_dim alpha(#ffffff, 0.5);\n@define-color calc_key alpha(#ffffff, 0.09); @define-color calc_key_hover alpha(#ffffff, 0.15);\n@define-color calc_key_active alpha(#ffffff, 0.24);\n@define-color calc_fn alpha(#a9b8ff, 0.22); @define-color calc_fn_hover alpha(#a9b8ff, 0.32);\n"
LIGHT = "@define-color calc_bg_top #f4f6fd; @define-color calc_bg_bottom #e3e7f6;\n@define-color calc_fg #1d1d2b; @define-color calc_dim alpha(#1d1d2b, 0.5);\n@define-color calc_key #ffffff; @define-color calc_key_hover #f0f2fb;\n@define-color calc_key_active #dfe3f5;\n@define-color calc_fn #d5dbf3; @define-color calc_fn_hover #c8d0f0;\n"

# tokens: cisla (luxos_calc), operatory, "(" a ")"; entry = prave psane cislo (bez formatovani, s teckou);
# fresh = entry je vysledek funkce, dalsi cislice ho nahradi; result = vysledek posledniho "=";
# prev_tokens = vyraz pred poslednim "=" (Backspace hned po "=" ho vrati k uprave); shown = text displeje
# (rozepsany priklad nebo vysledek), copy = co kopiruje Ctrl+C (cislo, ne cely priklad)
S = {"tokens": [], "entry": "", "fresh": False, "result": None, "degrees": True, "op_buttons": {},
     "prev_tokens": None, "shown": "0", "copy": "0", "fit_width": 0, "fit_pending": False}

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function locale_decimal_point():
    unsafe:
        conv = __lsl_qbe_call0(__lsl_symbol("localeconv"))
        point = glib.from_c(__lsl_qbe_load64(conv)) if conv != 0 else ""
    end
    return point if point != "" else "."
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

function label_max_width_chars(label, n):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_label_set_max_width_chars"), ptr(label), ptr(n))
    end
end

function label_justify_right(label):
    unsafe:
        # GTK_JUSTIFY_RIGHT
        call __lsl_qbe_call2(__lsl_symbol("gtk_label_set_justify"), ptr(label), 1)
    end
end

function key_button(label, classes, handler, bound):
    b = gtk.button_new(label)
    call gtk.widget_set_can_focus(b, False)
    for c in classes:
        call gtk.widget_add_class(b, c)
    end
    call gtk.connect_data(b, "clicked", 0, handler, bound)
    return b
end

function build():
    window = gtk.window_new(i18n.T("Calculator"))
    S["window"] = window
    call gtk.widget_add_class(window, "luxcalc")
    call gtk.window_set_resizable(window, False)
    call gtk.window_set_wmclass(window, "luxos-calculator", "luxos-calculator")
    # ostra ikona 16-256 px (Dock, Alt+Tab)
    call gtk.window_set_icon_list(window, "luxos-calculator")
    header = gtk.window_set_header(window, i18n.T("Calculator"))
    # male pomocne okno: nizke zahlavi 30 px (luxos-themes headerbar.compact, TITLEBAR height_compact)
    call gtk.widget_add_class(header, "compact")
    # Bez viditelneho titulku (jako kalkulacka v macOS), nazev okna zustava pro dock a listu
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_custom_title"), ptr(header), ptr(gtk.label_new("")))
    end
    toggle = gtk.toggle_button_new("f(x)")
    S["sci_toggle"] = toggle
    call gtk.widget_set_can_focus(toggle, False)
    call gtk.widget_set_valign(toggle, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(toggle, "mode")
    call gtk.widget_set_tooltip(toggle, i18n.T("Scientific (Ctrl+2)"))
    call gtk.connect_data(toggle, "toggled", 0, on_toggled, 0)
    call gtk.header_bar_pack_end(header, toggle)

    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_set_margins(box, 14, 14, 4, 14)
    call gtk.container_add(window, box)
    # po "=" je tu priklad; dlouhy se zkrati zleva (konec u "=" zustane videt) a okno nerozsiri
    S["expr"] = gtk.label_new("")
    call gtk.label_set_xalign(S["expr"], 1.0)
    # PANGO_ELLIPSIZE_START
    call gtk.label_set_ellipsize(S["expr"], 1)
    call label_max_width_chars(S["expr"], 1)
    call gtk.widget_add_class(S["expr"], "calc-expr")
    call gtk.widget_set_name(S["expr"], "expr")
    # rozepsany priklad je cely na tomto radku ("7 × 9"), po "=" tu je vysledek; dlouhy priklad se nejdriv
    # zmensi a kdyz se ani tak nevejde, zalomi se na dalsi radky (radky lame fit_value sam; ellipsize +
    # max_width_chars 1: okno se kvuli nemu nerozsiri, sirku dava klavesnice)
    S["value"] = gtk.label_new("")
    call gtk.label_set_xalign(S["value"], 1.0)
    call gtk.label_set_ellipsize(S["value"], 1)
    call label_max_width_chars(S["value"], 1)
    call label_justify_right(S["value"])
    call gtk.widget_add_class(S["value"], "calc-value")
    call gtk.widget_set_name(S["value"], "value")
    # sirka displeje se meni (vedecky panel): text znovu prizpusobit
    call gtk.connect_data(S["value"], "size-allocate", 1, on_value_allocate, 0)
    # prubezny vysledek pod prikladem (jako kalkulacka Samsung): "425 / 25" -> "= 17"
    S["preview"] = gtk.label_new("")
    call gtk.label_set_xalign(S["preview"], 1.0)
    call gtk.widget_add_class(S["preview"], "calc-preview")
    call gtk.widget_set_name(S["preview"], "preview")
    call gtk.box_pack_start(box, S["expr"], False, False, 0)
    call gtk.box_pack_start(box, S["value"], False, False, 0)
    call gtk.box_pack_start(box, S["preview"], False, False, 2)

    keys = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.box_pack_start(box, keys, True, True, 0)
    sci_grid = gtk.grid_new()
    S["sci_grid"] = sci_grid
    call gtk.grid_set_row_spacing(sci_grid, 10)
    call gtk.grid_set_column_spacing(sci_grid, 8)
    call gtk.grid_set_row_homogeneous(sci_grid, True)
    call gtk.grid_set_column_homogeneous(sci_grid, True)
    call gtk.widget_set_no_show_all(sci_grid, True)
    call gtk.box_pack_start(keys, sci_grid, False, False, 0)
    grid = gtk.grid_new()
    call gtk.grid_set_row_spacing(grid, 10)
    call gtk.grid_set_column_spacing(grid, 10)
    call gtk.grid_set_row_homogeneous(grid, True)
    call gtk.grid_set_column_homogeneous(grid, True)
    call gtk.box_pack_start(keys, grid, True, True, 0)

    layout = [[["AC", "fn", "clear"], ["±", "fn", "negate"], ["%", "fn", "percent"], ["/", "op", ""]],
        [["7", "", ""], ["8", "", ""], ["9", "", ""], ["*", "op", ""]],
        [["4", "", ""], ["5", "", ""], ["6", "", ""], ["-", "op", ""]],
        [["1", "", ""], ["2", "", ""], ["3", "", ""], ["+", "op", ""]],
        [["0", "", ""], [DEC, "", "point"], ["⌫", "fn", "backspace"], ["=", "eq", "equals"]]]
    for r in range(len(layout)):
        row = layout[r]
        for c in range(len(row)):
            label = row[c][0]
            kind = row[c][1]
            classes = ["key"]
            if kind != "":
                classes.append(kind)
            end
            if kind == "op":
                b = key_button(OPS[label], classes, on_operator, label)
                S["op_buttons"][label] = b
            elif row[c][2] != "":
                b = key_button(label, classes, on_action, row[c][2])
            else:
                b = key_button(label, classes, on_digit, label)
            end
            if label == "AC":
                S["clear_btn"] = b
            end
            call gtk.grid_attach(grid, b, c, r, 1, 1)
        end
    end

    sci = [[["(", "paren("], [")", "paren)"], ["x²", "func sq"], ["x³", "func cube"], ["xʸ", "op ^"]],
        [["eˣ", "func exp"], ["10ˣ", "func exp10"], ["1/x", "func inv"], ["√x", "func sqrt"], ["∛x", "func cbrt"]],
        [["ʸ√x", "op root"], ["ln", "func ln"], ["log₁₀", "func log10"], ["x!", "func fact"], ["π", "const pi"]],
        [["sin", "func sin"], ["cos", "func cos"], ["tan", "func tan"], ["e", "const e"], ["Rand", "const rand"]],
        [["sin⁻¹", "func asin"], ["cos⁻¹", "func acos"], ["tan⁻¹", "func atan"], ["|x|", "func abs"], ["Deg", "angle"]]]
    for r in range(len(sci)):
        row = sci[r]
        for c in range(len(row)):
            b = key_button(row[c][0], ["key", "sci"], on_action, row[c][1])
            if row[c][1] == "angle":
                S["angle_btn"] = b
                call gtk.widget_set_tooltip(b, i18n.T("Degrees / radians"))
            elif row[c][1] == "op ^":
                S["op_buttons"]["^"] = b
            elif row[c][1] == "op root":
                S["op_buttons"]["root"] = b
            end
            call gtk.grid_attach(sci_grid, b, c, r, 1, 1)
            call gtk.widget_show(b)
        end
    end

    call gtk.connect_data(window, "key-press-event", 1, on_key, 0)
    call gtk.connect_data(window, "destroy", 0, on_destroy, 0)
    call refresh()
    saved = ""
    safe:
        saved = readfile(CONFIG).strip()
    end
    if saved == "scientific":
        call gtk.toggle_button_set_active(toggle, True)
    end
end

# ---- rezim -------------------------------------------------------------------------------------------------------

function on_toggled(unused, toggle):
    call set_scientific(gtk.toggle_button_get_active(toggle))
    return 0
end

function set_scientific(on):
    call gtk.widget_set_visible(S["sci_grid"], on)
    if gtk.toggle_button_get_active(S["sci_toggle"]) != on:
        call gtk.toggle_button_set_active(S["sci_toggle"], on)
    end
    # zmensit okno po skryti panelu
    call gtk.window_resize(S["window"], 1, 1)
    safe:
        call sys.mkdir_p(glib.user_config_dir() + "/luxos")
        call writefile(CONFIG, "scientific" if on else "basic")
    end
end

function toggle_angle():
    S["degrees"] = not S["degrees"]
    call gtk.button_set_label(S["angle_btn"], "Deg" if S["degrees"] else "Rad")
end

# ---- logika ------------------------------------------------------------------------------------------------------

function last():
    t = S["tokens"]
    if len(t) == 0:
        return None
    end
    return t[len(t) - 1]
end

function is_op(t):
    return t != None and not calc.is_number(t) and t in calc.PRECEDENCE
end

function awaiting_operand():
    t = last()
    return t == None or t == "(" or is_op(t)
end

function open_parens():
    n = 0
    for t in S["tokens"]:
        if not calc.is_number(t):
            if t == "(":
                n += 1
            elif t == ")":
                n -= 1
            end
        end
    end
    return n
end

# Zacatek uzavrene zavorky na konci vyrazu, kterou funkce nahradi jednim cislem (-1 = neni)
function operand_start():
    t = S["tokens"]
    if S["entry"] != "" or last() != ")":
        return -1
    end
    depth = 0
    i = len(t) - 1
    while i >= 0:
        if not calc.is_number(t[i]):
            if t[i] == ")":
                depth += 1
            elif t[i] == "(":
                depth -= 1
                if depth == 0:
                    return i
                end
            end
        end
        i -= 1
    end
    return -1
end

function current():
    if S["entry"] != "":
        return calc.number(S["entry"])
    end
    start = operand_start()
    if start >= 0:
        return calc.evaluate_tokens(S["tokens"][start:])
    end
    if S["result"] != None:
        return S["result"]
    end
    return calc.ZERO
end

function set_current(value):
    start = operand_start()
    if start >= 0:
        S["tokens"] = S["tokens"][:start]
    end
    if len(S["tokens"]) == 0:
        S["result"] = None
    end
    S["entry"] = calc.exact_text(calc.rounded(value, len(value[1]) + 1))
    S["fresh"] = True
end

function forget_result():
    if S["result"] != None and len(S["tokens"]) == 0:
        S["result"] = None
    end
end

function digit(d):
    call forget_result()
    if S["fresh"]:
        S["entry"] = ""
        S["fresh"] = False
    end
    if len(S["entry"].replace("-", "").replace(".", "")) >= MAX_DIGITS:
        return 0
    end
    if S["entry"] == "" or S["entry"] == "0":
        S["entry"] = d
    elif S["entry"] == "-0":
        # 0, +/-, 5 -> -5, ne -05
        S["entry"] = "-" + d
    else:
        S["entry"] = S["entry"] + d
    end
    call refresh()
end

function point():
    call forget_result()
    if S["fresh"]:
        S["entry"] = ""
        S["fresh"] = False
    end
    if S["entry"].find(".") < 0:
        S["entry"] = (S["entry"] if S["entry"] != "" else "0") + "."
    end
    call refresh()
end

function push_entry():
    if S["entry"] != "":
        S["tokens"].append(calc.number(S["entry"]))
        S["entry"] = ""
        S["fresh"] = False
    end
end

function operator(op):
    if S["entry"] != "":
        call push_entry()
    elif len(S["tokens"]) == 0:
        S["tokens"].append(S["result"] if S["result"] != None else calc.ZERO)
    elif last() == "(":
        return 0
    end
    if is_op(last()):
        # zmena operatoru
        S["tokens"][len(S["tokens"]) - 1] = op
    else:
        S["tokens"].append(op)
    end
    S["result"] = None
    call refresh()
end

function paren(p):
    if p == "(":
        if S["entry"] != "" or last() == ")" or calc.is_number(last()):
            # 2(3+4) = 2 x (3+4)
            call push_entry()
            S["tokens"].append("*")
        elif S["result"] != None and len(S["tokens"]) == 0:
            S["result"] = None
        end
        S["tokens"].append("(")
    elif open_parens() > 0:
        call push_entry()
        if awaiting_operand():
            return 0
        end
        S["tokens"].append(")")
    end
    call refresh()
end

function equals():
    t = S["tokens"]
    if len(t) == 0:
        if S["entry"] != "":
            # samotne cislo + "=": dalsi cislice zacne nove cislo
            S["result"] = calc.number(S["entry"])
            S["entry"] = ""
            S["fresh"] = False
            call refresh()
        end
        return 0
    end
    if S["entry"] != "":
        call push_entry()
    end
    # "2 × (" + "=": prazdna zavorka by byla chyba -> "2 × ="
    while len(t) > 0 and last() == "(":
        call t.pop()
    end
    if len(t) == 0:
        call refresh()
        return 0
    end
    if is_op(last()):
        if len(t) >= 2 and calc.is_number(t[len(t) - 2]):
            # 5 + = -> 5 + 5
            t.append(t[len(t) - 2])
        else:
            call t.pop()
        end
    end
    for i in range(open_parens()):
        t.append(")")
    end
    expr = expression_text("") + " ="
    S["prev_tokens"] = t.copy()
    value = None
    safe:
        value = calc.evaluate_tokens(t)
    end
    S["tokens"] = []
    S["entry"] = ""
    S["fresh"] = False
    if value == None:
        # chybny vyraz (deleni nulou) jde po Backspace opravit
        S["result"] = calc.ZERO
        call show(expr, i18n.T("Error"), None)
        return 0
    end
    S["result"] = value
    call show(expr, fmt(value), None)
    call update_ops()
end

# Funkce jedne promenne na aktualni hodnotu (jako v macOS)
function func(name):
    r = None
    safe:
        r = calc.compute(name, current(), S["degrees"])
    end
    if r == None:
        S["entry"] = ""
        S["fresh"] = False
        call show(expression_text(""), i18n.T("Error"), None)
        return 0
    end
    call set_current(r)
    call refresh()
end

function constant(value):
    call forget_result()
    if S["entry"] != "" and not S["fresh"]:
        # 2 pi = 2 x pi
        call push_entry()
    end
    if calc.is_number(last()) or last() == ")":
        S["tokens"].append("*")
    end
    S["entry"] = calc.value_text(value)
    S["fresh"] = True
    call refresh()
end

function clear():
    if S["entry"] != "":
        S["entry"] = ""
        S["fresh"] = False
    else:
        S["tokens"] = []
        S["result"] = None
    end
    call refresh()
end

function negate():
    if S["entry"] != "":
        S["entry"] = S["entry"][1:] if S["entry"].startswith("-") else "-" + S["entry"]
    elif S["result"] != None:
        S["result"] = calc.negate(S["result"])
    elif operand_start() >= 0:
        value = None
        safe:
            value = calc.negate(current())
        end
        if value == None:
            call show(expression_text(""), i18n.T("Error"), None)
            return 0
        end
        call set_current(value)
    end
    call refresh()
end

# Levy operand pred koncovym + nebo -: cely vyraz od posledni neuzavrene zavorky (nebo od zacatku), at je
# to cislo, zavorka nebo soucin. [] kdyz zadny neni.
function left_side(prefix):
    depth = 0
    start = len(prefix) - 1
    i = len(prefix) - 2
    while i >= 0:
        t = prefix[i]
        if not calc.is_number(t):
            if t == ")":
                depth += 1
            elif t == "(":
                if depth == 0:
                    break
                end
                depth -= 1
            end
        end
        start = i
        i -= 1
    end
    return prefix[start:len(prefix) - 1]
end

function percent():
    value = None
    try:
        value = current()
        start = operand_start()
        prefix = S["tokens"][:start] if start >= 0 else S["tokens"]
        left = []
        if len(prefix) > 0 and (prefix[len(prefix) - 1] == "+" or prefix[len(prefix) - 1] == "-"):
            left = left_side(prefix)
        end
        if len(left) > 0:
            # 200 + 10 % -> 200 + 20; stejne (200) + 10 % i 2 x 100 + 10 % (C-19)
            value = calc.div(calc.mul(calc.evaluate_tokens(left), value), calc.HUNDRED)
        else:
            value = calc.div(value, calc.HUNDRED)
        end
    else:
        value = None
    end
    if value == None:
        call show(expression_text(""), i18n.T("Error"), None)
        return 0
    end
    call set_current(value)
    call refresh()
end

# Hotove cislo (operand pred operatorem, vysledek) zpet do rozpracovaneho, aby slo mazat po cislicich;
# delsi nez displej (1/3) nebo s exponentem se smaze cele ("")
function edit_value(value):
    text = calc.exact_text(value)
    if text.find("e") >= 0 or text.find("E") >= 0:
        return ""
    end
    if text.find(".") >= 0:
        text = text.rstrip("0").rstrip(".")
    end
    if text == "" or text == "-":
        text = "0"
    end
    if len(bigint_strip(text.replace("-", "").replace(".", ""))) > MAX_DIGITS:
        return ""
    end
    return text
end

function chop_entry(text):
    text = text[:len(text) - 1]
    if text == "-" or text == "-0":
        return ""
    end
    return text
end

function backspace():
    t = S["tokens"]
    if S["fresh"]:
        S["entry"] = ""
        S["fresh"] = False
    elif S["entry"] != "":
        S["entry"] = chop_entry(S["entry"])
    elif len(t) > 0:
        if is_op(last()):
            # "425 ×" + Backspace: zmizi operator a 425 jde dal mazat
            call t.pop()
            if len(t) > 0 and calc.is_number(last()):
                S["entry"] = edit_value(last())
                if S["entry"] != "":
                    # jinak (1/3 ×) zustane cislo jako hotovy operand
                    call t.pop()
                end
            end
        elif last() == "(" or last() == ")":
            call t.pop()
        elif calc.is_number(last()):
            S["entry"] = chop_entry(edit_value(t.pop()))
        end
    elif S["result"] != None and S["prev_tokens"] != None and len(S["prev_tokens"]) > 0:
        # hned po "=": vrati se cely priklad k uprave (425 / 25 = 17, Backspace -> 425 / 25)
        S["tokens"] = S["prev_tokens"]
        S["prev_tokens"] = None
        S["result"] = None
        if calc.is_number(last()):
            S["entry"] = edit_value(last())
            if S["entry"] != "":
                call S["tokens"].pop()
            end
        end
    elif S["result"] != None:
        # samotny vysledek (5 =): maze se po cislicich jako psane cislo
        S["entry"] = chop_entry(edit_value(S["result"]))
        S["result"] = None
    end
    call refresh()
end

# Prubezny vysledek rozpracovaneho prikladu, None kdyz jeste neni co pocitat (jen cislo)
function preview_value():
    toks = S["tokens"].copy()
    entry = S["entry"]
    if entry != "" and entry != "-" and entry != ".":
        n = calc.number(entry)
        if n == None:
            return None
        end
        toks.append(n)
    end
    while len(toks) > 0 and (toks[len(toks) - 1] == "(" or is_op(toks[len(toks) - 1])):
        call toks.pop()
    end
    has_op = False
    depth = 0
    for t in toks:
        if is_op(t):
            has_op = True
        elif not calc.is_number(t):
            if t == "(":
                depth += 1
            elif t == ")":
                depth -= 1
            end
        end
    end
    if not has_op:
        return None
    end
    for i in range(depth):
        toks.append(")")
    end
    value = None
    safe:
        value = calc.evaluate_tokens(toks)
    end
    return value
end

# ---- zobrazeni ---------------------------------------------------------------------------------------------------

function fmt(value):
    return calc.fmt(value, DEC, GROUP)
end

function expression_text(entry):
    parts = []
    for t in S["tokens"]:
        if calc.is_number(t):
            parts.append(fmt(t))
        else:
            parts.append(OPS.get(t, t))
        end
    end
    if entry != None and entry != "":
        parts.append(entry)
    end
    return " ".join(parts).replace("( ", "(").replace(" )", ")")
end

function entry_text():
    entry = S["entry"]
    if entry == "":
        return None
    end
    if S["fresh"]:
        return fmt(calc.number(entry))
    end
    neg = entry.startswith("-")
    body = entry[1:] if neg else entry
    dot = body.find(".")
    whole = body if dot < 0 else body[:dot]
    text = ("-" if neg else "") + calc.group_digits(whole if whole != "" else "0", GROUP, True)
    if dot >= 0:
        text = text + DEC + body[dot + 1:]
    end
    return text
end

# copy = co kopiruje Ctrl+C (None = zobrazeny text)
function show(expr, value, copy):
    S["copy"] = copy if copy != None else value
    call gtk.label_set_text(S["expr"], expr if expr != "" else " ")
    # po "=" a pri chybe; refresh() ho pak doplni
    call gtk.label_set_text(S["preview"], "")
    S["shown"] = value
    call render_value()
    call gtk.button_set_label(S["clear_btn"], "C" if S["entry"] != "" else "AC")
end

function markup(size, text):
    return "<span size=\"" + String(size * 1024) + "\">" + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</span>"
end

# Pocet bajtu znaku v UTF-8 (Pango vraci zacatky radku v bajtech, LSL indexuje znaky)
function utf8_len(ch):
    c = ord(ch)
    if c < 128:
        return 1
    elif c < 2048:
        return 2
    elif c < 65536:
        return 3
    end
    return 4
end

# [velikost pisma, text]: nejvetsi pismo, se kterym se text vejde na jeden radek; kdyz ani nejmensi
# nestaci, zalomi se na nejvys MAX_LINES radku a zacatek se nahradi "…"
function fit_value(text, width):
    unsafe:
        layout = __lsl_qbe_call2(__lsl_symbol("gtk_widget_create_pango_layout"), ptr(S["value"]), 0)
        # PANGO_WRAP_WORD_CHAR
        call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_wrap"), layout, 2)
        cells = __lsl_byte_zeros(16)
        base = __lsl_qbe_load64(__lsl_address(cells) + 24)
        size = 46
        while size >= MIN_SIZE:
            m = markup(size, text)
            call __lsl_qbe_call3(__lsl_symbol("pango_layout_set_markup"), layout, cstr(m), -1)
            call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_width"), layout, -1)
            call __lsl_qbe_call3(__lsl_symbol("pango_layout_get_pixel_size"), layout, base, base + 8)
            if __lsl_qbe_s32(__lsl_qbe_load32(base)) <= width:
                call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), layout)
                return [size, text]
            end
            size -= 2
        end
        call __lsl_qbe_call2(__lsl_symbol("pango_layout_set_width"), layout, ptr(width * 1024))
        m = markup(MIN_SIZE, text)
        call __lsl_qbe_call3(__lsl_symbol("pango_layout_set_markup"), layout, cstr(m), -1)
        if __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_layout_get_line_count"), layout)) > MAX_LINES:
            # nejmene znaku zepredu pryc, aby se veslo
            lo = 1
            hi = len(text) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                m = markup(MIN_SIZE, "…" + text[mid:])
                call __lsl_qbe_call3(__lsl_symbol("pango_layout_set_markup"), layout, cstr(m), -1)
                if __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_layout_get_line_count"), layout)) <= MAX_LINES:
                    hi = mid
                else:
                    lo = mid + 1
                end
            end
            text = "…" + text[lo:]
            m = markup(MIN_SIZE, text)
            call __lsl_qbe_call3(__lsl_symbol("pango_layout_set_markup"), layout, cstr(m), -1)
        end
        # radky podle Pango (bajtove pozice v UTF-8) -> text s "\n"
        count = __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("pango_layout_get_line_count"), layout))
        starts = []
        for i in range(count):
            line = __lsl_qbe_call2(__lsl_symbol("pango_layout_get_line_readonly"), layout, ptr(i))
            starts.append(__lsl_qbe_s32(__lsl_qbe_load32(line + 8)))
        end
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), layout)
    end
    lines = []
    current_line = ""
    byte = 0
    k = 1
    for ch in text:
        if k < len(starts) and byte >= starts[k]:
            lines.append(current_line.strip())
            current_line = ""
            k += 1
        end
        current_line = current_line + ch
        byte += utf8_len(ch)
    end
    lines.append(current_line.strip())
    return [MIN_SIZE, "\n".join(lines)]
end

function label_markup(label):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_label_get_label"), ptr(label)))
    end
end

function allocated_width(widget):
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("gtk_widget_get_allocated_width"), ptr(widget)))
    end
end

function render_value():
    S["fit_pending"] = False
    width = allocated_width(S["value"])
    text = S["shown"]
    size = 46
    if width > 1:
        S["fit_width"] = width
        fit = fit_value(text, width)
        size = fit[0]
        text = fit[1]
    elif len(text) > 9:
        # jeste nerozmistene okno: odhad podle delky
        size = max(MIN_SIZE, 46 - (len(text) - 9) * 3)
    end
    m = markup(size, text)
    if m != label_markup(S["value"]):
        call gtk.label_set_markup(S["value"], m)
        # mene radku (napr. po "=") -> okno zase nizsi
        call gtk.window_resize(S["window"], 1, 1)
    end
    return False
end

function on_value_idle(unused):
    call render_value()
    return False
end

function on_value_allocate(unused, allocation, label):
    if allocated_width(S["value"]) != S["fit_width"] and not S["fit_pending"]:
        S["fit_pending"] = True
        call glib.idle_add_data(on_value_idle, 0)
    end
    return 0
end

function refresh():
    text = entry_text()
    if text == None:
        if S["result"] != None:
            text = fmt(S["result"])
        else:
            text = "0"
            for t in S["tokens"]:
                if calc.is_number(t):
                    text = fmt(t)
                end
            end
        end
    end
    if len(S["tokens"]) > 0:
        # rozepsany priklad na jednom radku: "7 × 9" (horni radek je prazdny)
        call show("", expression_text(entry_text()), text)
    else:
        call show(expression_text(""), text, None)
    end
    value = preview_value()
    call gtk.label_set_text(S["preview"], "= " + fmt(value) if value != None else "")
    call update_ops()
end

function update_ops():
    pending = None
    if S["entry"] == "" and is_op(last()):
        pending = last()
    end
    for op in S["op_buttons"]:
        cls = "selected" if op == "+" or op == "-" or op == "*" or op == "/" else "active"
        if op == pending:
            call gtk.widget_add_class(S["op_buttons"][op], cls)
        else:
            call gtk.widget_remove_class(S["op_buttons"][op], cls)
        end
    end
end

# ---- tlacitka, klavesnice a schranka ---------------------------------------------------------------------------

function on_digit(d, b):
    call digit(d)
    return 0
end

function on_operator(op, b):
    call operator(op)
    return 0
end

function on_action(action, b):
    call act(action)
    return 0
end

function act(action):
    if action == "clear":
        call clear()
    elif action == "negate":
        call negate()
    elif action == "percent":
        call percent()
    elif action == "point":
        call point()
    elif action == "backspace":
        call backspace()
    elif action == "equals":
        call equals()
    elif action == "angle":
        call toggle_angle()
    elif action.startswith("paren"):
        call paren(action[5:])
    elif action.startswith("func "):
        call func(action[5:])
    elif action.startswith("op "):
        call operator(action[3:])
    elif action == "const pi":
        call constant(calc.PI)
    elif action == "const e":
        call constant(calc.E)
    elif action == "const rand":
        call constant(calc.from_float(random.random()))
    end
end

function paste(text):
    if text == None:
        return 0
    end
    text = text.strip().replace(GROUP, "").replace(" ", "").replace(DEC, ".")
    if len(text) > MAX_PASTE:
        return 0
    end
    value = calc.number(text)
    # "NaN", "Infinity" nejsou cisla pro kalkulacku
    if value == None:
        return 0
    end
    if not calc.in_range(value, MAX_PASTE):
        # 1e999999999: mimo rozsah, zadna obri alokace (C-05)
        S["entry"] = ""
        S["fresh"] = False
        call show(expression_text(""), i18n.T("Error"), None)
        return 0
    end
    # 1e5 -> 100000; delsi cislo nez displej se ukaze zaokrouhlene (jako vysledek funkce)
    S["entry"] = calc.exact_text(value)
    S["fresh"] = abs(calc.adjusted(value)) >= 40 or len(bigint_strip(S["entry"].replace("-", "").replace(".", ""))) > MAX_DIGITS
    call refresh()
end

function bigint_strip(digits):
    i = 0
    while i < len(digits) and digits[i] == "0":
        i += 1
    end
    return digits[i:]
end

function on_paste_text(unused, text):
    call paste(text)
    return 0
end

function on_key(unused, event, window):
    return handle_key(gtk.event_key_name(event), gtk.event_key_text(event), (gtk.event_key_state(event) & gtk.CONTROL_MASK) != 0)
end

function is_digit(ch):
    return len(ch) == 1 and ord(ch) >= 48 and ord(ch) <= 57
end

function handle_key(key, ch, ctrl):
    lower = key.lower()
    if ctrl and (key == "1" or key == "2"):
        call set_scientific(key == "2")
    elif ctrl and lower == "c":
        call gtk.selection_set_text(CLIPBOARD, S["copy"])
    elif ctrl and lower == "v":
        call gtk.selection_request_text(CLIPBOARD, on_paste_text, 0)
    elif is_digit(ch):
        call digit(ch)
    elif ch == "." or ch == ",":
        call point()
    elif ch != "" and "+-*/^".find(ch) >= 0:
        call operator(ch)
    elif ch == "(" or ch == ")":
        call paren(ch)
    elif ch == "%":
        call percent()
    elif ch == "!":
        call func("fact")
    elif key == "Return" or key == "KP_Enter" or ch == "=":
        call equals()
    elif key == "BackSpace":
        call backspace()
    elif key == "Escape" or key == "Delete":
        call clear()
    elif ctrl and (lower == "q" or lower == "w"):
        call gtk.window_close(S["window"])
    else:
        return False
    end
    return True
end

function on_destroy(unused, window):
    call gtk.main_quit()
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1) ------------------------------------------------------------------------------

# Skutecna udalost klavesy do okna (projde key-press-event jako stisk na klavesnici): "ctrl+v", "Return", "7"
function press(spec):
    ctrl = spec.startswith("ctrl+")
    name = spec[5:] if ctrl else spec
    unsafe:
        keyval = __lsl_qbe_call1(__lsl_symbol("gdk_keyval_from_name"), __lsl_address(name) + 16)
        if len(name) == 1 and (keyval == 0 or keyval == 16777215):
            keyval = __lsl_qbe_call1(__lsl_symbol("gdk_unicode_to_keyval"), ord(name))
        end
        # GDK_KEY_PRESS
        ev = __lsl_qbe_call1(__lsl_symbol("gdk_event_new"), 8)
        win = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_window"), ptr(S["window"]))
        call __lsl_qbe_store64(ev + 8, __lsl_qbe_call1(__lsl_symbol("g_object_ref"), win))
        call __lsl_qbe_store32(ev + 24, gtk.CONTROL_MASK if ctrl else 0)
        call __lsl_qbe_store32(ev + 28, keyval)
        call __lsl_qbe_call2(__lsl_symbol("gtk_widget_event"), ptr(S["window"]), ev)
        call __lsl_qbe_call1(__lsl_symbol("gdk_event_free"), ev)
    end
end

function button_label(b):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_button_get_label"), ptr(b)))
    end
end

function token_texts():
    out = []
    for t in S["tokens"]:
        out.append(calc.exact_text(t) if calc.is_number(t) else t)
    end
    return out
end

function on_test(command, rest):
    if command == "state":
        pending = []
        for op in S["op_buttons"]:
            if gtk.widget_has_class(S["op_buttons"][op], "selected") or gtk.widget_has_class(S["op_buttons"][op], "active"):
                pending.append(op)
            end
        end
        print "state " + json.encode({"value": gtk.label_get_text(S["value"]), "expr": gtk.label_get_text(S["expr"]),
            "preview": gtk.label_get_text(S["preview"]), "copy": S["copy"],
            "entry": S["entry"], "fresh": S["fresh"], "tokens": token_texts(),
            "result": calc.exact_text(S["result"]) if S["result"] != None else None, "degrees": S["degrees"],
            "scientific": gtk.widget_get_visible(S["sci_grid"]), "clear": button_label(S["clear_btn"]),
            "pending": pending, "size": gtk.window_get_size(S["window"])})
    elif command == "keys":
        # klavesove sekvence testu logiky: cislice, zavorky, "=", ostatni = operator
        for ch in rest:
            if is_digit(ch):
                call digit(ch)
            elif ch == "(" or ch == ")":
                call paren(ch)
            elif ch == "=":
                call equals()
            elif ch == ".":
                call point()
            else:
                call operator(ch)
            end
        end
    elif command == "act":
        call act(rest)
    elif command == "set-entry":
        S["entry"] = rest
        S["fresh"] = False
    elif command == "degrees":
        S["degrees"] = rest == "1"
    elif command == "reset":
        S["tokens"] = []
        S["entry"] = ""
        S["fresh"] = False
        S["result"] = None
        S["prev_tokens"] = None
        S["degrees"] = True
        call gtk.button_set_label(S["angle_btn"], "Deg")
        call refresh()
    elif command == "press":
        for spec in rest.split(" "):
            call press(spec)
        end
    elif command == "type":
        for ch in rest:
            call press(ch)
        end
    elif command == "copy-text":
        call gtk.selection_set_text(CLIPBOARD, rest)
    elif command == "close":
        call gtk.window_close(S["window"])
    end
end

# ---- start ---------------------------------------------------------------------------------------------------------

# WM_CLASS pro dock a horni listu
call glib.set_prgname("luxos-calculator")
call gtk.init()
DEC = locale_decimal_point()
GROUP = chr(8239) if DEC == "," else ","
dark = gtk.settings_theme_name().lower().find("dark") >= 0
call gtk.css_load((DARK if dark else LIGHT) + CSS)
call build()
call gtk.widget_show_all(S["window"])
call testctl.start(on_test)
call gtk.main()
