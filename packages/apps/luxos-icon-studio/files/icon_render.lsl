# lsl: internal-abi
# lsl: link libgdk_pixbuf-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0
# SVG is composed from validated primitives. Imported artwork is flattened to bounded PNG.
load icon_model
load glib

SIZES = [16, 24, 32, 48, 64, 96, 128, 256, 512, 1024]
MAX_DECODED_PIXELS = 8388608

function esc(text):
    return String(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")
end

function number(value):
    return String(value)
end

function svg_size(value):
    if type(value) != "Int" or value < 16 or value > 2048:
        Error(ExportError: "Choose an icon size between 16 and 2048 pixels.")
    end
    return value
end

function shape(item, fill, extra=""):
    x = number(item["x"])
    y = number(item["y"])
    width = number(item["width"])
    height = number(item["height"])
    kind = item["kind"]
    if kind == "rect":
        radius = min(item["radius"], min(item["width"], item["height"]) / 2.0)
        return "<rect x=\"" + x + "\" y=\"" + y + "\" width=\"" + width + "\" height=\"" + height + "\" rx=\"" + number(radius) + "\" fill=\"" + fill + "\" " + extra + "/>"
    elif kind == "circle" or kind == "ellipse":
        return "<ellipse cx=\"" + number(item["x"] + item["width"] / 2.0) + "\" cy=\"" + number(item["y"] + item["height"] / 2.0) + "\" rx=\"" + number(item["width"] / 2.0) + "\" ry=\"" + number(item["height"] / 2.0) + "\" fill=\"" + fill + "\" " + extra + "/>"
    end
    return ""
end

function glyph(item, fill):
    tag = item["glyph"]
    content = ""
    if tag == "spark":
        content = "<path d=\"M256 38 C285 186 326 227 474 256 C326 285 285 326 256 474 C227 326 186 285 38 256 C186 227 227 186 256 38Z\" fill=\"" + fill + "\"/><circle cx=\"409\" cy=\"91\" r=\"22\" fill=\"" + fill + "\" opacity=\"0.65\"/>"
    elif tag == "diamond":
        content = "<path d=\"M256 52 Q274 52 292 70 L442 220 Q478 256 442 292 L292 442 Q256 478 220 442 L70 292 Q34 256 70 220 L220 70 Q238 52 256 52Z\" fill=\"" + fill + "\"/>"
    elif tag == "leaf":
        content = "<path d=\"M414 68 C432 301 331 451 166 412 C21 378 85 115 414 68Z\" fill=\"" + fill + "\"/><path d=\"M117 429 Q222 268 354 142\" fill=\"none\" stroke=\"#355AF1\" stroke-opacity=\"0.3\" stroke-width=\"20\" stroke-linecap=\"round\"/>"
    elif tag == "wave":
        content = "<path d=\"M52 224 C130 68 190 68 256 224 C322 380 382 380 460 224 M52 316 C130 160 190 160 256 316 C322 472 382 472 460 316\" fill=\"none\" stroke=\"" + fill + "\" stroke-width=\"46\" stroke-linecap=\"round\"/>"
    else:
        content = "<ellipse cx=\"256\" cy=\"256\" rx=\"199\" ry=\"87\" transform=\"rotate(38 256 256)\" fill=\"none\" stroke=\"" + fill + "\" stroke-width=\"20\" opacity=\"0.48\"/><ellipse cx=\"256\" cy=\"256\" rx=\"199\" ry=\"87\" transform=\"rotate(-38 256 256)\" fill=\"none\" stroke=\"" + fill + "\" stroke-width=\"30\"/><rect x=\"191\" y=\"191\" width=\"130\" height=\"130\" rx=\"39\" transform=\"rotate(45 256 256)\" fill=\"" + fill + "\"/><circle cx=\"411\" cy=\"134\" r=\"28\" fill=\"#FFFFFF\"/>"
    end
    return "<svg x=\"" + number(item["x"]) + "\" y=\"" + number(item["y"]) + "\" width=\"" + number(item["width"]) + "\" height=\"" + number(item["height"]) + "\" viewBox=\"0 0 512 512\" overflow=\"visible\">" + content + "</svg>"
end

function svg(project, size=512, background="transparent"):
    call svg_size(size)
    clean = icon_model.normalize(project)
    call validate_assets(clean)
    backdrop = ""
    if background != "transparent":
        shade = background
        if background == "dark":
            shade = "#17243B"
        elif background == "light":
            shade = "#F1F5FA"
        end
        shade = icon_model.color(shade)
        backdrop = "<rect width=\"1024\" height=\"1024\" fill=\"" + shade + "\"/>"
    end
    definitions = ["<linearGradient id=\"studio-gloss\" x1=\"0\" y1=\"0\" x2=\"0.35\" y2=\"1\"><stop stop-color=\"#FFFFFF\" stop-opacity=\"0.75\"/><stop offset=\"0.48\" stop-color=\"#FFFFFF\" stop-opacity=\"0.04\"/><stop offset=\"1\" stop-color=\"#FFFFFF\" stop-opacity=\"0.15\"/></linearGradient>",
                   "<filter id=\"studio-shadow\" x=\"-50%\" y=\"-50%\" width=\"200%\" height=\"220%\"><feGaussianBlur in=\"SourceAlpha\" stdDeviation=\"18\"/><feOffset dy=\"20\"/><feColorMatrix type=\"matrix\" values=\"0 0 0 0 0.035 0 0 0 0 0.075 0 0 0 0 0.20 0 0 0 0.24 0\"/><feMerge><feMergeNode/><feMergeNode in=\"SourceGraphic\"/></feMerge></filter>"]
    content = [backdrop]
    index = 0
    for item in clean["layers"]:
        identity = "studio-layer-" + String(index)
        index += 1
        if not item["visible"] or item["opacity"] <= 0:
            continue
        end
        definitions.append("<linearGradient id=\"" + identity + "\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop stop-color=\"" + item["color"] + "\"/><stop offset=\"1\" stop-color=\"" + item["color2"] + "\"/></linearGradient>")
        fill = "url(#" + identity + ")"
        cx = item["x"] + item["width"] / 2.0
        cy = item["y"] + item["height"] / 2.0
        effect = ""
        if item["shadow"]:
            effect = " filter=\"url(#studio-shadow)\""
        end
        content.append("<g opacity=\"" + number(item["opacity"]) + "\" transform=\"rotate(" + number(item["rotation"]) + " " + number(cx) + " " + number(cy) + ")\"" + effect + ">")
        kind = item["kind"]
        if kind in ["rect", "circle", "ellipse"]:
            content.append(shape(item, fill))
            if item["gloss"] > 0:
                content.append(shape(item, "url(#studio-gloss)", "opacity=\"" + number(item["gloss"]) + "\""))
                content.append(shape(item, "none", "stroke=\"#FFFFFF\" stroke-opacity=\"" + number(item["gloss"] * 0.65) + "\" stroke-width=\"3\""))
            end
        elif kind == "text":
            content.append("<text x=\"" + number(cx) + "\" y=\"" + number(cy + item["font_size"] * 0.35) + "\" text-anchor=\"middle\" font-family=\"sans-serif\" font-weight=\"700\" font-size=\"" + number(item["font_size"]) + "\" fill=\"" + fill + "\">" + esc(item["text"]) + "</text>")
        elif kind == "glyph":
            content.append(glyph(item, fill))
        elif kind == "image" and item["data_url"]:
            content.append("<image x=\"" + number(item["x"]) + "\" y=\"" + number(item["y"]) + "\" width=\"" + number(item["width"]) + "\" height=\"" + number(item["height"]) + "\" preserveAspectRatio=\"xMidYMid meet\" href=\"" + item["data_url"] + "\"/>")
        end
        content.append("</g>")
    end
    return "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + String(size) + "\" height=\"" + String(size) + "\" viewBox=\"0 0 1024 1024\"><title>" + esc(clean["title"]) + "</title><defs>" + "".join(definitions) + "</defs>" + "".join(content) + "</svg>"
end

function clear_error(slot):
    error = __lsl_qbe_load64(icon_model.data(slot))
    if error != 0:
        call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
        call __lsl_qbe_store64(icon_model.data(slot), 0)
    end
end

function from_bytes(bytes, size=512, kind="svg"):
    if type(size) != "Int" or size < 1 or size > 2048:
        Error(ExportError: "Image dimensions must be between 1 and 2048 pixels.")
    end
    error = __lsl_byte_zeros(8)
    loader = __lsl_qbe_call2(__lsl_symbol("gdk_pixbuf_loader_new_with_type"), icon_model.cstr(kind), icon_model.data(error))
    call clear_error(error)
    if loader == 0:
        Error(ExportError: "The image loader is unavailable. Install the librsvg package.")
    end
    width = size
    height = size
    if kind == "png":
        dimensions = check_png(bytes)
        factor = min(1.0, Float(size) / max(dimensions[0], dimensions[1]))
        width = max(1, Int(dimensions[0] * factor))
        height = max(1, Int(dimensions[1] * factor))
    end
    call __lsl_qbe_call3(__lsl_symbol("gdk_pixbuf_loader_set_size"), loader, icon_model.ptr(width), icon_model.ptr(height))
    accepted = __lsl_qbe_call4(__lsl_symbol("gdk_pixbuf_loader_write"), loader, icon_model.data(bytes), len(bytes), icon_model.data(error))
    call clear_error(error)
    closed = __lsl_qbe_call2(__lsl_symbol("gdk_pixbuf_loader_close"), loader, icon_model.data(error))
    call clear_error(error)
    image = 0
    if accepted != 0 and closed != 0:
        borrowed = __lsl_qbe_call1(__lsl_symbol("gdk_pixbuf_loader_get_pixbuf"), loader)
        if borrowed != 0:
            image = __lsl_qbe_call1(__lsl_symbol("g_object_ref"), borrowed)
        end
    end
    call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), loader)
    if image == 0:
        Error(ExportError: "The artwork could not be rendered. Try a plain SVG or PNG file.")
    end
    return image
