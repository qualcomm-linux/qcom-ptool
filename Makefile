TOPDIR := $(PWD)

# Tools run from this checkout through uv, at the versions pinned in
# uv.lock. Without uv on PATH, make first installs it with pip into
# $(UV_DIR). Generating partition tables installs only qcom-ptool's
# runtime dependencies (--no-dev); the development tools (ruff, mypy,
# pytest) come from the dev group, or from PATH with RUN=.
PYTHON ?= python3
UV_DIR ?= $(CURDIR)/.uv
UV ?= $(or $(shell command -v uv 2>/dev/null),$(UV_DIR)/bin/uv)
UV_RUN := $(UV) run --locked --project $(CURDIR)
RUN ?= $(UV_RUN)
QCOM_PTOOL ?= $(UV_RUN) --no-dev qcom-ptool

# The pip-installed uv is an included makefile, so make installs it
# before anything else and then re-reads this file with uv in place.
# --target keeps it out of the system Python (PEP 668).
UV_STAMP := $(if $(findstring $(UV_DIR)/bin/uv,$(RUN) $(QCOM_PTOOL)),$(UV_DIR)/.installed)
ifneq ($(UV_STAMP),)
ifneq ($(MAKECMDGOALS),clean)
-include $(UV_STAMP)
endif
$(UV_STAMP):
	$(PYTHON) -m pip install -q --target $(UV_DIR) uv
	touch $@
endif

# Every generated artifact goes under $(OUT); platforms/ outside it holds
# only the YAML sources.
OUT ?= platforms/out

# Every platforms/<platform>.yaml lists the configurations of one board
# (platforms/boards/): each is a flavor (platforms/flavors/) on it. One
# `qcom-ptool build` per platform writes them all to
# $(OUT)/<name>/<storage-id>/; a stamp records when it last ran.
YAML_PLATFORMS := $(basename $(notdir $(wildcard platforms/*.yaml)))
YAML_SHARED := $(wildcard platforms/boards/*.yaml platforms/flavors/*.yaml \
    platforms/flavors/_common/*.yaml)
STAMPS := $(YAML_PLATFORMS:%=$(OUT)/.stamps/%)

UDEV_RULES := $(OUT)/55-qcom-raw-partitions-noblkid.rules

# optional build_id for Axiom contents.xml files
BUILD_ID ?=

.PHONY: all check check-checksums check-dev check-partitions clean generate-checksums lint integration unit-test

all: $(STAMPS) $(UDEV_RULES)

$(OUT)/.stamps/%: platforms/%.yaml $(YAML_SHARED)
	$(QCOM_PTOOL) build -o $(OUT) $(if $(BUILD_ID),--build-id $(BUILD_ID)) $<
	@mkdir -p $(@D) && touch $@

# Raw-partition udev rules from every platform.
$(UDEV_RULES): $(wildcard platforms/*.yaml) $(YAML_SHARED) \
    qcom_ptool/data/filesystem-partition-names.list \
    qcom_ptool/data/55-qcom-raw-partitions-noblkid.rules.in
	$(QCOM_PTOOL) gen_udev_rules platforms -o $@

lint:
	$(RUN) ruff check qcom_ptool
	$(RUN) mypy qcom_ptool

unit-test:
	$(RUN) pytest

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

# qcom-ptool development: lint and unit tests.
check-dev: lint unit-test

# Partition tables: build every platform and verify the generated files.
check-partitions: integration

check: check-dev check-partitions

# Deletes only generated file types, so an OUT pointed at a source
# directory never loses its YAML.
clean:
	@rm -rf $(OUT)/.stamps
	@if [ -d $(OUT) ]; then \
	  find $(OUT) -type f \( -name '*.bin' -o -name '*.xml' -o -name '*.rules' \) -delete; \
	  find $(OUT) -depth -type d -empty -delete; \
	fi
