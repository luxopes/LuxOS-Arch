# LSL examples

Complete programs for Lux Simple Lang 0.10.2. Every example on this page was compiled and run
with the 0.10.2 compiler (the HTTP example against the live LSL registry). Save as `NAME.lsl`
and run with `lsl NAME.lsl`.

## Hello world and arguments

```lsl
print "Hello, world!"
if arg_count() > 1:
    printl "First argument: {arg(1)}"
end
```

```bash
lsl hello.lsl Ada
lsl compile hello.lsl hello && ./hello Ada
```

## Number guessing game (input, loops, try/else, random)

```lsl
load random

secret = random.randint(1, 100)
attempts = 0
loop:
    text = input "Guess (1-100, empty = quit): "
    if text == "":
        break
    end
    try:
        guess = Int(text)
    else:
        print "Please type a whole number."
        continue
    end
    attempts += 1
    if guess < secret:
        print "Higher"
    elif guess > secret:
        print "Lower"
    else:
        printl "Correct in {attempts} attempts!"
        break
    end
end
```

`input` always returns a String, so the text is converted with `Int(...)` inside `try`. At end
of input (Ctrl-D or a pipe) `input` returns an empty string, which ends the loop here.

## Word count of a file (arguments, files, dictionaries, sorting)

```lsl
# Usage: lsl wordcount.lsl FILE
if arg_count() < 2:
    print "Usage: lsl wordcount.lsl FILE"
    exit(2)
end
path = arg(1)
if not exists(path):
    printl "No such file: {path}"
    exit(1)
end
counts = {}
for line in readfile(path).split("\n"):
    for word in line.lower().split(" "):
        word = word.strip()
        if word == "":
            continue
        end
        counts[word] = counts.get(word, 0) + 1
    end
end
words = sorted(counts.keys())
for word in words:
    print word, counts[word]
end
```

```bash
lsl wordcount.lsl notes.txt
```

## Loading a JSON configuration with validation (errors)

```lsl
load json

function load_config(path):
    try:
        text = readfile(path)
    else:
        Error(ConfigError: "cannot read configuration file: " + path)
    end
    try:
        config = json.decode(text)
    else:
        Error(ConfigError: "invalid JSON in " + path)
    end
    check("port" in config, "configuration must contain 'port'")
    check(config["port"] >= 1024, "port must be >= 1024")
    return config
end

try:
    cfg = load_config("app.json")
    printl "Listening on port {cfg[\"port\"]}"
else:
    print "Using defaults:", last_error()
    cfg = {"port": 8080}
end
```

Possible outputs: `Using defaults: ConfigError: cannot read configuration file: app.json`,
`Listening on port 9000`, or `Using defaults: CheckError: port must be >= 1024`.

## System information (os module, time)

```lsl
load os
load time

result = os.capture_result(["uname", "-sr"])
if result["ok"]:
    print "Kernel:", result["stdout"].strip()
end
if os.which("lux") != None:
    print "Running on LuxOS (lux found)"
end
print "CPUs:", cpu_count()
print "UTC:", time.iso8601(None, 0)
```

`os.capture_result` runs the program directly (no shell) and returns
`{stdout, stderr, status, ok}`.

## Classes, inheritance and custom errors

```lsl
class Account:
    function init(self, owner, balance=0):
        self.owner = owner
        self.balance = balance
    end

    function deposit(self, amount):
        check(amount > 0, "deposit must be positive")
        self.balance += amount
    end

    function withdraw(self, amount):
        if amount > self.balance:
            Error(InsufficientFunds: l"{self.owner} has only {self.balance}")
        end
        self.balance -= amount
    end
end

class SavingsAccount(Account):
    function init(self, owner, rate):
        call origin.init(owner, 0)
        self.rate = rate
    end

    function add_interest(self):
        self.balance += self.balance * self.rate
    end
end

acc = Account("Ada", 100)
acc.deposit(50)
try:
    acc.withdraw(500)
else:
    print "Refused:", last_error()
end
print acc.owner, acc.balance

s = SavingsAccount("Bob", 0.5)
s.deposit(10)
s.add_interest()
print s.owner, s.balance
```

Output:

```text
Refused: InsufficientFunds: Ada has only 150
Ada 150
Bob 15.0
```

## Records as dictionaries (comprehensions)

```lsl
people = [
    {"name": "Ada", "age": 36},
    {"name": "Bob", "age": 17},
    {"name": "Eve", "age": 25}
]
adults = [p["name"] for p in people if p["age"] >= 18]
print adults
ages = [p["age"] for p in people]
print "average age:", sum(ages) / len(ages)
by_name = {p["name"]: p for p in people}
print by_name["Eve"]["age"]
```

Dictionaries are the recommended way to keep lists of records; see the note about instances in
collections in [functions-and-classes.md](functions-and-classes.md#classes).

## HTTP request with JSON (requests)

```lsl
load requests
load json

url = "https://lsl.lux-ai.cz/packages/catalog.json"
response = requests.get(url, None, 30)
if not response.ok:
    printl "HTTP {response.status}: {response.text}"
    exit(1)
end
catalog = response.json()
print "Catalog keys:", catalog.keys()
```

## Threads with an atomic counter

```lsl
counter = IntArray()
counter.append(0)

function bump():
    i = 0
    while i < 1000:
        call atomic_add(counter, 0, 1)
        i += 1
    end
    return None
end

unsafe:
    t = thread_spawn(bump)
    u = thread_spawn(bump)
end
print thread_join(t), thread_join(u), counter[0]   # 0 0 2000
```

## Streaming AI chatbot (ai module, env, tui)

Needs an API key in `.env` next to the script (`LUX_AI_API=...`, optionally
`LUX_AI_MODEL=flash`). Translated from the official AI manual; it was compiled, not run.

```lsl
load ai
load env
load tui

parts = []
output = tui.Terminal()

function receive(text):
    parts.append(text)
    call output.emit(text)
    call output.flush()
end

function chat(token, model):
    messages = [{"role": "system", "content": "You are a friendly assistant."}]
    print "Chatbot - type 'exit' to quit"
    loop:
        user_input = input "You: "
        if user_input == "quit" or user_input == "exit" or user_input == "":
            break
        end
        messages.append({"role": "user", "content": user_input})
        parts.clear()
        call output.emit("AI: ")
        call output.flush()
        try:
            result = ai.stream("https://api.lux-ai.cz/v1/chat/completions",
                               token, model, messages,
                               {"max_tokens": 8000, "temperature": 0.7, "timeout": 120},
                               receive)
            print ""
            messages.append({"role": "assistant", "content": "".join(parts)})
        else:
            print ""
            printl "Error: {last_error()}"
            call messages.pop()
        end
    end
end

call chat(env.require("LUX_AI_API"), env.get("LUX_AI_MODEL", "flash"))
```

Text already printed cannot be taken back on error, so the answer is added to the history only
after `ai.stream` returns successfully.
