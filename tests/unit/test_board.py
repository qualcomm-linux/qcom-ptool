# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for the multi-storage board resolver (qcom_ptool/board.py).

These pin the composition contract: board-level ``extends``,
storage-level ``includes`` (with transitivity), variant overlays, deep-merge
by stable identifier, the deterministic ordering rule, cycle detection, and
the reduction to a byte-parity LoadedSpec.
"""

from __future__ import annotations

import os
import textwrap

import pytest

from qcom_ptool.board import (
    BoardResolveError,
    board_to_specs,
    resolve_board,
)
from qcom_ptool.gen_partition import generate_partition_xml
from qcom_ptool.loaders import load as load_spec

GUID_A = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
GUID_B = "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"
GUID_C = "DEA0BA2C-CBDD-4805-B4F9-F428251C3E98"
GUID_D = "CD6CDFAB-B3F7-46C6-BFFE-1A1D2B8B7BA0"


def _tree(tmp_path, files: dict[str, str]) -> str:
    """Write a mini platforms tree and return its root path."""
    root = tmp_path / "platforms"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
    return str(root)


def _names(storage: dict) -> list[str]:
    return [p["name"] for p in storage["partitions"]]


def _by_id(board, sid: str) -> dict:
    return next(s for s in board["storage"] if s["id"] == sid)


_BASE = """
    platform: {name: base}
    storage:
      - id: nvme0
        type: nvme
        size: 68719476736
        sector-size: 512
        write-protect-boundary: 65536
        grow-last-partition: true
        partitions:
          - name: efi
            size: "524288KB"
            type-guid: "%s"
            filename: efi.bin
          - name: rootfs
            size: "1024KB"
            type-guid: "%s"
