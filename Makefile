TOPDIR := $(PWD)
PARTITIONS := $(wildcard platforms/*/*/partitions.conf)
STAMPS := $(patsubst %/partitions.conf,%/.built, $(PARTITIONS))

CONTENTS_XML_IN := $(wildcard platforms/*/*/contents.xml.in)
CONTENTS_XML := $(patsubst %.xml.in,%.xml, $(CONTENTS_XML_IN))
BINS := gen_contents.py gen_partition.py msp.py ptool.py
PREFIX ?= /usr/local

# optional build_id for Axiom contents.xml files
BUILD_ID ?=

.PHONY: all check clean lint integration

all: $(STAMPS) $(CONTENTS_XML)

# Generate partitions.xml and GPT binaries from partitions.conf
# - single-disk: writes partitions.xml in the platform dir, runs ptool there
# - multi-disk: writes partitions0.xml, partitions1.xml, ... in the platform dir,
#   runs ptool in disk0/, disk1/, ... subdirectories
%/.built: %/partitions.conf
	$(TOPDIR)/gen_partition.py -i $< -o $*/partitions.xml
	@if [ -f $*/partitions.xml ]; then \
		(cd $* && $(TOPDIR)/ptool.py -x partitions.xml); \
	else \
		i=0; \
		while [ -f $*/partitions$${i}.xml ]; do \
			mkdir -p $*/disk$${i}; \
			(cd $*/disk$${i} && $(TOPDIR)/ptool.py -x ../partitions$${i}.xml); \
			i=$$((i+1)); \
		done; \
	fi
	@touch $@

%/contents.xml: %/contents.xml.in %/.built
	# default to partitions.xml from same dir; for multi-disk use partitions0.xml
	# with an explicit file prefix of disk0 for gen_contents
	@partxml="$*/partitions.xml"; prefix=""; \
	if [ ! -f "$$partxml" ]; then \
		partxml="$*/partitions0.xml"; prefix="disk0"; \
	fi; \
	$(TOPDIR)/gen_contents.py -p "$$partxml" -t $@.in -o $@ \
		$${prefix:+ -f $$prefix} $${BUILD_ID:+ -b $(BUILD_ID)}

lint:
	# W605: invalid escape sequence
	pycodestyle --select=W605 *.py

	# gen_contents.py is nearly perfect except E501: line too long.
	# Ensure there are no regressions.
	pycodestyle --ignore=E501 gen_contents.py

integration: all
	# make sure generated output has created expected files
	tests/integration/check-missing-files platforms/*/*/*.xml
	# test %include and multi-disk features
	tests/integration/check-include-multidisk

check: lint integration

install: $(BINS)
	install -d $(DESTDIR)$(PREFIX)/bin
	install -m 755 $^ $(DESTDIR)$(PREFIX)/bin

clean:
	@rm -f platforms/*/*/*.xml platforms/*/*/*.bin platforms/*/*/*/*.xml platforms/*/*/*/*.bin
	@rm -f platforms/*/*/.built
	@rm -rf platforms/*/*/disk[0-9]*/
