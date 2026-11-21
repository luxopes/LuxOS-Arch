# Test luxos_calc.lsl bez displeje (test_luxos_launchpad_wl.py, test_luxos_calculator.py): vypise radky
# "ok NAZEV" / "FAIL NAZEV ..."
load luxos_calc as calc

failures = 0

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

function show(text):
    result = calc.evaluate(text)
    if result == None:
        return None
    end
    return calc.format(result, ",", " ")
end

# prednost, zavorky, mocniny
call expect("precedence", show("2+2*3"), "8")
call expect("parens", show("12*(3+4)"), "84")
call expect("power", show("2^10"), "1024")
call expect("group", show("1000*1000"), "1 000 000")
call expect("power-right", show("2^3^2"), "512")
call expect("power-minus", show("-2^2"), "-4")
call expect("power-star", show("2**8"), "256")
call expect("power-frac", show("2^0.5"), "1,41421356237")
call expect("power-neg", show("2^-2"), "0,25")
call expect("decimal", show("0.1+0.2"), "0,3")
call expect("decimal-comma", show("1,5*2"), "3")
call expect("division", show("10/4"), "2,5")
call expect("symbols", show("6×7−2÷2"), "41")
call expect("implicit", show("2(3+4)"), "14")
call expect("unclosed", show("sqrt(2"), "1,41421356237")
# funkce a konstanty
call expect("sqrt", show("sqrt(2)"), "1,41421356237")
# √ a π jsou jednoznakova jmena: driv se na nich tokenizer zacyklil (seznam rostl do GB)
call expect("sqrt-sign", show("√16"), "4")
call expect("sqrt-sign-twice", show("√√16"), "2")
call expect("pi-sign", show("2π"), "6,28318530718")
call expect("sqrt-sign-alone", show("√"), None)
call expect("cbrt", show("cbrt(-27)"), "-3")
call expect("sin30", show("sin(30)"), "0,5")
call expect("sin180", show("sin(180)"), "0")
call expect("cos90", show("cos 90"), "0")
call expect("ln", show("ln(e)"), "1")
call expect("log", show("log(1000)"), "3")
call expect("pi", show("2pi"), "6,28318530718")
call expect("factorial", show("5!"), "120")
call expect("abs", show("abs(-3)"), "3")
# procenta jako Kalkulacka (C-19) a "z"/"of"
call expect("pct-add", show("200 + 10%"), "220")
call expect("pct-sub", show("200 - 10 %"), "180")
call expect("pct-of", show("15% z 300"), "45")
call expect("pct-of-en", show("15 % of 300"), "45")
call expect("pct-plain", show("50%*8"), "4")
# neni vypocet
call expect("number", show("42"), None)
call expect("negative-number", show("-5"), None)
call expect("constant", show("pi"), None)
call expect("word", show("firefox"), None)
call expect("word-digit", show("2048 game"), None)
call expect("empty", show(""), None)
call expect("grouped", show("1 000"), None)
call expect("trailing-op", show("2+"), None)
call expect("div-zero", show("1/0"), None)
call expect("sqrt-neg", show("sqrt(-1)"), None)
call expect("tan90", show("tan(90)"), None)
call expect("log-zero", show("log(0)"), None)
call expect("two-seps", show("1.2.3+1"), None)
# meze (C-05): zadne obri vypocty ani nekonecno
call expect("overflow", show("10^400"), None)
call expect("huge-power", show("2^1e9"), None)
call expect("factorial-limit", show("171!"), None)
call expect("factorial-frac", show("2.5!"), None)
deep = ""
for i in range(60):
    deep = deep + "("
end
call expect("depth", show(deep + "1+1"), None)
long = "1"
for i in range(150):
    long = long + "+1"
end
call expect("too-long", show(long), None)
# zobrazeni
call expect("fmt-big", calc.format(123456789012.0, ",", " "), "123 456 789 012")
call expect("fmt-sci", calc.format(1.0e20, ",", " "), "1e20")
call expect("fmt-sci-frac", calc.format(-1.5e-12, ".", ","), "-1.5e-12")
call expect("fmt-small", calc.format(0.000123, ".", ","), "0.000123")
call expect("fmt-en", calc.format(1234.5, ".", ","), "1,234.5")
call expect("fmt-no-group", calc.format(1234.5, ",", ""), "1234,5")
call expect("fmt-round", calc.format(2.0 / 3.0, ".", ""), "0.666666666667")
call expect("fmt-carry", calc.format(9.9999999999999e20, ".", ""), "1e21")

