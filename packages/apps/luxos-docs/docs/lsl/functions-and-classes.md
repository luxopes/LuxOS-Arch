# LSL functions and classes

Functions, scopes, first-class functions, classes, inheritance and modules split across
files. Module loading details are in [modules.md](modules.md).

## Defining and calling functions

```lsl
function motor(power):
    return power * 2
end

result = motor(10)      # use the result in an expression
call motor(10)          # discard the result
```

- `return VALUE` returns a value; a bare `return` or a function without `return` yields `None`.
- **`call` is required** when a function call is a statement on its own (since 0.10.0).
  Without it the compiler stops with `E2001: function call result is discarded without call`.
  Methods (`items.append(x)`) and built-in statements do not need `call`.
- The order in which several arguments are evaluated is not part of the public contract; do
  not depend on side effects between arguments.

## Default and named arguments (since 0.7.8)

```lsl
function greet(who, greeting="Hello"):
    return greeting + ", " + who
end

print greet("Ada")                     # Hello, Ada
print greet(greeting="Hi", who="Bob")  # Hi, Bob
```

- A default must be an immutable literal: a number (also signed), String, Bool or `None`.
- Required parameters come before optional ones; positional arguments before named ones.
- Missing, unknown and duplicate arguments are compile errors.
- Works for functions, methods, constructors and `origin` calls.
- Not supported: keyword arguments to built-ins, `*args`/`**kwargs`, keyword-only parameters,
  and first-class Function values with defaults.

## Scope: locals and globals

Functions can **read** module-level (global) variables. Assigning to a name inside a function
creates a **local** variable for that call. Since 0.9.1 assigning to a name that also exists
globally produces warning `W2004` (the global is not changed). To change a global, declare it:

```lsl
counter = 0

function bump():
    global counter
    counter += 1
end

call bump()
print counter      # 1
```

`global NAME [, NAME...]` makes assignments inside the function change the module-level
variables.

## Functions as values

Functions without default parameters are first-class values: they can be stored, passed and
returned; `type(f)` is `Function`.

```lsl
function double(x):
    return x * 2
end

function apply(fn, value):
    return fn(value)
end

f = double
print f(4), apply(double, 5)     # 8 10
```

Nested functions are not supported (`E1248`, since 0.10.7), so there are no lexical closures.
Define helpers at module level and pass data explicitly or use globals.

A function that returns a number on one path and `None` on another really returns `None`
(before 0.10.7 it could come back as `0`).

## Classes

```lsl
class Car:
    ctype Public

    function init(self, brand):
        self.brand = brand
    end

    function motor(self, power):
        return self.brand + ": " + String(power)
    end
end

car = Car("Lux")
print car.motor(10)        # Lux: 10
```

- A function whose first parameter is exactly `self` is bound as a method when accessed
  through an instance.
- `init(self, ...)` is the optional constructor; create instances by calling the class.
- Instance attributes are created by assigning `self.name = value`.
- `ctype Public` (default) exports the class from its module; `ctype Private` prevents export.
- The historical header `class Name(True):` remains valid.

**Instances in collections and parameters (since 0.10.7):** `x.field` and `x.method()` also
work on instances taken out of a List or Dictionary or passed to a function, where the
compiler does not know the class. Dictionary syntax `x["field"]` works as well.

```lsl
items = [Car("Lux"), Car("Nova")]
for c in items:
    print c.brand, c.motor(1), c["brand"]
end
```

**Note (0.11.1) – methods defined by several classes:** when the class of the receiver is not
known at compile time (parameter, List element) and more than one class defines a method with
that name (for example a parent and a child that overrides it), `x.method()` raises
`AttributeError: method ... is defined by several classes and the receiver's class is not
known` (or `E2001` at compile time). Call such methods on variables assigned from a
constructor, or give the methods distinct names. Also, inside an inherited method `self.m()`
calls the parent's own `m`, not the child's override (no virtual dispatch through `self`).

### Class (static) attributes

Variables assigned in the class body belong to the class and are shared:

```lsl
class Counter(True):
    ctype Public
    total = 0

    function init(self):
        Counter.total += 1
        self.number = Counter.total
    end
end

a = Counter()
b = Counter()
print a.number, b.number, Counter.total     # 1 2 2
```

**Note (0.11.1):** read class attributes through the class name (`Counter.total`). Reading a
class attribute through an instance (`a.total`), as shown in older specification examples,
still raises `KeyError` in 0.11.1.

### Inheritance and origin

Single inheritance: the parent class goes in parentheses. The child inherits the constructor
and all methods; its own methods override them. `origin.method(...)` calls the implementation
of the immediate parent.

```lsl
class ElectricCar(Car):
    function init(self, brand, capacity):
        call origin.init(brand)
        self.capacity = capacity
    end

    function motor(self, power):
        return origin.motor(power) + " electric"
    end
end

e = ElectricCar("Lux", 80)
print e.motor(5), e.capacity      # Lux: 5 electric 80
```

Only one parent class is allowed; cyclic inheritance is rejected at compile time.

### Classes vs Dictionaries

Technically classes and instances are dictionaries. For plain data without behaviour a
Dictionary is often simpler (`point = {"x": 1, "y": 2}`); use a class when you have methods.

## Splitting code into modules

Every `.lsl` file is a module. Public functions, variables and classes of `helpers.lsl` next
to the main file are available after `load helpers` under the `helpers.` prefix:

```lsl
# helpers.lsl
function area(w, h):
    return w * h
end
```

```lsl
# main.lsl
load helpers
print helpers.area(3, 4)
```

`load util.text` loads `util/text.lsl` relative to the importing file; in 0.11.1 its members
are then used with the last name component, `text.shout(...)` (or give an alias:
`load util.text as t`, then `t.shout(...)`). Avoid cyclic imports.
See [modules.md](modules.md) for aliases, `from ... load` and the search order.
