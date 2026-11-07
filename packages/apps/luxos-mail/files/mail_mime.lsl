# Posta LuxOS - MIME (RFC 2045-2049, 2047, 2231, 3676), znakove sady, HTML -> text, adresy a data.
# Vse pracuje nad ByteArray (indexace bajtu je v LSL rychla, indexace znaku Stringu ne).
#   parse_message(b)            strom casti zpravy
#   render(b)                   {subject, from, to, cc, date, text, html, attachments[]} pro zobrazeni
#   part_bytes(b, path)         dekodovany obsah casti (ulozeni prilohy)
#   decode_words(s)             hlavicka s kodovanymi slovy =?utf-8?B?...?= -> text
#   decode_text(b, od, do, cs)  bajty ve znakove sade -> String (UTF-8)
#   b64_decode / b64_encode / qp_decode, html_to_text, parse_addresses, parse_date, preview_text
load env
load net
load mail_bytes as mb

B64 = []
ENTITIES = {"nbsp": 32, "amp": 38, "lt": 60, "gt": 62, "quot": 34, "apos": 39, "copy": 169, "reg": 174,
            "trade": 8482, "ndash": 8211, "mdash": 8212, "hellip": 8230, "euro": 8364, "laquo": 171,
            "raquo": 187, "bdquo": 8222, "ldquo": 8220, "rdquo": 8221, "lsquo": 8216, "rsquo": 8217,
            "sbquo": 8218, "bull": 8226, "middot": 183, "times": 215, "deg": 176, "shy": -1, "zwnj": -1,
            "zwj": -1, "lrm": -1, "rlm": -1, "thinsp": 32, "ensp": 32, "emsp": 32, "pound": 163, "yen": 165,
            "cent": 162, "sect": 167, "para": 182, "plusmn": 177, "frac12": 189, "frac14": 188, "frac34": 190,
            "aacute": 225, "Aacute": 193, "eacute": 233, "Eacute": 201, "iacute": 237, "Iacute": 205,
            "oacute": 243, "Oacute": 211, "uacute": 250, "Uacute": 218, "yacute": 253, "Yacute": 221,
            "auml": 228, "Auml": 196, "ouml": 246, "Ouml": 214, "uuml": 252, "Uuml": 220, "szlig": 223,
            "ccaron": 269, "Ccaron": 268, "scaron": 353, "Scaron": 352, "zcaron": 382, "Zcaron": 381,
            "rcaron": 345, "Rcaron": 344, "ecaron": 283, "Ecaron": 282, "ncaron": 328, "Ncaron": 327,
            "dcaron": 271, "Dcaron": 270, "tcaron": 357, "Tcaron": 356, "uring": 367, "Uring": 366,
            "agrave": 224, "Agrave": 192, "egrave": 232, "Egrave": 200, "ccedil": 231, "Ccedil": 199,
            "ntilde": 241, "Ntilde": 209, "oslash": 248, "aring": 229, "Aring": 197, "acirc": 226,
            "ecirc": 234, "ocirc": 244, "ucirc": 251, "icirc": 238, "euml": 235, "iuml": 239, "lstrok": 322,
            "Lstrok": 321, "oelig": 339, "aelig": 230, "rarr": 8594, "larr": 8592, "check": 10003}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
ZONES = {"UT": 0, "UTC": 0, "GMT": 0, "Z": 0, "EST": -500, "EDT": -400, "CST": -600, "CDT": -500, "MST": -700, "MDT": -600, "PST": -800, "PDT": -700, "CET": 100, "CEST": 200}
BLOCK_TAGS = {"p": 2, "div": 1, "br": 0, "tr": 1, "table": 1, "ul": 1, "ol": 1, "h1": 2, "h2": 2, "h3": 2, "h4": 2, "h5": 2, "h6": 2,
              "blockquote": 1, "section": 1, "article": 1, "header": 1, "footer": 1, "center": 1, "dl": 1, "dt": 1, "dd": 1,
              "pre": 1, "address": 1, "form": 1, "hr": 1, "li": 1, "tbody": 0, "thead": 0, "main": 1, "nav": 1, "figure": 1}
SKIP_TAGS = {"script": 1, "style": 1, "head": 1, "title": 1, "noscript": 1, "template": 1, "svg": 1, "object": 1}

# ---- base64, quoted-printable ---------------------------------------------------------------------------

function b64_table():
    global B64
    if len(B64) == 256:
        return B64
    end
    t = []
    for i in range(256):
        t.append(-1)
    end
    alphabet = net.bytes("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
    for i in range(64):
        t[alphabet[i]] = i
    end
    # modifikovany base64 v nazvech schranek IMAP (RFC 3501 5.1.3) pouziva ","
    t[44] = 63
    B64 = t
    return B64
end

# Neplatne znaky (konce radku) preskoci; "=" vynuluje rozpracovanou skupinu (zretezene bloky s doplnenim)
function b64_decode(b, start, stop):
    t = b64_table()
    out = ByteArray()
    acc = 0
    bits = 0
    i = start
    if stop > len(b):
        stop = len(b)
    end
    while i < stop:
        c = b[i]
        i += 1
        v = t[c]
        if v < 0:
            if c == 61:
                acc = 0
                bits = 0
            end
            continue
        end
        acc = ((acc << 6) | v) & 16777215
        bits += 6
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 255)
        end
    end
    return out
