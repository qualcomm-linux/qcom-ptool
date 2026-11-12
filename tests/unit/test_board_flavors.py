# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for board flavors (qcom_ptool/board.py, resolve_board_flavors).

A flavor references a complete layout under platforms/flavors/; the board
contributes storage geometry (matched by id) and optional in-place
overrides. These pin that composition, the default output naming, output
collision detection, and the legacy single-flavor reduction.
"""

from __future__ import annotations

import os
import textwrap

import pytest

from qcom_ptool.board import (
    BoardResolveError,
    resolve_board,
    resolve_board_flavors,
)

GUID_A = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
GUID_B = "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"
GUID_C = "DEA0BA2C-CBDD-4805-B4F9-F428251C3E98"
GUID_D = "CD6CDFAB-B3F7-46C6-BFFE-1A1D2B8B7BA0"


def _tree(tmp_path, files: dict[str, str]) -> str:
    root = tmp_path / "platforms"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
    return str(root)


def _names(storage: dict) -> list[str]:
    return [p["name"] for p in storage["partitions"]]


def _by_id(flavor, sid: str) -> dict:
    return next(s for s in flavor["storage"] if s["id"] == sid)


_FLAVOR_TREE = {
    "flavors/fam-ufs.yaml": """
        storage:
          - id: ufs
            type: ufs
            luns:
              - lun: 0
                partitions:
                  - {name: hlos, size: "64KB", type-guid: "%(a)s", filename: hlos.img}
                  - {name: rootfs, size: "1024KB", type-guid: "%(b)s"}
              - lun: 1
                grow: false
                partitions:
                  - {name: xbl, size: "8KB", type-guid: "%(c)s"}
    """
    % {"a": GUID_A, "b": GUID_B, "c": GUID_C},
    "flavors/fam-emmc.yaml": """
        storage:
          - id: emmc
            type: emmc
            partitions:
              - {name: boot, size: "8KB", type-guid: "%(d)s"}
              - {name: rootfs, size: "1024KB", type-guid: "%(b)s"}
    """
    % {"b": GUID_B, "d": GUID_D},
    "boards/two-flavors.yaml": """
        platform: {name: two-flavors}
        storage:
          - id: ufs
            size: 68719476736
            sector-size: 4096
            write-protect-boundary: 0
            grow-last-partition: true
          - id: emmc
            size: 68719476736
            sector-size: 512
            write-protect-boundary: 65536
            grow-last-partition: true
        flavors:
          - layout: flavors/fam-ufs.yaml
          - layout: flavors/fam-emmc.yaml
            storage:
              - id: emmc
                partitions:
                  - {name: rootfs, size: "2048KB"}
    """,
}

_LEGACY = """
    platform: {name: legacy}
    storage:
      - id: nvme0
        type: nvme
        size: 68719476736
        partitions:
          - {name: efi, size: "524288KB", type-guid: "%s", filename: efi.bin}
          - {name: rootfs, size: "1024KB", type-guid: "%s"}
