# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for the board / flavor / platform resolver (qcom_ptool/board.py).

These pin the composition contract: boards carry hardware (plus the SoC
part of the contents metadata) unless self-contained, flavors
land on the board storage of their type, a platform lists a board's
configurations, flavor ``extends``, ``includes`` (with transitivity), LUN groups,
deep-merge by stable identifier, file-relative references, cycle
detection, and the reduction to a byte-parity LoadedSpec.
"""

from __future__ import annotations

import os
import textwrap

import pytest

from qcom_ptool.board import (
    BoardResolveError,
    config_to_specs,
    resolve,
    resolve_platform,
)
from qcom_ptool.gen_partition import generate_partition_xml
from qcom_ptool.loaders import load as load_spec

GUID_A = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
GUID_B = "B921B045-1DF0-41C3-AF44-4C6F280D3FAE"
GUID_C = "DEA0BA2C-CBDD-4805-B4F9-F428251C3E98"
GUID_D = "CD6CDFAB-B3F7-46C6-BFFE-1A1D2B8B7BA0"

_BOARD = """
    storage:
      - id: nvme0
        type: nvme
        size: 68719476736
        sector-size: 512
        write-protect-boundary: 65536
      - id: spinor0
        type: spinor
        size: 67108864
        sector-size: 4096
        write-protect-boundary: 0
      - id: ufs0
        type: ufs
        size: 137438953472
        sector-size: 4096
      - id: emmc0
        type: emmc
        size: 137438953472
        sector-size: 512
"""


def _tree(tmp_path, files: dict[str, str]) -> str:
    """Write a mini platforms tree (with the default board) and return its root."""
    root = tmp_path / "platforms"
    for rel, text in {"boards/b.yaml": _BOARD, **files}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
    return str(root)


def _resolve(root: str, flavor: str):
    return resolve(os.path.join(root, "boards/b.yaml"), os.path.join(root, flavor))


def _names(storage: dict) -> list[str]:
    return [p["name"] for p in storage["partitions"]]


def _by_id(platform, sid: str) -> dict:
    return next(s for s in platform["storage"] if s["id"] == sid)


_NVME_FLAVOR = """
    storage:
      - type: nvme
        grow-last-partition: true
        partitions:
          - {name: efi, size: "524288KB", type-guid: "%s", filename: efi.bin}
          - {name: rootfs, size: "1024KB", type-guid: "%s"}
""" % (GUID_A, GUID_B)


# ---------------------------------------------------------------------------
# board + flavor composition
# ---------------------------------------------------------------------------


def test_flavor_lands_on_board_storage_of_its_type(tmp_path):
    root = _tree(tmp_path, {"flavors/f.yaml": _NVME_FLAVOR})
    platform = _resolve(root, "flavors/f.yaml")
    assert platform["name"] == "b"
    # only the targeted storage is flashed; it takes id and geometry from
    # the board and the layout from the flavor.
    [nvme] = platform["storage"]
    assert nvme["id"] == "nvme0"
    assert nvme["size"] == 68719476736
    assert nvme["sector-size"] == 512
    assert nvme["grow-last-partition"] is True
    assert _names(nvme) == ["efi", "rootfs"]


_SPINOR_FLAVOR = """
    storage:
      - type: spinor
        partitions:
          - {name: cdt, size: "4KB", type-guid: "%s"}
