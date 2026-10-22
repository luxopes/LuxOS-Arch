# LSL syntax, variables, operators and output

Basic writing rules of Lux Simple Lang 0.10.2. Types and collections are in
[types-and-collections.md](types-and-collections.md), control flow in
[control-flow.md](control-flow.md).

## Lexical rules

- Source files are UTF-8, extension `.lsl`.
- Normally one statement per line; there are no semicolons.
- `#` starts a comment to the end of the line (outside strings). Block comments
  `/* ... */` (since 0.9.1) may span lines; an unterminated block comment is error `E0011`.
- A block starts with a header (`if`, `elif`, `else`, `for`, `while`, `loop`, `function`,
  `class`, `safe`, `try`, `unsafe`, `lock`) and ends with a line containing only `end`.
  The colon after the header is optional.
- Indentation has no meaning (four spaces are recommended).
- Names are case sensitive and match `[A-Za-z_][A-Za-z0-9_]*`. `2name` and `my-name` are
  invalid.
- A comma separates arguments. Multi-line `[]`, `()` and `{}` form one logical statement;
  in a simple multi-line dictionary the commas between lines are optional.
- The maximum source file size is 16 MiB (since 0.10.2).

## Variables and assignment

```lsl
enabled = True
count = 42
ratio = 1.5
name = "Lux"
nothing = None
```

A variable is created by assigning to it. A local variable must have a value on every
reachable path before it is read; otherwise the compiler reports **E2002** (also inside
`safe`). `del(x)` removes the binding again.

Compound assignment: `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `~=`, `<<=`, `>>=`.

**Note (0.10.2):** `//=` is not accepted by the parser (`E1100`); write `x = x // 2`.

### Multiple assignment and unpacking (since 0.9.1)

```lsl
a, b = 1, 2
a, b = b, a          # swap
p, q = [3, 4]        # unpack a List or Tuple of matching length
```

All values on the right side are read before any target is written.

### Increment and decrement

`i++`, `i--`, `++i`, `--i` are standalone statements on an initialized numeric variable,
equivalent to `+= 1` / `-= 1`. They are not expressions: `x = i++`, incrementing an indexed
element or a member, and chained increments are not supported.

### Type-constrained declarations

```lsl
Int(i) = 10
String(name) = "Lux"
List(items) = [1, 2]
```

`Int(i) = ...` is a **declaration**, not a conversion. The constraint holds for the whole
lexical scope, also for later assignments, `+=` and `for` bindings. A value of the wrong type
raises a catchable `TypeError` before the variable changes; to convert, write
`Int(i) = Int("10")`. Supported: `Int`, `Float`, `Bool`, `String`, `List`, `Tuple`,
`Dictionary`, `Set`, `RealArray`, `IntArray`, `FloatArray`, `ByteArray`, `Function` and the
non-restricting `Any`. Two different constraints on the same name are **E2003**; a function
parameter cannot be re-declared this way (use a new local).

## Operators

### Arithmetic

| Operator | Meaning |
|---|---|
| `+` `-` `*` | addition (also String/List concatenation), subtraction, multiplication (`String * Int` repeats) |
| `/` | division, always returns Float (`7 / 2` is `3.5`) |
| `//` | floor division, Int result rounded down also for negatives (`-7 // 3` is `-3`) |
| `%` | remainder, non-negative for a positive divisor (`-7 % 3` is `2`) |
| `^` | power, right associative (`2 ^ 3 ^ 2` is `512`); the old `**` is invalid since 0.6 |

`Int` is a signed 64-bit two's-complement value: arithmetic, power, negation and conversion
from decimal strings wrap modulo 2^64 (no `OverflowError`). Use the `bigint` module for
arbitrary precision.

### Comparison and logic

`==`, `!=`, `<`, `<=`, `>`, `>=`, `in` (membership in collections and substrings),
`and`, `or`, `not`. Comparisons return `Bool`. `1 == 1.0` is `True`, `0.0 == -0.0` is `True`
and NaN is not equal to anything.

