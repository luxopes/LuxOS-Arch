# Testovaci program pro Emoji a symboly (spousti test_luxos_emoji.py): jedna funkce modulu luxos_emoji_base
# podle prvniho argumentu, vysledek jako JSON na stdout (None = null).
#   luxos-emoji-test FUNKCE ARGUMENTY...
# Data z LUXOS_EMOJI_DATA (adresar s emoji.tsv a <jazyk>.tsv).
load json
load luxos_emoji_base as base

function out(value):
    if value == None:
        print "null"
    else:
        print json.encode(value)
    end
    return 0
end

function emojis(data, indexes):
    result = []
    for i in indexes:
        result.append(data["emoji"][i])
    end
    return result
end

argv = []
index = 2
while index < arg_count():
    argv.append(arg(index))
    index += 1
end
name = arg(1)
if name == "fold":
    call out(base.fold(argv[0]))
elif name == "cap_first":
    call out(base.cap_first(argv[0]))
elif name == "words":
    call out(base.query_words(argv[0]))
elif name == "word_score":
    call out(base.word_score(argv[0], argv[1], argv[2]))
elif name == "search":
    # search JAZYK DOTAZ LIMIT [NAPOSLEDY_POUZITE_JSON] -> emoji v poradi (s posilenim jako v okne)
    data = base.load_data(base.data_dir(), argv[0])
    boost = None
    if len(argv) > 3:
        boost = base.boost_set(data, json.decode(argv[3]))
    end
    call out(emojis(data, base.search(data, argv[1], Int(argv[2]), boost)))
elif name == "search_time":
    # search_time JAZYK DOTAZ... -> [ms nacteni dat, ms nejpomalejsiho dotazu, pocet emoji]
    t0 = monotonic()
    data = base.load_data(base.data_dir(), argv[0])
    t1 = monotonic()
    boost = base.boost_set(data, [])
    worst = 0.0
    for q in argv[1:]:
        s = monotonic()
        prefix = ""
        for ch in q:
            prefix = prefix + ch
            call base.search(data, prefix, 0, boost)
        end
        took = (monotonic() - s) / Float(len(q))
        if took > worst:
            worst = took
        end
    end
    call out([(t1 - t0) * 1000.0, worst * 1000.0, base.count(data)])
elif name == "info":
    # info JAZYK EMOJI -> [nazev, anglicky nazev, skupina, odstiny]
    data = base.load_data(base.data_dir(), argv[0])
    i = base.find_index(data, argv[1])
    if i < 0:
        call out(None)
    else:
        call out([data["name"][i], data["name_en"][i], data["group"][i], data["tones"][i]])
    end
elif name == "summary":
    data = base.load_data(base.data_dir(), argv[0])
    sizes = []
    for g in data["groups"]:
        sizes.append(len(g))
    end
    toned = 0
    for t in data["tones"]:
        if len(t) == 5:
            toned += 1
        end
    end
    call out({"count": base.count(data), "groups": sizes, "toned": toned, "tone_names": data["tone_names"], "ok": data["ok"]})
elif name == "with_tone":
    data = base.load_data(base.data_dir(), "en")
    call out(base.with_tone(data, base.find_index(data, argv[0]), Int(argv[1])))
elif name == "find_index":
    data = base.load_data(base.data_dir(), "en")
    i = base.find_index(data, argv[0])
    if i < 0:
        call out(None)
    else:
        call out(data["emoji"][i])
    end
elif name == "strip_tone":
    call out(base.strip_tone(argv[0]))
elif name == "add_recent":
    recent = json.decode(argv[0])
    call out(base.add_recent(recent, argv[1]))
elif name == "recent":
    # recent CESTA_CONFIG -> zobrazena naposledy pouzita (nebo vychozi)
    data = base.load_data(base.data_dir(), "en")
    cfg = base.load_config(argv[0])
    idx = base.recent_indexes(data, cfg["recent"])
    if len(idx) == 0:
        idx = base.default_indexes(data)
    end
    call out(emojis(data, idx))
elif name == "load_config":
    call out(base.load_config(argv[0]))
elif name == "save_config":
    call out(base.save_config(json.decode(argv[1]), argv[0]))
elif name == "paste_method":
    call out(base.paste_method(argv))
elif name == "parse_args":
    call out(base.parse_args(argv))
elif name == "canonical_args":
    call out(base.canonical_args(base.parse_args(argv)))
elif name == "request_roundtrip":
    call out(base.request_args(base.request_text(argv)))
elif name == "lang":
    call out(base.lang())
else:
    call eprint("unknown function " + name)
    call exit(2)
end