""" % GUID_C


def test_platform_lists_the_board_configurations(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/nvme.yaml": _NVME_FLAVOR,
            "flavors/spinor.yaml": _SPINOR_FLAVOR,
            "demo.yaml": """
                board: boards/b.yaml
                flavors:
                  - flavors/nvme.yaml
                  - flavor: flavors/spinor.yaml
                    name: demo-nor
            """,
        },
    )
    configs = resolve_platform(os.path.join(root, "demo.yaml"))
    # one configuration per entry, named after the platform file by default.
    assert [(c["name"], [s["id"] for s in c["storage"]]) for c in configs] == [
        ("demo", ["nvme0"]),
        ("demo-nor", ["spinor0"]),
    ]
    assert configs[0]["storage"] == _resolve(root, "flavors/nvme.yaml")["storage"]


def test_configurations_may_share_a_name_on_different_storages(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/nvme.yaml": _NVME_FLAVOR,
            "flavors/spinor.yaml": _SPINOR_FLAVOR,
            "demo.yaml": """
                board: boards/b.yaml
                flavors: [flavors/nvme.yaml, flavors/spinor.yaml]
            """,
        },
    )
    configs = resolve_platform(os.path.join(root, "demo.yaml"))
    assert [c["name"] for c in configs] == ["demo", "demo"]


def test_configurations_colliding_on_an_output_are_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/a.yaml": _NVME_FLAVOR,
            "flavors/b.yaml": _NVME_FLAVOR,
            "demo.yaml": """
                board: boards/b.yaml
                flavors: [flavors/a.yaml, flavors/b.yaml]
            """,
        },
    )
    with pytest.raises(BoardResolveError, match="collide on output demo/nvme0"):
        resolve_platform(os.path.join(root, "demo.yaml"))


def test_platform_requires_flavors(tmp_path):
    root = _tree(tmp_path, {"demo.yaml": "board: boards/b.yaml\n"})
    with pytest.raises(BoardResolveError, match="schema validation failed"):
        resolve_platform(os.path.join(root, "demo.yaml"))


def test_flavor_may_span_several_storages(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/f.yaml": """
                storage:
                  - type: ufs
                    partitions:
                      - {name: rootfs, size: "4KB", type-guid: "%s"}
                  - type: spinor
                    partitions:
                      - {name: cdt, size: "4KB", type-guid: "%s"}
            """ % (GUID_A, GUID_B),
        },
    )
    platform = _resolve(root, "flavors/f.yaml")
    assert [s["id"] for s in platform["storage"]] == ["ufs0", "spinor0"]


def test_flavor_without_matching_storage_is_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                storage:
                  - {id: emmc0, type: emmc, size: 137438953472}
            """,
            "flavors/f.yaml": _NVME_FLAVOR,
        },
    )
    with pytest.raises(BoardResolveError, match="no nvme storage"):
        _resolve(root, "flavors/f.yaml")


def test_ambiguous_storage_type_is_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                storage:
                  - {id: nvme0, type: nvme, size: 68719476736}
                  - {id: nvme1, type: nvme, size: 68719476736}
            """,
            "flavors/f.yaml": _NVME_FLAVOR,
        },
    )
    with pytest.raises(BoardResolveError, match="more than one nvme storage"):
        _resolve(root, "flavors/f.yaml")


_SELF_CONTAINED = """
    storage:
      - id: nvme0
        type: nvme
        size: 68719476736
        grow-last-partition: true
        includes: [../_common/boot.yaml]
        partitions:
          - {name: efi, size: "4KB", type-guid: "%s"}
      - id: spinor0
        type: spinor
        size: 67108864
    contents:
      product-name: Out.LE.0.0
      chip: OUT
""" % GUID_A


def test_self_contained_board_resolves_without_a_flavor(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/out.yaml": _SELF_CONTAINED,
            "_common/boot.yaml": """
                partitions:
                  - {name: boot, size: "8KB", type-guid: "%s"}
            """ % GUID_B,
        },
    )
    config = resolve(os.path.join(root, "boards/out.yaml"))
    assert config["name"] == "out"
    # Only storages carrying a layout are flashed.
    assert [s["id"] for s in config["storage"]] == ["nvme0"]
    assert _names(config["storage"][0]) == ["boot", "efi"]
    assert config["contents"] == {"product-name": "Out.LE.0.0", "chip": "OUT"}


def test_self_contained_board_takes_no_flavor(tmp_path):
    root = _tree(tmp_path, {"boards/b.yaml": _SELF_CONTAINED, "flavors/f.yaml": _NVME_FLAVOR})
    with pytest.raises(BoardResolveError, match="takes no flavor"):
        _resolve(root, "flavors/f.yaml")


def test_hardware_board_needs_a_flavor(tmp_path):
    root = _tree(tmp_path, {})
    with pytest.raises(BoardResolveError, match="no storage carries partitions"):
        resolve(os.path.join(root, "boards/b.yaml"))


def test_self_contained_board_layout_is_validated(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                storage:
                  - id: nvme0
                    type: nvme
                    size: 68719476736
                    partitions:
                      - {name: efi, size: "4 KB", type-guid: "%s"}
            """ % GUID_A,
        },
    )
    with pytest.raises(BoardResolveError, match="invalid layout"):
        resolve(os.path.join(root, "boards/b.yaml"))


