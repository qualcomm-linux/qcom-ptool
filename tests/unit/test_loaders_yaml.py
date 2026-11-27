# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for the YAML partition loader: size grammar, LUN grouping,
attribute decoding, named fields, and the schema rejections that protect
against the documented YAML footguns.
"""

from __future__ import annotations

import pytest

from qcom_ptool.loaders import UnsupportedFormatError, load
from qcom_ptool.loaders import yaml as yaml_loader


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


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
        # KB / Kb / K
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
    ],
)
def test_partition_size_in_kb_recognised_forms(size: str, expected: int) -> None:
    assert yaml_loader.partition_size_in_kb(size) == expected


@pytest.mark.parametrize(
    "size",
    [
        "abc",
        "1TB",
        "MB",
        "1PB",
        # decimals, signs, prefixes and spacing must not be silently misread
        "1.5MB",
        "0.5GB",
        "2.5KB",
        "-5KB",
        "foo123KB",
        "10 KB",
        "5KBMB",
        "",
    ],
)
def test_partition_size_in_kb_unrecognised_forms_raise(size: str) -> None:
    """Anything outside ^[0-9]+([KkMmGg][Bb]?)?$ (the YAML schema grammar)
    raises rather than being silently misread, e.g. "1.5MB" is not 5MB."""
    with pytest.raises(ValueError, match="Unrecognized size format"):
        yaml_loader.partition_size_in_kb(size)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["partitions.conf", "partitions"])
def test_dispatcher_rejects_conf(tmp_path, name):
    path = _write(tmp_path, name, "--disk --type=ufs --size=1\n")
    with pytest.raises(UnsupportedFormatError, match="no longer supported"):
        load(path)


def test_dispatcher_rejects_unknown_extension(tmp_path):
    with pytest.raises(UnsupportedFormatError, match="No loader registered"):
        load(_write(tmp_path, "p.toml", "not actually parsed"))


# ---------------------------------------------------------------------------
# LUN grouping and attribute bits
# ---------------------------------------------------------------------------


def test_multi_lun_and_attributes(tmp_path):
    """Partitions group by LUN; attribute bits decode to bootable/readonly."""
    yml = _write(
        tmp_path,
        "s.yaml",
        "disk:\n"
        "  type: ufs\n"
        "  size: 137438953472\n"
        "  write-protect-boundary: 0\n"
        "  sector-size: 4096\n"
        "  grow-last-partition: true\n"
        "partitions:\n"
        "  - name: rootfs\n"
        "    lun: 0\n"
        '    size: "79691776KB"\n'
        '    type-guid: "1B81E7E6-F50D-419B-A739-2AEEF8DA3335"\n'
        "    filename: rootfs.img\n"
        "  - name: xbl_a\n"
        "    lun: 1\n"
        '    size: "3584KB"\n'
        '    type-guid: "DEA0BA2C-CBDD-4805-B4F9-F428251C3E98"\n'
        "    filename: xbl.elf\n"
        '    attributes: "1000000000000004"\n',
    )
    spec = load(yml)
    assert spec["disk"]["SECTOR_SIZE_IN_BYTES"] == "4096"
    assert spec["disk"]["WRITE_PROTECT_BOUNDARY_IN_KB"] == "0"
    assert spec["disk"]["GROW_LAST_PARTITION_TO_FILL_DISK"] == "true"
    assert sorted(spec["partitions"]) == ["0", "1"]
    rootfs = spec["partitions"]["0"][0]
    assert rootfs["size_in_kb"] == "79691776"
    assert rootfs["bootable"] == "false"
    assert rootfs["readonly"] == "true"
    # attribute-bit decode: bit 2 -> bootable, bit 60 -> readonly.
    xbl = spec["partitions"]["1"][0]
    assert xbl["bootable"] == "true"
    assert xbl["readonly"] == "true"


# ---------------------------------------------------------------------------
# Loader behaviour
# ---------------------------------------------------------------------------


def test_dispatcher_routes_yaml_and_yml(tmp_path):
    """The dispatcher sends .yaml and .yml to the YAML loader."""
    body = (
        "disk:\n"
        "  type: nvme\n"
        "  size: 68719476736\n"
        "partitions:\n"
        "  - name: efi\n"
        '    size: "524288KB"\n'
        '    type-guid: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"\n'
    )
    for name in ("s.yaml", "s.yml"):
        spec = load(_write(tmp_path, name, body))
        assert spec["disk"]["type"] == "nvme"
        assert spec["partitions"]["0"][0]["label"] == "efi"


def test_sparse_boolean_normalised_to_lowercase(tmp_path):
    """A YAML boolean must serialise as "true", not Python's "True"."""
    spec = load(
        _write(
            tmp_path,
            "s.yaml",
            "disk:\n  type: nvme\n  size: 68719476736\n"
            "partitions:\n"
            "  - name: cache\n"
            '    size: "1024KB"\n'
            '    type-guid: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"\n'
            "    sparse: true\n",
        )
    )
    assert spec["partitions"]["0"][0]["sparse"] == "true"


