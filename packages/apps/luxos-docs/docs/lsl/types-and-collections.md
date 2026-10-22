# LSL types and collections

Built-in value types of Lux Simple Lang, conversions, and the methods of every collection
type. Source: LSL language specification and function reference (0.10.2), checked against the
0.10.2 compiler.

## Built-in types

`type(value)` returns the type name as a String.

| Value | `type()` | Notes |
|---|---|---|
| `True`, `False` | `Bool` | |
| `42`, `0xFF`, `0b101`, `0o17` | `Int` | signed 64-bit, wraps modulo 2^64 |
| `1.5` | `Float` | IEEE-754 Float64 |
| `"text"`, `'text'` | `String` | UTF-8, indexed by Unicode characters |
| `[1, "a", True]` | `List` | mutable, heterogeneous |
| `(10, 20)` | `Tuple` | immutable |
| `{"key": value}` | `Dictionary` | insertion ordered |
| `set([...])` | `Set` | unique immutable values (since 0.8.1) |
| `![1, 2, 3]` | `RealArray` | elements mutable, length fixed |
| `IntArray()` | `IntArray` | packed Int64 |
| `FloatArray()` | `FloatArray` | packed Float64 |
| `ByteArray()` | `ByteArray` | packed bytes 0–255 |
| `None` | `None` | "no value" |
| a function name | `Function` | first-class function value |

### Truthiness

In conditions `False`, `None`, `0`, `0.0`, `""` and empty collections are false; everything
else is true. `Bool(value)` converts explicitly.

### Conversions

| Function | Description |
|---|---|
| `Int(value)` | to integer; accepts numbers, Bool and decimal Strings (`Int("x")` raises `ValueError`) |
| `Float(value)` | to Float (correctly rounded decimal parsing since 0.9.2) |
| `String(value)` | to text; Float prints the shortest round-trip digits (like Python `repr`) |
| `Bool(value)` | to truth value |
| `List(value)` / `Tuple(value)` / `Dictionary(value)` | convert, or create empty with no argument |
| `IntArray()` / `FloatArray()` / `ByteArray()` | new empty packed array; with one argument a checked cast of an existing array of the same type |
| `set()` / `set(iterable)` | new Set; a Dictionary contributes its keys |
| `sorted(iterable)` | new stable ascending List (one argument, no `key`/`reverse`); works on sequences, Set and Dictionary keys of compatible numbers or Strings |
| `dedup(list)` | shallow List without duplicates in first-occurrence order (structural equality, nested collections allowed) |

## Indexing and slicing

Indexes start at 0, negative indexes count from the end, slices `value[start:stop]` exclude
`stop` and may omit either bound. String indexes, `len`, slicing, iteration, `find` and `index`
count valid Unicode code points, not UTF-8 bytes.

```lsl
items = ["A", 1, True]
items.append("end")
items.extend([2, 3])
first = items[0]
items[2] = "hello"
del(items[0])
print items[-2:]
```

**Note (0.10.2):** the alternative call-style indexing `items(1)` mentioned in older
specifications crashed the tested 0.10.2 build; always use `items[1]`.

## List

| Method | Description |
|---|---|
| `lst.append(x)` | add to the end |
| `lst.extend(other)` | append all elements of another list |
| `lst.insert(i, x)` | insert at position `i` |
| `lst.pop()` / `lst.pop(i)` | remove and return the last / i-th element |
| `lst.remove(x)` | remove the first occurrence of `x` |
| `lst.clear()` | remove all elements |
| `lst.index(x)` | index of the first occurrence |
| `lst.find(x)` | index of the first occurrence or `-1` (since 0.8.7; also Tuple, RealArray) |
| `lst.count(x)` | number of occurrences |
| `lst.sort()` | sort in place |
| `lst.reverse()` | reverse in place |
| `lst.copy()` | shallow copy |

`+` concatenates Lists (and Tuples).

## Dictionary

Keys may be immutable scalars: `String`, `Int`, `Bool`, `None`, `Float` or `Function`.
Collections, Dictionaries, classes and instances are rejected as keys. Iterating a Dictionary
(`for k in d`) yields keys in insertion order.

| Method | Description |
|---|---|
| `d.get(key, default)` | value for key, else `default` (or `None`) |
| `d.keys()` / `d.values()` | List of keys / values |
| `d.items()` | List of `(key, value)` Tuples |
| `d.update(other)` | add or overwrite keys from another Dictionary |
| `d.pop(key)` / `d.pop(key, default)` | remove and return; default when missing |
| `d.clear()` | empty the dictionary |
| `d.setdefault(key, default)` | set if missing, return the value |
| `d.copy()` | shallow copy |

