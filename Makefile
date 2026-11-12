TOPDIR := $(PWD)

# Single CLI entry point installed by `pip install .`
QCOM_PTOOL ?= qcom-ptool

# Boards in platforms/boards/<board>.yaml build via the grouped rule
# template below. The resolver enumerates each board's outputs (one
# "<board>:<flavor-dir>/<storage>..." line per board), so flavored and
# plain boards are handled alike.
YAML_BOARDS := $(basename $(notdir $(wildcard platforms/boards/*.yaml)))
BOARD_INDEX := $(shell $(QCOM_PTOOL) show --outputs platforms/boards/*.yaml)
$(foreach t,$(BOARD_INDEX),$(eval \
    $(firstword $(subst :, ,$(t)))_OUTPUTS := $(wordlist 2,999,$(subst :, ,$(t)))))

YAML_SHARED := $(wildcard platforms/flavors/*.yaml platforms/flavors/_common/*.yaml \
    platforms/variants/*/*.yaml)
YAML_PARTITIONS_XML := $(foreach b,$(YAML_BOARDS),$(foreach o,$($(b)_OUTPUTS),platforms/$(o)/partitions.xml))
YAML_CONF_EXCLUDE := $(patsubst %.xml,%.conf, $(YAML_PARTITIONS_XML))

PARTITIONS := $(filter-out $(YAML_CONF_EXCLUDE), $(wildcard platforms/*/*/partitions.conf))
PARTITIONS_XML := $(patsubst %.conf,%.xml, $(PARTITIONS)) $(YAML_PARTITIONS_XML)
PLATFORMS := $(patsubst %/partitions.xml,%/gpt, $(PARTITIONS_XML))

CONTENTS_XML_IN := $(wildcard platforms/*/*/contents.xml.in)
CONTENTS_XML := $(patsubst %.xml.in,%.xml, $(CONTENTS_XML_IN))

UDEV_RULES := platforms/55-qcom-raw-partitions-noblkid.rules

# optional build_id for Axiom contents.xml files
BUILD_ID ?=

.PHONY: all check check-checksums clean generate-checksums install lint integration unit-test

all: $(PLATFORMS) $(PARTITIONS_XML) $(CONTENTS_XML) $(UDEV_RULES)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(QCOM_PTOOL) ptool -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(QCOM_PTOOL) gen_partition -i $^ -o $@

# One grouped rule per YAML board: resolve once, emit all storage XMLs.
# Each flavor lands in platforms/<flavor-name>/<storage>/; a board without
# flavors is one flavor named after the board file.
define yaml-board-rule
$(foreach o,$($(1)_OUTPUTS),platforms/$(o)/partitions.xml) &: \
    platforms/boards/$(1).yaml $(YAML_SHARED)
	$$(QCOM_PTOOL) gen_partition --board platforms/boards/$(1).yaml -C platforms
endef
$(foreach b,$(YAML_BOARDS),$(eval $(call yaml-board-rule,$(b))))

%/contents.xml: %/partitions.xml %/contents.xml.in
	$(QCOM_PTOOL) gen_contents -p $< -t $@.in -o $@ $${BUILD_ID:+ -b $(BUILD_ID)}

# Raw-partition udev rules from every .conf layout and every YAML board.
$(UDEV_RULES): $(PARTITIONS) $(wildcard platforms/boards/*.yaml) $(YAML_SHARED) \
    qcom_ptool/data/filesystem-partition-names.list \
    qcom_ptool/data/55-qcom-raw-partitions-noblkid.rules.in
	$(QCOM_PTOOL) gen_udev_rules -o $@

lint:
	ruff check qcom_ptool
	mypy qcom_ptool

unit-test:
	pytest

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
	LC_ALL=C find platforms -type f \( -name '*.bin' -o -name '*.xml' -o -name '*.rules' \) \
	  ! -name '*.xml.in' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum \
	  > tests/integration/checksums.sha256

check: lint unit-test integration

install:
	pip install .

clean:
	@rm -f platforms/*/*/*.xml platforms/*/*/*.bin $(UDEV_RULES)
