# LuxOS countme - anonymni tydenni pocitani instalaci (podle Fedora DNF countme).
#
#   luxos-countme --bind 127.0.0.1 --port 8766 --state /var/lib/luxos-countme [--clock-file F]
#
# Protokol (pevny, pisi proti nemu klient v LuxOS i web):
#   GET /countme?v=1.0.0&arch=x86_64&ch=stable&age=1   -> 204 (zapocteno i ignorovano stejne), jinak 400
#   GET /stats/usage.json                              -> 200 JSON, prepocet nejvys jednou za 10 minut
#   GET /health                                        -> 200 "ok"
#   cokoli jineho                                      -> 404
#
# Soukromi (to je smysl sluzby):
# - na disk jdou jen citace {ISO tyden: {"v|arch|ch|age": pocet}}; zadne IP, hashe IP, user agenty,
#   soli ani cas jemnejsi nez ISO tyden. Nic se neloguje po pozadavcich.
# - deduplikace (1 zapocet za IP, tyden a v/arch/ch) a hodinovy limit jsou jen v pameti: klicem je
#   HMAC-SHA512(tydenni sul, ...) zkraceny na 63 bitu v otevrene hash tabulce (IntArray). Sul je
#   nahodna (jadro), drzi se jen v pameti a pri zmene ISO tydne se zahodi spolu s tabulkou.
# - je to heuristika: vic pocitacu za jednou IP (NAT) se pocita jednou, kdo strida VPN, prida par kusu.
#
# Sluzba bezi jen na 127.0.0.1 za Caddy; vlastni accept smycka s 1s timeoutem kvuli
# odlozenemu zapisu bez provozu a cistemu ukonceni po SIGTERM (zapis citacu pred koncem).

load httpserver
load json
load time
load random
load _random_hash

# --- konstanty ---
FLUSH_SECONDS = 30            # zapis citacu nejvys jednou za 30 s (pad ztrati < 1 min)
STATS_SECONDS = 600           # /stats/usage.json se prepocita nejvys jednou za 10 minut
STATS_WEEKS = 26
HOURLY_CAP = 60               # pozadavku za hodinu z jedne IP; navic -> 204, ale nepocita se
MAX_TARGET = 160
DEDUP_BITS = 20               # 2^20 slotu * 8 B = 8 MB
DEDUP_CAP = 500000            # pak az do konce tydne nove polozky nepocitat (--max-entries)
HOUR_BITS = 17                # 2^17 slotu * 2 * 8 B = 2 MB
HOUR_TABLE_CAP = 65536        # ruznych IP za hodinu
MAX_KEYS_PER_WEEK = 5000      # ruznych kombinaci v|arch|ch|age za tyden (proti nafukovani souboru)
ARCHES = ["x86_64"]
CHANNELS = ["stable", "staging"]
AGES = ["1", "2", "3", "4"]
PARAMS = ["v", "arch", "ch", "age"]

# --- argumenty ---
BIND = "127.0.0.1"
PORT = 8766
STATE_DIR = ""
CLOCK_FILE = ""

function usage():
    print "usage: luxos-countme --bind 127.0.0.1 --port 8766 --state DIR [--clock-file FILE] [--max-entries N]"
    call exit(2)
end

function parse_args():
    global BIND, PORT, STATE_DIR, CLOCK_FILE, DEDUP_CAP
    position = 1
    while position < arg_count():
        option = arg(position)
        if position + 1 >= arg_count():
            call usage()
        end
        given = arg(position + 1)
        if option == "--bind":
            BIND = given
        elif option == "--port":
            PORT = Int(given)
        elif option == "--state":
            STATE_DIR = given
        elif option == "--clock-file":
            CLOCK_FILE = given
        elif option == "--max-entries":
            # jen pro testy/ladeni; vic nez ~70 % slotu by zpomalilo tabulku
            DEDUP_CAP = min(max(Int(given), 1), 700000)
        else:
            call usage()
        end
        position += 2
    end
    return None
end

call parse_args()
if STATE_DIR == "":
    call usage()
end
while len(STATE_DIR) > 1 and STATE_DIR.endswith("/"):
    STATE_DIR = STATE_DIR[0:len(STATE_DIR) - 1]
end
STATE_FILE = STATE_DIR + "/counts.json"
TMP_FILE = STATE_DIR + "/counts.json.tmp"

