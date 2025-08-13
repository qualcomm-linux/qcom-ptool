TOPDIR := $(PWD)
PLATFORMS := $(foreach platform,$(wildcard platforms/*),$(platform)/gpt)
PARTITIONS_XML := $(foreach platform,$(wildcard platforms/*),$(platform)/partitions.xml)
BINS := gen_partition.py msp.py ptool.py
PREFIX ?= /usr/local

.PHONY: all check clean lint integration

all: $(PLATFORMS) $(PARTITIONS_XML)

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

clean:
	@rm -f platforms/*/*.xml platforms/*/*.bin