def test_image_map_overrides_filename(tmp_path):
    """The -m image map overrides filename."""
    spec = load(
        _write(
            tmp_path,
            "s.yaml",
            "disk:\n  type: nvme\n  size: 68719476736\n"
            "partitions:\n"
            "  - name: rootfs\n"
            '    size: "1024KB"\n'
            '    type-guid: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"\n'
            "    filename: rootfs.img\n",
        ),
        image_map={"rootfs": "override.img"},
    )
    assert spec["partitions"]["0"][0]["filename"] == "override.img"


# ---------------------------------------------------------------------------
# Schema validation (footgun rejection)
# ---------------------------------------------------------------------------

_VALID_DISK = "disk:\n  type: nvme\n  size: 68719476736\n"


def _partition(**overrides) -> str:
    fields = {
        "name": "efi",
        "size": '"524288KB"',
        "type-guid": '"C12A7328-F81F-11D2-BA4B-00A0C93EC93B"',
    }
    fields.update(overrides)
    lines = "".join(f"    {k}: {v}\n" for k, v in fields.items())
    return _VALID_DISK + "partitions:\n" + "  -\n" + lines


@pytest.mark.parametrize(
    "text",
    [
        # GUID left unquoted and all-digit -> parsed as int -> type error.
        _VALID_DISK
        + 'partitions:\n  - name: efi\n    size: "1KB"\n    type-guid: 0123456789012345678901234567\n',
        # size as a bare integer (unquoted) -> not a string -> rejected.
        _VALID_DISK
        + "partitions:\n  - name: efi\n    size: 524288\n"
        + '    type-guid: "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"\n',
        # unknown partition key -> additionalProperties: false.
        _partition(typo="1"),
        # missing required type-guid.
        _VALID_DISK + 'partitions:\n  - name: efi\n    size: "1KB"\n',
        # malformed size string.
        _partition(size='"12XB"'),
        # unknown disk type.
        "disk:\n  type: floppy\n  size: 1024\npartitions: []\n",
    ],
)
def test_schema_rejects_invalid(tmp_path, text):
    with pytest.raises(yaml_loader.YamlParseError):
        load(_write(tmp_path, "bad.yaml", text))


def test_top_level_must_be_mapping(tmp_path):
    with pytest.raises(yaml_loader.YamlParseError):
        load(_write(tmp_path, "list.yaml", "- 1\n- 2\n"))


# ---------------------------------------------------------------------------
# Named GPT attribute fields
# ---------------------------------------------------------------------------

_GUID = "DEA0BA2C-CBDD-4805-B4F9-F428251C3E98"
_UGUID = "11111111-2222-3333-4444-555555555555"


def _yaml_with(tmp_path, extra: str) -> str:
    return _write(
        tmp_path,
        "p.yaml",
        _VALID_DISK
        + "partitions:\n"
        + "  - name: boot_a\n"
        + '    size: "3584KB"\n'
        + '    type-guid: "%s"\n' % _GUID
        + extra,
    )


@pytest.mark.parametrize(
    ("yaml_field", "entry_key", "expected"),
    [
        ("bootable: true", "bootable", "true"),
        ("readonly: false", "readonly", "false"),
        ("priority: 2", "priority", "2"),
        ("tries-remaining: 6", "triesremaining", "6"),
        ("active: true", "active", "true"),
        ("successful: false", "successful", "false"),
        ("unbootable: true", "unbootable", "true"),
        ('unique-guid: "%s"' % _UGUID, "uniqueguid", _UGUID),
        ("sparse: true", "sparse", "true"),
    ],
)
def test_named_field(tmp_path, yaml_field, entry_key, expected):
    """Each named field loads to its partition entry key."""
    spec = load(_yaml_with(tmp_path, "    %s\n" % yaml_field))
    assert spec["partitions"]["0"][0][entry_key] == expected


def test_named_fields_override_attributes(tmp_path):
    """A named field wins over the raw attributes hex."""
    # attributes sets bootable (bit 2) and readonly (bit 60); named fields
    # invert both.
    spec = load(
        _yaml_with(
            tmp_path,
            '    attributes: "1000000000000004"\n'
            "    bootable: false\n"
            "    readonly: false\n",
        )
    )
    entry = spec["partitions"]["0"][0]
    assert entry["bootable"] == "false"
    assert entry["readonly"] == "false"


@pytest.mark.parametrize(
    "text",
    [
        # priority beyond the 2-bit field.
        _partition(priority="4"),
        # tries-remaining beyond the 3-bit field.
        _partition(**{"tries-remaining": "8"}),
        # named flags must be booleans, not strings.
        _partition(active='"yes"'),
        # malformed unique GUID.
        _partition(**{"unique-guid": '"not-a-guid"'}),
    ],
)
def test_schema_rejects_invalid_named_fields(tmp_path, text):
    with pytest.raises(yaml_loader.YamlParseError):
        load(_write(tmp_path, "bad.yaml", text))
