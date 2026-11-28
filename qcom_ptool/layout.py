# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Sector layout of one storage: where each partition of each LUN starts.

Partitions are placed back to back after the primary GPT, moved forward
to the performance boundary and, around read-only partitions, to the
write-protect boundary. The rules reproduce the historical ptool layout
exactly, quirks included, because GPT offsets are pinned by the
checksum manifest:

- the write-protect window grown by read-only partitions is shared by
  all LUNs of a storage;
- the distance to the next boundary is computed once per partition and
  reused: with no write-protect boundary, a read-only partition outside
  the window moves by the performance-alignment distance a second time;
- a grown last partition is placed with zero sectors (its real size is
  patched in at flash time).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from qcom_ptool.spec import DiskParams, PartitionEntry


@dataclass(frozen=True)
class Geometry:
    """The disk parameters that shape the layout."""

    sector: int
    write_protect_kb: int
    performance_kb: int
    align: bool
    grow_last: bool

    @property
    def primary_lbas(self) -> int:
        """Protective MBR, GPT header and partition array."""
        return 6 if self.sector == 4096 else 34

    @property
    def backup_lbas(self) -> int:
        """Partition array and backup GPT header."""
        return self.primary_lbas - 1

    def kb_to_sectors(self, kb: float) -> int:
        return int((kb * 1024) // self.sector)

    def till_boundary(self, lba: int, boundary_kb: int) -> int:
        """Sectors from ``lba`` to the next ``boundary_kb`` boundary."""
        step = self.kb_to_sectors(boundary_kb)
        if boundary_kb > 0 and lba % step:
            return step - lba % step
        return 0


def geometry(disk: DiskParams) -> Geometry:
    def number(key: str, default: str = "0") -> int:
        value = str(disk.get(key, default))
        return int(value) if value.isdigit() else 0

    def flag(key: str) -> bool:
        return str(disk.get(key, "false")).lower() == "true"

    return Geometry(
        sector=number("SECTOR_SIZE_IN_BYTES") or 512,
        write_protect_kb=number("WRITE_PROTECT_BOUNDARY_IN_KB", "65536"),
        performance_kb=number("PERFORMANCE_BOUNDARY_IN_KB"),
        align=flag("ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY"),
        grow_last=flag("GROW_LAST_PARTITION_TO_FILL_DISK"),
    )


class WriteProtect:
    """The write-protect window read-only partitions extend (or open)."""

    def __init__(self, geom: Geometry) -> None:
        self.geom = geom
        self.end: float = 0
        self.step = geom.write_protect_kb * 1024 / geom.sector

    def cover(self, start: int, sectors: int) -> None:
        if self.geom.write_protect_kb == 0:
            return
        if start - 1 > self.end:
            self.end = start + self.step - 1
        while start + sectors - 1 > self.end:
            self.end += self.step


@dataclass(frozen=True)
class Placement:
    """One partition on its LUN."""

    entry: PartitionEntry
    first: int
    sectors: int
    wipe_sectors: int
    grown: bool

    @property
    def last(self) -> int:
        return self.first + self.sectors - 1


def place_lun(entries: list[PartitionEntry], geom: Geometry, wp: WriteProtect) -> list[Placement]:
    """Place the partitions of one LUN, in order."""
    placements = []
    first = geom.primary_lbas
    till = 0
    for j, entry in enumerate(entries):
        is_last = j == len(entries) - 1
        if entry["size_in_kb"] == "0" and not is_last:
            raise ValueError(
                "partition '%s': size 0 is only allowed for the last partition of a LUN"
                % entry["label"]
            )
        size_bytes = max(math.ceil(float(entry["size_in_kb"])) * 1024, geom.sector)
        requested_kb = size_bytes // 1024
        size_kb: float = math.ceil(requested_kb * 1024 / geom.sector) * geom.sector / 1024

        if geom.performance_kb > 0 and geom.align:
            till = geom.till_boundary(first, geom.performance_kb)
            first += till
        if geom.write_protect_kb > 0:
            till = geom.till_boundary(first, geom.write_protect_kb)
        readonly = entry["readonly"] == "true"
        if readonly != (first <= wp.end):
            first += till

        grown = is_last and geom.grow_last
        if grown:
            size_kb = 0
        sectors = geom.kb_to_sectors(size_kb)
        if readonly:
            wp.cover(first, sectors)

        wipe = sectors + geom.kb_to_sectors(requested_kb) if is_last else sectors
        placements.append(Placement(entry, first, sectors, wipe, grown))
        first += sectors
    return placements


def validate(luns: list[list[PartitionEntry]]) -> None:
    """Reject layouts that cannot be addressed or flashed unambiguously.

    Names must be unique per LUN, and A/B partitions must come in pairs
    across the storage (boot LUNs split xbl_a / xbl_b by design).
    """
    errors = []
    bases_a: set[str] = set()
    bases_b: set[str] = set()
    for lun, entries in enumerate(luns):
        seen: dict[str, int] = {}
        for idx, entry in enumerate(entries):
            label = entry["label"]
            if label in seen:
                errors.append(
                    "lun=%d: duplicate partition name '%s' (positions %d and %d)"
                    % (lun, label, seen[label], idx)
                )
            else:
                seen[label] = idx
            if label.endswith("_a"):
                bases_a.add(label[:-2])
            elif label.endswith("_b"):
                bases_b.add(label[:-2])
    errors += ["'%s_a' present but '%s_b' missing" % (b, b) for b in sorted(bases_a - bases_b)]
    errors += ["'%s_b' present but '%s_a' missing" % (b, b) for b in sorted(bases_b - bases_a)]
    if errors:
        raise ValueError("partition validation failed:\n  " + "\n  ".join(errors))
