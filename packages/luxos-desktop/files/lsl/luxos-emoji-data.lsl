# LuxOS Emoji a symboly - generator dat pri sestaveni baliku (PKGBUILD build()), nikdy za behu.
# Z emoji-test.txt (poradi, skupiny, odstiny pleti) a anotaci CLDR (nazvy a klicova slova v jazycich,
# balicky cldr-annotations-full a cldr-annotations-derived-full) vytvori kompaktni data pro luxos_emoji:
#   luxos-emoji-data EMOJI_TEST ANNOTATIONS DERIVED VYSTUP JAZYK...
#     EMOJI_TEST   emoji-test.txt (Unicode Emoji)
#     ANNOTATIONS  adresar s <jazyk>/annotations.json (cldr-annotations-full/annotations)
#     DERIVED      adresar s <jazyk>/annotations.json (cldr-annotations-derived-full/annotationsDerived)
#     VYSTUP       sem emoji.tsv a <jazyk>.tsv (format viz luxos_emoji_base)
# Do dat jdou jen plne kvalifikovana emoji bez odstinu (varianty s odstinem jako sloupec emoji.tsv) a pet
# modifikatoru odstinu (nazvy pro nabidku odstinu). Jazyk bez anotace nejakeho emoji ho vynecha (za behu
# plati anglicky nazev).
load env, json
load luxos_sys
load luxos_text as text
load luxos_emoji_base as base

VS16 = chr(65039)

function fail(message):
    call eprint("luxos-emoji-data: " + message)
    call exit(1)
end

function hex_value(part):
    value = 0
    for ch in part.lower():
        code = ord(ch)
        if code >= 48 and code <= 57:
            value = value * 16 + code - 48
        elif code >= 97 and code <= 102:
            value = value * 16 + code - 87
        else:
            call fail("bad code point " + part)
        end
    end
    return value
end

function cps_text(cps):
    out = ""
    for part in cps.split(" "):
        if part != "":
            out = out + chr(hex_value(part))
        end
    end
    return out
end

# Odstiny v sekvenci: [klic bez odstinu a FE0F, ton 1-5 nebo 0 bez odstinu, -1 = ruzne odstiny]
function tone_info(e):
    tone = 0
    for m in base.TONE_MODIFIERS:
        if e.find(m) >= 0:
            t = base.TONE_MODIFIERS.index(m) + 1
            if tone != 0 and tone != t:
                return [base.strip_tone(e).replace(VS16, ""), -1]
            end
            tone = t
        end
    end
    return [base.strip_tone(e).replace(VS16, ""), tone]
end

# emoji-test.txt -> {"order": [[emoji, skupina]], "tones": {klic: [5 variant]}, "names": {emoji: anglicky nazev}, "modifiers": [...]}
function parse_test(path):
    content = ""
    try:
        content = readfile(path)
    else:
        call fail("cannot read " + path)
    end
    out = {"order": [], "tones": {}, "names": {}, "keys": {}, "version": ""}
    group = -2
    for line in content.split("\n"):
        if line.startswith("# Version:"):
            out["version"] = line[10:].strip()
            continue
        end
        if line.startswith("# group:"):
            name = line[8:].strip()
            if name in base.TEST_GROUPS:
                group = base.TEST_GROUPS.index(name)
            elif name == "Component":
                group = -1
            else:
                call fail("unknown group " + name)
            end
            continue
        end
        if line == "" or line.startswith("#"):
            continue
        end
        semi = line.find(";")
        hash = line.find("#")
        if semi < 0 or hash < 0:
            continue
        end
        status = line[semi + 1:hash].strip()
        e = cps_text(line[0:semi].strip())
        # anglicky nazev za "E15.0 "
        comment = line[hash + 1:].strip()
        name = ""
        cut = comment.find(" E")
        if cut >= 0:
            rest = comment[cut + 2:]
            sp = rest.find(" ")
            if sp >= 0:
                name = rest[sp + 1:].strip()
            end
        end
        if status == "component":
            if e in base.TONE_MODIFIERS:
                out["order"].append([e, -1])
                out["names"][e] = name
            end
            continue
        end
        if status != "fully-qualified":
            continue
        end
        if group < 0:
            continue
        end
        info = tone_info(e)
        if info[1] == 0:
            out["order"].append([e, group])
            out["names"][e] = name
            out["keys"][info[0]] = e
        elif info[1] > 0:
            if info[0] not in out["tones"]:
                out["tones"][info[0]] = ["", "", "", "", ""]
            end
            if out["tones"][info[0]][info[1] - 1] == "":
                out["tones"][info[0]][info[1] - 1] = e
            end
        end
    end
    # pojistka proti oriznutemu souboru (testy s malym vzorkem: LUXOS_EMOJI_DATA_MIN)
    minimum = text.to_int(env.get("LUXOS_EMOJI_DATA_MIN", ""), 1000)
    if len(out["order"]) < minimum:
        call fail("too few emoji in " + path)
    end
    return out
