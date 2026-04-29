TOPDIR := $(PWD)
PARTITIONS := $(wildcard platforms/*/*/partitions.conf)
PARTITIONS_XML := $(patsubst %.conf,%.xml, $(PARTITIONS))
PLATFORMS := $(patsubst %/partitions.conf,%/gpt, $(PARTITIONS))

CONTENTS_XML_IN := $(wildcard platforms/*/*/contents.xml.in)
CONTENTS_XML := $(patsubst %.xml.in,%.xml, $(CONTENTS_XML_IN))

# Single CLI entry point installed by `pip install .`
QCOM_PTOOL ?= qcom-ptool

# optional build_id for Axiom contents.xml files
BUILD_ID ?=

.PHONY: all check check-checksums clean generate-checksums install lint integration

all: $(PLATFORMS) $(PARTITIONS_XML) $(CONTENTS_XML)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(QCOM_PTOOL) ptool -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(QCOM_PTOOL) gen_partition -i $^ -o $@

%/contents.xml: %/partitions.xml %/contents.xml.in
	$(QCOM_PTOOL) gen_contents -p $< -t $@.in -o $@ $${BUILD_ID:+ -b $(BUILD_ID)}

lint:
	ruff check qcom_ptool
	mypy qcom_ptool

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

install:
	pip install .

clean:
	@rm -f platforms/*/*/*.xml platforms/*/*/*.bin