end

function b64_encode(data):
    b = data
    if type(data) == "String":
        b = net.bytes(data)
    end
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    chars = []
    for i in range(64):
        chars.append(alphabet[i])
    end
    out = []
    i = 0
    n = len(b)
    while i + 2 < n:
        v = (b[i] << 16) | (b[i + 1] << 8) | b[i + 2]
        out.append(chars[(v >> 18) & 63] + chars[(v >> 12) & 63] + chars[(v >> 6) & 63] + chars[v & 63])
        i += 3
    end
    if n - i == 1:
        v = b[i] << 16
        out.append(chars[(v >> 18) & 63] + chars[(v >> 12) & 63] + "==")
    elif n - i == 2:
        v = (b[i] << 16) | (b[i + 1] << 8)
        out.append(chars[(v >> 18) & 63] + chars[(v >> 12) & 63] + chars[(v >> 6) & 63] + "=")
    end
    return "".join(out)
end

function hexval(c):
    if c >= 48 and c <= 57:
        return c - 48
    elif c >= 65 and c <= 70:
        return c - 55
    elif c >= 97 and c <= 102:
        return c - 87
    end
    return -1
end

# header=True: "_" je mezera (kodovana slova Q)
function qp_decode(b, start, stop, header):
    out = ByteArray()
    i = start
    if stop > len(b):
        stop = len(b)
    end
    while i < stop:
        c = b[i]
        if c == 61:
            if i + 1 < stop and b[i + 1] == 10:
                i += 2
                continue
            end
            if i + 2 < stop and b[i + 1] == 13 and b[i + 2] == 10:
                i += 3
                continue
            end
            if i + 2 < stop:
                h1 = hexval(b[i + 1])
                h2 = hexval(b[i + 2])
                if h1 >= 0 and h2 >= 0:
                    out.append(h1 * 16 + h2)
                    i += 3
                    continue
                end
            end
            # mekky konec radku s mezerami za "=" (nekteri odesilatele)
            j = i + 1
            while j < stop and (b[j] == 32 or b[j] == 9):
                j += 1
            end
            if j < stop and (b[j] == 13 or b[j] == 10):
                if b[j] == 13 and j + 1 < stop and b[j + 1] == 10:
                    j += 1
                end
                i = j + 1
                continue
            end
            out.append(61)
            i += 1
            continue
        end
        if header and c == 95:
            out.append(32)
        else:
            out.append(c)
        end
        i += 1
    end
    return out
end

# ---- znakove sady -----------------------------------------------------------------------------------------

function is_utf8(b, start, stop):
    i = start
    while i < stop:
        c = b[i]
        if c < 128:
            i += 1
            continue
        end
        need = 0
        if c >= 194 and c <= 223:
            need = 1
        elif c >= 224 and c <= 239:
            need = 2
        elif c >= 240 and c <= 244:
            need = 3
        else:
            return False
        end
        if i + need >= stop:
            return False
        end
        k = 1
        while k <= need:
            d = b[i + k]
            if d < 128 or d > 191:
                return False
            end
            k += 1
        end
        i += need + 1
    end
    return True
end

function has_8bit(b, start, stop):
    i = start
    while i < stop:
        if b[i] >= 128:
            return True
        end
        i += 1
    end
    return False
end

# Znakova sada pro neoznaceny 8bitovy text podle jazyka uzivatele (jako Thunderbird)
function fallback_charset():
    value = env.get("LC_ALL", "")
    if value == None or value == "":
        value = env.get("LANG", "")
    end
    if value == None:
        value = ""
    end
    code = value[0:2].lower()
    if code in ["cs", "sk", "pl", "hu", "sl", "hr", "ro"]:
        return "WINDOWS-1250"
    elif code in ["uk", "ru", "bg", "be", "sr", "mk"]:
        return "WINDOWS-1251"
    end
    return "WINDOWS-1252"
end

function strip_quotes(s):
    t = s.strip()
    if len(t) >= 2 and t.startswith("\"") and t.endswith("\""):
        return t[1:len(t) - 1]
    end
    return t
end

