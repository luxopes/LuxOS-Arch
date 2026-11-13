# lsl: internal-abi
# lsl: link libglib-2.0.so.0 libc.so.6
# LuxOS Icon Studio: versioned, self-contained project format. No shell or interpreter.
load json
load glib

FORMAT = 1
CANVAS = 1024
MAX_LAYERS = 64
MAX_PROJECT_BYTES = 3500000
MAX_ASSET_BYTES = 1048576

function ptr(value):
    return __lsl_unbox_int(value)
end

function cstr(value):
    return __lsl_address(value) + 16
end

function data(bytes):
    return __lsl_qbe_load64(__lsl_address(bytes) + 24)
end

function check_path(path):
    if type(path) != "String" or not path or len(path) > 4096 or "\0" in path:
        Error(FileError: "Choose a valid file path.")
    end
end

function file_size(path):
    call check_path(path)
    buffer = __lsl_byte_zeros(256)
    if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("stat"), cstr(path), data(buffer))) != 0:
        Error(FileError: "The file could not be opened.")
    end
    # Linux x86_64 struct stat (the application's explicit compilation target).
    mode = __lsl_qbe_load32(data(buffer) + 24)
    if (mode & 61440) != 32768:
        Error(FileError: "Choose a regular file.")
    end
    return __lsl_qbe_load64(data(buffer) + 48)
end

function atomic_bytes(path, bytes):
    call check_path(path)
    errors = __lsl_byte_zeros(8)
    # CONSISTENT | DURABLE: GLib writes a sibling temporary file, fsyncs and renames.
    ok = __lsl_qbe_call6(__lsl_symbol("g_file_set_contents_full"), cstr(path), data(bytes), len(bytes), 3, 384, data(errors))
    problem = __lsl_qbe_load64(data(errors))
    if problem != 0:
        call __lsl_qbe_call1(__lsl_symbol("g_error_free"), problem)
    end
    if ok == 0:
        Error(FileError: "Could not save the file. Check the folder and its permissions.")
    end
    return True
end

function atomic_text(path, text):
    bytes = __lsl_byte_zeros(__lsl_text_byte_length(text))
    if len(bytes):
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), data(bytes), cstr(text), len(bytes))
    end
    return atomic_bytes(path, bytes)
end

function regex(pattern, text):
    return __lsl_qbe_call4(__lsl_symbol("g_regex_match_simple"), cstr(pattern), cstr(text), 1, 0) != 0
end

function bounded(value, fallback, low, high):
    if value == None:
        return fallback
    end
    if type(value) != "Int" and type(value) != "Float":
        Error(ProjectError: "Layer dimensions and effects must be numbers.")
    end
    number = Float(value)
    if number != number or number > 1000000000 or number < -1000000000:
        Error(ProjectError: "Layer dimensions must be finite numbers.")
    end
    return max(low, min(high, number))
end

function short_text(value, fallback, maximum):
    if value == None:
        return fallback
    end
    if type(value) != "String" or len(value) > maximum or "\0" in value:
        Error(ProjectError: "A project name or text layer is invalid or too long.")
    end
    return value
end

function color(value, fallback="#6085FF"):
    if value == None:
        return fallback
    end
    if type(value) != "String" or not regex("^#[0-9a-f]{6}$", value):
        Error(ProjectError: "Use a color in #RRGGBB format.")
    end
    return value
end

function boolean(value, fallback):
    if value == None:
        return fallback
    end
    if type(value) != "Bool":
        Error(ProjectError: "Layer visibility and shadow must be true or false.")
    end
    return value
end

function layer(kind="rect", identity="layer-1"):
    if kind == "rectangle" or kind == "rounded rectangle":
        kind = "rect"
    end
    return {"id": identity, "name": "New layer", "kind": kind, "visible": True, "opacity": 1.0,
            "x": 256.0, "y": 256.0, "width": 512.0, "height": 512.0, "rotation": 0.0,
            "color": "#7395FF", "color2": "#355AF1", "radius": 112.0, "gloss": 0.0,
            "shadow": False, "text": "L", "font_size": 300.0, "glyph": "orbit", "data_url": ""}
