"""LuxOS Care - cast v relaci uzivatele (bezi uvnitr luxos-daemon, zadny dalsi proces).

- hlida /var/lib/luxos-care (udalost souboru, zadne dotazovani) a ukazuje upozorneni
  ("LuxOS byl aktualizovan", "Restartujte pro dokonceni aktualizace jadra", "LuxOS opravil problem"),
- v rezimu carefree posle neznamy vazny problem LuxAI Flash s tokenem uzivatele
  (~/.config/luxai/account.json - k rootu se token nikdy nedostane). AI smi vybrat jen cislo
  jedne z moznosti, ktere pripravil root; volba se preda spustenim jednotky
  luxos-care-apply@<id>-<cislo>.service a root ji znovu overi. Zadny prikaz od AI se nespousti.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, "/usr/lib/luxos/python")
from luxos_i18n import LANG, _  # noqa: E402

from gi.repository import Gio, GLib  # noqa: E402

STATE_DIR = os.environ.get("LUXOS_CARE_ROOT", "") + "/var/lib/luxos-care"
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "luxos")
SEEN = os.path.join(CACHE, "care-seen")
ASKED = os.path.join(CACHE, "care-ai-asked")
APP = "luxos-update"
CHAT_PATH = "/api/ide/chat/completions"
ID_RE = re.compile(r"^[0-9a-f]{12}$")

_state = {"bus": None, "sys": None, "actions": {}, "asking": False, "monitor": None}


def log(msg):
    print(f"luxos-daemon: care: {msg}", file=sys.stderr, flush=True)


def read_json(name, default):
    try:
        with open(os.path.join(STATE_DIR, name)) as f:
            d = json.load(f)
        return d if isinstance(d, type(default)) else default
    except (OSError, ValueError):
        return default


def _read_lines(path):
    try:
        with open(path) as f:
            return [x.strip() for x in f if x.strip()]
    except OSError:
        return []


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def mode():
    try:
        with open(os.environ.get("LUXOS_CARE_ROOT", "") + "/etc/luxos/care.conf") as f:
            for line in f:
                if line.strip() == "MODE=classic":
                    return "classic"
    except OSError:
        pass
    return "carefree"


# ---- upozorneni --------------------------------------------------------------------------
def problem_text(ev):
    t = _(ev.get("title", ""))
    args = ev.get("args") or []
    if "%s" in t and args:
        t = t.replace("%s", str(args[0]))
    return t


def notification_for(ev):
    """(nadpis, text, akce [(id, popis)]) pro udalost, nebo None."""
    k = ev.get("kind")
    if k == "updated":
        if ev.get("reboot"):
            return (_("Restart to finish the kernel update"),
                    _("LuxOS installed a new kernel. Restart when it suits you."),
                    [("restart", _("Restart")), ("open", _("Details"))])
        n = int(ev.get("count", 0))
        return _("LuxOS was updated"), _("%d packages were updated.") % n, [("open", _("Details"))]
    if k == "updates_available":
        return (_("Updates are available"), _("%d updates are ready to install.") % int(ev.get("count", 0)),
                [("open", _("Update"))])
    if k == "update_failed":
        return _("Updates could not be installed"), _("LuxOS will try again later."), [("open", _("Details"))]
    if k == "update_skipped":
        why = {"offline": _("No internet connection."), "metered": _("The connection is metered (Data Saver)."),
               "battery": _("The battery is low - connect the charger.")}.get(ev.get("reason"), "")
        return _("Update postponed"), why, [("open", _("Details"))]
    if k == "repaired":
        body = problem_text(ev)
        if ev.get("ai"):
            body += "\n" + _("The repair was chosen by LuxAI Flash.")
        return _("LuxOS fixed a problem"), body, [("open", _("Details"))]
    if k == "problem":
        return _("LuxOS found a problem"), problem_text(ev), [("open", _("Details"))]
    return None


def notify(title, body, actions=()):
    bus = _state["bus"]
    if bus is None:
        return
    acts = []
    for a, label in actions:
        acts += [a, label]
    def done(b, res):
        try:
            _state["actions"][b.call_finish(res).unpack()[0]] = True
        except GLib.Error as e:
            log(f"notify: {e.message}")
    # Asynchronne: zaseknuty server upozorneni nesmi blokovat luxos-daemon
    bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
             "org.freedesktop.Notifications", "Notify",
             GLib.Variant("(susssasa{sv}i)", ("LuxOS", 0, "system-software-update", title, body, acts,
                                              {"desktop-entry": GLib.Variant("s", APP)}, -1)),
             GLib.VariantType("(u)"), 0, 5000, None, done)


def on_action(_c, _s, _p, _i, _sig, params):
    nid, action = params.unpack()
    if nid not in _state["actions"]:
        return
    _state["actions"].pop(nid, None)
    if action == "restart":
        _spawn("xfce4-session-logout", "--reboot", "--fast")
    elif action in ("open", "default"):
        _spawn(APP)


def _spawn(*cmd):
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        log(f"{cmd[0]}: {e}")


def new_events(events, seen, first_run, t=None):
    """Udalosti k upozorneni. Pri prvnim spusteni jen ty z posledni hodiny (ne cela historie)."""
    t = time.time() if t is None else t
    out = []
    for ev in events:
        seq = int(ev.get("seq", 0))
        if seq <= seen:
            continue
        if first_run and t - int(ev.get("time", 0)) > 3600:
            continue
        out.append(ev)
    # Z vice stejnych udalosti jen posledni
    last = {}
    for ev in out:
        last[(ev.get("kind"), ev.get("title", ""))] = ev
    return sorted(last.values(), key=lambda e: e["seq"])


def process_events():
    data = read_json("events.json", {"seq": 0, "events": []})
    lines = _read_lines(SEEN)
    first = not lines
    seen = int(lines[0]) if lines and lines[0].isdigit() else 0
    if seen > int(data.get("seq", 0)):
        seen = 0                                  # stav se smazal a zacal znovu
    for ev in new_events(data.get("events", []), seen, first):
        n = notification_for(ev)
        if n:
            notify(*n)
    _write(SEEN, str(int(data.get("seq", 0))) + "\n")


# ---- LuxAI Flash -------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are the repair advisor of LuxOS Care on a LuxOS computer (Arch Linux based). "
    "A serious problem was detected. You get a short redacted diagnosis and a numbered list of SAFE "
    "repair options prepared by the system. Choose exactly ONE option number from that list. "
    "Choose 0 when no option clearly fits or you are unsure. Never invent options or commands. "
    'Reply with JSON only: {"option": <number>, "reason": "<one short sentence for the user>"}. '
    "Write the reason in this language: %s."
)


def build_messages(problem):
    req = problem["ai"]
    opts = "\n".join(f"{o['n']}: {o['label']}" for o in req.get("options", []))
    user = (f"Problem: {problem.get('title', '')}\n\nDiagnosis:\n{req.get('diagnosis', '')}\n\n"
            f"Options:\n{opts}")
    lang = {"cs": "Czech"}.get(LANG, "English")
    return [{"role": "system", "content": SYSTEM_PROMPT % lang}, {"role": "user", "content": user}]


def parse_choice(content, options):
    """Cislo moznosti z odpovedi AI; None pokud odpoved neodpovida nabidce."""
    if not isinstance(content, str):
        return None, ""
    m = re.search(r"\{.*?\}", content, re.S)
    if not m:
        return None, ""
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None, ""
    n = d.get("option")
    if isinstance(n, str) and n.strip().isdigit():
        n = int(n.strip())
    if not isinstance(n, int) or isinstance(n, bool):
        return None, ""
    allowed = {int(o.get("n", -1)) for o in options}
    if n not in allowed:
        return None, ""
    reason = d.get("reason") if isinstance(d.get("reason"), str) else ""
    return n, reason[:300]


def ask_ai(problem):
    """Bezi ve vlakne: dotaz na LuxAI Flash -> volba -> spusteni jednotky v systemd."""
    req = problem["ai"]
    try:
        import luxai_account
        acc = luxai_account.load()
        if not acc:
            return None, "signed_out"
        body = {"model": "flash", "messages": build_messages(problem), "max_tokens": 300, "temperature": 0,
                "stream": False}
        r = luxai_account.request("POST", CHAT_PATH, body, token=acc["sessionToken"],
                                  origin=acc.get("origin", luxai_account.ORIGIN), timeout=60)
        content = (((r.get("choices") or [{}])[0]).get("message") or {}).get("content", "")
        n, reason = parse_choice(content, req.get("options", []))
        if n is None:
            return None, "bad_answer"
        return n, reason
    except Exception as e:  # noqa: BLE001
        return None, getattr(e, "code", type(e).__name__)


def start_apply(request_id, n):
    if not ID_RE.match(request_id) or not (0 <= int(n) <= 20):
        return False
    unit = f"luxos-care-apply@{request_id}-{int(n)}.service"
    try:
        _state["sys"].call_sync("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                                "org.freedesktop.systemd1.Manager", "StartUnit",
                                GLib.Variant("(ss)", (unit, "replace")), None, 0, 10000, None)
        return True
    except GLib.Error as e:
        log(f"start {unit}: {e.message}")
        return False


def process_ai():
    if _state["asking"] or mode() != "carefree" or _state["sys"] is None:
        return
    st = read_json("state.json", {})
    asked = _read_lines(ASKED)
    for p in st.get("problems", []):
        req = p.get("ai") or {}
        rid = req.get("request_id", "")
        if req.get("status") != "pending" or not ID_RE.match(rid) or rid in asked:
            continue
        _write(ASKED, "\n".join((asked + [rid])[-100:]) + "\n")
        _state["asking"] = True

        def work(p=p, rid=rid):
            n, info = ask_ai(p)
            GLib.idle_add(done, p, rid, n, info)

        def done(p, rid, n, info):
            _state["asking"] = False
            if n is None:
                log(f"LuxAI did not choose a repair ({info})")
                if info == "signed_out":
                    notify(_("LuxOS found a problem"), problem_text(p) + "\n" +
                           _("Sign in to LuxAI to let LuxOS fix unknown problems."), [("open", _("Details"))])
            elif start_apply(rid, n):
                log(f"LuxAI chose option {n} for {p.get('id')}")
            return False
        threading.Thread(target=work, daemon=True).start()
        return


# ---- napojeni ----------------------------------------------------------------------------
def on_change(*_a):
    try:
        process_events()
    except Exception as e:  # noqa: BLE001
        log(f"events: {e}")
    try:
        process_ai()
    except Exception as e:  # noqa: BLE001
        log(f"ai: {e}")
    return False


def subscribe():
    """Volano z luxos-daemon pri startu relace."""
    try:
        _state["bus"] = Gio.bus_get_sync(Gio.BusType.SESSION)
        _state["bus"].signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications",
                                       "ActionInvoked", "/org/freedesktop/Notifications", None, 0, on_action)
    except GLib.Error as e:
        log(f"session bus: {e.message}")
    try:
        _state["sys"] = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    except GLib.Error as e:
        log(f"system bus: {e.message}")
    pending = {}

    def changed(_m, f, other, ev):
        # Root zapisuje atomicky (docasny soubor + prejmenovani) -> rozhoduje cilove jmeno
        name = ((other if ev == Gio.FileMonitorEvent.RENAMED and other else f).get_basename()) or ""
        if name not in ("events.json", "state.json"):
            return
        if ev not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                      Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.RENAMED):
            return
        if "id" in pending:
            GLib.source_remove(pending["id"])
        pending["id"] = GLib.timeout_add(1500, lambda: (pending.pop("id", None), on_change())[1])
    try:
        mon = Gio.File.new_for_path(STATE_DIR).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
        mon.connect("changed", changed)
        _state["monitor"] = mon
    except GLib.Error as e:
        log(f"monitor: {e.message}")
    # Po prihlaseni: co se stalo pred chvili (napr. oprava pri startu)
    GLib.timeout_add_seconds(20, on_change)