function norm_charset(cs):
    if cs == None:
        return ""
    end
    c = strip_quotes(cs).lower()
    star = c.find("*")
    if star >= 0:
        c = c[0:star]
    end
    if c in ["utf8", "utf-8", "unicode-1-1-utf-8", "x-utf-8"]:
        return "utf-8"
    elif c in ["us-ascii", "ascii", "ansi_x3.4-1968", "7bit", "8bit", "unknown-8bit", "x-unknown", "unknown", "default", "x-user-defined", "us_ascii", "iso-646-us"]:
        return ""
    elif c == "iso-8859-1" or c == "latin1" or c == "iso8859-1" or c == "iso_8859-1":
        return "windows-1252"
    elif c == "ks_c_5601-1987" or c == "euc-kr":
        return "cp949"
    elif c == "iso-8859-8-i":
        return "iso-8859-8"
    elif c in ["gb2312", "gbk", "x-gbk", "cp936", "gb_2312-80"]:
        return "gb18030"
    elif c == "windows-874":
        return "cp874"
    elif c == "cp-1250" or c == "cp1250" or c == "x-cp1250":
        return "windows-1250"
    elif c == "cp-1251" or c == "cp1251" or c == "x-cp1251":
        return "windows-1251"
    elif c == "unicode-1-1-utf-7" or c == "utf7":
        return "utf-7"
    end
    return c
end

# Bajty [start, stop) ve znakove sade -> String (UTF-8); nikdy nevyhodi chybu
function decode_text(b, start, stop, charset):
    if stop > len(b):
        stop = len(b)
    end
    if stop <= start:
        return ""
    end
    c = norm_charset(charset)
    if c == "" or c == "utf-8":
        if not has_8bit(b, start, stop) or is_utf8(b, start, stop):
            return net.text(b, start, stop - start)
        end
        if c == "utf-8":
            return net.text(b, start, stop - start)
        end
        r = mb.convert(b, start, stop, fallback_charset())
        if r == False:
            return net.text(b, start, stop - start)
        end
        return r
    end
    r = mb.convert(b, start, stop, c.upper())
    if r == False:
        if is_utf8(b, start, stop):
            return net.text(b, start, stop - start)
        end
        r = mb.convert(b, start, stop, fallback_charset())
        if r == False:
            return net.text(b, start, stop - start)
        end
    end
    return r
end

# Hlavicka v surovych bajtech (8bit bez kodovani): UTF-8, jinak sada podle jazyka
function raw_header_text(b, start, stop):
    return decode_text(b, start, stop, "")
end

# ---- RFC 2047: kodovana slova v hlavickach ---------------------------------------------------------------

function flush_words(out, pending, charset):
    if len(pending) > 0:
        joined = mb.join(pending)
        out.append(decode_text(joined, 0, len(joined), charset))
        pending.clear()
    end
    return 0
end

function only_space(b, start, stop):
    i = start
    while i < stop:
        c = b[i]
        if c != 32 and c != 9 and c != 13 and c != 10:
            return False
        end
        i += 1
    end
    return True
end

function decode_words(s):
    if s == None:
        return ""
    end
    if s.find("=?") < 0:
        return s
    end
    b = net.bytes(s)
    n = len(b)
    out = []
    pending = []
    pending_cs = ""
    pos = 0
    last_word = False
    loop:
        a = mb.find(b, "=?", pos)
        if a < 0:
            break
        end
        q1 = mb.find_byte(b, 63, a + 2, n)
        if q1 < 0 or q1 + 2 >= n or b[q1 + 2] != 63:
            break
        end
        enc = b[q1 + 1] | 32
        if enc != 98 and enc != 113:
            # neni kodovane slovo: pokracovat za "=?"
            call flush_words(out, pending, pending_cs)
            out.append(net.text(b, pos, a + 2 - pos))
            pos = a + 2
            last_word = False
            continue
        end
        e = mb.find(b, "?=", q1 + 3)
        if e < 0:
            break
        end
        # mezera mezi dvema kodovanymi slovy se vynechava
        if a > pos:
            if not (last_word and only_space(b, pos, a)):
                call flush_words(out, pending, pending_cs)
                out.append(net.text(b, pos, a - pos))
            end
        end
        charset = norm_charset(net.text(b, a + 2, q1 - a - 2))
        if enc == 98:
            piece = b64_decode(b, q1 + 3, e)
        else:
            piece = qp_decode(b, q1 + 3, e, True)
        end
        if charset != pending_cs:
            call flush_words(out, pending, pending_cs)
            pending_cs = charset
        end
        pending.append(piece)
        pos = e + 2
        last_word = True
    end
    call flush_words(out, pending, pending_cs)
    if pos < n:
        out.append(net.text(b, pos, n - pos))
    end
    return "".join(out)
end

# ---- hlavicky ---------------------------------------------------------------------------------------------

# [seznam [jmeno_malymi, hodnota], zacatek tela]; pokracovaci radky spojene (unfold)
function parse_headers(b, start, stop):
    headers = []
    body = stop
    i = start
    name = ""
    pieces = []
    while i < stop:
        nl = mb.find_byte(b, 10, i, stop)
        line_end = stop
        nxt = stop
        if nl >= 0:
            line_end = nl
            nxt = nl + 1
        end
        le = line_end
        if le > i and b[le - 1] == 13:
            le -= 1
        end
        if le == i:
            body = nxt
            break
        end
        c = b[i]
        if (c == 32 or c == 9) and name != "":
            pieces.append(mb.sub(b, i, le))
        else:
            if name != "":
                v = mb.join(pieces)
                headers.append([name, raw_header_text(v, 0, len(v)).strip()])
            end
            name = ""
            pieces = []
            colon = mb.find_byte(b, 58, i, le)
            if colon > i:
                name = net.text(b, i, colon - i).strip().lower()
                pieces = [mb.sub(b, colon + 1, le)]
            end
        end
        i = nxt
    end
    if name != "":
        v = mb.join(pieces)
        headers.append([name, raw_header_text(v, 0, len(v)).strip()])
    end
    return [headers, body]
