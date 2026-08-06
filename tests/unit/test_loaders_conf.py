# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Tests for ``qcom_ptool.loaders.conf`` plus a small main() smoke test.

The bulk of these started life as characterization tests against the inline
parser in ``gen_partition.py`` and were rewritten to target the extracted
loader. They pin the contract that any future loader (e.g. YAML) must match
to remain byte-for-byte compatible with the .conf path.
"""

from __future__ import annotations

import pytest

from qcom_ptool import gen_partition as gp
from qcom_ptool import spec
from qcom_ptool.loaders import UnsupportedFormatError, conf, load


# ---------------------------------------------------------------------------
# partition_size_in_kb
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size,expected",
    [
        # bare bytes -> divided by 1024
        ("1024", 1),
        ("2048", 2),
        ("0", 0),
        # KB / Kb / Kk
        ("1KB", 1),
        ("128KB", 128),
        ("4Kb", 4),
        ("4K", 4),
        # MB / Mb / M -> *1024
        ("1MB", 1024),
        ("2MB", 2048),
        ("4M", 4096),
        # GB / Gb / G -> *1024*1024
        ("1GB", 1024 * 1024),
        ("64GB", 64 * 1024 * 1024),
        # mixed-prefix strings: regex returns the first numeric run before the suffix
        ("foo123KB", 123),
    ],
)
def test_partition_size_in_kb_recognised_forms(size: str, expected: int) -> None:
    assert conf.partition_size_in_kb(size) == expected


@pytest.mark.parametrize("size", ["abc", "1TB", "MB", "1PB"])
def test_partition_size_in_kb_unrecognised_suffix_raises(size: str) -> None:
    """Strings with letters that don't match K/M/G hit the explicit raise."""
    with pytest.raises(ValueError, match="Unrecognized size format"):
        conf.partition_size_in_kb(size)


def test_partition_size_in_kb_empty_string_raises_int_error() -> None:
    """Empty strings take the "no letters -> int(size)" branch and surface
    int()'s native ValueError rather than the explicit "Unrecognized" message.
    Pinning this asymmetry so any future loader normalises empty strings
    consistently."""
    with pytest.raises(ValueError, match="invalid literal for int"):
        conf.partition_size_in_kb("")


# ---------------------------------------------------------------------------
# disk_options
# ---------------------------------------------------------------------------


def test_disk_options_returns_defaults_when_no_options() -> None:
    result = conf.disk_options([])
    assert result == spec.DISK_PARAMS_DEFAULTS
    # ensure caller receives a copy, not the shared default
    assert result is not spec.DISK_PARAMS_DEFAULTS


def test_disk_options_basic_ufs() -> None:
    opts = [
        ("--type", "ufs"),
        ("--size", "137438953472"),
        ("--sector-size-in-bytes", "4096"),
        ("--write-protect-boundary", "0"),
        ("--grow-last-partition", ""),
    ]
    result = conf.disk_options(opts)
    assert result["type"] == "ufs"
    assert result["size"] == "137438953472"
    assert result["SECTOR_SIZE_IN_BYTES"] == "4096"
    assert result["WRITE_PROTECT_BOUNDARY_IN_KB"] == "0"
    assert result["GROW_LAST_PARTITION_TO_FILL_DISK"] == "true"


def test_disk_options_align_partitions_converts_bytes_to_kb() -> None:
    # --align-partitions takes a value in bytes; stored value is in KB
    result = conf.disk_options([("--align-partitions", "4096")])
    assert result["ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY"] == "true"
    assert result["PERFORMANCE_BOUNDARY_IN_KB"] == "4"


def test_disk_options_unknown_flag_silently_ignored() -> None:
    # The function intentionally only matches known flags; unknown flags
    # leave the params at their defaults.
    result = conf.disk_options([("--bogus", "x")])
    assert result == spec.DISK_PARAMS_DEFAULTS


# ---------------------------------------------------------------------------
# partition_options
# ---------------------------------------------------------------------------


def test_partition_options_basic() -> None:
    opts = [
        ("--lun", "0"),
        ("--name", "rootfs"),
        ("--size", "33554432KB"),
        ("--type-guid", "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"),
        ("--filename", "rootfs.img"),
    ]
    phys_part, entry = conf.partition_options(opts)
    assert phys_part == "0"
    assert entry["label"] == "rootfs"
    assert entry["size_in_kb"] == "33554432"
    assert entry["type"] == "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"
    assert entry["filename"] == "rootfs.img"


def test_partition_options_phys_part_alias() -> None:
    # --phys-part and --lun are equivalent
    _, entry = conf.partition_options([("--name", "x"), ("--phys-part", "3")])
    assert entry["label"] == "x"
    phys_part, _ = conf.partition_options([("--phys-part", "3")])
    assert phys_part == "3"


