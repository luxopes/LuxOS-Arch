# LuxOS - pocitani Kalkulacky (luxos-calculator) a vypoctu v hledani Launchpadu ("2+2*3", "15% z 300").
#
# Desitkova aritmetika jako Decimal v Pythonu (drivejsi Kalkulacka): 34 platnych cislic, zaokrouhleni
# polovina k sude, exponent do +-999999, takze 0,1 + 0,2 = 0,3 a 1234567890123,45 - 1234567890123 = 0,45.
# Funkce bez presne desitkove podoby (sin, ln, e^x, obecna mocnina) pocita libm ve Float a vysledek
# se vezme na 15 platnych cislic (bez sumu 0,49999999999999994).
#
# Cislo je [zaporne, cislice, exponent]: hodnota = (-1)^zaporne * cislice * 10^exponent.
#   number(text) -> cislo nebo None          value_text(cislo) -> text bez exponentu ("f" v Pythonu)
#   add sub mul div power compute(nazev, x, stupne) -> cislo; chyba (deleni nulou, mimo rozsah) = fail()
#   evaluate_tokens(seznam cisel, operatoru a zavorek) -> cislo        fmt(cislo, desetinny, tisice) -> displej
# Launchpad:
#   evaluate(text) -> cislo, nebo None kdyz text neni vypocet (jen cislo, slovo, chyba, deleni nulou ...)
#   format(cislo nebo Float, sep, group) -> text: sep = desetinny oddelovac jazyka, group = oddelovac tisicu
load bigint

PREC = 34
EMAX = 999999
ETINY = -999999 - PREC + 1
# Kalkulacka: mocnina celym exponentem presne do 10000, faktorial do 1000
MAX_INT_POWER = 10000
MAX_FACTORIAL = 1000
ZERO = [False, "0", 0]
ONE = [False, "1", 0]

lib = {"tried": False, "fns": {}}

function fail():
    Error(ValueError: "not a number")
end

# ---- cisla --------------------------------------------------------------------------------------------------------

function make(neg, digits, exp):
    digits = bigint._strip_leading_zeros(digits)
    if digits == "0":
        return ZERO
    end
    return [neg, digits, exp]
end

function from_int(n):
    if n < 0:
        return make(True, String(-n), 0)
    end
    return make(False, String(n), 0)
end

function is_zero(x):
    return x[1] == "0"
end

function adjusted(x):
    return x[2] + len(x[1]) - 1
end

function negate(x):
    if is_zero(x):
        return x
    end
    return [not x[0], x[1], x[2]]
end

function absolute(x):
    return [False, x[1], x[2]]
end

# "1"+"5" -> "16", "99" -> "100"
function increment(digits):
    return bigint._add_magnitude(digits, "1") if digits != "" else "1"
end

# Cislice zaokrouhlene na keep mist polovinou k sude -> [cislice, o kolik vzrostl exponent]
function round_digits(digits, keep):
    n = len(digits)
    if n <= keep:
        return [digits, 0]
    end
    if keep < 0:
        return ["0", n]
    end
    head = digits[:keep]
    first = ord(digits[keep]) - 48
    up = first > 5
    if first == 5:
        up = digits[keep + 1:].rstrip("0") != "" or (keep > 0 and (ord(head[keep - 1]) - 48) % 2 == 1)
    end
    if up:
        head = increment(head)
    end
    if head == "":
        head = "0"
    end
    return [head, n - keep]
end

# Vysledek operace: zaokrouhlit na prec cislic, bez koncovych nul, hlidat rozsah (preteceni = chyba,
# podteceni = nula jako v Pythonu bez pasti Underflow)
function finish(neg, digits, exp, prec):
    r = round_digits(bigint._strip_leading_zeros(digits), prec)
    digits = r[0]
    exp += r[1]
    stripped = digits.rstrip("0")
    if stripped == "":
        return ZERO
    end
    exp += len(digits) - len(stripped)
    if exp + len(stripped) - 1 > EMAX:
        call fail()
    end
    if exp + len(stripped) - 1 < ETINY:
        return ZERO
    end
    return [neg, stripped, exp]