end

function header(headers, name):
    for h in headers:
        if h[0] == name:
            return h[1]
        end
    end
    return ""
end

function unquote(s):
    b = net.bytes(s.strip())
    n = len(b)
    if n == 0 or b[0] != 34:
        return s.strip()
    end
    out = ByteArray()
    i = 1
    while i < n:
        c = b[i]
        if c == 92 and i + 1 < n:
            out.append(b[i + 1])
            i += 2
            continue
        end
        if c == 34:
            break
        end
        out.append(c)
        i += 1
    end
    return net.text(out)
end

function split_params(v):
    b = net.bytes(v)
    parts = []
    start = 0
    inq = False
    i = 0
    n = len(b)
    while i < n:
        c = b[i]
        if inq:
            if c == 92:
                i += 2
                continue
            end
            if c == 34:
                inq = False
            end
        elif c == 34:
            inq = True
        elif c == 59:
            parts.append(net.text(b, start, i - start))
            start = i + 1
        end
        i += 1
    end
    if start <= n:
        parts.append(net.text(b, start, n - start))
    end
    return parts
end

function percent_decode(s):
    b = net.bytes(s)
    out = ByteArray()
    i = 0
    n = len(b)
    while i < n:
        c = b[i]
        if c == 37 and i + 2 < n:
            h1 = hexval(b[i + 1])
            h2 = hexval(b[i + 2])
            if h1 >= 0 and h2 >= 0:
                out.append(h1 * 16 + h2)
                i += 3
                continue
            end
        end
        out.append(c)
        i += 1
    end
    return out
end

function to_int(s, fallback):
    t = s.strip()
    if t == "":
        return fallback
    end
    b = net.bytes(t)
    v = 0
    for c in b:
        if c < 48 or c > 57:
            return fallback
        end
        v = v * 10 + c - 48
    end
    return v
end

# "text/plain; charset=utf-8; name*0*=..." -> [hlavni hodnota malymi, {parametry}] (RFC 2045 + 2231)
function parse_params(value):
    parts = split_params(value)
    main = parts[0].strip().lower()
    params = {}
    pieces = {}
    for p in parts[1:]:
        eq = p.find("=")
        if eq <= 0:
            continue
        end
        name = p[0:eq].strip().lower()
        raw = p[eq + 1:].strip()
        val = unquote(raw)
        star = name.find("*")
        if star < 0:
            if name not in params:
                params[name] = decode_words(val)
            end
            continue
        end
        base = name[0:star]
        rest = name[star + 1:]
        encoded = name.endswith("*")
        index = 0
        if rest != "" and rest != "*":
            digits = rest
            if digits.endswith("*"):
                digits = digits[0:len(digits) - 1]
            end
            index = to_int(digits, 0)
        end
        if base not in pieces:
            pieces[base] = []
        end
        pieces[base].append([index, encoded, val])
    end
    for base in pieces.keys():
        items = pieces[base]
        ordered = []
        for k in range(len(items)):
            for it in items:
                if it[0] == k:
                    ordered.append(it)
                end
            end
        end
        if len(ordered) == 0:
            ordered = items
        end
        charset = ""
        chunks = []
        first = True
        for it in ordered:
            v = it[2]
            if it[1]:
                if first:
                    q1 = v.find("'")
                    if q1 >= 0:
                        charset = v[0:q1]
                        after = v[q1 + 1:]
                        q2 = after.find("'")
                        if q2 >= 0:
                            v = after[q2 + 1:]
                        else:
                            v = after
                        end
                    end
                end
                chunks.append(percent_decode(v))
            else:
                chunks.append(net.bytes(v))
            end
            first = False
        end
        joined = mb.join(chunks)
        params[base] = decode_text(joined, 0, len(joined), charset)
    end
    return [main, params]
end

# ---- strom MIME ----------------------------------------------------------------------------------------------

function child_path(path, index):
    if path == "":
        return String(index)
    end
    return path + "." + String(index)
end

# Oddelovac "--hranice" na zacatku radku od pozice `pos`; [zacatek, konec radku (za LF), uzaviraci?] nebo []
function find_delimiter(b, delim, pos, stop, body_start):
    p = pos
    loop:
        hit = mb.find(b, delim, p)
        if hit < 0 or hit >= stop:
            return []
        end
        if hit == body_start or b[hit - 1] == 10:
            closing = hit + len(delim) + 1 < stop and b[hit + len(delim)] == 45 and b[hit + len(delim) + 1] == 45
            nl = mb.find_byte(b, 10, hit, stop)
            after = stop
            if nl >= 0:
                after = nl + 1
            end
            return [hit, after, closing]
        end
        p = hit + 1
    end