def test_partition_options_size_with_suffix_normalises_to_kb() -> None:
    _, entry = conf.partition_options([("--size", "2MB")])
    assert entry["size_in_kb"] == "2048"

    _, entry = conf.partition_options([("--size", "1GB")])
    assert entry["size_in_kb"] == str(1024 * 1024)


def test_partition_options_attributes_bootable_and_readonly_bits() -> None:
    # bit 2 (0x4) -> bootable=true; bit 60 (1<<60) -> readonly=true
    _, entry = conf.partition_options([("--attributes", "1000000000000004")])
    assert entry["bootable"] == "true"
    assert entry["readonly"] == "true"

    # bit 2 alone -> bootable=true, readonly=false
    _, entry = conf.partition_options([("--attributes", "4")])
    assert entry["bootable"] == "true"
    assert entry["readonly"] == "false"

    # bit 60 alone -> bootable=false, readonly=true
    _, entry = conf.partition_options([("--attributes", "1000000000000000")])
    assert entry["bootable"] == "false"
    assert entry["readonly"] == "true"

    # neither bit -> bootable=false, readonly=false
    _, entry = conf.partition_options([("--attributes", "0")])
    assert entry["bootable"] == "false"
    assert entry["readonly"] == "false"


def test_partition_options_image_map_overrides_filename() -> None:
    _, entry = conf.partition_options(
        [("--name", "rootfs"), ("--filename", "default.img")],
        image_map={"rootfs": "custom-rootfs.img"},
    )
    assert entry["filename"] == "custom-rootfs.img"


def test_partition_options_image_map_no_match_keeps_filename() -> None:
    _, entry = conf.partition_options(
        [("--name", "rootfs"), ("--filename", "default.img")],
        image_map={"other": "wont-match.img"},
    )
    assert entry["filename"] == "default.img"


def test_partition_options_defaults_applied() -> None:
    _, entry = conf.partition_options([("--name", "x")])
    assert entry["type"] == "00000000-0000-0000-0000-000000000000"
    assert entry["bootable"] == "false"
    assert entry["readonly"] == "true"
    assert entry["sparse"] == "false"
    assert entry["filename"] == ""


# ---------------------------------------------------------------------------
# parse_disk_line (line-level)
# ---------------------------------------------------------------------------


def test_parse_disk_line_full_line() -> None:
    line = (
        "--disk --type=ufs --size=137438953472 "
        "--sector-size-in-bytes=4096 --write-protect-boundary=0 "
        "--grow-last-partition"
    )
    result = conf.parse_disk_line(line)
    assert result is not None
    assert result["type"] == "ufs"
    assert result["size"] == "137438953472"
    assert result["SECTOR_SIZE_IN_BYTES"] == "4096"
    assert result["GROW_LAST_PARTITION_TO_FILL_DISK"] == "true"


def test_parse_disk_line_returns_none_when_not_disk_line() -> None:
    # A line that doesn't start with --disk is silently dropped.
    assert conf.parse_disk_line("--partition --name=x --size=1KB") is None


# ---------------------------------------------------------------------------
# parse_partition_lines (line-level)
# ---------------------------------------------------------------------------


def test_parse_partition_lines_single_partition() -> None:
    lines = [
        "--partition --lun=0 --name=rootfs --size=1KB "
        "--type-guid=B921B045-1DF0-41C3-AF44-4C6F280D3FAE",
    ]
    result = conf.parse_partition_lines(lines)
    assert "0" in result
    assert len(result["0"]) == 1
    assert result["0"][0]["label"] == "rootfs"
    assert result["0"][0]["size_in_kb"] == "1"


def test_parse_partition_lines_groups_by_lun() -> None:
    lines = [
        "--partition --lun=0 --name=a --size=1KB "
        "--type-guid=00000000-0000-0000-0000-000000000001",
        "--partition --lun=0 --name=b --size=2KB "
        "--type-guid=00000000-0000-0000-0000-000000000002",
        "--partition --lun=1 --name=c --size=4KB "
        "--type-guid=00000000-0000-0000-0000-000000000003",
    ]
    result = conf.parse_partition_lines(lines)
    assert sorted(result.keys()) == ["0", "1"]
    assert [p["label"] for p in result["0"]] == ["a", "b"]
    assert [p["label"] for p in result["1"]] == ["c"]


def test_parse_partition_lines_skips_non_partition_lines() -> None:
    # Lines not starting with --partition are silently ignored by this helper.
    lines = ["--disk --type=ufs --size=1024", "--something-else"]
    assert conf.parse_partition_lines(lines) == {}


# ---------------------------------------------------------------------------
# loader public API: load() + dispatcher
# ---------------------------------------------------------------------------