```lsl
user = {"name": "Ada", "age": 36}
user["email"] = "ada@example.com"
if "age" in user:
    print user.get("city", "unknown")
end
for key, value in user.items():
    print key, value
end
```

## Tuple

Immutable. Methods: `t.index(x)`, `t.count(x)` (and `find`). Create from a comprehension with
`Tuple([x for x in rang(3)])`; generator syntax `(x for x in data)` is not supported.

## Set (since 0.8.1)

Elements: `Int`, `Float`, `Bool`, `None`, `String`, `Function` and recursively immutable
`Tuple`. Equality ignores order; iteration keeps insertion order. Supports `len`, `Bool`, `in`,
`for`, `List(s)`, `Tuple(s)` and `sorted(s)`. No indexing, slicing, Set literal, set
comprehension or operator shortcuts; a Set cannot be a Dictionary key. Lookup is linear (not a
hash set).

| Method | Description |
|---|---|
| `s.add(x)` | add if missing |
| `s.discard(x)` | remove if present |
| `s.remove(x)` | remove; missing element raises `KeyError` |
| `s.pop()` | remove and return the last inserted element; empty Set raises `KeyError` |
| `s.clear()` / `s.copy()` | empty / independent shallow copy |
| `s.update(iterable)` | validate input and add its elements in place |
| `s.union(it)` / `s.intersection(it)` / `s.difference(it)` / `s.symmetric_difference(it)` | new Set |
| `s.issubset(it)` / `s.issuperset(it)` / `s.isdisjoint(it)` | tests |

## Packed and fixed arrays

| Type | Methods and features |
|---|---|
| `RealArray` (`![...]`) | elements can be changed by index, length is fixed: `append`, `extend`, `pop` and `del(a[i])` fail. Methods `index`, `count`, `copy` |
| `IntArray` | contiguous Int64 without per-element objects. `append`, `clear`, indexing, index assignment, slicing, `len`, `for` |
| `FloatArray` | raw Float64. Same as IntArray plus native kernels (see [stdlib-compute.md](stdlib-compute.md)) |
| `ByteArray` | one byte per element (0–255) for `readbytes`/`writebytes`, native and OS I/O. Same as IntArray |

Indexing and iteration return `Int` (IntArray, ByteArray) or `Float` (FloatArray). `append`
and index assignment reject wrong types; ByteArray also rejects values outside `0..255`
(`ValueError`). Use `List` for heterogeneous data and IntArray/FloatArray for large numeric
tables (much faster).

## String methods

| Method | Description |
|---|---|
| `s.lower()` / `s.upper()` | lower / upper case |
| `s.strip()` / `s.lstrip()` / `s.rstrip()` | trim whitespace (both ends / start / end) |
| `s.split(sep)` | split into a List. Without argument (0.9.1+) splits on a single space `" "` and does **not** merge repeated spaces: `"a  b".split()` is `["a", "", "b"]` |
| `s.replace(old, new)` | replace all occurrences |
| `s.join(list)` | join Strings with `s` as separator |
| `s.startswith(p)` / `s.endswith(p)` | prefix / suffix test |
| `s.find(sub)` | index of the first occurrence or `-1` |
| `s.count(sub)` | number of occurrences |
| `s.title()` / `s.capitalize()` | capitalize words / the first letter |

## Comprehensions (since 0.7.8)

```lsl
squares = [x*x for x in rang(10) if x % 2 == 0]
mapping = {key: value*2 for key, value in [("a", 2), ("b", 3)]}
pairs = [(x, y) for x in rang(3) for y in rang(x) if y > 0]
matrix = [[x*y for y in rang(3)] for x in rang(2)]
fixed = Tuple([x for x in rang(3)])
```

Clauses run left to right like nested loops; a filter affects the following clauses. The outer
iterable is evaluated exactly once. Comprehension variables stay local and do not overwrite
outer variables. For Dictionaries the key is evaluated before the value and a later duplicate
key replaces the earlier value. Nesting, several `for`/`if` clauses and flat unpacking
(`for (a, b) in rows`) are supported (max 64 clauses); a wrong unpack length raises an error.
Results are eager Lists/Dictionaries; there are no lazy generators or set comprehensions.

## Deleting

```lsl
del(name)            # variable binding
del(items[0])        # list element / dictionary entry
del(object.member)   # member of an LSL instance or class
```
