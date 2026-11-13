# LuxOS Icon Studio

A native **Lux Simple Lang (LSL)** icon editor for LuxOS. The workspace combines an editable
layer list, a large live canvas and a property inspector. Its visual language uses cool light
panels, an ink-colored canvas, blue/violet accents and original layered artwork.

## Work with icons

Start from a built-in design or a blank project, then arrange shapes and imported artwork.
Edit layers, adjust their appearance, review small-size previews and export standard icon
assets. Save the editable design as a `.luxicon` project; exported SVG and PNG files are
ready for use in an application.

Imported artwork is embedded in the project. SVG imports are restricted and rasterized so
a saved project has no remote or external file dependencies. Export errors are reported;
the current document is preserved when opening another document fails.

The editor renders artwork while it is open and during export. Using an exported icon in
the desktop does not require an editor process, shader service or additional runtime.

## Install and run

Install the individual package with `lux install luxos-icon-studio`, or install the complete
developer kit with `lux install luxos-sdk`. The application appears as **LuxOS Icon Studio**.

```sh
luxos-icon-studio
luxos-icon-studio design.luxicon
luxos-icon-studio --help
```

The headless commands work without opening an editor window:

```sh
luxos-icon-studio --new Aurora.luxicon aurora
luxos-icon-studio --render Aurora.luxicon icon.svg 1024
luxos-icon-studio --render Aurora.luxicon icon.png 512
luxos-icon-studio --export Aurora.luxicon ./exported-icons
```

Built-in starting designs are `aurora`, `ember` and `blank`. Icon-set export creates
SVG plus PNG images from 16 to 1024 pixels. Choose an empty export folder: existing
output files are preserved. Imported SVG supports a passive subset of shapes and
gradients; save unsupported effects as PNG first. Imports are embedded as raster
artwork while shapes created in the editor remain editable vector layers.

Runtime dependencies are GTK 3, GLib, GdkPixbuf, Cairo, Pango and librsvg. The application
compiles to a native ELF executable and does not run Python or a web view. Application code,
project validation and rendering are in `files/*.lsl`. Python is used only for development
tests.

## Build and verify

Build with `makepkg` from this directory on a LuxOS/Arch build system. LSL 0.10.8 or newer
is required to compile. Keep the `!strip` package option: native LSL executables retain
runtime metadata that an ordinary strip operation would remove.

Run headless engine tests from the source tree:

```sh
env -u DISPLAY -u WAYLAND_DISPLAY python3 -m unittest discover -s tests -p 'test_*.py' -v
```

GUI tests use only an isolated X11/Xvfb or Broadway display with private HOME, XDG runtime
and D-Bus directories. Never run test fixtures against the user's actual desktop session.
Large build artifacts belong in the repository's `out/` directory.

The developer kit's [design guidelines](../luxos-sdk/DESIGN.md) describe the shared visual
and interaction principles. Local `.lux` export and publication are separate steps.