end

function rounded(x, prec):
    return finish(x[0], x[1], x[2], prec)
end

function shifted(digits, k):
    if k <= 0 or digits == "0":
        return digits
    end
    return digits + "0" * k
end

function compare(a, b):
    if is_zero(a) and is_zero(b):
        return 0
    end
    sa = 0 if is_zero(a) else (-1 if a[0] else 1)
    sb = 0 if is_zero(b) else (-1 if b[0] else 1)
    if sa != sb:
        return -1 if sa < sb else 1
    end
    c = 0
    if adjusted(a) != adjusted(b):
        c = -1 if adjusted(a) < adjusted(b) else 1
    else:
        e = min(a[2], b[2])
        c = bigint._compare_magnitude(shifted(a[1], a[2] - e), shifted(b[1], b[2] - e))
    end
    return -c if sa < 0 else c
end

function add_prec(a, b, prec):
    if is_zero(a):
        return rounded(b, prec)
    end
    if is_zero(b):
        return rounded(a, prec)
    end
    if adjusted(b) > adjusted(a):
        t = a
        a = b
        b = t
    end
    # b daleko pod zaokrouhlenim a: misto obriho zarovnani (1e999999 + 1) jen "neco malo" pod posledni cislici
    sticky = min(a[2], adjusted(a) - prec - 2) - 1
    if adjusted(b) + 1 <= sticky:
        b = [b[0], "1", sticky]
    end
    e = min(a[2], b[2])
    da = shifted(a[1], a[2] - e)
    db = shifted(b[1], b[2] - e)
    if a[0] == b[0]:
        return finish(a[0], bigint._add_magnitude(da, db), e, prec)
    end
    c = bigint._compare_magnitude(da, db)
    if c == 0:
        return ZERO
    elif c > 0:
        return finish(a[0], bigint._subtract_magnitude(da, db), e, prec)
    end
    return finish(b[0], bigint._subtract_magnitude(db, da), e, prec)
end

function add(a, b):
    return add_prec(a, b, PREC)
end

function sub(a, b):
    return add_prec(a, negate(b), PREC)
end

function mul_prec(a, b, prec):
    if is_zero(a) or is_zero(b):
        return ZERO
    end
    if adjusted(a) + adjusted(b) > EMAX + 1:
        call fail()
    end
    if adjusted(a) + adjusted(b) < ETINY - 2:
        return ZERO
    end
    return finish(a[0] != b[0], bigint._multiply_magnitude(a[1], b[1]), a[2] + b[2], prec)
end

function mul(a, b):
    return mul_prec(a, b, PREC)
end

function div_prec(a, b, prec):
    if is_zero(b):
        call fail()
    end
    if is_zero(a):
        return ZERO
    end
    # podil na prec + 1 cislic, nenulovy zbytek jako posledni cislice 1 (spravne zaokrouhleni)
    k = max(0, len(b[1]) - len(a[1]) + prec + 1)
    qr = bigint._divmod_magnitude(shifted(a[1], k), b[1])
    q = qr[0]
    exp = a[2] - b[2] - k
    if qr[1] != "0":
        q = q + "1"
        exp -= 1
    end
    return finish(a[0] != b[0], q, exp, prec)
end

function div(a, b):
    return div_prec(a, b, PREC)
end

function is_integer(x):
    return x[2] >= 0 or x[1][max(0, len(x[1]) + x[2]):].rstrip("0") == ""
end

# Cele cislo je liche (jen pro is_integer(x))
function is_odd(x):
    if x[2] > 0 or len(x[1]) + x[2] <= 0:
        return False
    end
    return (ord(x[1][len(x[1]) + x[2] - 1]) - 48) % 2 == 1
end

