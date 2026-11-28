# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for the partitions.xml emitter (qcom_ptool.gen_partition)."""

import xml.etree.ElementTree as ET

import pytest

from qcom_ptool.gen_partition import generate_partition_xml
from qcom_ptool.loaders import load
from qcom_ptool.loaders.yaml import YamlParseError

GUID = "00000000-0000-0000-0000-000000000001"
DISK = "disk: {type: emmc, size: 16777216, sector-size: 512}\n"

BASIC_YAML = DISK + """\
partitions:
  - {name: cdt, size: "2KB", type-guid: "A19F205F-CCD8-4B6D-8F1E-2D9BC24CFFB1", filename: cdt.bin}
  - {name: boot, size: "64MB", type-guid: "20117F86-E985-4357-B9EE-374BC1D8487D", attributes: "0000000000000004"}
  - {name: rootfs, size: "1GB", type-guid: "97D7B011-54DA-4835-B3C4-917AD6E73D74", attributes: "1000000000000000"}
"""


def run_gen_partition(tmp_path, yaml_text, image_map=None):
    """Load a partitions YAML and emit its partitions.xml; return the XML root."""
    source = tmp_path / "partitions.yaml"
    out = tmp_path / "partitions.xml"
    source.write_text(yaml_text, encoding="utf-8")
    spec = load(str(source), image_map=image_map)
    generate_partition_xml(spec["disk"], spec["partitions"], str(out))
    return ET.parse(out).getroot()


@pytest.fixture(scope="module")
def basic_output(tmp_path_factory):
    return run_gen_partition(tmp_path_factory.mktemp("gen_partition"), BASIC_YAML)


def get_partitions(root):
    return {
        p.get("label"): p
        for phys in root.findall("physical_partition")
        for p in phys.findall("partition")
    }


def test_generates_configuration_root(basic_output):
    assert basic_output.tag == "configuration"
    assert basic_output.find("parser_instructions") is not None
    assert len(basic_output.findall("physical_partition")) == 1


def test_sector_size_in_parser_instructions(basic_output):
    text = basic_output.find("parser_instructions").text
    assert "SECTOR_SIZE_IN_BYTES=512" in text


@pytest.mark.parametrize(
    ("label", "expected_kb"),
    [("cdt", "2"), ("boot", str(64 * 1024)), ("rootfs", str(1024 * 1024))],
)
def test_size_suffix_parsing(basic_output, label, expected_kb):
    # KB / MB / GB suffixes must all normalize to size_in_kb.
    assert get_partitions(basic_output)[label].get("size_in_kb") == expected_kb


def test_plain_size_is_interpreted_as_bytes(tmp_path):
    source = DISK + 'partitions:\n  - {name: data, size: "4096", type-guid: "%s"}\n' % GUID
    part = get_partitions(run_gen_partition(tmp_path, source))["data"]
    assert part.get("size_in_kb") == "4"


def test_attribute_bit2_sets_bootable(basic_output):
    parts = get_partitions(basic_output)
    assert parts["boot"].get("bootable") == "true"
    assert parts["boot"].get("readonly") == "false"


def test_attribute_bit60_sets_readonly(basic_output):
    parts = get_partitions(basic_output)
    assert parts["rootfs"].get("bootable") == "false"
    assert parts["rootfs"].get("readonly") == "true"


def test_filename_passthrough(basic_output):
    assert get_partitions(basic_output)["cdt"].get("filename") == "cdt.bin"


def test_partition_image_map_overrides_filename(tmp_path):
    root = run_gen_partition(tmp_path, BASIC_YAML, {"cdt": "other.bin", "boot": "boot.img"})
    parts = get_partitions(root)
    assert parts["cdt"].get("filename") == "other.bin"
    assert parts["boot"].get("filename") == "boot.img"
    assert parts["rootfs"].get("filename") == ""


def test_multiple_luns_sorted(tmp_path):
    source = """\
disk: {type: ufs, size: 16777216}
partitions:
  - {name: late, lun: 2, size: "1KB", type-guid: "%s"}
  - {name: early, lun: 0, size: "1KB", type-guid: "%s"}
""" % (GUID, GUID)
    luns = run_gen_partition(tmp_path, source).findall("physical_partition")
    assert len(luns) == 2
    # physical partitions must be emitted in ascending LUN order
    assert luns[0].find("partition").get("label") == "early"
    assert luns[1].find("partition").get("label") == "late"


def test_invalid_source_fails(tmp_path):
    source = DISK + 'partitions:\n  - {name: a, size: "1.5MB", type-guid: "%s"}\n' % GUID
    with pytest.raises(YamlParseError, match="schema validation failed"):
        run_gen_partition(tmp_path, source)
