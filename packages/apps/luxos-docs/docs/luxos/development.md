# Developing applications for LuxOS

The optional **LuxOS SDK** combines the LSL compiler, **LuxOS App Studio**, **LuxOS Icon
Studio**, native UI helpers and examples. The two studios and the helper library are written
in **Lux Simple Lang (LSL)** and compile to native Linux executables. They use GTK 3 and the
system graphics libraries. Installing the SDK starts no service and changes no desktop settings.

## Install the developer kit

```sh
lux install luxos-sdk
```

The individual applications are also available as `luxos-app-studio` and
`luxos-icon-studio`. Open them from the application menu or run those commands. The existing
[LSL IDE and Lux Code](../lsl/lux-code.md) are optional: LSL IDE edits source code and Lux Code
provides a terminal coding assistant. Creating, building and packaging an application does not
require an AI account.

## App Studio

App Studio takes you from an idea to an app in Launchpad. Start from the welcome screen:
create a project from the window-app or command-line template, or reopen a recent project.

- **Write code** in the built-in editor (syntax highlighting, line numbers). The sidebar lists
  the files in `src/`; **+** adds a module that `main.lsl` loads with `load NAME`. Files are
  saved automatically. You can still use LSL IDE or any other editor.
- **Run** (▶ or Ctrl+R) saves, builds and starts the app; its output appears below the editor.
  Run again while the app is open to restart it with the new code, **Stop** (Esc) ends it.
  A failed build shows the error above the editor and selects the line. Some LSL errors, such
  as an unknown variable inside a function, are found only when that code runs; when the app
  stops with such an error, App Studio shows it the same way.
- **Name, Icon and Install** sets the app name, summary, version, Launchpad category and icon
  (SVG or PNG, for example from Icon Studio). **Install on This Computer** adds the app to
  Launchpad for your account only (`~/.local`); **Uninstall** removes it again.

The command-line interface supports the same project tasks:

```sh
mkdir -p "$HOME/Projects"
luxos-app-studio --new "$HOME/Projects/hello-lux" --name "Hello Lux" --id hello-lux --type gtk
luxos-app-studio --inspect "$HOME/Projects/hello-lux"
luxos-app-studio --build "$HOME/Projects/hello-lux"
luxos-app-studio --package "$HOME/Projects/hello-lux" "$HOME/Projects"
```

Use `--type cli` for a terminal project. Project creation requires a new destination folder;
an existing folder is not overwritten. `--name` is the display name; `--id` is a lower-case
package name such as `hello-lux`. A generated GTK application uses the system GTK libraries
and declares that dependency in its package metadata.

Export produces a local `.lux` archive. Signing, repository upload and publication remain
explicit release steps. App Studio does not publish on your behalf. For the installed package
manager and local installation, see [Package management](package-management.md).

## Icon Studio

Icon Studio has a layer list, a live central canvas and a property inspector. Start from an
original built-in design or a blank project. Add shapes and artwork, arrange layers and
adjust appearance. Review the icon at the sizes in which people will actually see it and
on both light and dark backgrounds.

Save editable projects as **`.luxicon`** files. These preserve the layers and their settings;
PNG and SVG are exported artwork. Use PNG for an exact raster version of the design and SVG
for a scalable version. Keep the editable project alongside your application's source.
Artwork imported into the project is embedded so the project does not rely on the original
image staying in the same folder. Unsupported or unsafe SVG content is rejected.

Effects are rendered by the editor or during export. The desktop displays standard icon
files and needs no additional service to show them. Exported images can be used in a generated
application's `share/icons/hicolor/` tree and referenced by its `.desktop` file.

## Native UI helpers

The SDK installs a small source module and a working example:

```text
/usr/share/luxos-sdk/lsl/luxui.lsl
/usr/share/luxos-sdk/lsl/example.lsl
/usr/share/doc/luxos-sdk/DESIGN.md
```

Copy the two LSL files into a new development folder and compile `example.lsl`:

```sh
lsl compile --unsafe --target linux-x86_64-gnu example.lsl my-example
./my-example
```

`load luxui` makes the local helper module available. It provides a styled window, headings,
subtitles, cards, rows, columns and buttons. Application behavior remains your own LSL code.
The library is optional: App Studio's templates use GTK directly and do not require the
SDK on the end user's computer. Declare `gtk3` as a system dependency for GTK applications.
See [LSL overview](../lsl/overview.md) for the language and compiler.

## Design and testing

Use an original, readable icon and a clear hierarchy of controls. Preview small icon sizes,
keyboard focus, high DPI and narrow windows. Preserve unsaved work and show compiler or
export errors in readable language. Keep long builds off the GUI thread and bound history,
image dimensions and log buffers.

When developing LuxOS itself, run GUI checks on an isolated Xvfb display or in a VM with a
private HOME, XDG directories and D-Bus session. A test must not activate windows, modify
settings or terminate applications in the user's real desktop session.