# --- cas ---
# Testovaci hak: --clock-file nahradi hodiny (unix cas jako text, cte se pri kazdem pouziti).
function now():
    if CLOCK_FILE != "":
        try:
            return Float(readfile(CLOCK_FILE).strip())
        else:
            return time.time()
        end
    end
    return time.time()
end

function pad(number, width):
    text = String(number)
    while len(text) < width:
        text = "0" + text
    end
    return text
end

# ISO tyden "YYYY-Www" (pondeli, UTC): tyden patri roku, do ktereho padne jeho ctvrtek.
function iso_week(t):
    t = Int(t)
    u = time.utc(t)
    thursday = time.utc(t + (3 - u["weekday"]) * 86400)
    return pad(thursday["year"], 4) + "-W" + pad((thursday["yearday"] - 1) // 7 + 1, 2)
end

# Unix cas pulnoci pondeli tydne, do ktereho patri t (UTC).
function week_monday(t):
    t = Int(t)
    day = t - t % 86400
    return day - time.utc(day)["weekday"] * 86400
end

function valid_week_key(text):
    if type(text) != "String" or len(text) != 8 or text[4:6] != "-W":
        return False
    end
    return all_digits(text[0:4]) and all_digits(text[6:8])
end

# --- validace ---
function all_digits(text):
    if len(text) == 0:
        return False
    end
    for character in text:
        if "0123456789".find(character) < 0:
            return False
        end
    end
    return True
end

# ^[0-9]{1,2}\.[0-9]{1,3}\.[0-9]{1,3}$
function valid_version(text):
    parts = text.split(".")
    if len(parts) != 3:
        return False
    end
    limits = [2, 3, 3]
    for i in rang(3):
        if not all_digits(parts[i]) or len(parts[i]) > limits[i]:
            return False
        end
    end
    return True
end

function valid_count_key(key):
    if type(key) != "String":
        return False
    end
    parts = key.split("|")
    if len(parts) != 4:
        return False
    end
    return valid_version(parts[0]) and parts[1] in ARCHES and parts[2] in CHANNELS and parts[3] in AGES
end

# Rozebere query /countme; vrati {"v","arch","ch","age"} nebo None (-> 400).
function parse_countme_query(query):
    if query == "" or query.find("%") >= 0 or query.find("+") >= 0:
        return None
    end
    pairs = query.split("&")
    if len(pairs) != 4:
        return None
    end
    found = {}
    for pair in pairs:
        eq = pair.find("=")
        if eq <= 0 or pair.count("=") != 1:
            return None
        end
        key = pair[0:eq]
        value = pair[eq + 1:len(pair)]
        if key not in PARAMS or key in found:
            return None
        end
        found[key] = value
    end
    if not valid_version(found["v"]) or found["arch"] not in ARCHES or found["ch"] not in CHANNELS or found["age"] not in AGES:
        return None
    end
    return found
end

# --- HMAC-SHA512 (RFC 2104, blok 128 B) nad _random_hash.digest; klic = tydenni sul ---
SALT_WEEK = [""]
IPAD = [ByteArray()]
OPAD = [ByteArray()]

function new_salt(week):
    salt = random.SystemRandom().randbytes(32)
    ipad = ByteArray()
    opad = ByteArray()
    for i in rang(128):
        byte = 0
        if i < len(salt):
            byte = salt[i]
        end
        ipad.append(byte ~ 0x36)
        opad.append(byte ~ 0x5c)
    end
    IPAD[0] = ipad
    OPAD[0] = opad
    SALT_WEEK[0] = week
    return None
end

function joined(first, second):
    out = ByteArray()
    for byte in first:
        out.append(byte)
    end
    for byte in second:
        out.append(byte)
    end
    return out
end

function hmac_sha512(message):
    inner = _random_hash.digest(joined(IPAD[0], httpserver.text_bytes(message)))
    return _random_hash.digest(joined(OPAD[0], inner))
end

# Prvnich 8 bajtu HMAC jako nenulove 63bitove Int (klic hash tabulky; jen v pameti).
function keyed_id(message):
    digest = hmac_sha512(message)
    value = 0
    for i in rang(8):
        value = (value << 8) | digest[i]
    end
    value = value & 0x7FFFFFFFFFFFFFFF
    if value == 0:
        value = 1
    end
    return value
end

# --- otevrene hash tabulky v IntArray (Dictionary s 500k klici by mel ~70 MB) ---
function zeros(count):
    out = IntArray()
    for i in rang(count):
        out.append(0)
    end
    return out
end

DEDUP = [zeros(1 << DEDUP_BITS)]
DEDUP_STATE = IntArray()      # 0 pocet polozek, 1 plna (1 = uz zalogovano)
DEDUP_STATE.append(0)
DEDUP_STATE.append(0)
HOUR_KEYS = [zeros(1 << HOUR_BITS)]
HOUR_VALS = [zeros(1 << HOUR_BITS)]
HOUR_STATE = IntArray()       # 0 pocet IP, 1 cislo hodiny, 2 plna (1 = uz zalogovano)
HOUR_STATE.append(0)
HOUR_STATE.append(-1)
HOUR_STATE.append(0)

# Vrati index slotu s klicem, nebo prazdneho slotu, kam patri.
function slot(keys, key):
    mask = len(keys) - 1
    i = key & mask
    loop:
        current = keys[i]
        if current == 0 or current == key:
            return i
        end
        i = (i + 1) & mask
    end
end

# Zmena ISO tydne: nova sul, prazdna deduplikace. Zmena hodiny: prazdne hodinove citace.
function rotate(t):
    week = iso_week(t)
    if week != SALT_WEEK[0]:
        call new_salt(week)
        DEDUP[0] = zeros(1 << DEDUP_BITS)
        DEDUP_STATE[0] = 0
        DEDUP_STATE[1] = 0
        HOUR_STATE[1] = -1
    end
    hour = Int(t) // 3600
    if hour != HOUR_STATE[1]:
        HOUR_KEYS[0] = zeros(1 << HOUR_BITS)
        HOUR_VALS[0] = zeros(1 << HOUR_BITS)
        HOUR_STATE[0] = 0
        HOUR_STATE[1] = hour
        HOUR_STATE[2] = 0
    end
    return week
end

# Hodinovy limit na IP: True = pozadavek muze pokracovat.
function hourly_allow(ip):
    keys = HOUR_KEYS[0]
    vals = HOUR_VALS[0]
    key = keyed_id("h|" + ip)
    i = slot(keys, key)
    if keys[i] == 0:
        if HOUR_STATE[0] >= HOUR_TABLE_CAP:
            if HOUR_STATE[2] == 0:
                HOUR_STATE[2] = 1
                print "countme: hourly table full, ignoring new clients until the next hour"
            end
            return False
        end
        keys[i] = key
        HOUR_STATE[0] = HOUR_STATE[0] + 1
    end
    vals[i] = vals[i] + 1
    return vals[i] <= HOURLY_CAP
end

# Deduplikace za tyden: True = prvni vyskyt (zapocitat).
function dedup_first(ip, q):
    keys = DEDUP[0]
    key = keyed_id("d|" + ip + "|" + q["v"] + "|" + q["arch"] + "|" + q["ch"])
    i = slot(keys, key)
    if keys[i] != 0:
        return False
    end
    if DEDUP_STATE[0] >= DEDUP_CAP:
        if DEDUP_STATE[1] == 0:
            DEDUP_STATE[1] = 1
            print "countme: weekly dedupe table full, not counting new entries until the next ISO week"
        end
        return False
    end
    keys[i] = key
    DEDUP_STATE[0] = DEDUP_STATE[0] + 1
    return True
end

# --- citace a jejich soubor ---
COUNTS = [{}]
FLUSH = FloatArray()          # 0 cas posledniho zapisu
FLUSH.append(0.0)
DIRTY = IntArray()
DIRTY.append(0)

function cstring(text):
    data = httpserver.text_bytes(text)
    data.append(0)
    return data
end

function sys_rename(source, target):
    a = cstring(source)
    b = cstring(target)
    unsafe:
        result = __lsl_syscall(82, __lsl_data_address(a), __lsl_data_address(b), 0, 0)
    end
    return result
end

function sys_chmod(path, mode):
    a = cstring(path)
    unsafe:
        result = __lsl_syscall(90, __lsl_data_address(a), mode, 0, 0)
    end
    return result
end

function load_counts(t):
    if not exists(STATE_FILE):
        return {}
    end
    ok = False
    data = None
    try:
        data = json.decode(readfile(STATE_FILE))
        ok = valid_state(data)
    else:
        ok = False
    end
    if ok:
        return data["counts"]
    end
    # poskozeny soubor: odlozit vedle (nic nemazat) a zacit znovu
    target = STATE_FILE + ".corrupt-" + iso_week(t)
    n = 1
    while exists(target):
        n += 1
        target = STATE_FILE + ".corrupt-" + iso_week(t) + "-" + String(n)
    end
    call sys_rename(STATE_FILE, target)
    print "countme: state file is corrupt, moved aside to " + target + ", starting empty"
    return {}
end

function valid_state(data):
    if type(data) != "Dictionary" or data.get("schema") != 1 or type(data.get("counts")) != "Dictionary":
        return False
    end
    for week, per_week in data["counts"].items():
        if not valid_week_key(week) or type(per_week) != "Dictionary":
            return False
        end
        for key, count in per_week.items():
            if not valid_count_key(key) or type(count) != "Int" or count < 0:
                return False
            end
        end
    end
    return True
end

# Atomicky zapis: tmp (0600) + rename(2). Chyba se zaloguje bez obsahu a zkusi se priste.
function flush(t):
    text = json.encode({"schema": 1, "counts": COUNTS[0]}) + chr(10)
    ok = False
    try:
        call writefile(TMP_FILE, text)
        ok = sys_chmod(TMP_FILE, 0o600) == 0 and sys_rename(TMP_FILE, STATE_FILE) == 0
    else:
        ok = False
    end
    FLUSH[0] = Float(t)
    if ok:
        DIRTY[0] = 0
    else:
        print "countme: cannot write " + STATE_FILE + ", will retry"
    end
    return ok
end

function maybe_flush(t):
    if DIRTY[0] == 1 and (t - FLUSH[0] >= FLUSH_SECONDS or t < FLUSH[0]):
        call flush(t)
    end
    return None
end

function count(week, q):
    counts = COUNTS[0]
    if week not in counts:
        counts[week] = {}
    end
    per_week = counts[week]
    key = q["v"] + "|" + q["arch"] + "|" + q["ch"] + "|" + q["age"]
    if key not in per_week:
        if len(per_week) >= MAX_KEYS_PER_WEEK:
            return False
        end
        per_week[key] = 0
    end
    per_week[key] = per_week[key] + 1
    DIRTY[0] = 1
    return True
end

# --- statistiky ---
STATS = [""]                  # telo JSON z posledniho prepoctu
STATS_AT = FloatArray()
STATS_AT.append(-1.0)

function version_sort_key(v):
    parts = v.split(".")
    return pad(parts[0], 2) + "." + pad(parts[1], 3) + "." + pad(parts[2], 3) + "|" + v
end

function empty_series():
    out = []
    for i in rang(STATS_WEEKS):
        out.append(0)
    end
    return out
end

function build_stats(t):
    monday = week_monday(t)
    weeks = []
    starts = []
    for i in rang(STATS_WEEKS):
        m = monday - (STATS_WEEKS - 1 - i) * 7 * 86400
        weeks.append(iso_week(m))
        starts.append(time.strftime("%Y-%m-%d", m))
    end
    totals = empty_series()
    by_age = {}
    for a in AGES:
        by_age[a] = empty_series()
    end
    by_channel = {}
    for c in CHANNELS:
        by_channel[c] = empty_series()
    end
    by_arch = {}
    for a in ARCHES:
        by_arch[a] = empty_series()
    end
    versions = {}
    counts = COUNTS[0]
    for i in rang(STATS_WEEKS):
        per_week = counts.get(weeks[i])
        if per_week == None:
            continue
        end
        for key, n in per_week.items():
            parts = key.split("|")
            totals[i] = totals[i] + n
            by_age[parts[3]][i] = by_age[parts[3]][i] + n
            by_channel[parts[2]][i] = by_channel[parts[2]][i] + n
            by_arch[parts[1]][i] = by_arch[parts[1]][i] + n
            if parts[0] not in versions:
                versions[parts[0]] = empty_series()
            end
            versions[parts[0]][i] = versions[parts[0]][i] + n
        end
    end
    order = []
    for v in versions.keys():
        order.append(version_sort_key(v))
    end
    by_version = {}
    for item in sorted(order):
        v = item[item.find("|") + 1:len(item)]
        by_version[v] = versions[v]
    end
    stats = {"schema": 1, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", Int(t)), "current_week": weeks[STATS_WEEKS - 1], "weeks": weeks, "week_start": starts, "totals": totals, "by_age": by_age, "by_channel": by_channel, "by_version": by_version, "by_arch": by_arch}
    return json.encode(stats)
end

function stats_body(t):
    if STATS[0] == "" or t - STATS_AT[0] >= STATS_SECONDS or t < STATS_AT[0]:
        STATS[0] = build_stats(t)
        STATS_AT[0] = Float(t)
    end
    return STATS[0]
end

# --- HTTP ---
function client_ip(headers):
    forwarded = headers.get("x-forwarded-for")
    if forwarded == None:
        return "none"
    end
    parts = String(forwarded).split(",")
    ip = parts[len(parts) - 1].strip()
    if ip == "":
        return "none"
    end
    return ip[0:min(len(ip), 64)]
end

function bad():
    return {"status": 400, "body": "bad request" + chr(10)}
end

function handler(request):
    method = request["method"]
    target = request["target"]
    q_at = target.find("?")
    path = target
    query = ""
    if q_at >= 0:
        path = target[0:q_at]
        query = target[q_at + 1:len(target)]
    end
    if path == "/countme":
        if (method != "GET" and method != "HEAD") or len(request["body"]) > 0 or len(target) > MAX_TARGET or q_at < 0:
            return bad()
        end
        q = parse_countme_query(query)
        if q == None:
            return bad()
        end
        t = now()
        week = rotate(t)
        ip = client_ip(request["headers"])
        if hourly_allow(ip) and dedup_first(ip, q):
            call count(week, q)
        end
        call maybe_flush(t)
        return {"status": 204, "body": ""}
    elif path == "/stats/usage.json":
        if (method != "GET" and method != "HEAD") or len(request["body"]) > 0:
            return bad()
        end
        return {"status": 200, "body": stats_body(now()), "content_type": "application/json"}
    elif path == "/health":
        if method != "GET" and method != "HEAD":
            return bad()
        end
        return {"status": 200, "body": "ok" + chr(10)}
    end
    return {"status": 404, "body": "not found" + chr(10)}
end

# --- signaly: SIGTERM/SIGINT blokovane, smycka je kontroluje pres rt_sigpending ---
SIGSET = ByteArray()
for sig_byte in rang(8):
    SIGSET.append(0)
end
SIGSET[0] = 0x02              # SIGINT (2)
SIGSET[1] = 0x40              # SIGTERM (15)

function block_signals():
    unsafe:
        result = __lsl_syscall(14, 0, __lsl_data_address(SIGSET), 0, 8)
    end
    return result
end

function stop_requested():
    pending = ByteArray()
    for i in rang(8):
        pending.append(0)
    end
    unsafe:
        result = __lsl_syscall(127, __lsl_data_address(pending), 8, 0, 0)
    end
    return result == 0 and ((pending[0] & 0x02) != 0 or (pending[1] & 0x40) != 0)
end

# --- start ---
if not exists(STATE_DIR):
    print "countme: state directory " + STATE_DIR + " does not exist"
    call exit(1)
end
start = now()
COUNTS[0] = load_counts(start)
FLUSH[0] = Float(start)
call rotate(start)
call block_signals()
listener = httpserver.listen_ipv4(BIND, PORT, 128)
call httpserver.set_socket_timeout(listener, httpserver.SO_RCVTIMEO, 1)
print "luxos-countme listening on http://" + BIND + ":" + String(PORT) + "/ (state " + STATE_FILE + ", " + String(len(COUNTS[0])) + " weeks loaded)"

loop:
    if stop_requested():
        break
    end
    client = httpserver.accept_client(listener)
    if client >= 0:
        call httpserver.serve_client(client, -1, handler)
    elif client != -11 and client != -4:
        print "countme: accept failed (" + String(client) + ")"
        call time.sleep(0.2)
    end
    # odlozeny zapis i bez dalsiho provozu (smycka se probouzi aspon jednou za sekundu);
    # stara sul a tabulky se zahodi hned po zmene tydne/hodiny, ne az s dalsim pozadavkem
    tick = now()
    call rotate(tick)
    call maybe_flush(tick)
    call gc()
end
if DIRTY[0] == 1:
    call flush(now())
end
print "luxos-countme stopped"
call exit(0)
