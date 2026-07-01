# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for the YAML partition loader.

The load-bearing property is that the YAML loader produces the *same*
LoadedSpec as the .conf loader, so both emit byte-identical XML. These tests
pin that equivalence on a real board, on a synthetic multi-LUN spec with
attribute bits, and at the XML-bytes level, plus the schema rejections that
protect against the documented YAML footguns.
"""

from __future__ import annotations

import os

import pytest

from qcom_ptool.gen_partition import generate_partition_xml
from qcom_ptool.loaders import load
from qcom_ptool.loaders import yaml as yaml_loader

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
# Self-contained fixtures (not a live board): glymur-crd migrated to YAML,
# so the parity reference lives here rather than under platforms/.
GLYMUR_NVME_CONF = os.path.join(DATA_DIR, "glymur-crd-nvme.conf")
GLYMUR_NVME_YAML = os.path.join(DATA_DIR, "glymur-crd-nvme.yaml")


def _write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text)
    return str(path)


# ---------------------------------------------------------------------------
# Equivalence with the .conf loader
# ---------------------------------------------------------------------------


def test_yaml_matches_conf_for_glymur_nvme():
    """The committed YAML fixture and the real board .conf load identically."""
    assert load(GLYMUR_NVME_YAML) == load(GLYMUR_NVME_CONF)


def test_yaml_matches_conf_multi_lun_and_attributes(tmp_path):
    """LUN grouping and attribute-bit decoding match the .conf loader."""
    conf = _write(
        tmp_path,
        "s.conf",
        "--disk --type=ufs --size=137438953472 --write-protect-boundary=0 "
        "--sector-size-in-bytes=4096 --grow-last-partition\n"
        "--partition --lun=0 --name=rootfs --size=79691776KB "
        "--type-guid=1B81E7E6-F50D-419B-A739-2AEEF8DA3335 --filename=rootfs.img\n"
        "--partition --lun=1 --name=xbl_a --size=3584KB "
        "--type-guid=DEA0BA2C-CBDD-4805-B4F9-F428251C3E98 --filename=xbl.elf "
        "--attributes=1000000000000004\n",
    )
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
    assert spec == load(conf)
    # attribute-bit decode: bit 2 -> bootable, bit 60 -> readonly.
    xbl = spec["partitions"]["1"][0]
    assert xbl["bootable"] == "true"
    assert xbl["readonly"] == "true"


def test_yaml_and_conf_emit_byte_identical_xml(tmp_path):
    """End-to-end: the emitter output is identical for both source formats."""
    conf_xml = tmp_path / "from_conf.xml"
    yaml_xml = tmp_path / "from_yaml.xml"
    conf_spec = load(GLYMUR_NVME_CONF)
    yaml_spec = load(GLYMUR_NVME_YAML)
    generate_partition_xml(conf_spec["disk"], conf_spec["partitions"], str(conf_xml))
    generate_partition_xml(yaml_spec["disk"], yaml_spec["partitions"], str(yaml_xml))
    assert yaml_xml.read_bytes() == conf_xml.read_bytes()


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
    """The -m image map overrides filename, matching the .conf loader."""
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
