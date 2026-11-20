# Test luxos_calc.lsl bez displeje (test_luxos_launchpad_wl.py): vypise radky "ok NAZEV" / "FAIL NAZEV ..."
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
    value = calc.evaluate(text)
    if value == None:
        return None
    end
    return calc.format(value, ",", " ")
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
if failures > 0:
    exit(1)
end
