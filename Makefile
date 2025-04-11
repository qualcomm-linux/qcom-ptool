TOPDIR := $(PWD)
PLATFORMS := $(foreach platform,$(wildcard platforms/*),$(platform)/gpt)
BINS := gen_partition.py msp.py ptool.py
PREFIX ?= /usr/local

.PHONY: all

all: $(PLATFORMS)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(TOPDIR)/ptool.py -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(TOPDIR)/gen_partition.py -i $^ -o $@

check:
	# W605: invalid escape sequence
	pycodestyle --select=W605 *.py

install: $(BINS)
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 755 $^ $(DESTDIR)$(PREFIX)/bin
