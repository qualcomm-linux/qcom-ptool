TOPDIR := $(PWD)
PLATFORMS := $(foreach platform,$(wildcard platforms/*),$(platform)/gpt)
BINS := gen_partition.py msp.py ptool.py
PREFIX ?= /usr/local

.PHONY: all check lint integration

all: $(PLATFORMS)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(TOPDIR)/ptool.py -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(TOPDIR)/gen_partition.py -i $^ -o $@

lint:
	# W605: invalid escape sequence
	pycodestyle --select=W605 *.py

integration: all
	# make sure generated output has created expected files
	tests/integration/check-missing-files platforms/*/*.xml

check: lint integration

install: $(BINS)
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 755 $^ $(DESTDIR)$(PREFIX)/bin