""" % (GUID_A, GUID_B)


# ---------------------------------------------------------------------------
# extends
# ---------------------------------------------------------------------------


def test_extends_inherits_and_overrides_by_name(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/base.yaml": _BASE,
            "boards/derived.yaml": """
                extends: boards/base.yaml
                platform: {name: derived}
                storage:
                  - id: nvme0
                    partitions:
                      - name: rootfs
                        size: "2048KB"
            """,
        },
    )
    board = resolve_board(os.path.join(root, "boards/derived.yaml"))
    assert board["platform"] == {"name": "derived"}
    nvme = _by_id(board, "nvme0")
    rootfs = next(p for p in nvme["partitions"] if p["name"] == "rootfs")
    # size overridden, type-guid inherited field-by-field.
    assert rootfs["size"] == "2048KB"
    assert rootfs["type-guid"] == GUID_B
    # order preserved: overridden entry stays in place.
    assert _names(nvme) == ["efi", "rootfs"]


def test_extends_appends_new_storage_and_partition(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/base.yaml": _BASE,
            "boards/derived.yaml": """
                extends: boards/base.yaml
                storage:
                  - id: nvme0
                    partitions:
                      - name: extra
                        size: "8KB"
                        type-guid: "%s"
                  - id: emmc0
                    type: emmc
                    size: 1024
                    partitions:
                      - name: boot
                        size: "8KB"
                        type-guid: "%s"
            """ % (GUID_C, GUID_D),
        },
    )
    board = resolve_board(os.path.join(root, "boards/derived.yaml"))
    assert [s["id"] for s in board["storage"]] == ["nvme0", "emmc0"]
    assert _names(_by_id(board, "nvme0")) == ["efi", "rootfs", "extra"]


def test_extends_cycle_is_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/a.yaml": "extends: boards/b.yaml\nstorage: []\n",
            "boards/b.yaml": "extends: boards/a.yaml\nstorage: []\n",
        },
    )
    with pytest.raises(BoardResolveError, match="cycle"):
        resolve_board(os.path.join(root, "boards/a.yaml"))


# ---------------------------------------------------------------------------
# includes
# ---------------------------------------------------------------------------


def test_includes_concatenate_then_inline_last(tmp_path):
    root = _tree(
        tmp_path,
        {
            "_common/boot.yaml": """
                partitions:
                  - name: XBL_SC
                    size: "2520KB"
                    type-guid: "%s"
                  - name: BOOT_FW1
                    size: "12288KB"
                    type-guid: "%s"
            """ % (GUID_C, GUID_D),
            "boards/b.yaml": """
                platform: {name: b}
                storage:
                  - id: spinor0
                    type: spinor
                    size: 67108864
                    sector-size: 4096
                    write-protect-boundary: 0
                    includes: [_common/boot.yaml]
                    partitions:
                      - name: cdt
                        size: "4KB"
                        type-guid: "%s"
            """ % GUID_A,
        },
    )
    board = resolve_board(os.path.join(root, "boards/b.yaml"))
    # included fragments first (in order), inline partitions last.
    assert _names(_by_id(board, "spinor0")) == ["XBL_SC", "BOOT_FW1", "cdt"]


def test_includes_are_transitive(tmp_path):
    root = _tree(
        tmp_path,
        {
            "_common/leaf.yaml": """
                partitions:
                  - name: LEAF
                    size: "4KB"
                    type-guid: "%s"
            """ % GUID_A,
            "_common/mid.yaml": """
                includes: [_common/leaf.yaml]
                partitions:
                  - name: MID
                    size: "4KB"
                    type-guid: "%s"
            """ % GUID_B,
            "boards/b.yaml": """
                storage:
                  - id: spinor0
                    type: spinor
                    size: 67108864
                    sector-size: 4096
                    includes: [_common/mid.yaml]
                    partitions: []
            """,
        },
    )
    board = resolve_board(os.path.join(root, "boards/b.yaml"))
    assert _names(_by_id(board, "spinor0")) == ["LEAF", "MID"]


def test_includes_cycle_is_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "_common/a.yaml": "includes: [_common/b.yaml]\n",
            "_common/b.yaml": "includes: [_common/a.yaml]\n",
            "boards/b.yaml": """
                storage:
                  - id: s0
                    type: spinor
                    size: 67108864
                    includes: [_common/a.yaml]
            """,
        },
    )
    with pytest.raises(BoardResolveError, match="cycle"):
        resolve_board(os.path.join(root, "boards/b.yaml"))


# ---------------------------------------------------------------------------
# variant overlays
# ---------------------------------------------------------------------------


def test_variants_apply_last_over_includes(tmp_path):
    root = _tree(
        tmp_path,
        {
            "_common/boot.yaml": """
                partitions:
                  - name: BOOT_FW1
                    size: "12288KB"
                    type-guid: "%s"
                    filename: bootfw1.bin
            """ % GUID_D,
            "boards/b.yaml": """
                storage:
                  - id: nvme0
                    type: nvme
                    size: 68719476736
                    sector-size: 512
                    partitions:
                      - name: rootfs
                        size: "1024KB"
                        type-guid: "%s"
                  - id: spinor0
                    type: spinor
                    size: 67108864
                    sector-size: 4096
                    includes: [_common/boot.yaml]
                    partitions:
                      - name: cdt
                        size: "4KB"
                        type-guid: "%s"
            """ % (GUID_B, GUID_A),
            "variants/hlos/debian.yaml": """
                storage:
                  - id: nvme0
                    partitions:
                      - name: rootfs
                        size: "33554432KB"
                        filename: rootfs.img
            """,
            "variants/boot-fw/xbl-v3.yaml": """
                storage:
                  - id: spinor0
                    partitions:
                      - name: BOOT_FW1
                        size: "16384KB"
                        filename: bootfw1-v3.bin
                      - name: vm-data
                        size: "8192KB"
                        type-guid: "%s"
            """ % GUID_C,
        },
    )
    board = resolve_board(
        os.path.join(root, "boards/b.yaml"), hlos="debian", boot_fw="xbl-v3"
    )
    nvme = _by_id(board, "nvme0")
    rootfs = nvme["partitions"][0]
    assert rootfs["size"] == "33554432KB"
    assert rootfs["filename"] == "rootfs.img"
    assert rootfs["type-guid"] == GUID_B  # inherited through the overlay

    spinor = _by_id(board, "spinor0")
    # BOOT_FW1 overridden in place; vm-data appended after inline cdt.
    assert _names(spinor) == ["BOOT_FW1", "cdt", "vm-data"]
    boot_fw1 = spinor["partitions"][0]
    assert boot_fw1["size"] == "16384KB"
    assert boot_fw1["filename"] == "bootfw1-v3.bin"


# ---------------------------------------------------------------------------
# final validation
# ---------------------------------------------------------------------------


def test_resolved_storage_missing_type_is_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                storage:
                  - id: nvme0
                    size: 68719476736
                    partitions:
                      - name: efi
                        size: "1KB"
                        type-guid: "%s"
            """ % GUID_A,
        },
    )
    with pytest.raises(BoardResolveError, match="invalid spec"):
        resolve_board(os.path.join(root, "boards/b.yaml"))


