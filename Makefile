TOPDIR := $(PWD)
PLATFORMS := $(foreach platform,$(wildcard platforms/*),$(platform)/gpt)

.PHONY: all

all: $(PLATFORMS)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(TOPDIR)/ptool.py -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(TOPDIR)/gen_partition.py -i $^ -o $@