end

function text_bytes(text):
    bytes = __lsl_byte_zeros(__lsl_text_byte_length(text))
    if len(bytes):
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), icon_model.data(bytes), icon_model.cstr(text), len(bytes))
    end
    return bytes
end

function pixbuf(project, size=512, background="transparent"):
    return from_bytes(text_bytes(svg(project, size, background)), size, "svg")
end

function png_bytes(image):
    output = __lsl_byte_zeros(8)
    length = __lsl_byte_zeros(8)
    error = __lsl_byte_zeros(8)
    ok = __lsl_qbe_call7(__lsl_symbol("gdk_pixbuf_save_to_bufferv"), icon_model.ptr(image), icon_model.data(output), icon_model.data(length), icon_model.cstr("png"), 0, 0, icon_model.data(error))
    call clear_error(error)
    address = __lsl_qbe_load64(icon_model.data(output))
    count = __lsl_qbe_load64(icon_model.data(length))
    result = __lsl_byte_zeros(0)
    if ok != 0 and address != 0 and count <= 16777216:
        result = __lsl_byte_zeros(count)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), icon_model.data(result), address, count)
    end
    if address != 0:
        call __lsl_qbe_call1(__lsl_symbol("g_free"), address)
    end
    if not len(result):
        Error(ExportError: "The PNG could not be encoded.")
    end
    return result