# ---- Kalkulacka: desitkova aritmetika (drive Decimal v Pythonu) ----

function D(text):
    return calc.number(text)
end

function same(name, got, want):
    if got == None or calc.compare(got, want) != 0:
        return expect(name, calc.exact_text(got) if got != None else None, calc.exact_text(want))
    end
    return expect(name, True, True)
end

function tokens_value(items):
    out = []
    for item in items:
        if type(item) == "String" and item != "(" and item != ")" and not (item in calc.PRECEDENCE):
            out.append(D(item))
        else:
            out.append(item)
        end
    end
    result = None
    safe:
        result = calc.evaluate_tokens(out)
    end
    return result
end

function fails(name, f, a, b):
    ok = False
    try:
        call f(a, b)
    else:
        ok = True
    end
    return expect(name, ok, True)
end

function do_compute(name, x):
    return calc.compute(name, x[0], x[1])
end

function trig(name, value, degrees):
    return calc.compute(name, D(value), degrees)
end

function shown(x):
    return calc.fmt(x, ",", chr(8239))
end

call same("tok-precedence", tokens_value(["2", "+", "3", "*", "4"]), D("14"))
call same("tok-parens", tokens_value(["(", "2", "+", "3", ")", "*", "4"]), D("20"))
call same("tok-power-right", tokens_value(["2", "^", "3", "^", "2"]), D("512"))
call same("tok-decimal", tokens_value(["0.1", "+", "0.2"]), D("0.3"))
call expect("tok-div-zero", tokens_value(["1", "/", "0"]), None)
call expect("tok-trailing", tokens_value(["1", "+"]), None)
call same("tok-root", tokens_value(["27", "root", "3"]), D("3"))
call same("tok-root-neg", tokens_value(["-8", "root", "3"]), D("-2"))
call expect("tok-root-even-neg", tokens_value(["-16", "root", "2"]), None)
# presnost, kvuli ktere je aritmetika desitkova
call same("exact-sub", calc.sub(D("1234567890123.45"), D("1234567890123")), D("0.45"))
call same("exact-mul", calc.mul(D("0.1"), D("3")), D("0.3"))
call expect("third-times-three", shown(calc.mul(calc.div(D("1"), D("3")), D("3"))), "1")
call same("third-34", calc.div(D("1"), D("3")), D("0.3333333333333333333333333333333333"))
call same("two-thirds-round", calc.div(D("2"), D("3")), D("0.6666666666666666666666666666666667"))
call same("big-int", calc.mul(D("123456789012345678"), D("1000000007")), D("123456789876543201086419746"))
call same("fact-20", do_compute("fact", [D("20"), True]), D("2432902008176640000"))
call same("sqrt-exact", do_compute("sqrt", [D("1522756"), True]), D("1234"))
call same("sqrt-2", do_compute("sqrt", [D("2"), True]), D("1.414213562373095048801688724209698"))
call same("power-int", calc.power(D("2"), D("100")), D("1267650600228229401496703205376"))
call same("power-neg", calc.power(D("2"), D("-3")), D("0.125"))
call same("power-frac", calc.power(D("2"), D("0.5")), D("1.41421356237310"))
call fails("power-zero-zero", calc.power, D("0"), D("0"))
call fails("power-zero-neg", calc.power, D("0"), D("-1"))
call fails("power-neg-frac", calc.power, D("-8"), D("0.5"))
call same("half-even", calc.add(D("1"), D("5e-34")), D("1"))
call same("half-even-up", calc.add(D("1"), D("1.5e-33")), D("1.000000000000000000000000000000002"))
call same("far-apart", calc.add(D("1e999"), D("1")), D("1e999"))
call same("far-apart-sub", calc.sub(D("1e40"), D("1e-40")), D("1e40"))
call same("cancel", calc.sub(D("0.3"), D("0.1")), D("0.2"))
call expect("cmp", calc.compare(D("-2"), D("1.5")), -1)
call expect("cmp-eq", calc.compare(D("2.50"), D("2.5")), 0)
call fails("overflow", calc.mul, D("9e999990"), D("9e999990"))
call expect("fmt-zero", shown(D("0")), "0")
call expect("fmt-e20", shown(calc.power(D("10"), D("20"))), "1e20")
call expect("fmt-e-12", shown(D("1e-12")), "1e-12")
call expect("fmt-group", shown(D("1234567.5")), "1" + chr(8239) + "234" + chr(8239) + "567,5")
call expect("fmt-four", shown(D("1234")), "1" + chr(8239) + "234")
call expect("fmt-15", shown(D("123456789012345")), "123" + chr(8239) + "456" + chr(8239) + "789" + chr(8239) + "012" + chr(8239) + "345")
call expect("fmt-sci-round", shown(D("1234567895e20")), "1,2345679e29")
call expect("fmt-sci-carry", shown(D("9999999999e20")), "1e30")
call expect("fmt-small", shown(D("0.00000001234")), "0,00000001234")
call expect("fmt-neg", calc.fmt(D("-0.5"), ".", ","), "-0.5")
call expect("fmt-round14", shown(calc.div(D("2"), D("3"))), "0,66666666666667")
call expect("fmt-carry-int", shown(D("999999999999999.6")), "1" + chr(8239) + "000" + chr(8239) + "000" + chr(8239) + "000" + chr(8239) + "000" + chr(8239) + "000")
# C-20: maly nenulovy vysledek vedecky, ne jako 0
r = trig("sin", "1e-14", False)
call expect("sin-tiny", shown(r), "1e-14")
r = trig("sin", "180.0000000001", True)
call expect("sin-near-180", shown(r), "-1,74532925e-12")
call expect("cos-near-90", calc.is_zero(trig("cos", "90.000000001", True)), False)
call expect("asin-tiny", calc.is_zero(trig("asin", "1e-14", False)), False)
call expect("atan-tiny", calc.is_zero(trig("atan", "1e-13", False)), False)
# presne uhly
for case in [["sin", "180", "0"], ["sin", "360", "0"], ["sin", "-90", "-1"], ["cos", "90", "0"], ["cos", "270", "0"], ["cos", "180", "-1"], ["tan", "180", "0"], ["tan", "45", "1"], ["sin", "30", "0.5"], ["cos", "60", "0.5"], ["asin", "0.5", "30"], ["acos", "0.5", "60"], ["atan", "1", "45"], ["acos", "-1", "180"], ["sin", "-450", "-1"], ["cos", "1e30", "0.17364817766693"]]:
    call same("angle-" + case[0] + "-" + case[1], trig(case[0], case[1], True), D(case[2]))
