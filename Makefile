TOPDIR := $(PWD)
PARTITIONS := $(wildcard platforms/*/*/partitions.conf)
PARTITIONS_XML := $(patsubst %.conf,%.xml, $(PARTITIONS))
PLATFORMS := $(patsubst %/partitions.conf,%/gpt, $(PARTITIONS))

CONTENTS_XML_IN := $(wildcard platforms/*/*/contents.xml.in)
CONTENTS_XML := $(patsubst %.xml.in,%.xml, $(CONTENTS_XML_IN))
BINS := gen_contents.py gen_partition.py msp.py ptool.py
PREFIX ?= /usr/local

# optional build_id for Axiom contents.xml files
BUILD_ID ?=

.PHONY: all check check-checksums clean generate-checksums lint integration

all: $(PLATFORMS) $(PARTITIONS_XML) $(CONTENTS_XML)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(TOPDIR)/ptool.py -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(TOPDIR)/gen_partition.py -i $^ -o $@

%/contents.xml: %/partitions.xml %/contents.xml.in
	$(TOPDIR)/gen_contents.py -p $< -t $@.in -o $@ $${BUILD_ID:+ -b $(BUILD_ID)}

lint:
	ruff check *.py
	mypy *.py

integration: all
	# make sure generated output has created expected files
	tests/integration/check-missing-files platforms/*/*/*.xml

check-checksums: all
	# verify generated artifacts match tests/integration/checksums.sha256
	# (requires PTOOL_SEED to match the seed used to produce the manifest)
	tests/integration/check-checksums

generate-checksums: all
	# regenerate tests/integration/checksums.sha256 from current artifacts
	# (run with the same PTOOL_SEED that CI uses, otherwise the manifest
	# will not match CI builds)
	LC_ALL=C find platforms -type f \( -name '*.bin' -o -name '*.xml' \) \
	  ! -name '*.xml.in' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum \
	  > tests/integration/checksums.sha256

check: lint integration

install: $(BINS)
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 755 $^ $(DESTDIR)$(PREFIX)/bin

clean:
	@rm -f platforms/*/*/*.xml platforms/*/*/*.bin