def _contents_tree(tmp_path, board_contents: str, platform_contents: str) -> str:
    board = _BOARD + textwrap.indent(textwrap.dedent(board_contents), "    ")
    platform = """
        board: boards/b.yaml
        %s
        flavors:
          - flavors/f.yaml
          - flavor: flavors/f.yaml
            name: other
            contents:
              product-name: Other.UBUN.1.0
              additional-chipids: [ALT]
    """ % platform_contents
    return _tree(
        tmp_path,
        {"boards/b.yaml": board, "flavors/f.yaml": _NVME_FLAVOR, "p.yaml": platform},
    )


_SOC = """
contents:
  chip: SOC
  additional-chipids: [SOC1]
  common:
    - device-programmer: {file: prog.elf}
"""


def test_platform_contents_is_laid_over_the_board_soc_part(tmp_path):
    root = _contents_tree(
        tmp_path,
        _SOC,
        """contents:
          product-name: Soc.LE.0.0
          location: /
          chipids:
            - {flavor: sail_nor, storage: spinor, flash-phase: 2}
          common:
            - download: {file: sail.elf, path: ./sail_nor, path-flavor: sail_nor}
        """,
    )
    first, other = resolve_platform(os.path.join(root, "p.yaml"))
    assert first["contents"] == {
        "chip": "SOC",
        "additional-chipids": ["SOC1"],
        # Firmware first, then the platform's flashing entries.
        "common": [
            {"device-programmer": {"file": "prog.elf"}},
            {"download": {"file": "sail.elf", "path": "./sail_nor", "path-flavor": "sail_nor"}},
        ],
        "product-name": "Soc.LE.0.0",
        "location": "/",
        # Contents metadata holds no file references: a chipid's flavor
        # names a product flavor and is kept as written.
        "chipids": [{"flavor": "sail_nor", "storage": "spinor", "flash-phase": 2}],
    }
    # An entry's contents replaces the platform's, and may override a SoC key.
    assert other["contents"] == {
        "chip": "SOC",
        "additional-chipids": ["ALT"],
        "common": [{"device-programmer": {"file": "prog.elf"}}],
        "product-name": "Other.UBUN.1.0",
    }


def test_platform_without_contents_has_none(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": _BOARD + textwrap.indent(_SOC, "    "),
            "flavors/f.yaml": _NVME_FLAVOR,
            "p.yaml": "board: boards/b.yaml\nflavors: [flavors/f.yaml]\n",
        },
    )
    (config,) = resolve_platform(os.path.join(root, "p.yaml"))
    assert config["contents"] is None
    # Nor does a board composed with a flavor directly: its SoC part alone
    # is incomplete.
    assert _resolve(root, "flavors/f.yaml")["contents"] is None


def test_board_contents_carries_only_the_soc_part(tmp_path):
    root = _contents_tree(
        tmp_path,
        _SOC + "  hlos-type: LE\n",
        "contents: {product-name: Soc.LE.0.0}",
    )
    with pytest.raises(BoardResolveError, match="hlos-type belong in the platform"):
        resolve_platform(os.path.join(root, "p.yaml"))


