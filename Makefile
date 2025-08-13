TOPDIR := $(PWD)
PLATFORMS := $(foreach platform,$(wildcard platforms/*),$(platform)/gpt)
CONTENTS := $(foreach template,$(wildcard platforms/*/contents.in), $(patsubst %.in,%,$(template)))
BINS := gen_contents.py gen_partition.py msp.py ptool.py
PREFIX ?= /usr/local

.PHONY: all check clean lint integration

all: $(PLATFORMS) $(CONTENTS)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(TOPDIR)/ptool.py -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(TOPDIR)/gen_partition.py -i $^ -o $@

%/contents:
	$(TOPDIR)/gen_contents.py -i $@.in -o $@.xml

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

# preserve intermediate (partitions.xml etc.) targets
.SECONDARY:
