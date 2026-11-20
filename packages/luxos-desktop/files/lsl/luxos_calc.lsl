# LuxOS - vypocty v hledani Launchpadu ("2+2*3", "2^10", "15% z 300", "sqrt(2)"). Pravidla jako Kalkulacka
# (bin/luxos-calculator, Python s Decimal, takze ji nejde primo pouzit): prednost operatoru, zavorky, procenta
# "200 + 10 %" = 220 (C-19), meze vstupu a cisel misto obrich vypoctu (C-05), uhly ve stupnich jako vychozi
# rezim Kalkulacky. Pocita ve Float a zobrazuje 12 platnych cislic, takze 0,1 + 0,2 = 0,3.
#
#   evaluate(text) -> Float, nebo None kdyz text neni vypocet (jen cislo, slovo, chyba, deleni nulou ...)
#   format(value, sep, group) -> text: sep = desetinny oddelovac jazyka, group = oddelovac tisicu ("" = bez)
load math

MAX_TEXT = 200
MAX_DEPTH = 40
MAX_FACTORIAL = 170
MAX_INT_POWER = 1000
LIMIT = 1.0e300
DIGITS = 12
FUNCTIONS = ["sqrt", "cbrt", "ln", "log", "log2", "sin", "cos", "tan", "abs", "exp"]
CONSTANTS = {"pi": math.PI, "e": math.E}
# "15 % z 300", "15% of 300"
OF_WORDS = ["z", "ze", "of"]
# mezera, tabulator, nedelitelna a uzka nedelitelna mezera (oddelovac tisicu v cestine)
SPACES = [" ", "\t", chr(160), chr(8239)]
SYMBOLS = {"×": "*", "·": "*", "÷": "/", ":": "/", "−": "-", "√": "sqrt", "π": "pi"}

function is_digit(ch):
    code = ord(ch)
    return code >= 48 and code <= 57
end

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
            if literal.startswith("."):
                literal = "0" + literal
            end
            if literal.endswith("."):
                literal = literal + "0"
            end
            out.append(["num", Float(literal)])
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

function fail():
    Error(ValueError: "not an expression")
end

function finite(v):
    if v != v or abs(v) > LIMIT:
        call fail()
    end
    return v
end

function power(a, b):
    if b == Float(Int(b)) and abs(b) <= MAX_INT_POWER:
        k = Int(abs(b))
        if a == 0.0 and b < 0.0:
            call fail()
        end
        result = 1.0
        base = a
        # umocnovani ctvercem, hlidane po kazdem kroku (1e200^1000 nesmi pretect do inf)
        while k > 0:
            if k % 2 == 1:
                result = finite(result * base)
            end
            k = k // 2
            if k > 0:
                base = finite(base * base)
            end
        end
        if b < 0.0:
            return 1.0 / result
        end
        return result
    end
    if a < 0.0:
        call fail()
    end
    if a == 0.0:
        if b > 0.0:
            return 0.0
        end
        call fail()
    end
    exponent = b * math.log(a)
    if exponent > 690.0:
        call fail()
    end
    return math.exp(exponent)
end

# Stupne; presne nasobky 90 davaji presne 0, 1, -1 (sin 180 = 0, ne 1,2e-16)
function trig(name, degrees):
    turn = degrees - 360.0 * math.floor(degrees / 360.0)
    quarter = turn / 90.0
    if quarter == Float(Int(quarter)):
        q = Int(quarter) % 4
        if name == "sin":
            return [0.0, 1.0, 0.0, -1.0][q]
        elif name == "cos":
            return [1.0, 0.0, -1.0, 0.0][q]
        end
        if q % 2 == 1:
            call fail()
        end
        return 0.0
    end
    r = turn * math.PI / 180.0
    if name == "sin":
        return math.sin(r)
    elif name == "cos":
        return math.cos(r)
    end
    return math.sin(r) / math.cos(r)
end

function apply(name, x):
    if name == "sqrt":
        if x < 0.0:
            call fail()
        end
        return sqrt(x)
    elif name == "cbrt":
        if x < 0.0:
            return -power(-x, 1.0 / 3.0)
        end
        return power(x, 1.0 / 3.0)
    elif name == "ln" or name == "log" or name == "log2":
        if x <= 0.0:
            call fail()
        end
        if name == "log":
            return math.log10(x)
        elif name == "log2":
            return math.log2(x)
        end
        return math.log(x)
    elif name == "abs":
        return abs(x)
    elif name == "exp":
        if x > 690.0:
            call fail()
        end
        return math.exp(x)
    end
    return trig(name, x)
end

function factorial(x):
    if x < 0.0 or x != Float(Int(x)) or x > Float(MAX_FACTORIAL):
        call fail()
    end
    result = 1.0
    for k in range(2, Int(x) + 1):
        result *= Float(k)
    end
    return result
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
            value = left[0] * right[2] / 100.0
        end
        if tok[1] == "+":
            left = [finite(left[0] + value), False, 0.0]
        else:
            left = [finite(left[0] - value), False, 0.0]
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
                left = [finite(left[0] * right), False, 0.0]
            else:
                if right == 0.0:
                    call fail()
                end
                left = [finite(left[0] / right), False, 0.0]
            end
        elif left[1] and tok[0] == "name" and tok[1] in OF_WORDS:
            st["i"] += 1
            st["ops"] += 1
            left = [finite(left[0] * parse_unary(st)[0]), False, 0.0]
        elif tok[0] == "name" or is_op(tok, "("):
            # 2pi, 3(4+1), 2 sqrt(2); dve cisla vedle sebe ("1 000") vypocet nejsou
            st["ops"] += 1
            right = parse_unary(st)[0]
            left = [finite(left[0] * right), False, 0.0]
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
            return [-inner[0], inner[1], -inner[2]]
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
        return [finite(power(base[0], exponent)), False, 0.0]
    end
    return base
end

function parse_postfix(st):
    value = parse_atom(st)
    percent = False
    raw = 0.0
    while True:
        tok = peek(st)
        if is_op(tok, "!"):
            st["i"] += 1
            st["ops"] += 1
            value = factorial(value)
            percent = False
        elif is_op(tok, "%"):
            st["i"] += 1
            st["ops"] += 1
            raw = value
            value = value / 100.0
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

# ---- zobrazeni ----

function group_digits(digits, group):
    # ctyrmistna cisla se v cestine (mezera) neoddeluji, v anglictine ano (1,234)
    if group == "" or len(digits) <= 3 or (len(digits) == 4 and group != ","):
        return digits
    end
    out = ""
    while len(digits) > 3:
        out = group + digits[len(digits) - 3:] + out
        digits = digits[0:len(digits) - 3]
    end
    return digits + out
end

# Cela cast a desetinna cast jako cisla v textu (bez exponentu, ktery by dal String(Float))
function fixed(a, places):
    scale = 10 ^ places
    n = Int(math.round(a * Float(scale)))
    whole = String(n // scale)
    frac = String(n % scale)
    while len(frac) < places:
        frac = "0" + frac
    end
    while frac.endswith("0"):
        frac = frac[0:len(frac) - 1]
    end
    return [whole, frac]
end

function format(value, sep, group):
    if value == 0.0:
        return "0"
    end
    sign = ""
    if value < 0.0:
        sign = "-"
    end
    a = abs(value)
    magnitude = Int(math.floor(math.log10(a)))
    if a >= 1.0e15 or a < 1.0e-9:
        mantissa = a / power(10.0, Float(magnitude))
        # 9,9999999999 se zaokrouhli na 10
        parts = fixed(mantissa, 8)
        if parts[0] == "10":
            parts = ["1", ""]
            magnitude += 1
        end
        text = parts[0]
        if parts[1] != "":
            text = text + sep + parts[1]
        end
        return sign + text + "e" + String(magnitude)
    end
    places = max(0, min(DIGITS, DIGITS - 1 - magnitude))
    parts = fixed(a, places)
    if parts[0] == "0" and parts[1] == "":
        return "0"
    end
    text = group_digits(parts[0], group)
    if parts[1] != "":
        text = text + sep + parts[1]
    end
    return sign + text
end