end

function load_json(path, top):
    if not exists(path):
        return {}
    end
    content = ""
    try:
        content = readfile(path)
    else:
        call fail("cannot read " + path)
    end
    value = {}
    try:
        value = json.decode(content)
    else:
        call fail("bad JSON " + path + ": " + String(last_error()))
    end
    if top not in value or "annotations" not in value[top]:
        call fail("unexpected JSON " + path)
    end
    return value[top]["annotations"]
end

function clean(value):
    return value.replace("\t", " ").replace("\n", " ").replace("|", " ").strip()
end

# [nazev, [klicova slova]] nebo None
function lookup(e, ann, der):
    plain = e.replace(VS16, "")
    for table in [ann, der]:
        for key in [e, plain]:
            if key in table:
                entry = table[key]
                name = ""
                if "tts" in entry and len(entry["tts"]) > 0:
                    name = clean(entry["tts"][0])
                end
                kws = []
                if "default" in entry:
                    for kw in entry["default"]:
                        k = clean(kw)
                        if k != "" and k not in kws:
                            kws.append(k)
                        end
                    end
                end
                if name != "":
                    return [name, kws]
                end
            end
        end
    end
    return None
end

function lang_lines(lang, order, ann, der, names, header):
    lines = [header]
    found = 0
    for item in order:
        e = item[0]
        row = lookup(e, ann, der)
        if row == None and lang == "en":
            row = [names.get(e, ""), []]
        end
        if row == None or row[0] == "":
            continue
        end
        found += 1
        hay = "|" + base.fold(row[0])
        for kw in row[1]:
            hay = hay + "|" + base.fold(kw)
        end
        hay = hay + "|"
        # klicova slova jen po fold() v poslednim sloupci (zobrazuje se jen nazev)
        lines.append(e + "\t" + row[0] + "\t\t" + hay)
    end
    return [lines, found]
end

function main():
    if arg_count() < 6:
        call eprint("usage: luxos-emoji-data EMOJI_TEST ANNOTATIONS DERIVED OUTPUT LANG...")
        call exit(2)
    end
    test_path = arg(1)
    ann_dir = arg(2)
    der_dir = arg(3)
    out_dir = arg(4)
    langs = []
    index = 5
    while index < arg_count():
        langs.append(arg(index))
        index += 1
    end
    if "en" not in langs:
        langs.insert(0, "en")
    end
    parsed = parse_test(test_path)
    call luxos_sys.mkdir_p(out_dir)

    # poradi podle zalozek (skupina, pak poradi CLDR); modifikatory odstinu na konci
    by_group = []
    for g in base.GROUPS:
        by_group.append([])
    end
    modifiers = []
    for item in parsed["order"]:
        if item[1] < 0:
            modifiers.append(item)
        else:
            by_group[item[1]].append(item)
        end
    end
    order = []
    for g in by_group:
        order.extend(g)
    end
    order.extend(modifiers)

    header = "# " + base.DATA_VERSION + " - Unicode Emoji " + parsed["version"] + ", Unicode CLDR annotations (Unicode License v3)"
    lines = [header]
    toned = 0
    for item in order:
        e = item[0]
        tones = ""
        if item[1] >= 0:
            key = tone_info(e)[0]
            if key in parsed["tones"]:
                variants = parsed["tones"][key]
                if "" not in variants:
                    tones = " ".join(variants)
                    toned += 1
                end
            end
        end
        lines.append(e + "\t" + String(item[1]) + "\t" + tones)
    end
    call writefile(out_dir + "/emoji.tsv", "\n".join(lines) + "\n")
    print "emoji.tsv: " + String(len(order) - len(modifiers)) + " emoji, " + String(toned) + " with skin tones"

    for lang in langs:
        ann = load_json(ann_dir + "/" + lang + "/annotations.json", "annotations")
        der = load_json(der_dir + "/" + lang + "/annotations.json", "annotationsDerived")
        if len(ann) == 0:
            call fail("no annotations for " + lang)
        end
        result = lang_lines(lang, order, ann, der, parsed["names"], header)
        call writefile(out_dir + "/" + lang + ".tsv", "\n".join(result[0]) + "\n")
        print lang + ".tsv: " + String(result[1]) + " names"
    end
    return 0
end

call exit(main())
