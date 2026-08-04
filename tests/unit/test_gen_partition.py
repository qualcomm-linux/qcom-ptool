# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""Tests for qcom_ptool.gen_partition."""

import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

BASIC_CONF = """\
# comment lines and blank lines are ignored

--disk --type=emmc --size=16777216 --sector-size-in-bytes=512

--partition --name=cdt --size=2KB --type-guid=A19F205F-CCD8-4B6D-8F1E-2D9BC24CFFB1 --filename=cdt.bin
--partition --name=boot --size=64MB --type-guid=20117F86-E985-4357-B9EE-374BC1D8487D --attributes=0x0000000000000004
--partition --name=rootfs --size=1GB --type-guid=97D7B011-54DA-4835-B3C4-917AD6E73D74 --attributes=0x1000000000000000
"""


def run_gen_partition(tmp_path, conf_text, extra_args=()):
    conf = tmp_path / "partitions.conf"
    out = tmp_path / "partitions.xml"
    conf.write_text(conf_text, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcom_ptool.gen_partition",
            "-i",
            str(conf),
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
    result, out = run_gen_partition(tmp_path, BASIC_CONF)
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
    conf = """\
--disk --type=emmc --size=16777216
--partition --name=data --size=4096
"""
    result, out = run_gen_partition(tmp_path, conf)
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
        tmp_path, BASIC_CONF, extra_args=["-m", "cdt=other.bin,boot=boot.img"]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    parts = get_partitions(ET.parse(out).getroot())
    assert parts["cdt"].get("filename") == "other.bin"
    assert parts["boot"].get("filename") == "boot.img"
    assert parts["rootfs"].get("filename") == ""


def test_multiple_luns_sorted(tmp_path):
    conf = """\
--disk --type=ufs --size=16777216
--partition --lun=2 --name=late --size=1KB
--partition --lun=0 --name=early --size=1KB
"""
    result, out = run_gen_partition(tmp_path, conf)
    assert result.returncode == 0, result.stdout + result.stderr
    root = ET.parse(out).getroot()
    luns = root.findall("physical_partition")
    assert len(luns) == 2
    # physical partitions must be emitted in ascending LUN order
    assert luns[0].find("partition").get("label") == "early"
    assert luns[1].find("partition").get("label") == "late"


def test_duplicate_disk_entry_fails(tmp_path):
    conf = "--disk --type=emmc --size=1\n--disk --type=emmc --size=2\n--partition --name=a --size=1KB\n"
    result, _ = run_gen_partition(tmp_path, conf)
    assert result.returncode == 1
    assert "more than one --disk" in result.stdout + result.stderr


def test_missing_arguments_shows_usage():
    result = subprocess.run(
        [sys.executable, "-m", "qcom_ptool.gen_partition"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Usage" in result.stdout + result.stderr