# Nejblizsi cele cislo (polovina k sude, to_integral_value v Pythonu)
function to_integral(x):
    if x[2] >= 0 or is_zero(x):
        return x
    end
    drop = -x[2]
    digits = x[1]
    if drop > len(digits):
        return ZERO
    end
    r = round_digits(digits, len(digits) - drop)
    return finish(x[0], r[0], 0, len(r[0]) + 1)
end

# Cele cislo jako Int (jen male hodnoty: exponent mocniny, faktorial, ctvrtina otacky)
function to_int(x):
    n = Int(shifted(x[1], x[2]) if x[2] >= 0 else x[1][:len(x[1]) + x[2]])
    return -n if x[0] else n
end

function sqrt_dec(x):
    if x[0] and not is_zero(x):
        call fail()
    end
    if is_zero(x):
        return ZERO
    end
    # odmocnina z cislic s alespon 2 * (PREC + 1) misty a sudym exponentem
    k = max(0, 2 * (PREC + 1) - len(x[1]))
    if (x[2] - k) % 2 != 0:
        k += 1
    end
    n = shifted(x[1], k)
    s = isqrt(n)
    exp = (x[2] - k) // 2
    if bigint._multiply_magnitude(s, s) != n:
        s = s + "1"
        exp -= 1
    end
    return finish(False, s, exp, PREC)
end