end

function part_end(b, hit, floor):
    e = hit
    if e > floor and b[e - 1] == 10:
        e -= 1
        if e > floor and b[e - 1] == 13:
            e -= 1
        end
    end
    return e
end

function parse_part(b, start, stop, depth, path, default_type):
    hb = parse_headers(b, start, stop)
    headers = hb[0]
    body = hb[1]
    ct = header(headers, "content-type")
    main = default_type
    params = {}
    if ct != "":
        pp = parse_params(ct)
        main = pp[0]
        params = pp[1]
    end
    if main.find("/") < 0:
        main = "text/plain"
    end
    disp = ""
    dparams = {}
    dv = header(headers, "content-disposition")
    if dv != "":
        dp = parse_params(dv)
        disp = dp[0]
        dparams = dp[1]
    end
    filename = dparams.get("filename", "")
    if filename == "":
        filename = params.get("name", "")
    end
    cid = header(headers, "content-id").strip()
    if cid.startswith("<") and cid.endswith(">"):
        cid = cid[1:len(cid) - 1]
    end
    part = {"type": main, "params": params, "encoding": header(headers, "content-transfer-encoding").strip().lower(),
            "disposition": disp, "filename": filename, "cid": cid, "start": body, "stop": stop, "path": path,
            "parts": [], "headers": headers}
    if main.startswith("multipart/") and depth < 30:
        boundary = params.get("boundary", "")
        if boundary != "":
            delim = net.bytes("--" + boundary)
            child_type = "text/plain"
            if main == "multipart/digest":
                child_type = "message/rfc822"
            end
            d = find_delimiter(b, delim, body, stop, body)
            index = 1
            while len(d) == 3 and not d[2]:
                nxt = find_delimiter(b, delim, d[1], stop, body)
                cstop = stop
                if len(nxt) == 3:
                    cstop = part_end(b, nxt[0], d[1])
                end
                part["parts"].append(parse_part(b, d[1], cstop, depth + 1, child_path(path, index), child_type))
                index += 1
                d = nxt
            end
        end
    end
    return part
end

function parse_message(b):
    return parse_part(b, 0, len(b), 0, "", "text/plain")
end

function decode_body(b, part):
    enc = part["encoding"]
    if enc == "base64":
        return b64_decode(b, part["start"], part["stop"])
    elif enc == "quoted-printable":
        return qp_decode(b, part["start"], part["stop"], False)
    end
    return mb.sub(b, part["start"], part["stop"])
end

function find_part(part, path):
    if part["path"] == path:
        return part
    end
    for child in part["parts"]:
        found = find_part(child, path)
        if len(found) > 0:
            return found
        end
    end
    return {}
end

# Dekodovany obsah casti podle cesty ("1.2"); prazdny ByteArray kdyz neni
function part_bytes(b, path):
    tree = parse_message(b)
    p = find_part(tree, path)
    if len(p) == 0:
        return ByteArray()
    end
    return decode_body(b, p)
end

# format=flowed (RFC 3676): mekke konce radku (mezera na konci) se spoji
function unflow(text, delsp):
    lines = text.split("\n")
    out = []
    current = ""
    open_line = False
    for raw in lines:
        line = raw
        if line.endswith("\r"):
            line = line[0:len(line) - 1]
        end
        if line.startswith(" "):
            line = line[1:]
        end
        soft = line.endswith(" ") and line != "-- "
        if soft and delsp:
            line = line[0:len(line) - 1]
        end
        current = current + line
        if soft:
            open_line = True
            continue
        end
        out.append(current)
        current = ""
        open_line = False
    end
    if open_line or current != "":
        out.append(current)
    end
    return "\n".join(out)
end

function part_text(b, part):
    data = decode_body(b, part)
    text = decode_text(data, 0, len(data), part["params"].get("charset", ""))
    if part["type"] == "text/html":
        return html_to_text(text)
    end
    if part["params"].get("format", "").lower() == "flowed":
        text = unflow(text, part["params"].get("delsp", "").lower() == "yes")
    end
    return text.replace("\r\n", "\n")
end

function default_name(part, index):
    t = part["type"]
    ext = "bin"
    slash = t.find("/")
    if slash >= 0:
        ext = t[slash + 1:]
    end
    if t == "message/rfc822":
        ext = "eml"
    end
    if ext == "plain":
        ext = "txt"
    elif ext == "jpeg":
        ext = "jpg"
    elif ext == "octet-stream":
        ext = "bin"
    end
    return "attachment-" + String(index) + "." + ext
end

function choose_alternative(parts):
    plain = {}
    other = {}
    for p in parts:
        if p["type"] == "text/plain" and p["disposition"] != "attachment" and p["stop"] > p["start"]:
            plain = p
        elif p["type"] == "text/html" or p["type"].startswith("multipart/"):
            other = p
        end
    end
    if len(plain) > 0:
        return plain
    end
    return other
end

