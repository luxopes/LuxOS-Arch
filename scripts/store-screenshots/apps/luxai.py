"""LuxAI: chat se streamovanou odpovedi (Markdown s tabulkou) a ulozena konverzace rezimu Agent
s kartou nastroje. LuxAI ze zdrojoveho archivu packages/apps/luxai (prelozena jako v PKGBUILD),
ukazkovy ucet proti mistnimu falesnemu serveru LuxAI (LUXAI_ORIGIN na loopback) - nikdy lux-ai.cz;
odpovedi "modelu" jsou pevne texty z tohoto souboru. Historie konverzaci je predem ulozena v docasnem
HOME (format ~/.local/share/luxai/conversations/*.json)."""
import http.server
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _a  # noqa: E402

QUESTION = "Give me 5 ideas for a relaxed weekend trip in the Czech Republic."
ANSWER = """Here are five relaxed weekend trips, all easy to reach by train or car:

| Place | From Prague | Best for |
|---|---|---|
| **Český Krumlov** | 3 h | castle, old town, river rafting |
| **Kutná Hora** | 1 h | Gothic cathedral, silver mine tour |
| **Bohemian Switzerland** | 2 h | sandstone gorges, Pravčická brána |
| **Karlovy Vary** | 2 h | spa colonnades, hot springs |
| **Telč** | 2.5 h | quiet Renaissance square, lakes |

### Tips
- Book a **Saturday morning train** – trains are much less crowded than on Friday evening.
- In Bohemian Switzerland, take the **boat ride through the Edmund Gorge**.
- Pack layers: evenings in the hills are cool even in summer.

Would you like a day-by-day plan for one of them?"""
TITLE = "Weekend trips in Czechia"

USER = {"id": "u-demo", "email": "alex@example.com", "displayName": "Alex Morgan", "username": "alex.morgan",
        "settings": {"theme": "light", "aiResponseStyle": "balanced"},
        "usage": {"fastTokens": 412500, "fastLimit": 1000000, "liteTokens": 2350000, "liteLimit": 10000000}}


def chunks(text, size=24):
    for i in range(0, len(text), size):
        yield text[i:i + size]