# Cela odmocnina retezce cislic (Newton shora)
function isqrt(n):
    x = "1" + "0" * ((len(n) + 1) // 2)
    while True:
        y = bigint._divmod_magnitude(bigint._add_magnitude(x, bigint._divmod_magnitude(n, x)[0]), "2")[0]
        if bigint._compare_magnitude(y, x) >= 0:
            return x
        end
        x = y
    end
end

# ---- text --------------------------------------------------------------------------------------------------------

function is_digit(ch):
    code = ord(ch)
    return code >= 48 and code <= 57
end

# "12.5", "-1e5", "2E+500", ".5", "1." -> cislo; None kdyz to cislo neni (NaN, Infinity, slovo ...)
function number(text):
    s = text.strip()
    neg = False
    if s.startswith("-") or s.startswith("+"):
        neg = s.startswith("-")
        s = s[1:]
    end
    cut = s.find("e")
    if cut < 0:
        cut = s.find("E")
    end
    exp = 0
    if cut >= 0:
        tail = s[cut + 1:]
        s = s[:cut]
        exp_neg = tail.startswith("-")
        if tail.startswith("-") or tail.startswith("+"):
            tail = tail[1:]
        end
        if tail == "" or len(tail) > 300:
            return None
        end
        for ch in tail:
            if not is_digit(ch):
                return None
            end
        end
        tail = bigint._strip_leading_zeros(tail)
        # obri exponent je mimo rozsah tak jako tak (in_range), Int nesmi pretect
        exp = Int(tail) if len(tail) < 16 else 1000000000000000
        if exp_neg:
            exp = -exp
        end
    end
    dot = s.find(".")
    whole = s
    frac = ""
    if dot >= 0:
        whole = s[:dot]
        frac = s[dot + 1:]
    end
    if whole + frac == "":
        return None
    end
    for ch in whole + frac:
        if not is_digit(ch):
            return None
        end
    end
    digits = bigint._strip_leading_zeros(whole + frac)
    if digits == "0":
        return ZERO
    end
    return [neg, digits, exp - len(frac)]
end

# Hodnota bez exponentu (format(x, "f")); cislice zustanou, jak jsou (1.50 zustane 1.50)
function value_text(x):
    digits = x[1]
    sign = "-" if x[0] else ""
    if x[2] >= 0:
        return sign + shifted(digits, x[2])
    end
    point = len(digits) + x[2]
    if point > 0:
        return sign + digits[:point] + "." + digits[point:]
    end
    return sign + "0." + "0" * (-point) + digits
end

# Text, ze ktereho number() vrati totez cislo (i s obrim exponentem)
function exact_text(x):
    if abs(adjusted(x)) < 40:
        return value_text(x)
    end
    return ("-" if x[0] else "") + x[1] + "e" + String(x[2])
end

# Cislo ze schranky v rozsahu aritmetiky (exponent i pocet cislic omezene)
function in_range(x, max_digits):
    return len(x[1]) <= max_digits and (is_zero(x) or (adjusted(x) >= ETINY and adjusted(x) <= EMAX))
end

# ---- Float a libm -----------------------------------------------------------------------------------------------

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

# Funkce libm (stejne jako modul math Pythonu); knihovna je v procesu GTK stejne nactena
function libm(name):
    if not lib["tried"]:
        lib["tried"] = True
        unsafe:
            # RTLD_NOW
            handle = __lsl_qbe_call2(__lsl_symbol("dlopen"), cstr("libm.so.6"), 2)
        end
        if handle != 0:
            for symbol in ["sin", "cos", "tan", "asin", "acos", "atan", "exp", "log", "log10", "log2", "pow", "tgamma"]:
                unsafe:
                    lib["fns"][symbol] = __lsl_qbe_call2(__lsl_symbol("dlsym"), handle, cstr(symbol))
                end
            end
        end
    end
    address = lib["fns"].get(name, 0)
    if address == 0:
        call fail()
    end
    return ptr(address)
end

function f1(name, x):
    unsafe:
        return __lsl_qbe_fcall1(libm(name), Float(x))
    end
end

function f2(name, x, y):
    unsafe:
        return __lsl_qbe_fcall2(libm(name), Float(x), Float(y))
    end
end

function to_float(x):
    return Float(("-" if x[0] else "") + x[1] + "e" + String(x[2]))
end

# Float -> cislo na 15 platnych cislic presne zaokrouhlenych z binarni hodnoty ("%.15g" v Pythonu, bez sumu
# 0,49999999999999994); nekonecno a NaN jsou chyba
function from_float(f):
    if f != f or f - f != 0.0:
        call fail()
    end
    unsafe:
        buffer = __lsl_byte_zeros(64)
        n = __lsl_qbe_s32(__lsl_qbe_call4(__lsl_symbol("strfromd"), __lsl_qbe_load64(__lsl_address(buffer) + 24), 64, cstr("%.14e"), Float(f)))
        text = __lsl_text_from_bytes(buffer, 0, n)
    end
    x = number(text)
    if x == None:
        call fail()
    end
    return rounded(x, 15)
end

# ---- Kalkulacka ----------------------------------------------------------------------------------------------------

PI = number("3.14159265358979323846264338327950")
E = number("2.71828182845904523536028747135266")
RIGHT_DEG = from_int(90)
RIGHT_RAD = div(PI, from_int(2))
TINY = number("1e-30")
QUARTER_LIMIT = number("4e34")
DEG_TO_RAD = 3.141592653589793 / 180.0
RAD_TO_DEG = 180.0 / 3.141592653589793

function int_power(a, n):
    if is_zero(a) and n == 0:
        call fail()
    end
    k = abs(n)
    # pracovni presnost s rezervou; vysledek se zaokrouhli jednou na PREC
    work = PREC + 10 + len(String(k))
    result = ONE
    base = a
    while k > 0:
        if k % 2 == 1:
            result = mul_prec(result, base, work)
        end
        k = k // 2
        if k > 0:
            base = mul_prec(base, base, work)
        end
    end
    if n < 0:
        return div(ONE, result)
    end
    return rounded(result, PREC)
end

function power(a, b):
    if is_integer(b) and compare(absolute(b), from_int(MAX_INT_POWER)) <= 0:
        if is_zero(a) and b[0]:
            call fail()
        end
        return int_power(a, to_int(b))
    end
    if a[0]:
        call fail()
    end
    return from_float(f2("pow", to_float(a), to_float(b)))
end

function apply_op(op, a, b):
    if op == "+":
        return add(a, b)
    elif op == "-":
        return sub(a, b)
    elif op == "*":
        return mul(a, b)
    elif op == "/":
        return div(a, b)
    elif op == "^":
        return power(a, b)
    elif op == "root":
        # a y-root b = b-ta odmocnina z a
        if is_zero(b):
            call fail()
        end
        if a[0] and is_integer(b) and is_odd(b):
            return negate(power(negate(a), div(ONE, b)))
        end
        return power(a, div(ONE, b))
    end
    call fail()
end

# sin/cos/tan: presne nuly (a 1, -1) jen pro presne uhly - nasobky 90 stupnu, v radianech nasobky pi/2
# (s toleranci na presnost konstanty pi); jinak skutecna hodnota, i velmi mala (vedecky zapis).
# x = q * (pravy uhel) + r, |r| <= polovina praveho uhlu; zbytek v desitkove aritmetice, aby
# sin(180,0000000001 stupne) nezanikl v chybe zaokrouhleni pi ve float
function trig(name, x, degrees):
    right = RIGHT_DEG if degrees else RIGHT_RAD
    q = to_integral(div(x, right))
    # ctvrtina otacky (q % 4 v Pythonu) jde jen u podilu do 34 cislic, vetsi uhel je chyba
    if compare(absolute(q), QUARTER_LIMIT) >= 0:
        call fail()
    end
    r = sub(x, mul(q, right))
    quarter = 0
    if q[2] < 2:
        last = q[1][max(0, len(q[1]) - 3):]
        quarter = (Int(last) * (10 ^ q[2])) % 4
        if q[0]:
            quarter = (4 - quarter) % 4
        end
    end
    if is_zero(r) or (not degrees and compare(absolute(r), TINY) < 0):
        if name == "sin":
            return from_int([0, 1, 0, -1][quarter])
        elif name == "cos":
            return from_int([1, 0, -1, 0][quarter])
        end
        if quarter % 2 == 1:
            # tan(90 stupnu) neexistuje
            call fail()
        end
        return ZERO
    end
    a = to_float(r)
    if degrees:
        a = a * DEG_TO_RAD
    end
    s = f1("sin", a)
    c = f1("cos", a)
    sin_v = [s, c, -s, -c][quarter]
    cos_v = [c, -s, -c, s][quarter]
    if name == "sin":
        return from_float(sin_v)
    elif name == "cos":
        return from_float(cos_v)
    end
    return from_float(sin_v / cos_v)
end

function factorial(n):
    result = ONE
    # do ~40! presne, dal 50 cislic (zobrazuje se 15, pocita 34)
    for k in range(2, n + 1):
        result = mul_prec(result, from_int(k), 50)
    end
    return result
end

# Funkce jedne promenne (tlacitka vedeckeho rezimu); degrees = uhly ve stupnich
function compute(name, x, degrees):
    f = to_float(x)
    if name == "sq":
        return mul(x, x)
    elif name == "cube":
        return mul(mul(x, x), x)
    elif name == "inv":
        return div(ONE, x)
    elif name == "sqrt":
        return sqrt_dec(x)
    elif name == "cbrt":
        r = f2("pow", abs(f), 1.0 / 3.0)
        return from_float(-r if f < 0.0 else r)
    elif name == "abs":
        return absolute(x)
    elif name == "exp":
        return from_float(f1("exp", f))
    elif name == "exp10":
        return power(from_int(10), x)
    elif name == "ln" or name == "log10" or name == "log2":
        if f <= 0.0:
            call fail()
        end
        return from_float(f1("log" if name == "ln" else name, f))
    elif name == "fact":
        if is_integer(x) and not x[0] and compare(x, from_int(MAX_FACTORIAL)) <= 0:
            return factorial(to_int(x))
        end
        return from_float(f1("tgamma", f + 1.0))
    elif name == "sin" or name == "cos" or name == "tan":
        return trig(name, x, degrees)
    elif name == "asin" or name == "acos" or name == "atan":
        v = f1(name, f)
        return from_float(v * RAD_TO_DEG if degrees else v)
    end
    call fail()
end

PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2, "^": 3, "root": 3}