end
call same("rad-sin-pi", calc.compute("sin", calc.PI, False), D("0"))
call same("rad-cos-half-pi", calc.compute("cos", calc.div(calc.PI, D("2")), False), D("0"))
call same("rad-sin-2pi", calc.compute("sin", calc.mul(calc.PI, D("2")), False), D("0"))
for value in ["90", "270", "-90"]:
    call fails("tan-" + value, do_compute, "tan", [D(value), True])
end
call fails("tan-half-pi", do_compute, "tan", [calc.div(calc.PI, D("2")), False])
call fails("sqrt-neg", do_compute, "sqrt", [D("-4"), True])
call fails("ln-zero", do_compute, "ln", [D("0"), True])
call fails("inv-zero", do_compute, "inv", [D("0"), True])
call same("cbrt-neg", calc.compute("cbrt", D("-27"), True), D("-3"))
call same("exp10", calc.compute("exp10", D("3"), True), D("1000"))
call same("fact-frac", calc.compute("fact", D("0.5"), True), D("0.886226925452758"))
call fails("fact-neg", do_compute, "fact", [D("-1"), True])
call expect("fact-1000", shown(calc.compute("fact", D("1000"), True)), "4,0238726e2567")
# C-05: obri exponent mimo rozsah bez obri alokace
call expect("range-huge", calc.in_range(D("1e999999999"), 200), False)
call expect("range-tiny", calc.in_range(D("1e-999999999"), 200), False)
call expect("range-1e999", calc.in_range(D("1e999"), 200), True)
call expect("range-zero", calc.in_range(D("0"), 200), True)
call expect("range-text", len(calc.exact_text(D("1e999"))) < 20, True)
call expect("exact-text-roundtrip", calc.compare(D(calc.exact_text(D("-1234e-60"))), D("-1234e-60")), 0)
call expect("number-nan", D("NaN"), None)
call expect("number-inf", D("-Infinity"), None)
call expect("number-snan", D("sNaN"), None)
call expect("value-text", calc.value_text(D("1.50")), "1.50")
call expect("value-text-e5", calc.value_text(D("1e5")), "100000")
call expect("value-text-small", calc.value_text(D("-25e-4")), "-0.0025")
if failures > 0:
    exit(1)
end
