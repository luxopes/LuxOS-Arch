project('luxcomp', 'c',
  version: '0.1.0',
  meson_version: '>=0.59.0',
  default_options: ['c_std=c11', 'warning_level=2', 'buildtype=release'])

add_project_arguments('-DWLR_USE_UNSTABLE', '-Wno-unused-parameter', language: 'c')
add_project_arguments('-DLUXCOMP_LIBEXEC="' + (get_option('prefix') / get_option('libexecdir') / 'luxcomp') + '"',
  language: 'c')

wayland_scanner = find_program('wayland-scanner')
wl_protocols = dependency('wayland-protocols').get_variable('pkgdatadir')
wlroots = dependency('wlroots-0.20', version: ['>=0.20.0', '<0.21.0'])

# wlroots ocekava hlavicky protokolu vygenerovane kompozitorem
protos = []
foreach xml : [
  wl_protocols / 'stable/xdg-shell/xdg-shell.xml',
  wl_protocols / 'staging/cursor-shape/cursor-shape-v1.xml',
  wl_protocols / 'unstable/tablet/tablet-unstable-v2.xml',
  wl_protocols / 'staging/ext-image-copy-capture/ext-image-copy-capture-v1.xml',
  wl_protocols / 'staging/ext-image-capture-source/ext-image-capture-source-v1.xml',
  'protocols/wlr-layer-shell-unstable-v1.xml',
]
  protos += custom_target(xml.underscorify() + '_h', input: xml,
    output: '@BASENAME@-protocol.h',
    command: [wayland_scanner, 'server-header', '@INPUT@', '@OUTPUT@'])
endforeach

deps = [
  wlroots,
  dependency('wayland-server'),
  dependency('xkbcommon'),
  dependency('libinput'),
  dependency('libdrm'),
  dependency('egl'),
  dependency('glesv2'),
  dependency('pixman-1'),
  dependency('cairo'),
  dependency('pangocairo'),
  meson.get_compiler('c').find_library('m'),
]

lib = shared_library('luxcomp',
  'lib/core.c', 'lib/view.c', 'lib/input.c', 'lib/deco.c', 'lib/workspace.c',
  'lib/renderer.c', 'lib/security.c', 'lib/foreign.c', 'lib/lock.c', 'lib/idle.c',
  'lib/xwayland.c', 'lib/shadow.c', 'lib/blur.c', 'lib/ipc.c', 'lib/anim.c', protos,
  include_directories: include_directories('include'),
  dependencies: deps,
  gnu_symbol_visibility: 'hidden',
  version: meson.project_version(),
  soversion: '0',
  install: true)

install_headers('include/luxcomp.h')
import('pkgconfig').generate(lib, description: 'LuxOS compositor core on wlroots')

executable('luxcomp-demo', 'tests/demo.c',
  include_directories: include_directories('include'),
  link_with: lib,
  install: true,
  install_dir: get_option('libexecdir') / 'luxcomp')

install_data('xwayland-sw', install_dir: get_option('libexecdir') / 'luxcomp', install_mode: 'rwxr-xr-x')
