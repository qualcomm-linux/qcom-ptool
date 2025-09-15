TOPDIR := $(PWD)
PARTITIONS := $(wildcard platforms/*/partitions.conf platforms/*/*/partitions.conf)
PARTITIONS_XML := $(patsubst %.conf,%.xml, $(PARTITIONS))
PLATFORMS := $(patsubst %/partitions.conf,%/gpt, $(PARTITIONS))

CONTENTS_XML_IN := $(wildcard platforms/*/contents.xml.in platforms/*/*/contents.xml.in)
CONTENTS_XML := $(patsubst %.xml.in,%.xml, $(CONTENTS_XML_IN))
BINS := gen_contents.py gen_partition.py msp.py ptool.py
PREFIX ?= /usr/local

.PHONY: all check clean lint integration

all: $(PLATFORMS) $(PARTITIONS_XML) $(CONTENTS_XML)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(TOPDIR)/ptool.py -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(TOPDIR)/gen_partition.py -i $^ -o $@

%/contents.xml: %/partitions.xml %/contents.xml.in
	$(TOPDIR)/gen_contents.py -p $< -t $@.in -o $@

lint:
	# W605: invalid escape sequence
	pycodestyle --select=W605 *.py

	# gen_contents.py is nearly perfect except E501: line too long.
	# Ensure there are no regressions.
	pycodestyle --ignore=E501 gen_contents.py

integration: all
	# make sure generated output has created expected files
	tests/integration/check-missing-files platforms/*/*.xml

check: lint integration

install: $(BINS)
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 755 $^ $(DESTDIR)$(PREFIX)/bin

clean:
	@rm -f platforms/*/*.xml platforms/*/*.bin
