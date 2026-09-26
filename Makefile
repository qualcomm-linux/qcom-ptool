TOPDIR := $(PWD)

# Boards migrated to platforms/boards/<board>.yaml build via the grouped
# rule template below. Storage ids are read from each board file to form
# the output paths; a board must declare all its storages at top level.
YAML_BOARDS := $(basename $(notdir $(wildcard platforms/boards/*.yaml)))
board-storages = $(shell sed -n 's/^  - id: //p' platforms/boards/$(1).yaml)
$(foreach b,$(YAML_BOARDS),$(eval $(b)_STORAGES := $(call board-storages,$(b))))

YAML_SHARED := $(wildcard platforms/_common/*.yaml platforms/variants/*/*.yaml)
YAML_PARTITIONS_XML := $(foreach b,$(YAML_BOARDS),$(foreach s,$($(b)_STORAGES),platforms/$(b)/$(s)/partitions.xml))
YAML_CONF_EXCLUDE := $(patsubst %.xml,%.conf, $(YAML_PARTITIONS_XML))

PARTITIONS := $(filter-out $(YAML_CONF_EXCLUDE), $(wildcard platforms/*/*/partitions.conf))
PARTITIONS_XML := $(patsubst %.conf,%.xml, $(PARTITIONS)) $(YAML_PARTITIONS_XML)
PLATFORMS := $(patsubst %/partitions.xml,%/gpt, $(PARTITIONS_XML))

CONTENTS_XML_IN := $(wildcard platforms/*/*/contents.xml.in)
CONTENTS_XML := $(patsubst %.xml.in,%.xml, $(CONTENTS_XML_IN))

# Single CLI entry point installed by `pip install .`
QCOM_PTOOL ?= qcom-ptool

# optional build_id for Axiom contents.xml files
BUILD_ID ?=

.PHONY: all check check-checksums clean generate-checksums install lint integration unit-test

all: $(PLATFORMS) $(PARTITIONS_XML) $(CONTENTS_XML)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(QCOM_PTOOL) ptool -x partitions.xml

%/partitions.xml: %/partitions.conf
	$(QCOM_PTOOL) gen_partition -i $^ -o $@

# One grouped rule per YAML board: resolve once, emit all storage XMLs.
define yaml-board-rule
$(foreach s,$($(1)_STORAGES),platforms/$(1)/$(s)/partitions.xml) &: \
    platforms/boards/$(1).yaml $(YAML_SHARED)
	$$(QCOM_PTOOL) gen_partition --board platforms/boards/$(1).yaml -C platforms/$(1)
endef
$(foreach b,$(YAML_BOARDS),$(eval $(call yaml-board-rule,$(b))))

%/contents.xml: %/partitions.xml %/contents.xml.in
	$(QCOM_PTOOL) gen_contents -p $< -t $@.in -o $@ $${BUILD_ID:+ -b $(BUILD_ID)}

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
	LC_ALL=C find platforms -type f \( -name '*.bin' -o -name '*.xml' \) \
	  ! -name '*.xml.in' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum \
	  > tests/integration/checksums.sha256

check: lint unit-test integration

install:
	pip install .

clean:
	@rm -f platforms/*/*/*.xml platforms/*/*/*.bin