end

function render_png(project, path, size=512):
    call icon_model.check_path(path)
    image = pixbuf(project, size)
    bytes = __lsl_byte_zeros(0)
    try:
        bytes = png_bytes(image)
    else:
        call glib.object_unref(image)
        Error(ExportError: "The PNG could not be encoded.")
    end
    call glib.object_unref(image)
    return icon_model.atomic_bytes(path, bytes)
end

function base64_encode(bytes):
    return glib.take_c(__lsl_qbe_call2(__lsl_symbol("g_base64_encode"), icon_model.data(bytes), len(bytes)))
end

function base64_decode(text):
    if len(text) % 4 != 0 or not icon_model.regex("^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$", text):
        Error(ProjectError: "Embedded PNG data is malformed.")
    end
    size = __lsl_byte_zeros(8)
    address = __lsl_qbe_call2(__lsl_symbol("g_base64_decode"), icon_model.cstr(text), icon_model.data(size))
    count = __lsl_qbe_load64(icon_model.data(size))
    result = __lsl_byte_zeros(count)
    if count > 0:
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), icon_model.data(result), address, count)
    end
    if address != 0:
        call __lsl_qbe_call1(__lsl_symbol("g_free"), address)
    end
    return result
end

function big_endian(bytes, offset):
    return bytes[offset] * 16777216 + bytes[offset + 1] * 65536 + bytes[offset + 2] * 256 + bytes[offset + 3]
