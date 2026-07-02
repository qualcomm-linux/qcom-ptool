TOPDIR := $(PWD)

# Partition sources come in two forms:
#   * legacy boards - platforms/<board>/<storage>/partitions.conf
#   * migrated boards - a YAML board under platforms/boards/ that emits one
#     partitions.xml per storage (see the grouped rules below).

# Migrated board: Glymur-CRD (YAML board, Debian HLOS variant).
GLYMUR_XML := platforms/glymur-crd/nvme/partitions.xml \
              platforms/glymur-crd/spinor/partitions.xml

YAML_PARTITIONS_XML := $(GLYMUR_XML)

# Legacy .conf sources, excluding any board already migrated to YAML.
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

# Glymur-CRD: both storage XMLs are emitted by one board resolution.
# The storage output dirs may not exist on a fresh checkout (a migrated
# storage need not carry any tracked file), so create them first.
$(GLYMUR_XML) &: platforms/boards/glymur-crd.yaml \
                 platforms/variants/hlos/qcom-deb-images.yaml
	@mkdir -p $(dir $(GLYMUR_XML))
	$(QCOM_PTOOL) gen_partition --board platforms/boards/glymur-crd.yaml \
	    --hlos qcom-deb-images $(addprefix -o ,$(GLYMUR_XML))

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