end

function normalize_layer(value):
    if type(value) != "Dictionary":
        Error(ProjectError: "Each layer must be an object.")
    end
    kind = short_text(value.get("kind"), "rect", 24)
    if kind == "rectangle" or kind == "rounded rectangle":
        kind = "rect"
    end
    if kind not in ["rect", "circle", "ellipse", "text", "glyph", "image"]:
        Error(ProjectError: "This layer type is not supported.")
    end
    result = layer(kind, short_text(value.get("id"), "", 80))
    if not result["id"]:
        Error(ProjectError: "Each layer needs a unique id.")
    end
    result["name"] = short_text(value.get("name"), "Layer", 100)
    result["visible"] = boolean(value.get("visible"), True)
    result["shadow"] = boolean(value.get("shadow"), False)
    result["opacity"] = bounded(value.get("opacity"), 1.0, 0.0, 1.0)
    result["gloss"] = bounded(value.get("gloss"), 0.0, 0.0, 1.0)
    result["x"] = bounded(value.get("x"), 256.0, -4096.0, 4096.0)
    result["y"] = bounded(value.get("y"), 256.0, -4096.0, 4096.0)
    result["width"] = bounded(value.get("width"), 512.0, 1.0, 4096.0)
    result["height"] = bounded(value.get("height"), 512.0, 1.0, 4096.0)
    result["rotation"] = bounded(value.get("rotation"), 0.0, -360.0, 360.0)
    result["radius"] = bounded(value.get("radius"), 112.0, 0.0, 2048.0)
    result["font_size"] = bounded(value.get("font_size"), 300.0, 8.0, 1024.0)
    result["color"] = color(value.get("color"))
    result["color2"] = color(value.get("color2"), result["color"])
    result["text"] = short_text(value.get("text"), "L", 256)
    result["glyph"] = short_text(value.get("glyph"), "orbit", 24)
    if result["glyph"] not in ["orbit", "spark", "diamond", "leaf", "wave"]:
        result["glyph"] = "orbit"
    end
    image = value.get("data_url", "")
    if type(image) != "String" or len(image) > 1450000:
        Error(ProjectError: "An image layer is invalid or too large.")
    end
    if image and not regex("^data:image/png;base64,[A-Za-z0-9+/]+={0,2}$", image):
        Error(ProjectError: "Image layers must contain embedded PNG data. Import the image again.")
    end
    result["data_url"] = image
    return result
end

function normalize(project):
    if type(project) != "Dictionary" or type(project.get("format")) != "Int" or project.get("format") != FORMAT:
        Error(ProjectError: "This is not a supported LuxOS Icon Studio project (format 1).")
    end
    if project.get("canvas", CANVAS) != CANVAS:
        Error(ProjectError: "This project uses an unsupported canvas size.")
    end
    layers = project.get("layers")
    if type(layers) != "List" or len(layers) > MAX_LAYERS:
        Error(ProjectError: "A project can contain at most 64 layers.")
    end
    result = {"format": FORMAT, "title": short_text(project.get("title"), "Untitled icon", 120), "canvas": CANVAS, "layers": []}
    seen = []
    total = 0
    for item in layers:
        clean = normalize_layer(item)
        if clean["id"] in seen:
            Error(ProjectError: "Layer ids must be unique.")
        end
        seen.append(clean["id"])
        total += len(clean["data_url"])
        if total > 3000000:
            Error(ProjectError: "Embedded artwork exceeds the 3 MB project limit.")
        end
        result["layers"].append(clean)
    end
    return result
end

function clone(project):
    return json.decode(json.encode(project))
end