end

function check_png(bytes):
    if len(bytes) < 33 or len(bytes) > icon_model.MAX_ASSET_BYTES:
        Error(ImportError: "PNG artwork must be at most 1 MB.")
    end
    if bytes[0] != 137 or bytes[1] != 80 or bytes[2] != 78 or bytes[3] != 71 or bytes[4] != 13 or bytes[5] != 10 or bytes[6] != 26 or bytes[7] != 10 or bytes[12] != 73 or bytes[13] != 72 or bytes[14] != 68 or bytes[15] != 82:
        Error(ImportError: "This is not a valid PNG file.")
    end
    width = big_endian(bytes, 16)
    height = big_endian(bytes, 20)
    if width < 1 or height < 1 or width > 2048 or height > 2048:
        Error(ImportError: "PNG artwork must be no larger than 2048 × 2048 pixels.")
    end
    return [width, height]
end

function check_png_url(url):
    return check_png(base64_decode(url[22:]))
end

function validate_assets(project):
    pixels = 0
    for item in project["layers"]:
        if item["kind"] == "image" and item["data_url"]:
            dimensions = check_png_url(item["data_url"])
            pixels += dimensions[0] * dimensions[1]
            if pixels > MAX_DECODED_PIXELS:
                Error(ProjectError: "Embedded artwork exceeds the 8 megapixel decoded-image limit. Reduce image dimensions or remove image layers.")
            end
        end
    end
    return pixels
end

function safe_svg(text):
    if __lsl_text_byte_length(text) > icon_model.MAX_ASSET_BYTES or "\0" in text:
        Error(ImportError: "SVG artwork must be at most 1 MB.")
    end
    if not icon_model.regex("<svg(?:\\s|>)", text):
        Error(ImportError: "This is not an SVG image.")
    end
    # Import a deliberately small, passive subset. No external resource resolution,
    # XML entities, CSS escaping, active objects, recursive use or unbounded filters.
    if "<!" in text or "&" in text or "\\" in text or "@" in text or icon_model.regex("<\\s*(?:[a-z0-9_-]+:)?(?:script|foreignobject|image|use|style|filter|fe[a-z]+|animate[a-z]*|set|iframe|object|embed|audio|video)\\b", text):
        Error(ImportError: "This SVG contains unsupported active content, entities or effects. Save it as a plain SVG or PNG first.")
    end
    if icon_model.regex("(?:\\s|:)on[a-z]+\\s*=|(?:\\s|:)(?:src|base)\\s*=|(?:\\s|:)href\\s*=\\s*[\"'](?!#)|url\\s*\\((?!\\s*[\"']?#)|javascript\\s*:|data\\s*:|<\\?(?!xml\\s)", text):
        Error(ImportError: "External SVG resources are not supported. Embed the artwork in a PNG first.")
    end
    return text
