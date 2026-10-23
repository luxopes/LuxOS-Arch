# LuxOS - pomocne funkce pro text, ktere String v LSL 0.10.5 nema (isdigit, rfind, find od pozice, ...).
# Az budou ve standardni knihovne, tento modul zmizi.

function is_digits(text):
    if len(text) == 0:
        return False
    end
    for ch in text:
        if not is_digit(ch):
            return False
        end
    end
    return True
end

function is_digit(ch):
    code = ord(ch)
    return code >= 48 and code <= 57
end

# Posledni vyskyt sub, -1 kdyz chybi
function rfind(text, sub):
    best = -1
    start = 0
    while True:
        hit = find_from(text, sub, start)
        if hit < 0:
            return best
        end
        best = hit
        start = hit + 1
    end
    return best
end

# Prvni vyskyt sub od pozice start, -1 kdyz chybi
function find_from(text, sub, start):
    if start > len(text):
        return -1
    end
    hit = text[start:].find(sub)
    if hit < 0:
        return -1
    end
    return hit + start
end

# Odstrani zadane znaky z konce
function rstrip_chars(text, chars):
    end_index = len(text)
    while end_index > 0 and text[end_index - 1] in chars:
        end_index -= 1
    end
    return text[0:end_index]
end

function lstrip_chars(text, chars):
    start = 0
    while start < len(text) and text[start] in chars:
        start += 1
    end
    return text[start:]
end

# [pred, za] podle prvniho vyskytu oddelovace; [text, ""] kdyz chybi
function partition(text, sep):
    hit = text.find(sep)
    if hit < 0:
        return [text, ""]
    end
    return [text[0:hit], text[hit + len(sep):]]
end

# [pred, za] podle posledniho vyskytu oddelovace; ["", text] kdyz chybi
function rpartition(text, sep):
    hit = rfind(text, sep)
    if hit < 0:
        return ["", text]
    end
    return [text[0:hit], text[hit + len(sep):]]
end

# Pocet bajtu UTF-8 jednoho znaku
function utf8_length(ch):
    code = ord(ch)
    if code < 128:
        return 1
    elif code < 2048:
        return 2
    elif code < 65536:
        return 3
    end
    return 4
end

# Radky textu (bez prazdneho posledniho po koncovem \n)
function lines(text):
    out = text.split("\n")
    if len(out) > 0 and out[-1] == "":
        call out.pop()
    end
    return out
end

# Int z textu, nebo default pri chybe
function to_int(text, default):
    value = default
    try:
        value = Int(text.strip())
    else:
        value = default
    end
    return value
end

# Radek "klic=hodnota" -> Dictionary (prazdne a neplatne radky se preskoci)
function parse_kv(text):
    out = {}
    for line in text.split("\n"):
        pair = partition(line.strip(), "=")
        if pair[1] != "" or line.find("=") >= 0:
            out[pair[0]] = pair[1]
        end
    end
    return out
end

function join(items, sep):
    out = ""
    first = True
    for item in items:
        if not first:
            out = out + sep
        end
        out = out + String(item)
        first = False
    end
    return out
end

# "%s" / "%d" v sablone nahradi hodnotami v poradi, "%%" je "%"
function format(template, values):
    out = ""
    index = 0
    used = 0
    while index < len(template):
        ch = template[index]
        if ch == "%" and index + 1 < len(template):
            code = template[index + 1]
            if code == "%":
                out = out + "%"
                index += 2
                continue
            elif code == "s" or code == "d":
                if used < len(values):
                    out = out + String(values[used])
                end
                used += 1
                index += 2
                continue
            end
        end
        out = out + ch
        index += 1
    end
    return out
end

# Cislo na 6 mistnych cislic ("%06d")
function pad(n, width):
    text = String(n)
    while len(text) < width:
        text = "0" + text
    end
    return text
end
