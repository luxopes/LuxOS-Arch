"""Lux Code: uvodni obrazovka a odpoved agenta nad malym ukazkovym projektem LSL (cteni souboru
nastroji, Markdown s tabulkou). Lux Code ze zdrojoveho archivu packages/apps/lux-code (prelozeny
"lsl compile" jako v PKGBUILD), v Terminalu LuxOS (nainstalovany luxos-terminal jen jako hostitel
okna, .desktop ma Terminal=true). Model = mistni falesny endpoint kompatibilni s OpenAI (API klic
"demo", LUX_AI_ENDPOINT na loopback), referencni knihovna se nestahuje (LUX_CODE_REFERENCES=0)."""
import http.server
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402

PROMPT = "What does this project do?"
ANSWER = """**Shopping list** is a small LSL demo that prints a priced shopping list.

| File | Purpose |
|---|---|
| `main.lsl` | builds the list, prints every line and the total |
| `basket.lsl` | helpers `item`, `cost`, `total` and `money` (prices in cents) |

Run it with `lsl main.lsl`. Orders over **$20.00** also print *Free delivery!*

Would you like me to add a discount code option?"""


def sse(handler, events):
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    for event in events:
        handler.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()
    handler.close_connection = True


def tool_events(calls):
    deltas = [{"index": i, "id": "call_%d" % i, "type": "function",
               "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(calls)]
    return [{"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": deltas}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
             "usage": {"prompt_tokens": 4200, "completion_tokens": 60, "total_tokens": 4260}}]


def text_events(text):
    out = [{"choices": [{"index": 0, "delta": {"content": text[i:i + 30]}}]} for i in range(0, len(text), 30)]
    out.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5600, "completion_tokens": 140, "total_tokens": 5740}})
    return out


class FakeModel(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/v1/models"):
            raw = json.dumps({"data": [{"id": "luxai/flash", "name": "LuxAI Flash", "context_length": 128000,
                                        "max_completion_tokens": 16000}]}).encode()
            self.send_response(200)
        else:
            raw = b'{"error": "not_found"}'
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        tools = sum(1 for m in body.get("messages", []) if m.get("role") == "tool")
        if tools == 0:
            events = tool_events([("session_title", {"title": "Shopping list overview"}),
                                  ("directory_tree", {"path": ".", "depth": 2})])
        elif tools < 4:
            events = tool_events([("read_file", {"path": "main.lsl"}), ("read_file", {"path": "basket.lsl"})])
        else:
            events = text_events(ANSWER)
        sse(self, events)


def build(s):
    src = _a.extract(s, "apps/lux-code/lux-code-0.1.2.tar.gz", "lux-code")
    key = "lux-code-" + _a.file_hash(s.src("apps/lux-code/lux-code-0.1.2.tar.gz"))

    def compile_app(out):
        _a.run(["lsl", "compile", "chat.lsl", out], cwd=src)
    binary = _a.build_cached(s, key, "lux-code", compile_app)
    target = os.path.join(s.tmp, "lux-code-bin", "lux-code")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy(binary, target)
    os.chmod(target, 0o755)
    return target


# Hlavicka Lux Code ukazuje celou cestu pracovni slozky (bez ~). Docasny HOME by tam byl jako
# /tmp/luxos-store-shots-.../home, proto Lux Code bezi ve vlastnim jmennem prostoru (unshare, bez
# opravneni): prazdny tmpfs pres /home (skutecne domovske slozky nejsou videt) a docasny HOME
# pripojeny jako /home/alex. Mimo tento proces se nic nemeni.
#   $1 = s.tmp (HOME je s.tmp/home, program s.tmp/lux-code-bin), muze lezet pod /home -> nejdriv
#   ho pripojit na /mnt, pak teprve tmpfs pres /home
RUN = '''#!/bin/sh
mount --bind "$1" /mnt || exit 1
mount -t tmpfs none /home || exit 1
mkdir -p /home/alex && mount --bind /mnt/home /home/alex || exit 1
cd /home/alex/Projects/shopping-list || exit 1
export HOME=/home/alex XDG_CONFIG_HOME=/home/alex/.config XDG_DATA_HOME=/home/alex/.local/share \\
    XDG_CACHE_HOME=/home/alex/.cache XDG_STATE_HOME=/home/alex/.local/state \\
    LUX_CODE_HOME=/home/alex/.local/share/lux-code LUX_CODE_CONFIG=/home/alex/.config/lux-code/.env
exec /mnt/lux-code-bin/lux-code
'''


def shots(s):
    exe = build(s)
    _a.demo_lsl_project(s)
    # opravneni "ask" (cteni automaticky, zmeny a shell s potvrzenim)
    s.write(".local/share/lux-code/permissions.json", json.dumps({"mode": "ask"}))
    port = s.serve_http(FakeModel)
    s.env.update({
        "LUX_CODE_AUTH": "apikey",
        "LUX_AI_API": "demo",
        "LUX_AI_ENDPOINT": "http://127.0.0.1:%d/v1/chat/completions" % port,
        "LUX_CODE_REFERENCES": "0",
        "TERM": "xterm-256color",
        "GTK_USE_PORTAL": "0", "GIO_USE_VFS": "local",
    })
    run = os.path.join(s.tmp, "run-lux-code.sh")
    with open(run, "w", encoding="utf-8") as f:
        f.write(RUN)
    os.chmod(run, 0o755)
    assert exe == os.path.join(s.tmp, "lux-code-bin", "lux-code")
    s.launch(["luxos-terminal", "--disable-server", "--geometry", "126x34", "-T", "Lux Code",
              "-x", "unshare", "-rm", run, s.tmp])
    # okno podle titulku (-T): terminal muze okno vytvorit i v jinem procesu nez spoustec
    win = s.window(name="Lux Code", size=None, timeout=40)
    s.sleep(3.0)
    s.capture("2", win)
    s.type(PROMPT, win)
    s.key("Return", win, delay=8.0)
    s.capture("1", win)
