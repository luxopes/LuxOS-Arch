# Nastroje harnessu: make OUT=.../out/wl-test (wlt to vola samo)
OUT ?= ../../out/wl-test
BIN := $(OUT)/bin
GEN := $(OUT)/gen
# xdg-shell.xml z wayland-protocols hostitele nebo ze sysrootu (fetch-sysroot.sh)
XDG_SHELL ?= $(firstword $(wildcard /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml \
	$(OUT)/sysroot/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml))
XDG_DECO ?= $(subst stable/xdg-shell/xdg-shell.xml,unstable/xdg-decoration/xdg-decoration-unstable-v1.xml,$(XDG_SHELL))
CFLAGS ?= -O2 -g -Wall -Wextra -Wno-unused-parameter
WL_LIBS := $(shell pkg-config --libs wayland-client xkbcommon)
WL_CFLAGS := $(shell pkg-config --cflags wayland-client xkbcommon) -I$(GEN)

all: $(BIN)/wlt-input $(BIN)/wlt-client $(BIN)/wlt-bar $(BIN)/wlt-popups $(BIN)/wlt-qmp $(BIN)/wlt-frames

$(GEN)/%-client-protocol.h: protocol/%.xml
	@mkdir -p $(GEN)
	wayland-scanner client-header $< $@
$(GEN)/%-protocol.c: protocol/%.xml
	@mkdir -p $(GEN)
	wayland-scanner private-code $< $@
$(GEN)/xdg-shell-client-protocol.h: $(XDG_SHELL)
	@mkdir -p $(GEN)
	wayland-scanner client-header $< $@
$(GEN)/xdg-shell-protocol.c: $(XDG_SHELL)
	@mkdir -p $(GEN)
	wayland-scanner private-code $< $@
$(GEN)/xdg-decoration-unstable-v1-client-protocol.h: $(XDG_DECO)
	@mkdir -p $(GEN)
	wayland-scanner client-header $< $@
$(GEN)/xdg-decoration-unstable-v1-protocol.c: $(XDG_DECO)
	@mkdir -p $(GEN)
	wayland-scanner private-code $< $@

INPUT_PROTO := wlr-virtual-pointer-unstable-v1 virtual-keyboard-unstable-v1

$(BIN)/wlt-input: src/wlt-input.c src/scen.c src/scen.h $(INPUT_PROTO:%=$(GEN)/%-client-protocol.h) $(INPUT_PROTO:%=$(GEN)/%-protocol.c)
	@mkdir -p $(BIN)
	$(CC) $(CFLAGS) $(WL_CFLAGS) -o $@ src/wlt-input.c src/scen.c $(INPUT_PROTO:%=$(GEN)/%-protocol.c) $(WL_LIBS)

CLIENT_PROTO := xdg-shell xdg-decoration-unstable-v1

$(BIN)/wlt-client: src/wlt-client.c $(CLIENT_PROTO:%=$(GEN)/%-client-protocol.h) $(CLIENT_PROTO:%=$(GEN)/%-protocol.c)
	@mkdir -p $(BIN)
	$(CC) $(CFLAGS) $(WL_CFLAGS) -o $@ src/wlt-client.c $(CLIENT_PROTO:%=$(GEN)/%-protocol.c) $(WL_LIBS)

BAR_PROTO := wlr-layer-shell-unstable-v1 xdg-shell

$(BIN)/wlt-bar: src/wlt-bar.c $(BAR_PROTO:%=$(GEN)/%-client-protocol.h) $(BAR_PROTO:%=$(GEN)/%-protocol.c)
	@mkdir -p $(BIN)
	$(CC) $(CFLAGS) $(WL_CFLAGS) -o $@ src/wlt-bar.c $(BAR_PROTO:%=$(GEN)/%-protocol.c) $(WL_LIBS)

$(BIN)/wlt-popups: src/wlt-popups.c $(BAR_PROTO:%=$(GEN)/%-client-protocol.h) $(BAR_PROTO:%=$(GEN)/%-protocol.c)
	@mkdir -p $(BIN)
	$(CC) $(CFLAGS) $(WL_CFLAGS) -o $@ src/wlt-popups.c $(BAR_PROTO:%=$(GEN)/%-protocol.c) $(WL_LIBS)

$(BIN)/wlt-qmp: src/wlt-qmp.c src/scen.c src/scen.h
	@mkdir -p $(BIN)
	$(CC) $(CFLAGS) -o $@ src/wlt-qmp.c src/scen.c

$(BIN)/wlt-frames: src/wlt-frames.c
	@mkdir -p $(BIN)
	$(CC) $(CFLAGS) -o $@ src/wlt-frames.c

.PHONY: all