function collect(b, part, ctx, related):
    t = part["type"]
    if t.startswith("multipart/"):
        if t == "multipart/alternative":
            choice = choose_alternative(part["parts"])
            if len(choice) > 0:
                call collect(b, choice, ctx, related)
            end
            return 0
        end
        rel = related or t == "multipart/related"
        for child in part["parts"]:
            call collect(b, child, ctx, rel)
        end
        return 0
    end
    attachment = part["disposition"] == "attachment"
    if (t == "text/plain" or t == "text/html") and not attachment:
        text = part_text(b, part)
        if t == "text/html":
            ctx["html"] = True
        end
        if text.strip() != "":
            ctx["texts"].append(text)
        end
        return 0
    end
    # obrazky vlozene do HTML (cid:) v multipart/related nejsou prilohy
    if related and part["cid"] != "" and not attachment and part["filename"] == "":
        return 0
    end
    name = part["filename"]
    if name == "":
        name = default_name(part, len(ctx["attachments"]) + 1)
    end
    size = part["stop"] - part["start"]
    if part["encoding"] == "base64":
        size = size * 3 // 4
    end
    ctx["attachments"].append({"name": name, "type": t, "size": size, "path": part["path"]})
    return 0
end

# Zprava pripravena k zobrazeni
function render(b):
    tree = parse_message(b)
    hs = tree["headers"]
    ctx = {"texts": [], "attachments": [], "html": False}
    call collect(b, tree, ctx, False)
    from_list = parse_addresses(decode_words(header(hs, "from")))
    return {"subject": decode_words(header(hs, "subject")), "from": from_list, "to": parse_addresses(decode_words(header(hs, "to"))),
            "cc": parse_addresses(decode_words(header(hs, "cc"))), "reply_to": parse_addresses(decode_words(header(hs, "reply-to"))),
            "date": parse_date(header(hs, "date")), "message_id": header(hs, "message-id"), "text": "\n\n".join(ctx["texts"]),
            "html": ctx["html"], "attachments": ctx["attachments"], "list_unsubscribe": header(hs, "list-unsubscribe")}
end

# ---- HTML -> text ---------------------------------------------------------------------------------------------

function lower_bytes(b):
    out = mb.sub(b, 0, len(b))
    i = 0
    n = len(out)
    while i < n:
        c = out[i]
        if c >= 65 and c <= 90:
            out[i] = c + 32
        end
        i += 1
    end
    return out
end

# Vystup HTML -> text: st = {"out": ByteArray, "ws": cekajici mezera}; mezery se zapisuji az pred dalsim
# znakem, takze na konci radku nikdy nezustanou (ByteArray nema pop)
function emit_byte(st, c):
    out = st["out"]
    if st["ws"]:
        if len(out) > 0 and out[len(out) - 1] != 10:
            out.append(32)
        end
        st["ws"] = False
    end
    out.append(c)
    return 0
end

function emit_text(st, s):
    for c in net.bytes(s):
        call emit_byte(st, c)
    end
    return 0
end

function append_raw(out, s):
    for c in net.bytes(s):
        out.append(c)
    end
    return 0
end

function newlines(st, count):
    st["ws"] = False
    out = st["out"]
    if len(out) == 0:
        return 0
    end
    have = 0
    i = len(out) - 1
    while i >= 0 and out[i] == 10:
        have += 1
        i -= 1
    end
    while have < count:
        out.append(10)
        have += 1
    end
    return 0
end

# Hodnota atributu ze surove znacky (lower = stejna znacka malymi pismeny)
function attribute(tag, lower, name):
    key = net.bytes(name + "=")
    p = 0
    loop:
        hit = mb.find(lower, key, p)
        if hit < 0:
            return ""
        end
        if hit > 0 and lower[hit - 1] != 32 and lower[hit - 1] != 9 and lower[hit - 1] != 10 and lower[hit - 1] != 13:
            p = hit + 1
            continue
        end
        i = hit + len(key)
        n = len(tag)
        if i >= n:
            return ""
        end
        q = tag[i]
        if q == 34 or q == 39:
            e = mb.find_byte(tag, q, i + 1, n)
            if e < 0:
                e = n
            end
            return net.text(tag, i + 1, e - i - 1)
        end
        e = i
        while e < n and tag[e] != 32 and tag[e] != 62 and tag[e] != 9:
            e += 1
        end
        return net.text(tag, i, e - i)
    end
end

function entity_text(name):
    if name.startswith("#"):
        code = 0
        if name.startswith("#x") or name.startswith("#X"):
            for c in net.bytes(name[2:]):
                h = hexval(c)
                if h < 0:
                    return ""
                end
                code = code * 16 + h
            end
        else:
            code = to_int(name[1:], -1)
        end
        if code == 160:
            return " "
        end
        if code <= 0 or code > 1114111 or (code >= 55296 and code <= 57343):
            return ""
        end
        return chr(code)
    end
    code = ENTITIES.get(name, -2)
    if code == -2:
        code = ENTITIES.get(name.lower(), -2)
    end
    if code == -2:
        return "&" + name + ";"
    elif code == -1:
        return ""
    end
    return chr(code)
