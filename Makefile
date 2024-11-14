TOPDIR := $(PWD)
PLATFORMS := $(wildcard platforms/*)

.PHONY: $(PLATFORMS) all

$(PLATFORMS):
	$(MAKE) -C $@ -f $(PWD)/Makefile all

all:
	$(TOPDIR)/gen_partition.py -i partitions.conf -o partitions.xml
	$(TOPDIR)/ptool.py -x partitions.xml