def test_partition_missing_type_guid_after_resolution_is_rejected(tmp_path):
    # rootfs never gets a type-guid from base or any overlay -> invalid.
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                storage:
                  - id: nvme0
                    type: nvme
                    size: 68719476736
                    partitions:
                      - name: rootfs
                        size: "1KB"
            """,
        },
    )
    with pytest.raises(BoardResolveError, match="invalid spec"):
        resolve_board(os.path.join(root, "boards/b.yaml"))


# ---------------------------------------------------------------------------
# reduction / byte parity
# ---------------------------------------------------------------------------


def test_board_reduces_to_byte_identical_xml(tmp_path):
    """A resolved single-storage board emits the same XML as the equivalent
    hand-written single-storage YAML loaded via the Phase 2 loader."""
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                platform: {name: b}
                storage:
                  - id: nvme0
                    type: nvme
                    size: 68719476736
                    write-protect-boundary: 65536
                    sector-size: 512
                    grow-last-partition: true
                    partitions:
                      - name: efi
                        size: "524288KB"
                        type-guid: "%s"
                        filename: efi.bin
                      - name: rootfs
                        size: "33554432KB"
                        type-guid: "%s"
                        filename: rootfs.img
            """ % (GUID_A, GUID_B),
        },
    )
    single = tmp_path / "single.yaml"
    single.write_text(
        textwrap.dedent(
            """
            disk:
              type: nvme
              size: 68719476736
              write-protect-boundary: 65536
              sector-size: 512
              grow-last-partition: true
            partitions:
              - name: efi
                size: "524288KB"
                type-guid: "%s"
                filename: efi.bin
              - name: rootfs
                size: "33554432KB"
                type-guid: "%s"
                filename: rootfs.img
            """ % (GUID_A, GUID_B)
        )
    )

    board = resolve_board(os.path.join(root, "boards/b.yaml"))
    (sid, spec) = board_to_specs(board)[0]
    assert sid == "nvme0"

    board_xml = tmp_path / "board.xml"
    single_xml = tmp_path / "single.xml"
    generate_partition_xml(spec["disk"], spec["partitions"], str(board_xml))
    single_spec = load_spec(str(single))
    generate_partition_xml(single_spec["disk"], single_spec["partitions"], str(single_xml))
    assert board_xml.read_bytes() == single_xml.read_bytes()


def test_image_map_flows_through_reduction(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                storage:
                  - id: nvme0
                    type: nvme
                    size: 68719476736
                    partitions:
                      - name: rootfs
                        size: "1KB"
                        type-guid: "%s"
                        filename: rootfs.img
            """ % GUID_B,
        },
    )
    board = resolve_board(os.path.join(root, "boards/b.yaml"))
    specs = board_to_specs(board, image_map={"rootfs": "override.img"})
    assert specs[0][1]["partitions"]["0"][0]["filename"] == "override.img"