def test_conf_load_full(tmp_path) -> None:
    p = tmp_path / "p.conf"
    p.write_text(
        "# header\n"
        "--disk --type=ufs --size=1073741824 --sector-size-in-bytes=4096\n"
        "--partition --lun=0 --name=rootfs --size=1KB "
        "--type-guid=B921B045-1DF0-41C3-AF44-4C6F280D3FAE --filename=r.img\n"
    )
    result = conf.load(str(p))
    assert result["disk"]["type"] == "ufs"
    assert result["disk"]["size"] == "1073741824"
    assert result["partitions"]["0"][0]["label"] == "rootfs"
    assert result["partitions"]["0"][0]["filename"] == "r.img"


def test_conf_load_image_map_overrides_filename(tmp_path) -> None:
    p = tmp_path / "p.conf"
    p.write_text(
        "--disk --type=ufs --size=1073741824 --sector-size-in-bytes=4096\n"
        "--partition --lun=0 --name=rootfs --size=1KB "
        "--type-guid=B921B045-1DF0-41C3-AF44-4C6F280D3FAE --filename=default.img\n"
    )
    result = conf.load(str(p), image_map={"rootfs": "override.img"})
    assert result["partitions"]["0"][0]["filename"] == "override.img"


def test_conf_load_rejects_two_disk_lines(tmp_path) -> None:
    p = tmp_path / "p.conf"
    p.write_text("--disk --type=ufs --size=1\n--disk --type=ufs --size=2\n")
    with pytest.raises(conf.ConfParseError, match="more than one --disk"):
        conf.load(str(p))


def test_conf_load_rejects_missing_disk_line(tmp_path) -> None:
    p = tmp_path / "p.conf"
    p.write_text(
        "--partition --lun=0 --name=x --size=1KB "
        "--type-guid=00000000-0000-0000-0000-000000000001\n"
    )
    with pytest.raises(conf.ConfParseError, match="no --disk entry"):
        conf.load(str(p))


def test_dispatcher_routes_conf_extension(tmp_path) -> None:
    p = tmp_path / "p.conf"
    p.write_text(
        "--disk --type=ufs --size=1073741824 --sector-size-in-bytes=4096\n"
        "--partition --lun=0 --name=x --size=1KB "
        "--type-guid=00000000-0000-0000-0000-000000000001\n"
    )
    result = load(str(p))
    assert result["disk"]["type"] == "ufs"


def test_dispatcher_rejects_unknown_extension(tmp_path) -> None:
    p = tmp_path / "p.toml"
    p.write_text("not actually parsed")
    with pytest.raises(UnsupportedFormatError, match="No loader registered"):
        load(str(p))


# ---------------------------------------------------------------------------
# main() smoke test (end-to-end via gen_partition.main)
# ---------------------------------------------------------------------------


def test_main_produces_xml_for_minimal_conf(tmp_path) -> None:
    conf_path = tmp_path / "partitions.conf"
    conf_path.write_text(
        "# comment line, should be ignored\n"
        "\n"
        "--disk --type=ufs --size=1073741824 --sector-size-in-bytes=4096\n"
        "--partition --lun=0 --name=rootfs --size=1KB "
        "--type-guid=B921B045-1DF0-41C3-AF44-4C6F280D3FAE --filename=r.img\n"
    )
    out = tmp_path / "partitions.xml"

    rc = gp.main(["gen_partition", "-i", str(conf_path), "-o", str(out)])

    assert rc == 0
    content = out.read_text()
    assert "physical_partition" in content
    assert 'label="rootfs"' in content
    assert 'size_in_kb="1"' in content


def test_main_image_map_override_applied(tmp_path) -> None:
    conf_path = tmp_path / "partitions.conf"
    conf_path.write_text(
        "--disk --type=ufs --size=1073741824 --sector-size-in-bytes=4096\n"
        "--partition --lun=0 --name=rootfs --size=1KB "
        "--type-guid=B921B045-1DF0-41C3-AF44-4C6F280D3FAE --filename=default.img\n"
    )
    out = tmp_path / "partitions.xml"

    rc = gp.main(
        [
            "gen_partition",
            "-i", str(conf_path),
            "-o", str(out),
            "-m", "rootfs=override.img",
        ]
    )

    assert rc == 0
    assert 'filename="override.img"' in out.read_text()


def test_main_rejects_two_disk_lines(tmp_path, capsys) -> None:
    conf_path = tmp_path / "partitions.conf"
    conf_path.write_text(
        "--disk --type=ufs --size=1\n"
        "--disk --type=ufs --size=2\n"
    )
    out = tmp_path / "partitions.xml"

    rc = gp.main(["gen_partition", "-i", str(conf_path), "-o", str(out)])

    assert rc == 1
    assert "more than one --disk" in capsys.readouterr().out
