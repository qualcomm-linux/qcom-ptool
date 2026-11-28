# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
GPT and flashing artifacts of one storage.

Every LUN with partitions gets its GPT images (``gpt_main/backup/both/
empty``) and firehose XML (``rawprogram``, ``patch`` and the wipe and
blank-GPT variants), numbered by its position among those LUNs; the
storage gets the zero-filled images the wipe files write and
``wipe_rawprogram_PHYn.xml``.
"""

from __future__ import annotations

import os
import random
from xml.etree.ElementTree import Element

from qcom_ptool import firehose
from qcom_ptool.gpt import build_tables
from qcom_ptool.layout import Placement, WriteProtect, geometry, place_lun, validate
from qcom_ptool.spec import LoadedSpec

# Physical partitions the wipe files cover. The list is ptool.py's, kept
# so that the output does not change: it is the eMMC numbering, where 3
# is RPMB, and is applied to every storage type.
WIPE_PHYS = (0, 1, 2, 4, 5, 6, 7)


def rng_for_build() -> random.Random:
    """Random GUIDs, reproducible across runs when PTOOL_SEED is set."""
    seed = os.environ.get("PTOOL_SEED")
    return random.Random(seed) if seed else random.Random()


def _write(outdir: str, name: str, data: bytes | Element) -> None:
    path = os.path.join(outdir, name)
    if isinstance(data, Element):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(firehose.render(data))
    else:
        with open(path, "wb") as f:
            f.write(data)


def write_storage(
    spec: LoadedSpec, outdir: str, rng: random.Random | None = None
) -> list[list[Placement]]:
    """Write the artifacts of ``spec`` to ``outdir``; return its layout."""
    if rng is None:
        rng = rng_for_build()
    geom = geometry(spec["disk"])
    luns = [entries for _, entries in sorted(spec["partitions"].items(), key=lambda i: int(i[0]))
            if entries]
    validate(luns)

    os.makedirs(outdir, exist_ok=True)
    wp = WriteProtect(geom)
    layout = []
    for lun, entries in enumerate(luns):
        placements = place_lun(entries, geom, wp)
        tables = build_tables(placements, geom, rng)
        _write(outdir, "gpt_main%d.bin" % lun, tables.primary)
        _write(outdir, "gpt_backup%d.bin" % lun, tables.backup)
        _write(outdir, "gpt_both%d.bin" % lun, tables.primary + tables.backup)
        _write(outdir, "gpt_empty%d.bin" % lun, tables.empty)
        for name, root in firehose.lun_documents(placements, geom, lun, tables.num_entries).items():
            _write(outdir, name, root)
        layout.append(placements)

    for sectors in sorted({1, geom.backup_lbas, 33}):
        _write(outdir, firehose.zeros_name(sectors), bytes(sectors * geom.sector))
    for phy in WIPE_PHYS:
        _write(outdir, "wipe_rawprogram_PHY%d.xml" % phy, firehose.wipe_phy(geom, phy))
    return layout
