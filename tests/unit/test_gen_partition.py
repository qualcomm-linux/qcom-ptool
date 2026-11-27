# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for qcom_ptool.gen_partition."""

import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

GUID = "00000000-0000-0000-0000-000000000001"
DISK = "disk: {type: emmc, size: 16777216, sector-size: 512}\n"

BASIC_YAML = DISK + """\
partitions:
  - {name: cdt, size: "2KB", type-guid: "A19F205F-CCD8-4B6D-8F1E-2D9BC24CFFB1", filename: cdt.bin}
  - {name: boot, size: "64MB", type-guid: "20117F86-E985-4357-B9EE-374BC1D8487D", attributes: "0000000000000004"}
  - {name: rootfs, size: "1GB", type-guid: "97D7B011-54DA-4835-B3C4-917AD6E73D74", attributes: "1000000000000000"}
"""


def run_gen_partition(tmp_path, yaml_text, extra_args=()):
    source = tmp_path / "partitions.yaml"
    out = tmp_path / "partitions.xml"
    source.write_text(yaml_text, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcom_ptool.gen_partition",
            "-i",
            str(source),
            "-o",
            str(out),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, out


@pytest.fixture(scope="module")
def basic_output(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("gen_partition")
    result, out = run_gen_partition(tmp_path, BASIC_YAML)
    assert result.returncode == 0, result.stdout + result.stderr
    return ET.parse(out).getroot()


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
    result, out = run_gen_partition(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr
    part = get_partitions(ET.parse(out).getroot())["data"]
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
    result, out = run_gen_partition(
        tmp_path, BASIC_YAML, extra_args=["-m", "cdt=other.bin,boot=boot.img"]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    parts = get_partitions(ET.parse(out).getroot())
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
    result, out = run_gen_partition(tmp_path, source)
    assert result.returncode == 0, result.stdout + result.stderr
    root = ET.parse(out).getroot()
    luns = root.findall("physical_partition")
    assert len(luns) == 2
    # physical partitions must be emitted in ascending LUN order
    assert luns[0].find("partition").get("label") == "early"
    assert luns[1].find("partition").get("label") == "late"


def test_invalid_source_fails(tmp_path):
    source = DISK + 'partitions:\n  - {name: a, size: "1.5MB", type-guid: "%s"}\n' % GUID
    result, _ = run_gen_partition(tmp_path, source)
    assert result.returncode == 1
    assert "schema validation failed" in result.stdout + result.stderr


def test_conf_input_is_rejected(tmp_path):
    source = tmp_path / "partitions.conf"
    source.write_text("--disk --type=emmc --size=1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "qcom_ptool.gen_partition", "-i", str(source), "-o", "x.xml"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "no longer supported" in result.stdout + result.stderr


def test_missing_arguments_shows_usage():
    result = subprocess.run(
        [sys.executable, "-m", "qcom_ptool.gen_partition"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Usage" in result.stdout + result.stderr
