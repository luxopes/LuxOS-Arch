# LuxOS - cteni kanalu xfconf primo ze souboru (na Waylandu xfconfd nemusi bezet): systemovy vychozi kanal
# z /etc/xdg a uzivatelsky v ~/.config, ktery ma prednost. Vlastnosti jako {"/saver/idle-activation/delay": "10"}.
#
#   xfconf.channel(nazev) -> {cesta: hodnota}     cela vlastnost jako text (bool "true"/"false")
#   xfconf.user_path(nazev)                       soubor uzivatele (pro gio.file_monitor)
#   xfconf.write(nazev, {cesta: [typ, hodnota]})   zmeni vlastnosti v souboru uzivatele (ostatni zustanou),
#                                                 atomicky; jen kdyz xfconfd nebezi (Wayland), jinak xfconf-query
load glib
load luxos_glib as lglib
load luxos_text as text

SYSTEM = "/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/"

function user_path(name):
    return glib.user_config_dir() + "/xfce4/xfconf/xfce-perchannel-xml/" + name + ".xml"
end

function attr(line, name):
    cut = line.find(name + "=\"")
    if cut < 0:
        return ""
    end
    rest = line[cut + len(name) + 2:]
    return rest[0:rest.find("\"")]
end

# vnorene <property> skladaji cestu
function read_into(path, into):
    stack = []
    for raw in text.lines(lglib.read_text(path)):
        line = raw.strip()
        if line.startswith("<property "):
            name = attr(line, "name")
            if line.endswith("/>"):
                into["/" + text.join(stack + [name], "/")] = attr(line, "value")
            else:
                stack.append(name)
            end
        elif line.startswith("</property>") and len(stack) > 0:
            call stack.pop()
        end
    end
    return into
end

function channel(name):
    return read_into(user_path(name), read_into(SYSTEM + name + ".xml", {}))
end

# ---- zapis (soubor ve formatu xfconfd) ----

function unescape(value):
    return value.replace("&quot;", "\"").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
end

function escape(value):
    return String(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")
end

# strom vlastnosti: {"name", "type", "value", "children", "raw"}; obsah poli (<value .../>) zustava jako text
function parse_tree(content):
    root = {"name": "", "type": "empty", "value": "", "children": [], "raw": []}
    stack = [root]
    for raw in text.lines(content):
        line = raw.strip()
        top = stack[len(stack) - 1]
        if line.startswith("<property "):
            node = {"name": unescape(attr(line, "name")), "type": attr(line, "type"), "value": unescape(attr(line, "value")), "children": [], "raw": []}
            top["children"].append(node)
            if not line.endswith("/>"):
                stack.append(node)
            end
        elif line.startswith("<value ") and len(stack) > 1:
            top["raw"].append(line)
        elif line.startswith("</property>") and len(stack) > 1:
            call stack.pop()
        end
    end
    return root
end

function child(node, name):
    for c in node["children"]:
        if c["name"] == name:
            return c
        end
    end
    c = {"name": name, "type": "empty", "value": "", "children": [], "raw": []}
    node["children"].append(c)
    return c
end

function serialize(node, depth, out):
    pad = ""
    for i in range(depth):
        pad = pad + "  "
    end
    head = pad + "<property name=\"" + escape(node["name"]) + "\" type=\"" + node["type"] + "\""
    if node["type"] != "empty" and node["type"] != "array":
        head = head + " value=\"" + escape(node["value"]) + "\""
    end
    if len(node["children"]) == 0 and len(node["raw"]) == 0:
        out.append(head + "/>")
        return out
    end
    out.append(head + ">")
    for line in node["raw"]:
        out.append(pad + "  " + line)
    end
    for c in node["children"]:
        call serialize(c, depth + 1, out)
    end
    out.append(pad + "</property>")
    return out
end

function write(name, changes):
    path = user_path(name)
    root = parse_tree(lglib.read_text(path))
    for key in changes.keys():
        node = root
        for part in key.split("/"):
            if part != "":
                node = child(node, part)
            end
        end
        node["type"] = changes[key][0]
        node["value"] = changes[key][1]
    end
    out = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "", "<channel name=\"" + escape(name) + "\" version=\"1.0\">"]
    for c in root["children"]:
        call serialize(c, 1, out)
    end
    out.append("</channel>")
    call lglib.mkdir_p(path[0:text.rfind(path, "/")])
    return lglib.write_atomic(path, text.join(out, "\n") + "\n")
end