function is_number(token):
    return type(token) == "List"
end

# Cisla, operatory a zavorky Kalkulacky (shunting-yard s prednosti operatoru, ^ a root zprava)
function evaluate_tokens(tokens):
    out = []
    ops = []
    for t in tokens:
        if is_number(t):
            out.append(t)
        elif t == "(":
            ops.append(t)
        elif t == ")":
            while len(ops) > 0 and ops[len(ops) - 1] != "(":
                call reduce_top(out, ops)
            end
            if len(ops) > 0:
                call ops.pop()
            end
        else:
            while len(ops) > 0 and ops[len(ops) - 1] != "(" and (PRECEDENCE[ops[len(ops) - 1]] > PRECEDENCE[t] or (PRECEDENCE[ops[len(ops) - 1]] == PRECEDENCE[t] and t != "^" and t != "root")):
                call reduce_top(out, ops)
            end
            ops.append(t)
        end
    end
    while len(ops) > 0:
        if ops[len(ops) - 1] == "(":
            call ops.pop()
        else:
            call reduce_top(out, ops)
        end
    end
    if len(out) != 1:
        call fail()
    end
    return out[0]
end

function reduce_top(out, ops):
    if len(out) < 2:
        call fail()
    end
    op = ops.pop()
    b = out.pop()
    a = out.pop()
    out.append(apply_op(op, a, b))
