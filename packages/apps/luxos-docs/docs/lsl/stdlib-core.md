# LSL standard library: core modules

`lux`, `math`, `bigint`, `json`, `lconf`, `env`, `time` and `random`. All are bundled with
LSL 0.10.2 (`load NAME`). `lsl man NAME` shows the offline manual of a module.

## lux

Core module with small helpers.

| Export | Description |
|---|---|
| `lux.version` | version String of the module |
| `lux.name` | language name, `"Lux Simple Lang"` |
| `lux.identity(value)` | returns the value unchanged |
| `lux.clamp(value, low, high)` | clamp into `<low, high>` |
| `lux.is_empty(collection)` | `True` if the collection is empty |

**Note (0.10.2):** the reference also lists `lux.l(value)` (alias of `type`), but the shipped
`lux.lsl` does not define it – use `type(value)`. The shipped `lux.version` still says `"0.7.8"`;
use `lsl version` for the real compiler version.

## math

Mathematical constants and numeric functions in pure LSL. Errors: `MathError` (domain errors,
invalid arguments), `ValueError`, `OverflowError` (gcd/lcm).

| Export | Description |
|---|---|
| `math.PI`, `math.TAU`, `math.E` | Float64 constants |
| `math.pi(decimal_places)` | π as a decimal String with the requested number of places |
| `math.floor(x)`, `math.ceil(x)` | Int; NaN/Infinity/out of Int range raise `ValueError` |
| `math.round(x, digits=None)` | half away from zero; without digits returns Int, with digits Float (negative digits round to tens, hundreds...) |
| `math.trunc(x, digits=None)` | toward zero |
| `math.sign(x)`, `math.clamp(x, lower, upper)`, `math.lerp(start, stop, amount)` | sign, clamp, linear interpolation |
| `math.degrees(r)`, `math.radians(d)` | angle conversion |
| `math.gcd(a, b)`, `math.lcm(a, b)` | greatest common divisor / least common multiple |
| `math.factorial(n)` | factorial in Int64 |
| `math.factorial_big(n)` | factorial as `bigint.BigInt` |
| `math.exp(x)`, `math.log(x)`, `math.log2(x)`, `math.log10(x)` | exponential and logarithms |
| `math.sin(x)`, `math.cos(x)`, `math.tan(x)` | trigonometry in radians |
| `math.hypot(x, y)` | hypotenuse without overflow |
| `math.sigmoid(x)`, `math.tanh(x)`, `math.relu(x)`, `math.softplus(x)`, `math.swish(x)` | activation functions |
| `math.is_close(a, b, relative_tolerance, absolute_tolerance)` | approximate equality |
| `math.mean(values)`, `math.median(values)` | mean and median |
| `math.variance(values)`, `math.standard_deviation(values)` | population variance and standard deviation |

`math.round(2.675, 2)` is `2.68`: digits are counted from the decimal text of the value as
printed by `String(x)`.

```lsl
load math
print math.gcd(48, 36)          # 12
print math.sigmoid(0)           # 0.5
print math.mean([1, 2, 3, 4])   # 2.5
print math.pi(5)                # 3.14159
print math.round(2.675, 2)      # 2.68
```

## bigint

Arbitrary-precision integers, a separate type so that normal Int64 keeps native speed.

```lsl
load bigint
number = bigint.BigInt("123456789012345678901234567890")
print number.power(2).text()
```

`BigInt` (and the compatible alias `SuperInt`) methods: `text`, `add`, `subtract`, `multiply`,
`floor_divide`, `divide`, `modulo`, `power`, `compare`, `equals`, `negate`, `absolute`,
`is_zero` and checked `to_int`. `power(exponent)` uses exponentiation by squaring and returns
a new BigInt; the exponent must be a non-negative Int (`x.power(0)` is 1, also `0.power(0)`),
negative raises `ValueError`.

## json

| Function | Description |
|---|---|
| `json.encode(value)` | serialize to a compact JSON String |
| `json.decode(text)` | parse JSON into LSL values (`null` → `None`); 4 MiB input limit; errors raise `JsonError` |
| `json.pretty(value)` | like `encode` (currently compact plus a newline) |

```lsl
load json
data = json.decode("{\"name\": \"Ada\", \"values\": [1, 2, 3]}")
print data["name"], json.encode({"ok": True, "items": [1, None]})
# Ada {"ok":true,"items":[1,null]}
```

## lconf

Codec for the dependency manifest `config.lconf` (used for `.lux` package archives).

| Function | Description |
|---|---|
| `lconf.decode(text)` | parse manifest text, return `{apt, lux, lsl}` Lists |
| `lconf.encode(manifest)` | serialize back to text (one `kind: name` line per entry) |
| `lconf.parse(text, path)` | like `decode`, `path` is used in error messages |

```lsl
load lconf
deps = lconf.decode("apt: curl, git\nlux: myapp\nlsl: textkit\n")
# {'apt': ['curl', 'git'], 'lux': ['myapp'], 'lsl': ['textkit']}
```

