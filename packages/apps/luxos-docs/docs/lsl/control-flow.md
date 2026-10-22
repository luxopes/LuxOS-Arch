# LSL control flow

Conditions and loops in Lux Simple Lang. Every block ends with `end`; the colon after the
header is optional. Error-handling blocks (`safe`, `try`) are in [errors.md](errors.md).

## if / elif / else

```lsl
if score > 90:
    print "A"
elif score > 70:
    print "B"
else:
    print "C"
end
```

At most one branch runs. `elif` and `else` are optional and conditions may nest. Any value can
be a condition (see truthiness in [types-and-collections.md](types-and-collections.md#truthiness)).

## for

`for ITEM in ITERABLE: ... end` iterates over Lists, Tuples, Sets, arrays, Dictionaries (keys),
Strings (characters) and `rang(...)`.

```lsl
for i in rang(5):           # 0 1 2 3 4
    print i
end

for name in ["Ada", "Bob"]:
    print "Hello", name
end

for key in {"a": 1, "b": 2}:
    print key
end

for ch in "abc":
    printr ch
end
```

### Unpacking in for (since 0.9.1)

`for A, B in PAIRS` unpacks each item (a List or Tuple of matching length):

```lsl
for name, score in [("a", 1), ("b", 2)]:
    print name, score
end
for key, value in settings.items():
    print key, "=", value
end
```

Nested loops that reuse the same variable name have their own counters.

## rang / range

`rang(stop)`, `rang(start, stop)`, `rang(start, stop, step)` produce integers from `start`
(default 0) up to but **excluding** `stop`; `step` must not be zero and may be negative
(`rang(10, 0, -3)` is 10, 7, 4, 1). `range(...)` is an alias.

In `for i in rang(...)` no List is built. Anywhere else (since 0.8.7) `rang(...)` is a List
value, so `List(rang(2, 101))`, `len(rang(10))` or `print rang(3)` work. At most 100,000,000
elements.

## while

```lsl
attempts = 0
while attempts < 3:
    attempts += 1
end
```

Repeats while the condition is true.

## loop

`loop: ... end` is an unconditional loop; leave it with `break` (or `return` inside a function).

```lsl
loop:
    line = input "> "
    if line == "quit":
        break
    end
    print "You typed", line
end
```

## break and continue

`break` exits the innermost loop, `continue` skips the rest of the current iteration. Both are
allowed only inside a loop.

```lsl
for i in rang(1, 10):
    if i == 5:
        continue
    elif i > 7:
        break
    end
    print i          # 1 2 3 4 6 7
end
```

## lock (threads)

`lock LOCKS[, SLOT]: ... end` holds a spinlock over an `IntArray` slot (default slot 0) and
releases it even when the body fails. `return`, `break` and `continue` may not leave the
block. See threads in [builtins.md](builtins.md#threads-and-atomics).

```lsl
locks = IntArray()
locks.append(0)
lock locks:
    shared_total += 1
end
```

## Exiting the program

`exit(status)` terminates the whole program immediately with the given integer exit status. It
cannot be caught by `safe` or `try`.
