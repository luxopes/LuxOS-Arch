# Posta LuxOS - zprava jako bezpecny dokument HTML pro zobrazeni ve WebKitGTK (mail_web).
#   document(b, opts)     cela zprava (.eml) -> {"html", "remote", "has_html", "inline": [cid]}
#                         opts: {"remote": True = povolit vzdalene obrazky, "dark": tmavy vzhled, "images": nahledy priloh}
#   sanitize(html, ctx)   HTML zpravy -> bezpecny fragment (whitelist znacek a atributu)
#   text_to_html(text)    prosty text -> HTML: odkazy, citace (> ...) jako bloky s carou, podpis "-- " ztlumeny,
#                         tabulky z ASCII a kod neproporcionalnim pismem
# Bezpecnost: zadne skripty, obsluhy udalosti (on*), formulare, iframe/object/embed, odkazy jen http(s)/mailto/tel/#,
# zadne externi styly (@import, <link>), url() v CSS jen data:/cid:. Vzdalene obrazky (sledovaci pixely) jen kdyz
# je uzivatel povoli; sledovaci obrazky 1x1 nikdy. Dokument navic nese Content-Security-Policy (default-src 'none'),
# takze ani prehlednuty odkaz na sit se nenacte. Obrazky z priloh (cid:) se vlozi jako data:.
load net
load mail_bytes as mb
load mail_mime as mime

DROP_CONTENT = {"script": 1, "title": 1, "iframe": 1, "frameset": 1, "object": 1, "applet": 1,
                "svg": 1, "math": 1, "template": 1, "textarea": 1, "select": 1, "audio": 1, "video": 1, "canvas": 1,
                "noembed": 1, "noframes": 1, "xml": 1, "button": 1, "option": 1}
# zahazovane znacky bez obsahu (prazdne prvky: nemaji koncovou znacku, obsah za nimi zustava)
DROP_VOID = {"embed": 1, "frame": 1, "param": 1, "source": 1, "track": 1, "input": 1, "link": 1, "meta": 1, "base": 1,
             "area": 1, "keygen": 1}
ALLOWED = {"a": 1, "abbr": 1, "address": 1, "article": 1, "aside": 1, "b": 1, "bdi": 1, "bdo": 1, "big": 1, "blockquote": 1,
           "br": 1, "caption": 1, "center": 1, "cite": 1, "code": 1, "col": 1, "colgroup": 1, "dd": 1, "del": 1, "details": 1,
           "dfn": 1, "div": 1, "dl": 1, "dt": 1, "em": 1, "figcaption": 1, "figure": 1, "font": 1, "footer": 1, "h1": 1,
           "h2": 1, "h3": 1, "h4": 1, "h5": 1, "h6": 1, "header": 1, "hr": 1, "i": 1, "img": 1, "ins": 1, "kbd": 1, "li": 1,
           "main": 1, "mark": 1, "nav": 1, "ol": 1, "p": 1, "pre": 1, "q": 1, "s": 1, "samp": 1, "section": 1, "small": 1,
           "span": 1, "strike": 1, "strong": 1, "sub": 1, "summary": 1, "sup": 1, "table": 1, "tbody": 1, "td": 1, "tfoot": 1,
           "th": 1, "thead": 1, "time": 1, "tr": 1, "tt": 1, "u": 1, "ul": 1, "var": 1, "wbr": 1, "label": 1}
VOID = {"br": 1, "hr": 1, "img": 1, "wbr": 1, "col": 1}
ATTRS = {"style": 1, "class": 1, "id": 1, "dir": 1, "lang": 1, "title": 1, "align": 1, "valign": 1, "width": 1, "height": 1,
         "bgcolor": 1, "color": 1, "border": 1, "cellpadding": 1, "cellspacing": 1, "colspan": 1, "rowspan": 1, "nowrap": 1,
         "face": 1, "size": 1, "start": 1, "type": 1, "reversed": 1, "alt": 1, "href": 1, "src": 1, "background": 1, "name": 1,
         "hspace": 1, "vspace": 1, "scope": 1, "headers": 1, "summary": 1, "open": 1, "datetime": 1, "role": 1}
IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/x-icon", "image/vnd.microsoft.icon"]
MAX_INLINE = 10485760

# Hledani od pozice (String.find umi jen od zacatku)
function find_from(s, sub, start):
    if start >= len(s):
        return -1
    end
    p = s[start:].find(sub)
    if p < 0:
        return -1
    end
    return p + start
end

function esc(s):
    return String(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")
end

# Hodnota atributu s entitami -> text (&amp; &#x61; &quot; ...)
function decode_entities(s):
    if s.find("&") < 0:
        return s
    end
    b = net.bytes(s)
    n = len(b)
    out = []
    i = 0
    start = 0
    while i < n:
        if b[i] == 38:
            semi = mb.find_byte(b, 59, i + 1, min(n, i + 12))
            if semi > i + 1:
                if i > start:
                    out.append(net.text(b, start, i - start))
                end
                name = net.text(b, i + 1, semi - i - 1)
                t = mime.entity_text(name)
                if t == "&" + name + ";" and name.lower() in ["amp", "quot", "lt", "gt", "apos"]:
                    t = {"amp": "&", "quot": "\"", "lt": "<", "gt": ">", "apos": "'"}[name.lower()]
                end
                out.append(t)
                i = semi + 1
                start = i
                continue
            end
        end
        i += 1
    end
    if start < n:
        out.append(net.text(b, start, n - start))
    end
    return "".join(out)
end

# Adresa bez mezer a ridicich znaku pro kontrolu schematu ("java\tscript:" -> "javascript:")
function compact_url(v):
    out = ByteArray()
    for c in net.bytes(v.strip()):
        if c > 32 and c != 127:
            out.append(c)
        end
    end
    return net.text(out)
end

function safe_href(v):
    u = compact_url(v)
    low = u.lower()
    if low.startswith("http://") or low.startswith("https://") or low.startswith("mailto:") or low.startswith("tel:") or u.startswith("#"):
        return u
    end
    return ""
end

function is_tracking(attrs):
    w = mime.to_int(attrs.get("width", "").replace("px", ""), -1)
    h = mime.to_int(attrs.get("height", "").replace("px", ""), -1)
    if (w >= 0 and w <= 2) and (h >= 0 and h <= 2):
        return True
    end
    st = attrs.get("style", "").replace(" ", "").lower()
    if st.find("width:1px") >= 0 or st.find("width:0") >= 0 or st.find("display:none") >= 0:
        return True
    end
    return False
end

# Obrazek ze zpravy (cid:) -> data:; {} kdyz neni
function cid_data(ctx, url):
    cid = url[4:]
    if cid.startswith("<") and cid.endswith(">"):
        cid = cid[1:len(cid) - 1]
    end
    cid = mime.decode_text(mime.percent_decode(cid), 0, len(mime.percent_decode(cid)), "utf-8")
    part = ctx["cids"].get(cid, {})
    if len(part) == 0:
        return ""
    end
    if cid not in ctx["used"]:
        ctx["used"].append(cid)
    end
    if cid in ctx["data"]:
        return ctx["data"][cid]
    end
    data = mime.decode_body(ctx["b"], part)
    if len(data) > MAX_INLINE:
        return ""
    end
    t = part["type"]
    if t not in IMAGE_TYPES:
        t = "image/png"
    end
    uri = "data:" + t + ";base64," + mb.b64_text(data)
    ctx["data"][cid] = uri
    return uri
end

# Adresa obrazku: cid: -> data:, data:image/* (ne SVG) zustane, vzdalena jen s povolenim; "" = vynechat
function image_url(ctx, v, tracking):
    u = compact_url(v)
    low = u.lower()
    if low.startswith("cid:"):
        return cid_data(ctx, u)
    end
    if low.startswith("data:image/") and not low.startswith("data:image/svg"):
        return u
    end
    if low.startswith("http://") or low.startswith("https://") or low.startswith("//"):
        if tracking:
            ctx["tracking"] = ctx["tracking"] + 1
            return ""
        end
        if ctx["remote"]:
            if low.startswith("//"):
                return "https:" + u
            end
            return u
        end
        ctx["blocked"] = ctx["blocked"] + 1
        return ""
    end
    return ""
end

# CSS (atribut style i blok <style>): pryc expression(), javascript:, behavior, -moz-binding, @import; url() jen
# data:/cid: (vzdalene s povolenim); "" = cely styl zahodit
function clean_css(ctx, css):
    low = css.lower()
    for bad in ["expression(", "javascript:", "vbscript:", "behavior:", "-moz-binding", "</style"]:
        if low.find(bad) >= 0:
            return ""
        end
    end
    out = []
    rest = css
    loop:
        lowrest = rest.lower()
        p = lowrest.find("url(")
        q = lowrest.find("@import")
        if q >= 0 and (p < 0 or q < p):
            semi = find_from(rest, ";", q)
            out.append(rest[0:q])
            if semi < 0:
                rest = ""
            else:
                rest = rest[semi + 1:]
            end
            continue
        end
        if p < 0:
            out.append(rest)
            break
        end
        close = find_from(rest, ")", p)
        if close < 0:
            out.append(rest[0:p])
            break
        end
        inner = rest[p + 4:close].strip()
        if inner.startswith("\"") or inner.startswith("'"):
            inner = inner[1:len(inner) - 1]
        end
        u = image_url(ctx, decode_entities(inner), False)
        out.append(rest[0:p])
        if u == "":
            out.append("none")
        else:
            out.append("url(\"" + u.replace("\"", "%22") + "\")")
        end
        rest = rest[close + 1:]
    end
    result = "".join(out)
    rl = result.lower()
    if rl.find("color") >= 0 or rl.find("background") >= 0:
        ctx["colors"] = True
    end
    return result
end

# Atributy znacky -> {jmeno: hodnota} (hodnoty s dekodovanymi entitami)
function parse_attrs(b, start, stop):
    out = {}
    i = start
    while i < stop:
        c = b[i]
        if c == 32 or c == 9 or c == 10 or c == 13 or c == 47:
            i += 1
            continue
        end
        ns = i
        while i < stop and b[i] != 61 and b[i] != 32 and b[i] != 9 and b[i] != 10 and b[i] != 13 and b[i] != 47 and b[i] != 62:
            i += 1
        end
        name = net.text(b, ns, i - ns).lower()
        while i < stop and (b[i] == 32 or b[i] == 9 or b[i] == 10 or b[i] == 13):
            i += 1
        end
        value = ""
        if i < stop and b[i] == 61:
            i += 1
            while i < stop and (b[i] == 32 or b[i] == 9 or b[i] == 10 or b[i] == 13):
                i += 1
            end
            if i < stop and (b[i] == 34 or b[i] == 39):
                q = b[i]
                e = mb.find_byte(b, q, i + 1, stop)
                if e < 0:
                    e = stop
                end
                value = net.text(b, i + 1, e - i - 1)
                i = e + 1
            else:
                vs = i
                while i < stop and b[i] != 32 and b[i] != 9 and b[i] != 10 and b[i] != 13 and b[i] != 62:
                    i += 1
                end
                value = net.text(b, vs, i - vs)
            end
        end
        if name != "" and name not in out:
            out[name] = decode_entities(value)
        end
    end
    return out
end

function clean_attrs(ctx, tag, attrs):
    out = []
    tracking = tag == "img" and is_tracking(attrs)
    for name in attrs.keys():
        v = attrs[name]
        if name not in ATTRS or name.startswith("on"):
            continue
        end
        if name == "href":
            if tag != "a":
                continue
            end
            v = safe_href(v)
            if v == "":
                continue
            end
        elif name == "src":
            if tag != "img":
                continue
            end
            v = image_url(ctx, v, tracking)
            if v == "":
                return ["", False]
            end
        elif name == "background":
            v = image_url(ctx, v, False)
            if v == "":
                continue
            end
        elif name == "style":
            v = clean_css(ctx, v)
            if v == "":
                continue
            end
        elif name == "bgcolor" or name == "color" or name == "text":
            ctx["colors"] = True
        end
        out.append(" " + name + "=\"" + esc(v) + "\"")
    end
    if tag == "img" and "src" not in attrs:
        return ["", False]
    end
    return ["".join(out), True]
end

# Konec obsahu zahazovane znacky: index za "</jmeno ...>" nebo konec
function skip_to_close(b, low, name, start, n):
    key = net.bytes("</" + name)
    p = start
    loop:
        hit = mb.find(low, key, p)
        if hit < 0:
            return n
        end
        after = hit + len(key)
        if after >= n or b[after] == 62 or b[after] == 32 or b[after] == 9 or b[after] == 10 or b[after] == 13:
            gt = mb.find_byte(b, 62, after, n)
            if gt < 0:
                return n
            end
            return gt + 1
        end
        p = hit + 1
    end
end

# Konec znacky od "<" (">" mimo uvozovky); -1 kdyz neni
function tag_end(b, start, n):
    i = start
    q = 0
    while i < n:
        c = b[i]
        if q != 0:
            if c == q:
                q = 0
            end
        elif c == 34 or c == 39:
            # uvozovky jen v hodnote atributu (po "=")
            j = i - 1
            while j > start and (b[j] == 32 or b[j] == 9):
                j -= 1
            end
            if b[j] == 61:
                q = c
            end
        elif c == 62:
            return i
        end
        i += 1
    end
    return -1
end

function new_ctx(b, cids, remote):
    return {"b": b, "cids": cids, "remote": remote, "blocked": 0, "tracking": 0, "colors": False, "used": [], "data": {}}
end

function sanitize(html, ctx):
    b = net.bytes(html)
    low = mime.lower_bytes(b)
    n = len(b)
    out = []
    i = 0
    while i < n:
        lt = mb.find_byte(b, 60, i, n)
        if lt < 0:
            out.append(net.text(b, i, n - i))
            break
        end
        if lt > i:
            out.append(net.text(b, i, lt - i))
        end
        # komentare (i podminene <!--[if mso]>), <!DOCTYPE>, <?xml ...?>
        if lt + 3 < n and b[lt + 1] == 33 and b[lt + 2] == 45 and b[lt + 3] == 45:
            e = mb.find(b, "-->", lt + 4)
            if e < 0:
                break
            end
            i = e + 3
            continue
        end
        if lt + 1 < n and (b[lt + 1] == 33 or b[lt + 1] == 63):
            e = mb.find_byte(b, 62, lt + 1, n)
            if e < 0:
                break
            end
            i = e + 1
            continue
        end
        closing = lt + 1 < n and b[lt + 1] == 47
        ns = lt + 1
        if closing:
            ns += 1
        end
        ne = ns
        while ne < n and ((low[ne] >= 97 and low[ne] <= 122) or (low[ne] >= 48 and low[ne] <= 57) or low[ne] == 58 or low[ne] == 45):
            ne += 1
        end
        if ne == ns or not (low[ns] >= 97 and low[ns] <= 122):
            out.append("&lt;")
            i = lt + 1
            continue
        end
        gt = tag_end(b, ne, n)
        if gt < 0:
            break
        end
        name = net.text(low, ns, ne - ns)
        i = gt + 1
        if name == "style":
            if closing:
                continue
            end
            stop = skip_to_close(b, low, "style", i, n)
            close = stop
            k = stop - 1
            while k > i and b[k] != 60:
                k -= 1
            end
            if k > i:
                close = k
            end
            css = clean_css(ctx, net.text(b, i, close - i))
            if css != "":
                out.append("<style>" + css.replace("<", "") + "</style>")
            end
            i = stop
            continue
        end
        if name in DROP_VOID:
            continue
        end
        if name in DROP_CONTENT:
            if not closing and b[gt - 1] != 47:
                i = skip_to_close(b, low, name, i, n)
            end
            continue
        end
        if name == "body":
            if not closing:
                attrs = parse_attrs(b, ne, gt)
                st = ""
                if "bgcolor" in attrs:
                    st = st + "background-color:" + esc(attrs["bgcolor"]).replace(";", "") + ";"
                    ctx["colors"] = True
                end
                if "text" in attrs:
                    st = st + "color:" + esc(attrs["text"]).replace(";", "") + ";"
                    ctx["colors"] = True
                end
                if "style" in attrs:
                    st = st + clean_css(ctx, attrs["style"])
                end
                if st != "":
                    out.append("<div class=\"lux-mail-body\" style=\"" + esc(st) + "\">")
                else:
                    out.append("<div class=\"lux-mail-body\">")
                end
                ctx["body_open"] = True
            elif ctx.get("body_open", False):
                out.append("</div>")
                ctx["body_open"] = False
            end
            continue
        end
        if name not in ALLOWED:
            continue
        end
        if closing:
            if name not in VOID:
                out.append("</" + name + ">")
            end
            continue
        end
        attrs = parse_attrs(b, ne, gt)
        r = clean_attrs(ctx, name, attrs)
        if not r[1]:
            alt = attrs.get("alt", "").strip()
            if alt != "" and name == "img":
                out.append("<span class=\"lux-blocked\">" + esc(alt) + "</span>")
            end
            continue
        end
        out.append("<" + name + r[0] + ">")
    end
    if ctx.get("body_open", False):
        out.append("</div>")
        ctx["body_open"] = False
    end
    return "".join(out)
end

# ---- prosty text ----------------------------------------------------------------------------------------------

TRAIL = ".,;:!?'\")]>}"

function link_html(word):
    # obal <...> a (...) kolem adresy
    lead = ""
    w = word
    while len(w) > 0 and "(<\"'[".find(w[0:1]) >= 0:
        lead = lead + w[0:1]
        w = w[1:]
    end
    trail = ""
    while len(w) > 0 and TRAIL.find(w[len(w) - 1:]) >= 0:
        ch = w[len(w) - 1:]
        if ch == ")" and w.count("(") > w.count(")") - 1 and w.count("(") > 0:
            break
        end
        trail = ch + trail
        w = w[0:len(w) - 1]
    end
    low = w.lower()
    href = ""
    if low.startswith("http://") or low.startswith("https://"):
        if len(w) > 8:
            href = w
        end
    elif low.startswith("www.") and find_from(w, ".", 4) > 4:
        href = "https://" + w
    elif low.startswith("mailto:") and w.find("@") > 7:
        href = w
    else:
        at = w.find("@")
        if at > 0 and find_from(w, ".", at) > at + 1 and find_from(w, "@", at + 1) < 0 and not w.endswith("."):
            ok = True
            for ch in w:
                if "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.!#$%&'*+-/=?^_`{|}~@".find(ch) < 0:
                    ok = False
                    break
                end
            end
            if ok:
                href = "mailto:" + w
            end
        end
    end
    if href == "":
        return esc(word)
    end
    return esc(lead) + "<a href=\"" + esc(href) + "\">" + esc(w) + "</a>" + esc(trail)
end

function linkify(line):
    if line.find(".") < 0 and line.find("@") < 0:
        return esc(line)
    end
    out = []
    for w in line.split(" "):
        if w.find(".") >= 0 or w.find("@") >= 0 or w.find(":") >= 0:
            out.append(link_html(w))
        else:
            out.append(esc(w))
        end
    end
    return " ".join(out)
end

# Uroven citace "> > text" -> [uroven, text]
function quote_level(line):
    level = 0
    i = 0
    n = len(line)
    while i < n:
        ch = line[i:i + 1]
        if ch == ">":
            level += 1
            i += 1
            if i < n and line[i:i + 1] == " ":
                i += 1
            end
        elif ch == " " and level > 0 and i + 1 < n and line[i + 1:i + 2] == ">":
            i += 1
        else:
            break
        end
    end
    return [level, line[i:]]
end

BOX_CHARS = "│┃─━┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬"

# Radek, ktery vypada jako tabulka z ASCII nebo kod (zarovnani mezerami): neproporcionalni pismo
function mono_line(line):
    if line.startswith("    ") or line.startswith("\t"):
        return line.strip() != ""
    end
    if line.count("|") >= 2 or line.find("+--") >= 0 or line.find("--+") >= 0 or line.find("===") >= 0 and line.strip().startswith("="):
        return True
    end
    for ch in BOX_CHARS:
        if line.find(ch) >= 0:
            return True
        end
    end
    return line.strip().find("   ") > 0 and line.count("  ") >= 3
end

function block_html(lines):
    # bloky radku: neproporcionalni useky (aspon 2 radky za sebou) v <pre>, zbytek text s odkazy
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if mono_line(lines[i]):
            j = i
            while j < n and (mono_line(lines[j]) or (lines[j].strip() == "" and j + 1 < n and mono_line(lines[j + 1]))):
                j += 1
            end
            if j - i >= 2:
                rows = []
                for l in lines[i:j]:
                    rows.append(linkify(l))
                end
                out.append("<pre class=\"mono\">" + "\n".join(rows) + "</pre>")
                i = j
                continue
            end
        end
        out.append(linkify(lines[i]) + "\n")
        i += 1
    end
    return "".join(out)
end

function text_to_html(text):
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while len(lines) > 0 and lines[len(lines) - 1].strip() == "":
        call lines.pop()
    end
    # podpis: posledni radek "-- " mimo citaci
    sig = -1
    k = len(lines) - 1
    while k >= 0:
        if lines[k] == "-- " or lines[k] == "--":
            sig = k
            break
        end
        k -= 1
    end
    out = ["<div class=\"plain\">"]
    level = 0
    run = []
    i = 0
    for raw in lines:
        if i == sig:
            if len(run) > 0:
                out.append(block_html(run))
                run = []
            end
            while level > 0:
                out.append("</blockquote>")
                level -= 1
            end
            out.append("<div class=\"sig\">")
        end
        q = [0, raw]
        if sig < 0 or i < sig:
            q = quote_level(raw)
        end
        if q[0] != level:
            if len(run) > 0:
                out.append(block_html(run))
                run = []
            end
            while level < q[0]:
                out.append("<blockquote class=\"q\">")
                level += 1
            end
            while level > q[0]:
                out.append("</blockquote>")
                level -= 1
            end
        end
        run.append(q[1])
        i += 1
    end
    if len(run) > 0:
        out.append(block_html(run))
    end
    while level > 0:
        out.append("</blockquote>")
        level -= 1
    end
    if sig >= 0:
        out.append("</div>")
    end
    out.append("</div>")
    return "".join(out)
end

# ---- cela zprava -------------------------------------------------------------------------------------------------

function collect_cids(part, cids):
    if part["cid"] != "" and part["type"].startswith("image/"):
        cids[part["cid"]] = part
    end
    for child in part["parts"]:
        call collect_cids(child, cids)
    end
    return 0
end

function has_html_part(part):
    if part["type"] == "text/html" and part["disposition"] != "attachment":
        return True
    end
    for child in part["parts"]:
        if has_html_part(child):
            return True
        end
    end
    return False
end

# Telo k zobrazeni: u multipart/alternative HTML (kdyz je), jinak text; prilohy obrazku pro nahledy
function view_collect(b, part, vctx, ctx):
    t = part["type"]
    if t.startswith("multipart/"):
        if t == "multipart/alternative":
            choice = {}
            for p in part["parts"]:
                if has_html_part(p):
                    choice = p
                end
            end
            if len(choice) == 0:
                choice = mime.choose_alternative(part["parts"])
            end
            if len(choice) > 0:
                call view_collect(b, choice, vctx, ctx)
            end
            return 0
        end
        for child in part["parts"]:
            call view_collect(b, child, vctx, ctx)
        end
        return 0
    end
    attachment = part["disposition"] == "attachment"
    if (t == "text/plain" or t == "text/html") and not attachment and part["filename"] == "":
        data = mime.decode_body(b, part)
        text = mime.decode_text(data, 0, len(data), part["params"].get("charset", ""))
        if t == "text/html":
            vctx["html"] = True
            vctx["pieces"].append(sanitize(text, ctx))
        else:
            if part["params"].get("format", "").lower() == "flowed":
                text = mime.unflow(text, part["params"].get("delsp", "").lower() == "yes")
            end
            vctx["pieces"].append(text_to_html(text))
        end
        return 0
    end
    if t in IMAGE_TYPES and part["cid"] == "" or (t in IMAGE_TYPES and attachment):
        vctx["images"].append(part)
    end
    return 0
end

PALETTE_LIGHT = {"bg": "#ffffff", "fg": "#1d1d1f", "link": "#0a64d6", "dim": "#6e6e73", "q1": "#3b82f6", "q2": "#22a06b", "q3": "#a855f7", "pre": "#f4f4f6"}
PALETTE_DARK = {"bg": "#232325", "fg": "#e6e6e8", "link": "#6cb4ff", "dim": "#9a9aa0", "q1": "#5b9dff", "q2": "#3ccf8e", "q3": "#c084fc", "pre": "#2c2c30"}

function base_css(pal, paper):
    bg = pal["bg"]
    fg = pal["fg"]
    link = pal["link"]
    if paper:
        # zprava s vlastnimi barvami: na bilem papire i v tmavem vzhledu (citelnost, jako Posta v macOS)
        bg = "#ffffff"
        fg = "#1d1d1f"
        link = "#0a64d6"
    end
    return "html,body{margin:0;padding:0}body{background:" + bg + ";color:" + fg + ";font:14px/1.5 'Inter','Cantarell','Noto Sans',sans-serif;padding:14px 22px 26px;overflow-wrap:break-word;word-wrap:break-word}" + "a{color:" + link + "}img{max-width:100%;height:auto}table{border-collapse:collapse}" + ".plain{white-space:pre-wrap}.plain pre.mono{font-family:'JetBrainsMono Nerd Font','DejaVu Sans Mono',monospace;font-size:12.5px;white-space:pre;overflow-x:auto;background:" + pal["pre"] + ";padding:8px 10px;border-radius:6px;margin:4px 0}" + "blockquote.q{margin:4px 0;padding:0 0 0 12px;border-left:3px solid " + pal["q1"] + ";color:" + pal["dim"] + "}blockquote.q blockquote.q{border-left-color:" + pal["q2"] + "}blockquote.q blockquote.q blockquote.q{border-left-color:" + pal["q3"] + "}" + ".sig{color:" + pal["dim"] + ";font-size:13px}.lux-blocked{display:inline-block;color:" + pal["dim"] + ";border:1px dashed " + pal["dim"] + ";border-radius:4px;padding:0 4px;font-size:12px}" + "hr.lux-split{border:0;border-top:1px solid " + pal["dim"] + ";opacity:.4;margin:16px 0}.lux-images{margin-top:18px}.lux-images img{max-width:min(100%,520px);max-height:420px;border-radius:6px;margin:0 10px 10px 0;box-shadow:0 1px 3px rgba(0,0,0,.25)}"
end

function document(b, opts):
    tree = mime.parse_message(b)
    cids = {}
    call collect_cids(tree, cids)
    ctx = new_ctx(b, cids, opts.get("remote", False))
    vctx = {"pieces": [], "images": [], "html": False}
    call view_collect(b, tree, vctx, ctx)
    body = "<hr class=\"lux-split\">".join(vctx["pieces"])
    if len(vctx["pieces"]) == 0:
        body = ""
    end
    if opts.get("images", True) and len(vctx["images"]) > 0:
        imgs = []
        for p in vctx["images"]:
            if p["cid"] != "" and p["cid"] in ctx["used"]:
                continue
            end
            if p["stop"] - p["start"] > MAX_INLINE * 4 // 3:
                continue
            end
            data = mime.decode_body(b, p)
            imgs.append("<img alt=\"\" src=\"data:" + p["type"] + ";base64," + mb.b64_text(data) + "\">")
        end
        if len(imgs) > 0:
            body = body + "<div class=\"lux-images\">" + "".join(imgs) + "</div>"
        end
    end
    pal = PALETTE_LIGHT
    if opts.get("dark", False):
        pal = PALETTE_DARK
    end
    paper = vctx["html"] and ctx["colors"]
    img_src = "data:"
    if ctx["remote"]:
        img_src = "data: https: http:"
    end
    csp = "default-src 'none'; img-src " + img_src + "; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none'"
    cls = "plain-mail"
    if vctx["html"]:
        cls = "html-mail"
    end
    html = "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" content=\"" + csp + "\"><meta name=\"referrer\" content=\"no-referrer\"><style>" + base_css(pal, paper) + "</style></head><body class=\"" + cls + "\">" + body + "</body></html>"
    return {"html": html, "remote": ctx["blocked"], "tracking": ctx["tracking"], "has_html": vctx["html"], "paper": paper,
            "inline": ctx["used"]}
end