def test_merged_contents_is_validated(tmp_path):
    # No product-name anywhere.
    root = _contents_tree(tmp_path, _SOC, "contents: {hlos-type: LE}")
    with pytest.raises(BoardResolveError, match="invalid contents"):
        resolve_platform(os.path.join(root, "p.yaml"))


def test_flavor_rejects_geometry(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/f.yaml": """
                storage:
                  - type: nvme
                    size: 68719476736
                    partitions: []
            """,
        },
    )
    with pytest.raises(BoardResolveError, match="schema validation failed"):
        _resolve(root, "flavors/f.yaml")


def test_duplicate_board_storage_ids_are_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "boards/b.yaml": """
                storage:
                  - {id: s, type: nvme, size: 68719476736}
                  - {id: s, type: spinor, size: 67108864}
            """,
            "flavors/f.yaml": _NVME_FLAVOR,
        },
    )
    with pytest.raises(BoardResolveError, match="unique"):
        _resolve(root, "flavors/f.yaml")


# ---------------------------------------------------------------------------
# flavor extends
# ---------------------------------------------------------------------------


def test_extends_inherits_and_overrides_by_name(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/base.yaml": _NVME_FLAVOR,
            "flavors/derived.yaml": """
                extends: base.yaml
                storage:
                  - type: nvme
                    partitions:
                      - {name: rootfs, size: "33554432KB", filename: rootfs.img}
                      - {name: data, size: "4KB", type-guid: "%s"}
            """ % GUID_C,
        },
    )
    nvme = _by_id(_resolve(root, "flavors/derived.yaml"), "nvme0")
    # rootfs overridden in place and keeps its inherited type-guid; data appended.
    assert _names(nvme) == ["efi", "rootfs", "data"]
    rootfs = nvme["partitions"][1]
    assert rootfs["size"] == "33554432KB"
    assert rootfs["filename"] == "rootfs.img"
    assert rootfs["type-guid"] == GUID_B


def test_extends_appends_new_storage_type(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/base.yaml": _NVME_FLAVOR,
            "flavors/derived.yaml": """
                extends: base.yaml
                storage:
                  - type: spinor
                    partitions:
                      - {name: cdt, size: "4KB", type-guid: "%s"}
            """ % GUID_C,
        },
    )
    platform = _resolve(root, "flavors/derived.yaml")
    assert [s["id"] for s in platform["storage"]] == ["nvme0", "spinor0"]


def test_extends_overrides_partition_in_lun_group(tmp_path):
    """Derived-flavor overrides merge by (lun, name); new groups append."""
    root = _tree(
        tmp_path,
        {
            "flavors/base.yaml": """
                storage:
                  - type: ufs
                    luns:
                      - lun: 0
                        partitions:
                          - {name: rootfs, size: "4KB", type-guid: "%s"}
            """ % GUID_A,
            "flavors/derived.yaml": """
                extends: base.yaml
                storage:
                  - type: ufs
                    luns:
                      - lun: 0
                        partitions:
                          - {name: rootfs, size: "8KB"}
                      - lun: 6
                        grow: false
                        partitions:
                          - {name: extra, size: "4KB", type-guid: "%s"}
            """ % GUID_B,
        },
    )
    parts = _by_id(_resolve(root, "flavors/derived.yaml"), "ufs0")["partitions"]
    assert [(p["name"], p["lun"], p["size"]) for p in parts] == [
        ("rootfs", 0, "8KB"),
        ("extra", 6, "4KB"),
        ("last_parti", 6, "0KB"),
    ]


def test_extends_cycle_is_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/a.yaml": """
                extends: b.yaml
                storage: [{type: nvme}]
            """,
            "flavors/b.yaml": """
                extends: a.yaml
                storage: [{type: nvme}]
            """,
        },
    )
    with pytest.raises(BoardResolveError, match="cycle"):
        _resolve(root, "flavors/a.yaml")


def test_identical_include_directives_expand_once(tmp_path):
    """A directive repeated verbatim through extends expands once."""
    root = _tree(
        tmp_path,
        {
            "flavors/_common/boot.yaml": """
                partitions:
                  - {name: XBL_SC, size: "4KB", type-guid: "%s"}
            """ % GUID_A,
            "flavors/base.yaml": """
                storage:
                  - type: spinor
                    partitions:
                      - include: _common/boot.yaml
            """,
            "flavors/derived.yaml": """
                extends: base.yaml
                storage:
                  - type: spinor
                    partitions:
                      - include: _common/boot.yaml
            """,
        },
    )
    assert _names(_by_id(_resolve(root, "flavors/derived.yaml"), "spinor0")) == ["XBL_SC"]


# ---------------------------------------------------------------------------
# includes
# ---------------------------------------------------------------------------


def test_includes_concatenate_then_inline_last(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/_common/boot.yaml": """
                partitions:
                  - {name: XBL_SC, size: "2520KB", type-guid: "%s"}
                  - {name: BOOT_FW1, size: "12288KB", type-guid: "%s"}
            """ % (GUID_C, GUID_D),
            "flavors/f.yaml": """
                storage:
                  - type: spinor
                    includes: [_common/boot.yaml]
                    partitions:
                      - {name: cdt, size: "4KB", type-guid: "%s"}
            """ % GUID_A,
        },
    )
    spinor = _by_id(_resolve(root, "flavors/f.yaml"), "spinor0")
    # included fragments first (in order), inline partitions last.
    assert _names(spinor) == ["XBL_SC", "BOOT_FW1", "cdt"]


def test_references_are_relative_to_the_referencing_file(tmp_path):
    """A fragment names its sibling directly; a flavor outside the tree works."""
    root = _tree(
        tmp_path,
        {
            "flavors/_common/leaf.yaml": """
                partitions:
                  - {name: LEAF, size: "4KB", type-guid: "%s"}
            """ % GUID_A,
            "flavors/_common/mid.yaml": """
                includes: [leaf.yaml]
                partitions:
                  - {name: MID, size: "4KB", type-guid: "%s"}
            """ % GUID_B,
        },
    )
    own = tmp_path / "elsewhere" / "mine.yaml"
    own.parent.mkdir()
    own.write_text(
        textwrap.dedent(
            """
            storage:
              - type: spinor
                includes: [../platforms/flavors/_common/mid.yaml]
            """
        )
    )
    platform = resolve(os.path.join(root, "boards/b.yaml"), str(own))
    assert _names(_by_id(platform, "spinor0")) == ["LEAF", "MID"]



def test_include_dirs_resolve_references_missing_next_to_their_file(tmp_path):
    """Own directory first, then each include directory in order."""
    root = _tree(tmp_path, {"flavors/f.yaml": _NVME_FLAVOR.replace(
        "partitions:", "includes: [_common/boot.yaml]\n        partitions:", 1)})
    for name, guid in (("first", GUID_B), ("second", GUID_C), ("platforms/flavors", GUID_D)):
        frag = tmp_path / name / "_common" / "boot.yaml"
        frag.parent.mkdir(parents=True, exist_ok=True)
        frag.write_text('partitions:\n  - {name: boot, size: "8KB", type-guid: "%s"}\n' % guid)

    def boot_guid(include_dirs):
        config = resolve(
            os.path.join(root, "boards/b.yaml"),
            os.path.join(root, "flavors/f.yaml"),
            include_dirs=include_dirs,
        )
        return next(p for p in config["storage"][0]["partitions"] if p["name"] == "boot")[
            "type-guid"
        ]

    # A fragment next to the referencing file wins over any include dir.
    assert boot_guid([str(tmp_path / "first")]) == GUID_D
    os.remove(os.path.join(root, "flavors/_common/boot.yaml"))
    assert boot_guid([str(tmp_path / "first"), str(tmp_path / "second")]) == GUID_B
    assert boot_guid([str(tmp_path / "missing"), str(tmp_path / "second")]) == GUID_C
    with pytest.raises(BoardResolveError, match="cannot read"):
        boot_guid([])

def test_same_name_on_different_luns_is_not_merged(tmp_path):
    """Partition identity is (lun, name): names repeat across LUNs."""
    root = _tree(
        tmp_path,
        {
            "flavors/_common/luns.yaml": """
                partitions:
                  - {name: last_parti, lun: 0, size: "4KB", type-guid: "%s"}
                  - {name: last_parti, lun: 1, size: "4KB", type-guid: "%s"}
            """ % (GUID_A, GUID_B),
            "flavors/f.yaml": """
                storage:
                  - type: ufs
                    includes: [_common/luns.yaml]
                    partitions:
                      - {name: last_parti, lun: 1, size: "8KB"}
            """,
        },
    )
    parts = _by_id(_resolve(root, "flavors/f.yaml"), "ufs0")["partitions"]
    # both survive; the inline override touched only the lun-1 entry.
    assert [(p["lun"], p["size"]) for p in parts] == [(0, "4KB"), (1, "8KB")]


def test_include_directive_expands_in_place(tmp_path):
    """An include: item splices the fragment between inline partitions."""
    root = _tree(
        tmp_path,
        {
            "flavors/_common/boot.yaml": """
                partitions:
                  - {name: XBL_SC, size: "2520KB", type-guid: "%s"}
            """ % GUID_C,
            "flavors/f.yaml": """
                storage:
                  - type: spinor
                    partitions:
                      - {name: ALIGN, size: "4KB", type-guid: "%s"}
                      - include: _common/boot.yaml
                      - {name: cdt, size: "4KB", type-guid: "%s"}
            """ % (GUID_A, GUID_B),
        },
    )
    spinor = _by_id(_resolve(root, "flavors/f.yaml"), "spinor0")
    assert _names(spinor) == ["ALIGN", "XBL_SC", "cdt"]


def test_lun_groups_place_partitions_and_fragments(tmp_path):
    """A group's lun places lun-less items; one fragment copy serves two LUNs."""
    root = _tree(
        tmp_path,
        {
            "flavors/_common/xbl.yaml": """
                partitions:
                  - {name: xbl, size: "4KB", type-guid: "%s"}
                  - {name: pinned, lun: 7, size: "4KB", type-guid: "%s"}
            """ % (GUID_A, GUID_B),
            "flavors/f.yaml": """
                storage:
                  - type: ufs
                    luns:
                      - lun: 1
                        partitions:
                          - include: _common/xbl.yaml
                      - lun: 2
                        partitions:
                          - include: _common/xbl.yaml
                          - {name: xbl, size: "8KB"}
            """,
        },
    )
    parts = _by_id(_resolve(root, "flavors/f.yaml"), "ufs0")["partitions"]
    # a fragment entry that places itself keeps its lun, so the second
    # expansion merges into the first copy by (lun, name); the inline
    # override matched the lun-2 copy the same way, keeping the order.
    assert [(p["name"], p["lun"], p["size"]) for p in parts] == [
        ("xbl", 1, "4KB"),
        ("pinned", 7, "4KB"),
        ("xbl", 2, "8KB"),
    ]


def test_phys_part_group_places_fragment(tmp_path):
    """eMMC storages spell the same grouping as phys-parts:."""
    root = _tree(
        tmp_path,
        {
            "flavors/_common/cdt.yaml": """
                partitions:
                  - {name: cdt, size: "4KB", type-guid: "%s"}
            """ % GUID_A,
            "flavors/f.yaml": """
                storage:
                  - type: emmc
                    phys-parts:
                      - phys-part: 1
                        partitions:
                          - include: _common/cdt.yaml
            """,
        },
    )
    parts = _by_id(_resolve(root, "flavors/f.yaml"), "emmc0")["partitions"]
    assert [(p["name"], p["phys-part"]) for p in parts] == [("cdt", 1)]


def test_lun_group_grow_false_appends_absorber(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/f.yaml": """
                storage:
                  - type: ufs
                    grow-last-partition: true
                    luns:
                      - lun: 0
                        partitions:
                          - {name: rootfs, size: "4KB", type-guid: "%s"}
                      - lun: 1
                        grow: false
                        partitions:
                          - {name: xbl, size: "4KB", type-guid: "%s"}
            """ % (GUID_A, GUID_B),
        },
    )
    parts = _by_id(_resolve(root, "flavors/f.yaml"), "ufs0")["partitions"]
    # lun 0 grows its own last partition; lun 1 gets the zero-GUID absorber.
    assert [(p["name"], p["lun"]) for p in parts] == [
        ("rootfs", 0),
        ("xbl", 1),
        ("last_parti", 1),
    ]
    absorber = parts[-1]
    assert absorber["size"] == "0KB"
    assert absorber["type-guid"] == "00000000-0000-0000-0000-000000000000"


def test_partitions_and_luns_are_mutually_exclusive(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/f.yaml": """
                storage:
                  - type: ufs
                    partitions:
                      - {name: a, size: "4KB", type-guid: "%s"}
                    luns:
                      - lun: 0
                        partitions:
                          - {name: b, size: "4KB", type-guid: "%s"}
            """ % (GUID_A, GUID_B),
        },
    )
    with pytest.raises(BoardResolveError, match="mutually exclusive"):
        _resolve(root, "flavors/f.yaml")


def test_includes_cycle_is_rejected(tmp_path):
    root = _tree(
        tmp_path,
        {
            "flavors/_common/a.yaml": "includes: [b.yaml]\n",
            "flavors/_common/b.yaml": "includes: [a.yaml]\n",
            "flavors/f.yaml": """
                storage:
                  - type: spinor
                    includes: [_common/a.yaml]
            """,
        },
    )
    with pytest.raises(BoardResolveError, match="cycle"):
        _resolve(root, "flavors/f.yaml")


# ---------------------------------------------------------------------------
# final validation
# ---------------------------------------------------------------------------


def test_partition_missing_type_guid_after_resolution_is_rejected(tmp_path):
    # rootfs never gets a type-guid from any flavor -> invalid.
    root = _tree(
        tmp_path,
        {
            "flavors/f.yaml": """
                storage:
                  - type: nvme
                    partitions:
                      - {name: rootfs, size: "1KB"}
            """,
        },
    )
    with pytest.raises(BoardResolveError, match="invalid spec"):
        _resolve(root, "flavors/f.yaml")


# ---------------------------------------------------------------------------
# reduction / byte parity
# ---------------------------------------------------------------------------


def test_platform_reduces_to_byte_identical_xml(tmp_path):
    """A resolved storage emits the same XML as the equivalent hand-written
    single-storage YAML loaded via the format loader."""
    root = _tree(tmp_path, {"flavors/f.yaml": _NVME_FLAVOR})
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
              - {name: efi, size: "524288KB", type-guid: "%s", filename: efi.bin}
              - {name: rootfs, size: "1024KB", type-guid: "%s"}
            """ % (GUID_A, GUID_B)
        )
    )

    (sid, spec) = config_to_specs(_resolve(root, "flavors/f.yaml"))[0]
    assert sid == "nvme0"

    platform_xml = tmp_path / "platform.xml"
    single_xml = tmp_path / "single.xml"
    generate_partition_xml(spec["disk"], spec["partitions"], str(platform_xml))
    single_spec = load_spec(str(single))
    generate_partition_xml(single_spec["disk"], single_spec["partitions"], str(single_xml))
    assert platform_xml.read_bytes() == single_xml.read_bytes()


def test_image_map_flows_through_reduction(tmp_path):
    root = _tree(tmp_path, {"flavors/f.yaml": _NVME_FLAVOR})
    specs = config_to_specs(
        _resolve(root, "flavors/f.yaml"), image_map={"efi": "override.img"}
    )
    assert specs[0][1]["partitions"]["0"][0]["filename"] == "override.img"