**Note (0.10.2):** ordered comparison (`<`, `>` ...) requires numeric operands; comparing two
Strings with `<` is a compile error.

### Bitwise operators

| Operator | Meaning |
|---|---|
| `a & b` | AND |
| `a \| b` | OR |
| `a ~ b` | XOR (because `^` is power, as in Lua) |
| `~a` | NOT (ones' complement) |
| `a << b` | shift left; `b >= 64` gives `0`, negative `b` raises `ValueError` |
| `a >> b` | arithmetic shift right = `a // 2^b`; `b >= 64` gives `0` or `-1` by sign |

Operands must be `Int` or `Bool` (Bool counts as 0/1); the result is always `Int`. A static
Float or collection operand is a compile error, a dynamic one raises `TypeError`. Integer
literals may use `0x`, `0o`, `0b` prefixes (case-insensitive); they wrap modulo 2^64, so
`0xFFFFFFFFFFFFFFFF` is `-1`. Built-ins `popcount(x)` and `trailing_zeros(x)` count bits.

### Precedence

From lowest to highest: `or`, `and`, comparisons, `|`, `~` (XOR), `&`, `<<` `>>`, `+` `-`,
`*` `/` `//` `%`, unary operators, `^`. Therefore `1 << 2 + 1 == 8` and `5 & 3 | 8 == 9`.
`not` is unary and binds tighter than comparisons and bitwise operators: `not 0 & 1` means
`(not 0) & 1`. Use parentheses when in doubt.

## Strings

Strings are UTF-8 text in double or single quotes. `+` concatenates, `len()` counts Unicode
characters (code points), indexing and slicing work on characters, negative indexes count from
the end.

```lsl
text = "Hello world"
print text[0], text[-1], text[0:5], text[6:]   # H d Hello world
print len("Čeština")                          # 7
```

Escapes: `\n` newline, `\t` tab, `\"` quote, `\\` backslash.

**Raw strings** (since 0.9.1) with prefix `r` take the content literally – backslashes and
braces have no special meaning: `r"C:\new\table"`, `r'\d+\.\d+'`. A raw string cannot contain
its own delimiter quote.

**Lux strings (interpolation)** with prefix `l` evaluate expressions in `{...}` immediately and
produce an ordinary first-class String that can be assigned, returned or passed:

```lsl
name = "Ada"
greeting = l"Hello {name}, 2 + 3 = {2 + 3}"
print greeting                 # Hello Ada, 2 + 3 = 5
print l"literal braces: {{x}}" # literal braces: {x}
```

Since 0.8.6 an interpolated expression may contain strings with the same quotes without
escaping (`l"{"a" * n}"`), nested brackets and nested l-strings. Errors inside an
interpolation report the exact line and column.

String methods are listed in [types-and-collections.md](types-and-collections.md#string-methods).

## Output and input

| Statement | Behaviour |
|---|---|
| `print a, b, ...` | prints values separated by one space and ends with a newline |
| `printl "text {expr}"` | prints an interpolated string and a newline (same as `print l"..."`) |
| `printr a, b, ...` | (0.9.1+) prints values exactly, no separators, no trailing newline |
| `input "prompt"` / `input("prompt")` | prints the prompt without a newline, reads one line from stdin, returns a String without the trailing LF/CRLF |

```lsl
printr "Loading"
for i in rang(3):
    printr "."
end
printr "\n"
answer = input "Number: "      # always a String
print Int(answer) * 2          # convert before arithmetic ("42" * 2 would repeat text)
```

Output to files, pipes or `/dev/null` is buffered and flushed before anything where order
matters (input, syscalls, sleep, fork, threads, stderr, exit).

## Statements that call functions

Since 0.10.0 a function call used as a statement must start with `call`; otherwise the
compiler reports `function call result is discarded without call` (E2001). Methods of objects
(`items.append(1)`) and built-in statements (`print`, `printl`, `printr`) can be written without
`call`.

```lsl
call save_report(data)     # result discarded
total = compute(data)      # result used
items.append(4)            # method call: no call needed
```
