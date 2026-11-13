# LuxOS App Studio

A native LSL + GTK workshop for creating LuxOS applications. The compiler, editor
and exported applications use **Lux Simple Lang**, unrelated to Linden Scripting Language.
The application has no Python runtime and starts no background service.

Start on the welcome screen: create a **New Project** from a template (window app or
command line) or reopen one of your **Recent Projects**. A new project always gets a
**new** folder; existing directories are never overwritten.

The project window works like a small Xcode:

* **Editor** – the sidebar lists the LSL files in `src/`; `+` adds a module
  (`load NAME` from `main.lsl`). Syntax highlighting, line numbers and the LuxOS editor
  colours come from GtkSourceView (`lsl.lang` from luxos-text). Files are saved
  automatically before building, when you switch files and when you close the window.
* **Run** (▶, Ctrl+R) saves, builds when the sources changed and starts the app. Its
  output appears below the editor. Run while the app is running restarts it with the
  new code; **Stop** (Esc) ends the app's process group. A failed build shows the first
  compiler error above the editor and selects its line; the full log stays in Output.
* **Name, Icon and Install** – app name, summary, version and Launchpad category
  (written to `studio.json`, `package/lux.json` and the desktop entry), the icon (SVG or
  PNG, for example exported from Icon Studio) and:
  * **Install on This Computer** builds the app and installs it for the current user
    only: `~/.local/bin/NAME`, a Launchpad entry and the icon in `~/.local/share`.
    Files of another program with the same name are never overwritten. **Uninstall**
    removes exactly these files.
  * **Export .lux Package…** uses `lux pack` or GNU tar + zstd, preserving the
    documented `.lux` format. Existing export names are refused. Export never
    installs, signs or publishes a package.
* The `⋯` menu also offers Build (Ctrl+B), Open in LSL IDE, Design in Icon Studio and
  Show Project Folder.

Builds compile `src/main.lsl` to a temporary native ELF and atomically replace the last
executable after success; a SHA256 stamp covers the local LSL source tree. Closing App
Studio stops and reaps its active compiler or app. Logs display at most the last 64 KiB.

The GUI follows Czech `LANG`/`LANGUAGE` settings, with English as fallback.
Keyboard: Ctrl+N new project, Ctrl+O open, Ctrl+S save, Ctrl+B build, Ctrl+R run,
Ctrl+E export, Escape stop.

## Command line

```sh
luxos-app-studio --new /absolute/path/my-app --name "My application" --id my-app --type gtk
luxos-app-studio --inspect /absolute/path/my-app
luxos-app-studio --build /absolute/path/my-app
luxos-app-studio --package /absolute/path/my-app /absolute/path/exports
luxos-app-studio /absolute/path/my-app
```

Use `--type cli` for a terminal app. JSON results and process exit status are suitable
for automation. The generated project is self-contained: installed applications do
not depend on App Studio, the SDK or the LSL compiler. GTK projects depend on GTK 3.

Project contents: `src/main.lsl`, `studio.json`, `README.md`, `package/lux.json`,
`package/app/`, a Desktop Entry, an original SVG icon, `build/` and `exports/`.
Review the metadata, application license and runtime dependencies before distribution.
Choose the icon on the Name, Icon and Install page (SVG goes to `scalable/apps`, PNG to
`256x256/apps`). Projects support up to 500 source files and 4 MiB
per LSL source file; source symlinks are rejected.

## Development and verification

```sh
lsl compile --unsafe --target linux-x86_64-gnu files/main.lsl build/luxos-app-studio
python3 -m unittest discover -s tests -v
```

Tests create projects and binaries under the repository's `out/` directory. GUI
tests use a private HOME, XDG directories, D-Bus session and Xvfb display, never the
developer's actual display or session. Python is only used by the test harness.