## env

`load env` reads process environment variables and (since 0.8.9) automatically loads a `.env`
file at run time – values are never compiled into the binary.

- `lsl program.lsl`: `.env` next to the script (even when started from another directory).
- A program built with `lsl compile`: `.env` next to the executable.
- Interactive mode / stdin source: `.env` in the working directory.

A missing `.env` is fine; an unreadable or invalid one raises an error. Parent directories are
not searched. **Exported process variables win**, even when empty. Values from `.env` live only
inside the `env` module and are not exported to child processes. `env` is not available in pure
`lsl config` mode.

| Function | Description |
|---|---|
| `env.get(name, default=None)` | process variable, else `.env` value, else default (`None` since 0.10.2 when omitted) |
| `env.has(name)` | `True` if the variable exists |
| `env.require(name)` | value, or raise an error when missing |
| `env.load_dotenv(path=None)` | explicitly load another file, or reload the default |

`.env` format: `NAME=value`, optional `export`, `#` comments (at line start or after
whitespace), `"double quotes"` with `\n \r \t \" \\` escapes, `'single quotes'` literal, LF or
CRLF, UTF-8, last occurrence wins, max 1 MiB, no multi-line values, no shell expansion. Errors
report path and line number, never the content.

```lsl
load env
token = env.require("LUX_AI_API")
debug = env.get("DEBUG", "false") == "true"
```

## time

| Function | Description |
|---|---|
| `time.time()` / `time.now()` | Unix timestamp (Float seconds, wall clock) |
| `time.monotonic()` / `time.perf_counter()` | monotonic seconds for intervals, timeouts, benchmarks |
| `time.sleep(seconds)` | sleep (Float seconds, `clock_nanosleep`) |
| `time.utc(seconds=None)` | Dictionary `year, month, day, hour, minute, second, microsecond, weekday` (Monday = 0), `yearday` |
| `time.iso8601(seconds=None, digits=6)` | ISO-8601 UTC timestamp, e.g. `2026-10-09T04:01:53.833305+00:00` (fraction truncated) |
| `time.strftime(format, seconds=None)` | UTC formatting: `%Y %y %m %d %e %H %I %p %M %S %f %j %a %A %b %B %u %w %F %T %s %z %Z %%` (unknown directive: `ValueError`) |
| `time.parse_iso8601(text)` | `YYYY-MM-DDTHH:MM:SS[.frac]` with `Z` or `±HH:MM` (space allowed instead of `T`) → Unix time |

Supported years 1–9999. No local time zones or DST – store times in UTC. Measure intervals with
`monotonic`/`perf_counter`, never with wall-clock time or `clock()`.

```lsl
load time
start = time.monotonic()
call time.sleep(0.1)
print time.monotonic() - start          # ~0.1
print time.strftime("%d. %m. %Y %H:%M")
```

## random

Python-style random numbers (bundled since 0.7.8), pure LSL MT19937 with SHA-512 seeding.
Module functions share one generator; `random.Random(seed)` has its own state;
`random.SystemRandom()` uses Linux `getrandom` (ignores `seed`, rejects `getstate/setstate`).
MT19937 is **not** cryptographically secure – for tokens or keys use
`random.SystemRandom().randbytes(n)`.

| Function / method | Description |
|---|---|
| `seed(a=None, version=2)` | seed from Int, Bool, Float, String, ByteArray or BigInt; `None` uses OS entropy |
| `random()` | Float in [0, 1) with 53 random bits |
| `getstate()` / `setstate(state)` | snapshot / restore the generator |
| `getrandbits(k)` | 0–63 bits → Int, 64–4096 bits → BigInt |
| `randbytes(n)` | new ByteArray of n bytes |
| `randrange(start, stop=None, step=1)` | element of a half-open range (negative step allowed) |
| `randint(a, b)` | integer including both bounds |
| `choice(seq)` | one element of a non-empty sequence |
| `choices(population, weights=None, cum_weights=None, k=1)` | k picks with replacement |
| `sample(population, k, counts=None)` | picks without replacement |
| `shuffle(x)` | shuffle a mutable sequence in place, returns `None` |
| `uniform`, `triangular`, `normalvariate`, `gauss`, `lognormvariate`, `expovariate`, `gammavariate`, `betavariate`, `vonmisesvariate`, `paretovariate`, `weibullvariate`, `binomialvariate` | distributions |

Sequences: List, Tuple, String and typed arrays (a Dictionary is not a sequence – use
`keys()`/`values()`/`items()`). Errors are catchable; `last_error()` contains `RandomError` and
the cause. Limits: 1 MiB of seed bytes, 4096 bits per `getrandbits`/range, 1,048,576 bytes per
`randbytes` and per k/n.

```lsl
load random
call random.seed(42)
print random.randint(1, 6)
rng = random.Random("my experiment")
data = [rng.normalvariate(mu=0, sigma=1) for i in rang(20)]
call rng.shuffle(data)
print rng.sample(data, 3)
```