end

# ---- zobrazeni ---------------------------------------------------------------------------------------------------

# Cela cast po trojicich: group = oddelovac ("" = bez), short = i ctyrmistna cisla (1 234)
function group_digits(digits, group, short):
    if group == "" or len(digits) <= 3 or (len(digits) == 4 and not short):
        return digits
    end
    out = ""
    while len(digits) > 3:
        out = group + digits[len(digits) - 3:] + out
        digits = digits[:len(digits) - 3]
    end
    return digits + out
end

# Cislo -> text: vedecky zapis s 8 desetinnymi misty od 10^sci_high a pod 10^sci_low, jinak nejvys
# min(cap, base - rad) desetinnych mist
function show(x, sep, group, short, cap, base, sci_low):
    if is_zero(x):
        return "0"
    end
    sign = "-" if x[0] else ""
    exp = adjusted(x)
    if exp >= 15 or exp < sci_low:
        r = round_digits(x[1], 9)
        mant = r[0]
        if len(mant) > 9:
            mant = mant[:9]
            exp += 1
        end
        mant = mant.rstrip("0")
        if len(mant) > 1:
            mant = mant[:1] + sep + mant[1:]
        end
        return sign + mant + "e" + String(exp)
    end
    places = max(0, min(cap, base - exp))
    keep = len(x[1]) + x[2] + places
    r = round_digits(x[1], keep)
    q = finish(x[0], r[0], x[2] + r[1], len(r[0]) + 1)
    if is_zero(q):
        return "0"
    end
    text = value_text(absolute(q))
    dot = text.find(".")
    if dot < 0:
        return sign + group_digits(text, group, short)
    end
    return sign + group_digits(text[:dot], group, short) + sep + text[dot + 1:]
end

# Displej Kalkulacky: 15 platnych cislic, vedecky od 10^15 a pod 10^-8, tisice vzdy oddelene
function fmt(x, sep, group):
    return show(x, sep, group, True, 14, 14, -8)
end

# Vysledek v Launchpadu: 12 platnych cislic, vedecky od 10^15 a pod 10^-9, ctyrmistna cisla v cestine
# bez oddelovace
function format(value, sep, group):
    if type(value) == "Float":
        if value == 0.0:
            return "0"
        end
        value = number(String(value))
    end
    return show(value, sep, group, group == ",", 12, 11, -9)