end

function html_to_text(html):
    b = net.bytes(html)
    low = lower_bytes(b)
    n = len(b)
    st = {"out": ByteArray(), "ws": False}
    out = st["out"]
    i = 0
    pre = 0
    links = []
    while i < n:
        c = b[i]
        if c == 60:
            if i + 3 < n and b[i + 1] == 33 and b[i + 2] == 45 and b[i + 3] == 45:
                e = mb.find(b, "-->", i + 4)
                if e < 0:
                    break
                end
                i = e + 3
                continue
            end
            e = mb.find_byte(b, 62, i + 1, n)
            if e < 0:
                break
            end
            j = i + 1
            closing = False
            if j < e and b[j] == 47:
                closing = True
                j += 1
            end
            k = j
            while k < e and ((low[k] >= 97 and low[k] <= 122) or (low[k] >= 48 and low[k] <= 57)):
                k += 1
            end
            name = net.text(low, j, k - j)
            tag = mb.sub(b, i, e + 1)
            ltag = mb.sub(low, i, e + 1)
            i = e + 1
            if name == "":
                continue
            end
            if not closing and name in SKIP_TAGS:
                endtag = mb.find(low, "</" + name, i)
                if endtag < 0:
                    i = n
                else:
                    close = mb.find_byte(b, 62, endtag, n)
                    if close < 0:
                        i = n
                    else:
                        i = close + 1
                    end
                end
                continue
            end
            if name == "br":
                st["ws"] = False
                out.append(10)
            elif name == "li" and not closing:
                call newlines(st, 1)
                call emit_text(st, "• ")
            elif name == "hr":
                call newlines(st, 1)
                call emit_text(st, "――――――――――")
                call newlines(st, 1)
            elif name in BLOCK_TAGS:
                call newlines(st, BLOCK_TAGS[name])
                if name == "pre":
                    if closing:
                        pre = max(0, pre - 1)
                    else:
                        pre += 1
                    end
                end
            elif name == "td" or name == "th":
                if not closing:
                    st["ws"] = True
                end
            elif name == "a":
                if closing:
                    if len(links) > 0:
                        link = links.pop()
                        href = link[0]
                        shown = net.text(out, link[1], len(out) - link[1]).strip()
                        if (href.startswith("http://") or href.startswith("https://")) and len(href) <= 200 and shown.find(href) < 0 and (shown == "" or href.find(shown) < 0):
                            call emit_text(st, " <" + href + ">")
                        end
                    end
                else:
                    links.append([attribute(tag, ltag, "href").strip(), len(out)])
                end
            elif name == "img" and not closing:
                alt = attribute(tag, ltag, "alt").strip()
                if alt != "":
                    call emit_text(st, "[" + alt + "]")
                end
            end
            continue
        end
        if c == 38:
            semi = mb.find_byte(b, 59, i + 1, min(n, i + 12))
            if semi > i + 1:
                call emit_text(st, entity_text(net.text(b, i + 1, semi - i - 1)))
                i = semi + 1
                continue
            end
        end
        if c == 32 or c == 9 or c == 10 or c == 13:
            if pre > 0:
                if c != 13:
                    st["ws"] = False
                    out.append(c)
                end
            else:
                st["ws"] = True
            end
            i += 1
            continue
        end
        call emit_byte(st, c)
        i += 1
    end
    text = net.text(out)
    lines = []
    blank = 0
    for line in text.split("\n"):
        l = line.rstrip()
        if l.strip() == "":
            blank += 1
            if blank > 1 or len(lines) == 0:
                continue
            end
            lines.append("")
            continue
        end
        blank = 0
        lines.append(l)
    end
    while len(lines) > 0 and lines[len(lines) - 1] == "":
        call lines.pop()
    end
    return "\n".join(lines)
end

# ---- adresy -------------------------------------------------------------------------------------------------

function split_addresses(s):
    b = net.bytes(s)
    items = []
    start = 0
    inq = False
    angle = 0
    paren = 0
    i = 0
    n = len(b)
    while i < n:
        c = b[i]
        if inq:
            if c == 92:
                i += 2
                continue
            end
            if c == 34:
                inq = False
            end
        elif c == 34:
            inq = True
        elif c == 60:
            angle += 1
        elif c == 62:
            angle = max(0, angle - 1)
        elif c == 40:
            paren += 1
        elif c == 41:
            paren = max(0, paren - 1)
        elif (c == 44 or c == 59) and angle == 0 and paren == 0:
            items.append(net.text(b, start, i - start))
            start = i + 1
        end
        i += 1
    end
    items.append(net.text(b, start, n - start))
    return items
end