end

function import_image(path):
    if icon_model.file_size(path) > icon_model.MAX_ASSET_BYTES:
        Error(ImportError: "Choose SVG or PNG artwork smaller than 1 MB.")
    end
    image = 0
    if path.lower().endswith(".svg"):
        text = safe_svg(readfile(path))
        image = from_bytes(text_bytes(text), 1024, "svg")
    elif path.lower().endswith(".png"):
        bytes = readbytes(path)
        dimensions = check_png(bytes)
        image = from_bytes(bytes, min(1024, max(dimensions[0], dimensions[1])), "png")
    else:
        Error(ImportError: "Choose an SVG or PNG image.")
    end
    encoded = __lsl_byte_zeros(0)
    try:
        encoded = png_bytes(image)
    else:
        call glib.object_unref(image)
        Error(ImportError: "The artwork could not be converted to PNG.")
    end
    call glib.object_unref(image)
    call check_png(encoded)
    return "data:image/png;base64," + base64_encode(encoded)
end

function import_asset(project, path):
    embedded = import_image(path)
    # Validate aggregate limits before changing the user's current project.
    draft = {"format": project["format"], "title": project["title"], "canvas": project["canvas"], "layers": project["layers"].copy()}
    trial = icon_model.add_layer(draft, "image")
    trial["data_url"] = embedded
    call validate_assets(icon_model.normalize(draft))
    item = icon_model.add_layer(project, "image")
    item["data_url"] = embedded
    title = path.split("/")
    item["name"] = title[len(title) - 1][:100]
    return item
end

function export_set(project, folder, basename="icon"):
    call icon_model.check_path(folder)
    if type(basename) != "String" or len(basename) > 80 or basename in [".", ".."] or not icon_model.regex("^[a-z0-9_.-]+$", basename):
        Error(ExportError: "Choose a simple icon file name without folders.")
    end
    clean = icon_model.normalize(project)
    call validate_assets(clean)
    if __lsl_qbe_call2(__lsl_symbol("g_mkdir_with_parents"), icon_model.cstr(folder), 493) != 0:
        Error(ExportError: "The export folder could not be created.")
    end
    prefix = folder + "/" + basename
    result = [prefix + ".svg"]
    for size in SIZES:
        result.append(prefix + "-" + String(size) + ".png")
    end
    # Selecting an export folder does not authorize replacing existing files.
    for path in result:
        if __lsl_qbe_call2(__lsl_symbol("g_file_test"), icon_model.cstr(path), 18) != 0:
            Error(ExportError: "Export files already exist. Choose an empty folder or a different icon name.")
        end
    end
    # Complete all rendering before the first write, keeping invalid artwork
    # from leaving a half-populated export directory.
    encoded = []
    image = pixbuf(clean, 1024)
    try:
        for size in SIZES:
            small = __lsl_qbe_call4(__lsl_symbol("gdk_pixbuf_scale_simple"), icon_model.ptr(image), icon_model.ptr(size), icon_model.ptr(size), 2)
            if small == 0:
                Error(ExportError: "The icon could not be scaled.")
            end
            try:
                encoded.append(png_bytes(small))
            else:
                call glib.object_unref(small)
                Error(ExportError: "The icon could not be encoded.")
            end
            call glib.object_unref(small)
        end
    else:
        call glib.object_unref(image)
        Error(ExportError: "The icon set could not be rendered.")
    end
    call glib.object_unref(image)
    call icon_model.atomic_text(result[0], svg(clean, 1024))
    for index in rang(len(encoded)):
        call icon_model.atomic_bytes(result[index + 1], encoded[index])
    end
    return result
end