end

# ---- vypocty v hledani Launchpadu --------------------------------------------------------------------------------
# Pravidla jako Kalkulacka: prednost operatoru, zavorky, procenta "200 + 10 %" = 220 (C-19), uhly ve stupnich.
# Meze vstupu a cisel misto obrich vypoctu (C-05).

MAX_TEXT = 200
MAX_DEPTH = 40
LP_FACTORIAL = 170
LIMIT = number("1e300")
FUNCTIONS = ["sqrt", "cbrt", "ln", "log", "log2", "sin", "cos", "tan", "abs", "exp"]
CONSTANTS = {"pi": PI, "e": E}
# "15 % z 300", "15% of 300"
OF_WORDS = ["z", "ze", "of"]
# mezera, tabulator, nedelitelna a uzka nedelitelna mezera (oddelovac tisicu v cestine)
SPACES = [" ", "\t", chr(160), chr(8239)]
SYMBOLS = {"×": "*", "·": "*", "÷": "/", ":": "/", "−": "-", "√": "sqrt", "π": "pi"}
HUNDRED = from_int(100)

function is_letter(ch):
    code = ord(ch)
    return (code >= 97 and code <= 122) or (code >= 65 and code <= 90)
end

# Text -> seznam [druh, hodnota]: num, name, op (+ - * / ^ % ! ( )); None pri neznamem znaku
function tokens(text):
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in SYMBOLS:
            ch = SYMBOLS[ch]
        end
        if ch in SPACES:
            i += 1
        elif is_digit(ch) or ch == "." or ch == ",":
            start = i
            seps = 0
            while i < n and (is_digit(text[i]) or text[i] == "." or text[i] == ","):
                if not is_digit(text[i]):
                    seps += 1
                end
                i += 1
            end
            literal = text[start:i].replace(",", ".")
            if seps > 1 or literal == ".":
                return None
            end
            out.append(["num", number(literal)])
        elif ch == "sqrt" or ch == "pi":
            # √ a π: jmeno z jednoho znaku (pred is_letter, ten by z "sqrt" videl jen "s" a necetl dal)
            out.append(["name", ch])
            i += 1
        elif is_letter(text[i]):
            start = i
            while i < n and is_letter(text[i]):
                i += 1
            end
            out.append(["name", text[start:i].lower()])
        elif ch == "*" and i + 1 < n and text[i + 1] == "*":
            out.append(["op", "^"])
            i += 2
        elif ch in ["+", "-", "*", "/", "^", "%", "!", "(", ")"]:
            out.append(["op", ch])
            i += 1
        else:
            return None
        end
    end
    return out
end

function peek(st):
    if st["i"] < len(st["t"]):
        return st["t"][st["i"]]
    end
    return ["end", ""]
end

function is_op(tok, op):
    return tok[0] == "op" and tok[1] == op
end

function finite(v):
    if compare(absolute(v), LIMIT) > 0:
        call fail()
    end
    return v
end

function apply(name, x):
    if name == "log":
        return compute("log10", x, True)
    end
    return compute(name, x, True)
end

# soucet: "a + b %" je a + a * b / 100 (Kalkulacka C-19)
function parse_sum(st):
    left = parse_product(st)
    while True:
        tok = peek(st)
        if not (is_op(tok, "+") or is_op(tok, "-")):
            return left[0]
        end
        st["i"] += 1
        st["ops"] += 1
        right = parse_product(st)
        value = right[0]
        if right[1]:
            value = div(mul(left[0], right[2]), HUNDRED)
        end
        if tok[1] == "+":
            left = [finite(add(left[0], value)), False, ZERO]
        else:
            left = [finite(sub(left[0], value)), False, ZERO]
        end
    end
end