# "Jan Novak <jan@x.cz>, b@y.cz" -> [[jmeno, adresa], ...]
function parse_addresses(s):
    out = []
    if s == None or s.strip() == "":
        return out
    end
    for raw in split_addresses(s):
        item = raw.strip()
        colon = item.find(":")
        lt = item.find("<")
        if colon >= 0 and (lt < 0 or colon < lt) and item.find("\"") < 0:
            # skupina "Jmeno: a@b, c@d;" - jmeno skupiny vynechat
            item = item[colon + 1:].strip()
            lt = item.find("<")
        end
        if item == "":
            continue
        end
        name = ""
        email = ""
        if lt >= 0:
            gt = item.find(">")
            if gt < lt:
                gt = len(item)
            end
            email = item[lt + 1:gt].strip()
            name = item[0:lt].strip()
        else:
            lp = item.find("(")
            if lp >= 0:
                rp = item.find(")")
                if rp < lp:
                    rp = len(item)
                end
                name = item[lp + 1:rp].strip()
                email = item[0:lp].strip()
            else:
                email = item
            end
        end
        name = unquote(name)
        if name == email:
            name = ""
        end
        if email == "" and name == "":
            continue
        end
        out.append([name, email])
    end
    return out
end

function address_display(pair):
    if pair[0] != "":
        return pair[0]
    end
    return pair[1]
end

function address_full(pair):
    if pair[0] != "" and pair[1] != "":
        return pair[0] + " <" + pair[1] + ">"
    end
    return address_display(pair)
end

# ---- data -----------------------------------------------------------------------------------------------------

function days_from_civil(y0, m, d):
    y = y0
    if m <= 2:
        y -= 1
    end
    era = y // 400
    yoe = y - era * 400
    mp = (m + 9) % 12
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468
end

function words(s):
    out = []
    for w in s.replace(",", " ").replace("\t", " ").split(" "):
        if w != "":
            out.append(w)
        end
    end
    return out
end

# RFC 5322 ("Tue, 5 Nov 2026 14:03:22 +0100 (CET)") i IMAP INTERNALDATE ("05-Nov-2026 14:03:22 +0100")
# -> Unix cas; 0 kdyz nejde precist
function parse_date(s):
    if s == None:
        return 0
    end
    tokens = []
    for w in words(s):
        if w.count("-") == 2 and not w.startswith("-"):
            tokens.extend(w.split("-"))
        else:
            tokens.append(w)
        end
    end
    day = -1
    month = -1
    year = -1
    hh = 0
    mm = 0
    ss = 0
    zone = 0
    for t in tokens:
        low = t.lower()
        if len(low) >= 3 and low[0:3] in MONTHS and month < 0 and to_int(low[0:1], -1) < 0:
            month = MONTHS[low[0:3]]
            continue
        end
        if t.find(":") > 0:
            hms = t.split(":")
            hh = to_int(hms[0], 0)
            if len(hms) > 1:
                mm = to_int(hms[1], 0)
            end
            if len(hms) > 2:
                ss = to_int(hms[2][0:2], 0)
            end
            continue
        end
        if (t.startswith("+") or t.startswith("-")) and len(t) == 5:
            v = to_int(t[1:], -1)
            if v >= 0:
                zone = v
                if t.startswith("-"):
                    zone = -v
                end
            end
            continue
        end
        if t.upper() in ZONES:
            zone = ZONES[t.upper()]
            continue
        end
        v = to_int(t, -1)
        if v < 0:
            continue
        end
        if day < 0 and v >= 1 and v <= 31 and len(t) <= 2:
            day = v
        elif year < 0:
            year = v
            if len(t) <= 2:
                if v < 50:
                    year = 2000 + v
                else:
                    year = 1900 + v
                end
            end
        end
    end
    if day < 0 or month < 0 or year < 1970:
        return 0
    end
    offset = (zone // 100) * 3600 + (zone % 100) * 60
    if zone < 0:
        offset = -((-zone) // 100 * 3600 + ((-zone) % 100) * 60)
    end
    return days_from_civil(year, month, day) * 86400 + hh * 3600 + mm * 60 + ss - offset
end

# ---- nahled zpravy v seznamu -------------------------------------------------------------------------------------

function collapse_space(text):
    b = net.bytes(text)
    out = ByteArray()
    space = True
    for c in b:
        if c == 32 or c == 9 or c == 10 or c == 13:
            if not space:
                out.append(32)
                space = True
            end
        else:
            out.append(c)
            space = False
        end
    end
    return net.text(out).strip()
end

# Zacatek tela (castecny FETCH) -> jednoradkovy nahled bez citaci
function preview_text(data, encoding, charset, html):
    enc = encoding.lower()
    raw = data
    if enc == "base64":
        raw = b64_decode(data, 0, len(data))
    elif enc == "quoted-printable":
        raw = qp_decode(data, 0, len(data), False)
    end
    text = decode_text(raw, 0, len(raw), charset)
    if html:
        text = html_to_text(text)
    end
    kept = []
    total = 0
    for line in text.split("\n"):
        l = line.strip()
        if l == "" or l.startswith(">"):
            continue
        end
        kept.append(l)
        total += len(l)
        if total > 400:
            break
        end
    end
    p = collapse_space(" ".join(kept))
    if p.endswith("�"):
        p = p[0:len(p) - 1]
    end
    if len(p) > 220:
        p = p[0:220]
    end
    return p
end