function new_project(preset="aurora"):
    result = {"format": FORMAT, "title": "Aurora", "canvas": CANVAS, "layers": []}
    if preset == "blank":
        result["title"] = "Untitled icon"
        return result
    end
    if preset not in ["aurora", "ember"]:
        Error(ProjectError: "Choose the aurora, ember or blank preset.")
    end
    base = layer("rect", "layer-1")
    base["name"] = "Aurora · glass foundation"
    base["x"] = 100.0
    base["y"] = 100.0
    base["width"] = 824.0
    base["height"] = 824.0
    base["radius"] = 216.0
    base["color"] = "#49E2CB"
    base["color2"] = "#464EE8"
    base["gloss"] = 0.48
    base["shadow"] = True
    halo = layer("ellipse", "layer-2")
    halo["name"] = "Soft light"
    halo["x"] = 177.0
    halo["y"] = 154.0
    halo["width"] = 670.0
    halo["height"] = 570.0
    halo["color"] = "#CAFFF3"
    halo["color2"] = "#81C8FF"
    halo["opacity"] = 0.20
    emblem = layer("glyph", "layer-3")
    emblem["name"] = "Orbit · Lux mark"
    emblem["x"] = 240.0
    emblem["y"] = 232.0
    emblem["width"] = 544.0
    emblem["height"] = 544.0
    emblem["color"] = "#FFFFFF"
    emblem["color2"] = "#C4F8FF"
    emblem["gloss"] = 0.25
    emblem["shadow"] = True
    result["layers"] = [base, halo, emblem]
    if preset == "ember":
        result["title"] = "Ember"
        base["name"] = "Ember · warm light"
        base["color"] = "#FFC57B"
        base["color2"] = "#EF537F"
        halo["color"] = "#FFF2C7"
        halo["color2"] = "#FFDC9B"
        emblem["glyph"] = "spark"
        emblem["name"] = "Spark"
    end
    return result
end

function fresh_id(project):
    candidate = 1
    identities = []
    for item in project["layers"]:
        identities.append(item["id"])
    end
    while "layer-" + String(candidate) in identities:
        candidate += 1
    end
    return "layer-" + String(candidate)
end

function find_layer(project, identity):
    for item in project["layers"]:
        if item["id"] == identity:
            return item
        end
    end
    return None
end

function add_layer(project, kind):
    if len(project["layers"]) >= MAX_LAYERS:
        Error(ProjectError: "A project can contain at most 64 layers.")
    end
    item = layer(kind, fresh_id(project))
    item["name"] = {"rect": "Rounded rectangle", "rectangle": "Rounded rectangle", "circle": "Circle", "ellipse": "Ellipse", "text": "Text", "glyph": "Orbit", "image": "Imported artwork"}.get(kind, "Layer")
    if kind == "circle" or kind == "ellipse":
        item["radius"] = 256.0
    end
    project["layers"].append(item)
    return item
end

function duplicate_layer(project, identity):
    original = find_layer(project, identity)
    if original == None:
        Error(ProjectError: "Select a layer first.")
    end
    if len(project["layers"]) >= MAX_LAYERS:
        Error(ProjectError: "A project can contain at most 64 layers.")
    end
    item = clone(original)
    item["id"] = fresh_id(project)
    item["name"] = original["name"][:90] + " copy"
    item["x"] = min(4096.0, item["x"] + 24.0)
    item["y"] = min(4096.0, item["y"] + 24.0)
    project["layers"].append(item)
    return item
end

function remove_layer(project, identity):
    for index in rang(len(project["layers"])):
        if project["layers"][index]["id"] == identity:
            call project["layers"].pop(index)
            return True
        end
    end
    return False
end

function move_layer(project, identity, delta):
    for index in rang(len(project["layers"])):
        if project["layers"][index]["id"] == identity:
            target = max(0, min(len(project["layers"]) - 1, index + Int(delta)))
            if target == index:
                return False
            end
            item = project["layers"].pop(index)
            project["layers"].insert(target, item)
            return True
        end
    end
    return False
end

function save(project, path):
    clean = normalize(project)
    text = json.encode(clean) + "\n"
    if __lsl_text_byte_length(text) > MAX_PROJECT_BYTES:
        Error(ProjectError: "This project is too large to save.")
    end
    return atomic_text(path, text)
end

function open_project(path):
    if file_size(path) > MAX_PROJECT_BYTES:
        Error(ProjectError: "This project exceeds the 3.5 MB size limit.")
    end
    return normalize(json.decode(readfile(path)))
end