# soucin -> [hodnota, je procento, cislo pred %]
function parse_product(st):
    left = parse_unary(st)
    while True:
        tok = peek(st)
        if is_op(tok, "*") or is_op(tok, "/"):
            st["i"] += 1
            st["ops"] += 1
            right = parse_unary(st)[0]
            if tok[1] == "*":
                left = [finite(mul(left[0], right)), False, ZERO]
            else:
                left = [finite(div(left[0], right)), False, ZERO]
            end
        elif left[1] and tok[0] == "name" and tok[1] in OF_WORDS:
            st["i"] += 1
            st["ops"] += 1
            left = [finite(mul(left[0], parse_unary(st)[0])), False, ZERO]
        elif tok[0] == "name" or is_op(tok, "("):
            # 2pi, 3(4+1), 2 sqrt(2); dve cisla vedle sebe ("1 000") vypocet nejsou
            st["ops"] += 1
            right = parse_unary(st)[0]
            left = [finite(mul(left[0], right)), False, ZERO]
        else:
            return left
        end
    end
end

function parse_unary(st):
    tok = peek(st)
    if is_op(tok, "-") or is_op(tok, "+"):
        st["i"] += 1
        inner = parse_unary(st)
        if tok[1] == "-":
            return [negate(inner[0]), inner[1], negate(inner[2])]
        end
        return inner
    end
    return parse_power(st)
end

# mocnina zprava: 2^3^2 = 2^9, -2^2 = -4 (unarni minus ma mensi prednost)
function parse_power(st):
    base = parse_postfix(st)
    if is_op(peek(st), "^"):
        st["i"] += 1
        st["ops"] += 1
        exponent = parse_unary(st)[0]
        return [finite(power(base[0], exponent)), False, ZERO]
    end
    return base
end

function parse_postfix(st):
    value = parse_atom(st)
    percent = False
    raw = ZERO
    while True:
        tok = peek(st)
        if is_op(tok, "!"):
            st["i"] += 1
            st["ops"] += 1
            if value[0] or not is_integer(value) or compare(value, from_int(LP_FACTORIAL)) > 0:
                call fail()
            end
            value = factorial(to_int(value))
            percent = False
        elif is_op(tok, "%"):
            st["i"] += 1
            st["ops"] += 1
            raw = value
            value = div(value, HUNDRED)
            percent = True
        else:
            return [value, percent, raw]
        end
    end
end

function parse_atom(st):
    tok = peek(st)
    st["i"] += 1
    if tok[0] == "num":
        return tok[1]
    elif tok[0] == "name" and tok[1] in CONSTANTS:
        return CONSTANTS[tok[1]]
    elif tok[0] == "name" and tok[1] in FUNCTIONS:
        st["ops"] += 1
        return finite(apply(tok[1], parse_power(st)[0]))
    elif is_op(tok, "("):
        st["depth"] += 1
        if st["depth"] > MAX_DEPTH:
            call fail()
        end
        value = parse_sum(st)
        st["depth"] -= 1
        # chybejici zaviraci zavorka na konci se doplni ("sqrt(2")
        if is_op(peek(st), ")"):
            st["i"] += 1
        elif peek(st)[0] != "end":
            call fail()
        end
        return value
    end
    call fail()
end

function evaluate(text):
    if len(text) > MAX_TEXT:
        return None
    end
    toks = tokens(text.strip())
    if toks == None or len(toks) == 0:
        return None
    end
    has_number = False
    for tok in toks:
        if tok[0] == "num" or (tok[0] == "name" and tok[1] in CONSTANTS):
            has_number = True
        elif tok[0] == "name" and not (tok[1] in FUNCTIONS or tok[1] in OF_WORDS):
            return None
        end
    end
    if not has_number:
        return None
    end
    st = {"t": toks, "i": 0, "depth": 0, "ops": 0}
    value = None
    safe:
        value = parse_sum(st)
    end
    # samotne cislo nebo konstanta neni vypocet
    if value == None or st["i"] != len(toks) or st["ops"] == 0:
        return None
    end
    return value
end
