TOPDIR := $(PWD)

# Single CLI entry point installed by `pip install .`
QCOM_PTOOL ?= qcom-ptool

# Every generated artifact goes under $(OUT); platforms/ outside it holds
# only the YAML sources.
OUT ?= platforms/out

# Every platforms/<platform>.yaml lists the configurations of one board
# (platforms/boards/): each is a flavor (platforms/flavors/) on it, built
# into $(OUT)/<name>/<storage-id>/. The resolver lists each platform's
# outputs ("<platform>:<name>/<storage-id>..." per platform).
YAML_PLATFORMS := $(basename $(notdir $(wildcard platforms/*.yaml)))
PLATFORM_INDEX := $(shell $(QCOM_PTOOL) show --outputs $(wildcard platforms/*.yaml))
$(foreach t,$(PLATFORM_INDEX),$(eval \
    $(firstword $(subst :, ,$(t)))_OUTPUTS := $(wordlist 2,999,$(subst :, ,$(t)))))

YAML_SHARED := $(wildcard platforms/boards/*.yaml platforms/flavors/*.yaml \
    platforms/flavors/_common/*.yaml)
PARTITIONS_XML := $(foreach p,$(YAML_PLATFORMS),$(foreach o,$($(p)_OUTPUTS),$(OUT)/$(o)/partitions.xml))
PLATFORMS := $(patsubst %/partitions.xml,%/gpt, $(PARTITIONS_XML))

# Platforms carrying contents metadata, enumerated by the resolver as one
# "<platform>:<output>^<partitions dependency>..." line per platform.
PLATFORM_CONTENTS_INDEX := $(shell $(QCOM_PTOOL) show --contents $(wildcard platforms/*.yaml))
$(foreach t,$(PLATFORM_CONTENTS_INDEX),$(eval \
    $(firstword $(subst :, ,$(t)))_CONTENTS := $(wordlist 2,999,$(subst :, ,$(t)))))
yaml-contents-outs = $(foreach p,$($(1)_CONTENTS),$(OUT)/$(firstword $(subst ^, ,$(p))))
yaml-contents-deps = $(foreach p,$($(1)_CONTENTS),$(OUT)/$(word 2,$(subst ^, ,$(p))))
CONTENTS_XML := $(foreach p,$(YAML_PLATFORMS),$(call yaml-contents-outs,$(p)))

UDEV_RULES := $(OUT)/55-qcom-raw-partitions-noblkid.rules

# optional build_id for Axiom contents.xml files
BUILD_ID ?=

.PHONY: all check check-checksums clean generate-checksums install lint integration unit-test

all: $(PLATFORMS) $(PARTITIONS_XML) $(CONTENTS_XML) $(UDEV_RULES)

%/gpt: %/partitions.xml
	cd $(shell dirname $^) && $(QCOM_PTOOL) ptool -x partitions.xml

# One grouped rule per platform: resolve once, emit all storage XMLs.
define yaml-platform-rule
$(foreach o,$($(1)_OUTPUTS),$(OUT)/$(o)/partitions.xml) &: \
    platforms/$(1).yaml $(YAML_SHARED)
	$$(QCOM_PTOOL) gen_partition --platform platforms/$(1).yaml -C $(OUT)
endef
$(foreach p,$(YAML_PLATFORMS),$(eval $(call yaml-platform-rule,$(p))))

# One grouped rule per platform with contents metadata: resolve once,
# emit every configuration's contents.xml.
define yaml-contents-rule
$(call yaml-contents-outs,$(1)) &: platforms/$(1).yaml $(call yaml-contents-deps,$(1))
	$$(QCOM_PTOOL) gen_contents -o $(OUT) $$$${BUILD_ID:+ -b $$(BUILD_ID)} platforms/$(1).yaml
endef
$(foreach p,$(YAML_PLATFORMS),$(if $($(p)_CONTENTS),$(eval $(call yaml-contents-rule,$(p)))))

# Raw-partition udev rules from every platform.
$(UDEV_RULES): $(wildcard platforms/*.yaml) $(YAML_SHARED) \
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
	tests/integration/check-missing-files $(OUT)/*/*/*.xml $(wildcard $(OUT)/*/contents.xml)

check-checksums: all
	# verify generated artifacts match tests/integration/checksums.sha256
	# (requires PTOOL_SEED to match the seed used to produce the manifest)
	tests/integration/check-checksums

generate-checksums: all
	# regenerate tests/integration/checksums.sha256 from current artifacts
	# (run with the same PTOOL_SEED that CI uses, otherwise the manifest
	# will not match CI builds)
	LC_ALL=C find $(OUT) -type f \( -name '*.bin' -o -name '*.xml' -o -name '*.rules' \) \
	  -print0 | LC_ALL=C sort -z | xargs -0 sha256sum \
	  > tests/integration/checksums.sha256

check: lint unit-test integration

install:
	pip install .

# Deletes only generated file types, so an OUT pointed at a source
# directory never loses its YAML.
clean:
	@if [ -d $(OUT) ]; then \
	  find $(OUT) -type f \( -name '*.bin' -o -name '*.xml' -o -name '*.rules' \) -delete; \
	  find $(OUT) -depth -type d -empty -delete; \
	fi