class FakeLuxAI(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def send_json(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/me":
            return self.send_json(200, {"user": USER})
        self.send_json(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path != "/api/ide/chat/completions":
            return self.send_json(404, {"error": "not_found"})
        last = body.get("messages", [{}])[-1].get("content")
        is_title = isinstance(last, str) and "Return only the title." in last
        text = TITLE if is_title else ANSWER
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for piece in chunks(text):
            event = {"choices": [{"index": 0, "delta": {"content": piece}}]}
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.flush()
            if not is_title:
                time.sleep(0.01)
        done = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 260, "total_tokens": 1160}}
        self.wfile.write(b"data: " + json.dumps(done).encode() + b"\n\ndata: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


def conversation(cid, title, mode, messages, age_hours):
    t = time.time() - age_hours * 3600
    return {"version": 1, "id": cid, "title": title, "title_source": "model", "mode": mode, "model": "flash",
            "created": t, "updated": t, "messages": messages}


def tool_call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


DU = ("5.8G\t/home/alex/Videos\n2.1G\t/home/alex/Downloads\n1.4G\t/home/alex/Pictures\n"
      "620M\t/home/alex/.cache\n310M\t/home/alex/Documents\n96M\t/home/alex/Music\n")
LARGE = ("1.9G\t/home/alex/Videos/2026-08 Summer holiday.mp4\n1.2G\t/home/alex/Videos/Screen recording 2026-10-02.mkv\n"
         "860M\t/home/alex/Downloads/ubuntu-24.04-desktop-amd64.iso\n")
AGENT_ANSWER = """Your home folder uses about **10.3 GB**. Most of it is in three places:

| Folder | Size | What is there |
|---|---|---|
| Videos | 5.8 GB | two large recordings (3.1 GB) |
| Downloads | 2.1 GB | an old Ubuntu ISO image (860 MB) |
| Pictures | 1.4 GB | photos |

The quickest win is the **ISO image in Downloads** – you probably do not need it any more. The screen recording from October is another 1.2 GB.

Should I move the ISO image to the Trash?"""


def history():
    agent = [
        {"role": "user", "content": "What is using the most disk space in my home folder?"},
        {"role": "assistant", "content": "I'll check the size of each folder in your home.",
         "tool_calls": [tool_call("call_du1", "run_command", {"command": "du -sh ~/* ~/.cache 2>/dev/null | sort -rh | head"})]},
        {"role": "tool", "tool_call_id": "call_du1", "content": json.dumps({"ok": True, "exit_code": 0, "output": DU, "duration_s": 0.8})},
        {"role": "assistant", "content": None,
         "tool_calls": [tool_call("call_du2", "run_command", {"command": "du -ah ~/Videos ~/Downloads | sort -rh | sed -n '3,5p'"})]},
        {"role": "tool", "tool_call_id": "call_du2", "content": json.dumps({"ok": True, "exit_code": 0, "output": LARGE, "duration_s": 0.5})},
        {"role": "assistant", "content": AGENT_ANSWER},
    ]
    return [
        conversation("20261107-081200-a1b2c3", "Free up disk space", "agent", agent, 2),
        conversation("20261106-174500-d4e5f6", "Birthday message for grandma", "chat", [
            {"role": "user", "content": "Help me write a short birthday message for my grandma, she turns 80."},
            {"role": "assistant", "content": "Happy 80th birthday, Grandma! Thank you for all the stories, the best "
                                             "apple pie in the world and for always being there for us. We love you!"}], 16),
        conversation("20261105-120000-0a1b2c", "Explain HTTPS simply", "chat", [
            {"role": "user", "content": "Explain how HTTPS keeps my connection private, in simple terms."},
            {"role": "assistant", "content": "HTTPS wraps everything you send in a lock that only you and the website "
                                             "can open."}], 50),
        conversation("20261103-093000-3d4e5f", "Read a JSON file in Python", "chat", [
            {"role": "user", "content": "How do I read a JSON file in Python? Show a short example."},
            {"role": "assistant", "content": "```python\nimport json\n\nwith open(\"data.json\") as f:\n    data = json.load(f)\n```"}], 100),
        conversation("20261101-200000-6a7b8c", "Pasta for four people", "chat", [
            {"role": "user", "content": "How much dry pasta do I need for four people?"},
            {"role": "assistant", "content": "About **400 g** – roughly 100 g per person for a main course."}], 150),
    ]


def build(s):
    src = _a.extract(s, "apps/luxai/luxai-2.0.2.tar.gz", "luxai")
    key = "luxai-" + _a.file_hash(s.src("apps/luxai/luxai-2.0.2.tar.gz"))

    def compile_app(out):
        _a.run(["lsl", "compile", "--unsafe", "--target", "linux-x86_64-gnu", "lsl/main.lsl", out], cwd=src)
    binary = _a.build_cached(s, key, "luxai", compile_app)
    # program hleda data (i18n/, data/) o slozku vys: build/luxai ve zdrojich jako tools/build-lsl.sh app
    os.makedirs(os.path.join(src, "build"), exist_ok=True)
    target = os.path.join(src, "build", "luxai")
    shutil.copy(binary, target)
    os.chmod(target, 0o755)
    return target


def shots(s):
    exe = build(s)
    _a.no_real_avatar(s)
    port = s.serve_http(FakeLuxAI)
    origin = "http://127.0.0.1:%d" % port
    s.env["LUXAI_ORIGIN"] = origin
    _a.demo_account(s, origin, "Alex Morgan", "alex@example.com", "alex.morgan")
    # workdir /home: radek stavu Agenta ukazuje slozku celou (bez ~), docasny HOME by vypadal divne;
    # agent v postupu nic nespousti
    s.write(".config/luxai/settings.json", json.dumps({"version": 1, "mode": "chat", "model": "flash",
                                                       "theme": "system", "window": [1100, 720], "sidebar": 250,
                                                       "workdir": "/home"}))
    for c in history():
        s.write(".local/share/luxai/conversations/%s.json" % c["id"], json.dumps(c, ensure_ascii=False), 0o600)
    s.env.update({"GTK_USE_PORTAL": "0", "LUXAI_DOCS_DIR": s.src("apps/luxos-docs/docs")})
    p = s.launch([exe])
    win = s.window(pid=p.pid, size=(1100, 720))
    s.sleep(2.0)
    s.type(QUESTION, win)
    s.key("Return", win, delay=6.0)
    s.capture("1", win)
    # ulozena konverzace Agenta (druhy radek historie pod novou konverzaci)
    s.click(110, 230, win, delay=2.0)
    s.capture("2", win)
