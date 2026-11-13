# LuxOS SDK

The optional official developer kit for native LuxOS applications. Application code,
the two studios and the included UI helpers are written in **Lux Simple Lang (LSL)**.
Applications compile to native Linux executables and use the system GTK 3 libraries.
The kit starts no service and changes no desktop settings.

Install with `lux install luxos-sdk`. Open **LuxOS App Studio** to create an LSL window
or terminal project, build it, inspect its output and export an installable `.lux`
package. Open **LuxOS Icon Studio** to create its icon. The existing LSL IDE and
Lux Code are optional editors and assistants; using AI is not required.

## Small UI library

Copy `/usr/share/luxos-sdk/lsl/luxui.lsl` into your project and use `load luxui`.
This source module provides a styled native window, headings, cards, rows, columns
and buttons. It is deliberately optional: App Studio's generated applications use
GTK directly and do not depend on an SDK installation on the end user's computer.

Try the complete example in an ordinary development session:

```sh
mkdir my-luxos-example
cp /usr/share/luxos-sdk/lsl/*.lsl my-luxos-example/
cd my-luxos-example
lsl compile --unsafe --target linux-x86_64-gnu example.lsl my-example
./my-example
```

The resulting executable uses the system GTK 3 libraries; declare `gtk3` in your
application's package dependencies. Native GTK bindings use LSL's internal ABI,
which is why the compile command includes `--unsafe`. Regular application behavior
is still written in LSL.

## Application delivery

App Studio creates a self-contained source project and package metadata. Building,
running and exporting are separate actions. Export creates a local `.lux` file;
signing, repository upload and publication remain explicit release steps.
See the installed LuxOS documentation page `luxos/development.md` and the package
format reference `docs/lux-package-format.md` in the LuxOS source repository.

Read [DESIGN.md](DESIGN.md) for visual and interaction guidelines. The component API
in this first SDK version is small and versioned by `luxui.VERSION`.

The helper module and example use the MIT license so they can be included in
your own applications. Preserve the license notice when copying them.
