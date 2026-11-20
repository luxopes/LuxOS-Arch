# libluxos-wl: wayland-scanner z protocol/*.xml + C lepidlo (viz luxos-wl.h)
#   make OUT=adresar      knihovna $(OUT)/libluxos-wl.so.0
OUT ?= .
PROTOCOLS := $(wildcard protocol/*.xml)
GEN := $(OUT)/gen
HEADERS := $(patsubst protocol/%.xml,$(GEN)/%-client-protocol.h,$(PROTOCOLS))
CODE := $(patsubst protocol/%.xml,$(GEN)/%-protocol.c,$(PROTOCOLS))
SRC := core.c toplevel.c lock.c capture.c clipboard.c vkbd.c heads.c idle.c
PKGS := wayland-client xkbcommon glib-2.0
CFLAGS ?= -O2 -g
override CFLAGS += -std=c11 -Wall -Wextra -fPIC -fvisibility=hidden $(shell pkg-config --cflags $(PKGS)) -I$(GEN) -I.
LDLIBS := $(shell pkg-config --libs $(PKGS))

$(OUT)/libluxos-wl.so.0: $(SRC) $(CODE) $(HEADERS) luxos-wl.h internal.h
	$(CC) $(CFLAGS) $(LDFLAGS) -shared -Wl,-soname,libluxos-wl.so.0 -Wl,--no-undefined -o $@ $(SRC) $(CODE) $(LDLIBS)

$(GEN)/%-client-protocol.h: protocol/%.xml
	@mkdir -p $(GEN)
	wayland-scanner client-header $< $@

$(GEN)/%-protocol.c: protocol/%.xml
	@mkdir -p $(GEN)
	wayland-scanner private-code $< $@

.PHONY: clean
clean:
	rm -rf $(GEN) $(OUT)/libluxos-wl.so.0
