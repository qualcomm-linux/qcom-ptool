# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for the contents metadata emitter (qcom_ptool/contents_yaml.py).

The generated contents.xml is pinned byte for byte by
data/contents-expected.xml: _META exercises every construct the platforms
use (an extra product flavor, a second chipid, device programmers with and
without attributes, literal downloads, sahara and flavored), and a platform
split into board and platform parts must build the same file as one
self-contained board.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from qcom_ptool import gen_contents
from qcom_ptool.contents_yaml import (
    ContentsError,
    contents_paths,
    default_storage,
)

EXPECTED = Path(__file__).parent / "data" / "contents-expected.xml"

GUID_A = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
GUID_B = "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"

_META = {
    "product-name": "Demo.LE.0.0",
    "hlos-type": "LE",
    "chip": "DEMO",
    "chipset": "DEMOCHIPSET",
    "additional-chipids": ["DEMO1", "DEMO2"],
    "apps-image-dir": "build",
    "chipids": [{"flavor": "sail_nor", "storage": "spinor", "flash-phase": 2}],
    "product-flavors": [{"name": "sail_nor", "components": ["common"]}],
    "common": [
        {
            "device-programmer": {
                "file": "qsahara_device_programmer.xml",
                "attributes": {"cmm_file_var": "FIREHOSE_DDR_ELF"},
            }
        },
        {
            "download": {
                "file": "xbl_sc.elf",
                "attributes": {"qsahara_image_id": "21"},
            }
        },
        {
            "device-programmer": {
                "file": "prog_firehose_lite.elf",
                "attributes": {"firehose_type": "lite"},
            }
        },
        {
            "download": {
                "file": "sailhyp.elf",
                "path": "./sail_nor",
                "path-flavor": "sail_nor",
                "attributes": {"storage_type": "spinor", "fastboot_complete": "SAIL_HYP"},
            }
        },
        {
            "partition": {
                "file": "rawprogram0.xml",
                "path": "./sail_nor",
                "path-flavor": "sail_nor",
                "attributes": {"storage_type": "spinor", "flavor": "sail_nor"},
            }
        },
    ],
}

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


_SOC_KEYS = ("chip", "chipset", "additional-chipids")


def _split_meta():
    """_META split the way the repo splits it: SoC part / HLOS and flashing part."""
    firmware = [e for e in _META["common"] if "path-flavor" not in next(iter(e.values()))]
    flashing = [e for e in _META["common"] if e not in firmware]
    soc = {k: _META[k] for k in _SOC_KEYS}
    soc["common"] = firmware
    platform = {k: v for k, v in _META.items() if k not in _SOC_KEYS and k != "common"}
    platform["common"] = flashing
    return soc, platform


_UFS = """
  - id: ufs
    type: ufs
    size: 1073741824
    sector-size: 4096
    write-protect-boundary: 0
"""


def test_platform_pipeline(tmp_path):
    """The board's SoC part and the platform's part merge back into _META."""
    soc, hlos = _split_meta()
    _write(tmp_path, "boards/demo.yaml", "storage:%s\ncontents: %r\n" % (_UFS, soc))
    _write(
        tmp_path,
        "flavors/demo-ufs.yaml",
        """
        storage:
          - type: ufs
            grow-last-partition: true
            partitions:
              - {name: efi, size: "1KB", type-guid: "%s", filename: efi.bin}
        """
        % GUID_A,
    )
    platform = _write(
        tmp_path,
        "demo.yaml",
        "board: boards/demo.yaml\ncontents: %r\nflavors: [flavors/demo-ufs.yaml]\n" % hlos,
    )
    out = tmp_path / "out"

    assert gen_contents.generate_from_file(str(platform), None, str(out), "") == 0
    # Contents land next to the default storage's partitions by default.
    built = (out / "demo" / "ufs" / "contents.xml").read_bytes()
    assert built == EXPECTED.read_bytes()


def test_self_contained_board_pipeline(tmp_path):
    """An out-of-tree board: layout and complete contents in one file."""
    board = _write(
        tmp_path,
        "board.yaml",
        "storage:%s    grow-last-partition: true\n"
        "    partitions:\n"
        '      - {name: efi, size: "1KB", type-guid: "%s", filename: efi.bin}\n'
        "contents: %r\n" % (_UFS, GUID_A, _META),
    )
    out = tmp_path / "out"

    assert gen_contents.generate_from_file(str(board), None, str(out), "") == 0
    built = (out / "ufs" / "contents.xml").read_bytes()
    assert built == EXPECTED.read_bytes()


def test_contents_paths_location():
    config = {
        "name": "demo",
        "storage": [{"id": "emmc"}, {"id": "spinor"}],
        "contents": {"product-name": "x", "chip": "X"},
    }
    # Default: the first storage, even with a second storage's chipid.
    config["contents"]["chipids"] = [{"flavor": "sail_nor", "storage": "spinor", "flash-phase": 2}]
    assert contents_paths(config) == ("emmc/contents.xml", "emmc")

    config["contents"]["location"] = "spinor"
    assert contents_paths(config) == ("spinor/contents.xml", "spinor")
    assert default_storage(config) == "spinor"

    config["contents"]["location"] = "/"
    assert contents_paths(config) == ("contents.xml", "emmc")
    assert default_storage(config) == "emmc"

    config["contents"]["location"] = "nvme"
    with pytest.raises(ContentsError):
        contents_paths(config)

    assert contents_paths({"name": "demo", "storage": [{"id": "ufs"}], "contents": None}) is None