""" % (GUID_A, GUID_B)


def test_flavors_merge_geometry_and_overrides(tmp_path):
    root = _tree(tmp_path, _FLAVOR_TREE)
    flavors = resolve_board_flavors(os.path.join(root, "boards/two-flavors.yaml"))

    assert [f["name"] for f in flavors] == ["two-flavors", "two-flavors"]
    assert [f["layout"] for f in flavors] == [
        "flavors/fam-ufs.yaml",
        "flavors/fam-emmc.yaml",
    ]

    ufs = _by_id(flavors[0], "ufs")
    # Geometry comes from the board, partitions from the layout (groups
    # flattened, grow: false appends the absorber).
    assert ufs["size"] == 68719476736
    assert ufs["sector-size"] == 4096
    assert _names(ufs) == ["hlos", "rootfs", "xbl", "last_parti"]
    # The UFS flavor does not gain the board's unrelated eMMC geometry.
    assert [s["id"] for s in flavors[0]["storage"]] == ["ufs"]

    emmc = _by_id(flavors[1], "emmc")
    rootfs = next(p for p in emmc["partitions"] if p["name"] == "rootfs")
    # In-place override: size replaced, type-guid inherited from the layout.
    assert rootfs["size"] == "2048KB"
    assert rootfs["type-guid"] == GUID_B
    assert _names(emmc) == ["boot", "rootfs"]


def test_flavor_explicit_name_sets_output(tmp_path):
    files = dict(_FLAVOR_TREE)
    files["boards/named.yaml"] = """
        platform: {name: named}
        storage:
          - id: ufs
            size: 68719476736
            sector-size: 4096
            write-protect-boundary: 0
            grow-last-partition: true
        flavors:
          - layout: flavors/fam-ufs.yaml
          - layout: flavors/fam-ufs.yaml
            name: named-variant
    """
    root = _tree(tmp_path, files)
    flavors = resolve_board_flavors(os.path.join(root, "boards/named.yaml"))
    assert [f["name"] for f in flavors] == ["named", "named-variant"]


def test_flavors_colliding_outputs_are_rejected(tmp_path):
    files = dict(_FLAVOR_TREE)
    files["boards/clash.yaml"] = """
        platform: {name: clash}
        storage:
          - id: ufs
            size: 68719476736
            sector-size: 4096
            write-protect-boundary: 0
            grow-last-partition: true
        flavors:
          - layout: flavors/fam-ufs.yaml
          - layout: flavors/fam-ufs.yaml
    """
    root = _tree(tmp_path, files)
    with pytest.raises(BoardResolveError, match="collide"):
        resolve_board_flavors(os.path.join(root, "boards/clash.yaml"))


def test_resolve_board_rejects_flavored_board(tmp_path):
    root = _tree(tmp_path, _FLAVOR_TREE)
    with pytest.raises(BoardResolveError, match="flavors"):
        resolve_board(os.path.join(root, "boards/two-flavors.yaml"))


def test_inline_flavor_defines_storage_in_the_board_file(tmp_path):
    files = dict(_FLAVOR_TREE)
    files["boards/mixed.yaml"] = """
        platform: {name: mixed}
        storage:
          - id: ufs
            size: 68719476736
            sector-size: 4096
            write-protect-boundary: 0
            grow-last-partition: true
        flavors:
          - layout: flavors/fam-ufs.yaml
          - name: mixed-emmc
            storage:
              - id: emmc
                type: emmc
                size: 68719476736
                sector-size: 512
                write-protect-boundary: 65536
                grow-last-partition: true
                partitions:
                  - {name: boot, size: "8KB", type-guid: "%s"}
    """ % GUID_D
    root = _tree(tmp_path, files)
    flavors = resolve_board_flavors(os.path.join(root, "boards/mixed.yaml"))
    assert [f["name"] for f in flavors] == ["mixed", "mixed-emmc"]
    assert flavors[1]["layout"] is None
    assert _names(_by_id(flavors[1], "emmc")) == ["boot"]


def test_includes_resolve_relative_to_their_file_first(tmp_path):
    files = {
        "flavors/_common/boot.yaml": """
            partitions:
              - {name: xbl, size: "8KB", type-guid: "%s"}
        """
        % GUID_C,
        "flavors/_common/combo.yaml": """
            includes: [boot.yaml]
            partitions:
              - {name: cdt, size: "4KB", type-guid: "%s"}
        """
        % GUID_D,
        "flavors/with-include.yaml": """
            storage:
              - id: ufs
                type: ufs
                luns:
                  - lun: 0
                    partitions:
                      - include: _common/combo.yaml
                      - {name: rootfs, size: "1024KB", type-guid: "%s"}
        """
        % GUID_B,
        "boards/fr.yaml": """
            platform: {name: fr}
            storage:
              - id: ufs
                size: 68719476736
                sector-size: 4096
                write-protect-boundary: 0
                grow-last-partition: true
            flavors:
              - layout: flavors/with-include.yaml
        """,
    }
    root = _tree(tmp_path, files)
    flavors = resolve_board_flavors(os.path.join(root, "boards/fr.yaml"))
    # The layout's include and the fragment's sibling include both resolve
    # relative to their own files, without spelling out flavors/_common/.
    assert _names(_by_id(flavors[0], "ufs")) == ["xbl", "cdt", "rootfs"]


def test_legacy_board_is_a_single_default_flavor(tmp_path):
    root = _tree(tmp_path, {"boards/legacy.yaml": _LEGACY})
    flavors = resolve_board_flavors(os.path.join(root, "boards/legacy.yaml"))
    assert len(flavors) == 1
    assert flavors[0]["name"] == "legacy"
    assert flavors[0]["layout"] is None
    assert _names(_by_id(flavors[0], "nvme0")) == ["efi", "rootfs"]
