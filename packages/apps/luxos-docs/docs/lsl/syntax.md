# LSL syntax, variables, operators and output

Basic writing rules of Lux Simple Lang 0.11.1. Types and collections are in
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

**Note (0.11.1):** `//=` is not accepted by the parser (`E1100`); write `x = x // 2`.

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
| `//` | floor division, rounded down also for negatives (`-7 // 3` is `-3`); Int for two Ints, Float otherwise (`7.5 // 2` is `3.0`) |
| `%` | remainder with the sign of the divisor (`-7 % 3` is `2`, `7 % -3` is `-2`); also for Floats (`7.5 % 2` is `1.5`) |
| `^` | power, right associative (`2 ^ 3 ^ 2` is `512`); the old `**` is invalid since 0.6 |

The exponent of `^` must be an `Int`: `Int ^ Int` gives an Int (a negative exponent raises
`ValueError`), a Float base gives a Float (`2.0 ^ -1` is `0.5`). A Float exponent such as
`2 ^ 0.5` is a compile error (a dynamic one raises `TypeError`); use `sqrt(x)` or
`math.exp(y * math.log(x))`. Division or remainder by zero raises `ZeroDivisionError`.
Float results of `%`, `//` and `^` stored in local variables were wrong in 0.10.11–0.10.13
(fixed in 0.10.13 and 0.10.14).

`Int` is a signed 64-bit two's-complement value: arithmetic, power, negation and conversion
from decimal strings wrap modulo 2^64 (no `OverflowError`). Use the `bigint` module for
arbitrary precision.

### Comparison and logic

`==`, `!=`, `<`, `<=`, `>`, `>=`, `in` (membership in collections and substrings),
`and`, `or`, `not`. Comparisons return `Bool`. `1 == 1.0` is `True`, `0.0 == -0.0` is `True`
and NaN is not equal to anything. Since 0.10.12 an Int is compared with a Float exactly, also
above 2^53 (`9007199254740993 == 9007199254740992.0` is `False`), and `in` uses the same
equality as `==` (`2 in [2.0]` and `(1, 2) in [(1, 2)]` are `True`).

**Note (0.11.1):** ordered comparison (`<`, `>` ...) requires numeric operands (Int, Float,
Bool); comparing two Strings with `<` is a compile error, or a `TypeError` at run time when the
types are not known statically. `sorted()` and `.sort()` still order Strings (by code point).

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
`*` `/` `//` `%`, `^`, unary operators (`-`, `+`, `not`, `~`). Therefore `1 << 2 + 1 == 8`
and `5 & 3 | 8 == 9`. Unary operators bind tighter than everything else, including `^`:
`-2 ^ 2` is `4` (write `-(2 ^ 2)` for `-4`), and `not 0 & 1` means `(not 0) & 1`. Use
parentheses when in doubt.

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
| `eprint(value)` | (0.10.6+) prints a value and a newline to stderr |
| `input "prompt"` / `input("prompt")` | prints the prompt without a newline, reads one line from stdin, returns a String without the trailing LF/CRLF; at end of input it returns `""` |
| `input_eof()` | (0.10.10+) `True` when the last `input` hit end of input (Ctrl-D, end of a pipe), so it can be told apart from an empty line |

`print(a, b)` written without a space before the parenthesis prints the arguments separated by
a space (since 0.10.10); `print (a, b)` with a space prints the Tuple `('a', 1)`.

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
