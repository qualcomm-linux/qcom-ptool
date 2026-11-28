# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
GUID Partition Table images of one LUN (UEFI specification, chapter 5).

The primary image is the protective MBR, the GPT header and the
partition array; the backup image is the partition array followed by
the backup header. Values only known on the device (the disk size, so
the backup location and the size of a grown last partition) are written
for the smallest possible disk and fixed up by the patch XML at flash
time.
"""

from __future__ import annotations

import random
import struct
import uuid
import zlib
from dataclasses import dataclass

from qcom_ptool.layout import Geometry, Placement

ENTRY_SIZE = 128
NAME_BYTES = 72  # 36 UTF-16 code units

# GPT attribute bits (UEFI, plus the Qualcomm A/B slot bits of
# gpt-utils.h used by qbootctl).
ATTR_PRIORITY_SHIFT = 48
ATTR_ACTIVE = 1 << 50
ATTR_TRIES_SHIFT = 51
ATTR_SUCCESSFUL = 1 << 54
ATTR_UNBOOTABLE = 1 << 55
ATTR_READONLY = 1 << 60


@dataclass(frozen=True)
class Tables:
    """The GPT images of one LUN and the values the patches refer to."""

    primary: bytes
    backup: bytes
    empty: bytes
    num_entries: int


def _guid128(rng: random.Random) -> bytes:
    """A random unique GUID, drawn the way ptool always drew them."""
    return (rng.randint(0, 2**128) & (2**128 - 1)).to_bytes(16, "little")


def _attributes(entry: dict[str, str]) -> int:
    attributes = 0
    if entry.get("readonly") == "true":
        attributes |= ATTR_READONLY
    tries = int(entry.get("triesremaining", 0))
    if tries > 0:
        attributes |= tries << ATTR_TRIES_SHIFT
    priority = int(entry.get("priority", 0))
    if priority > 0:
        attributes |= priority << ATTR_PRIORITY_SHIFT
    if entry.get("active") == "true":
        attributes |= ATTR_ACTIVE
    if entry.get("successful") == "true":
        attributes |= ATTR_SUCCESSFUL
    if entry.get("unbootable") == "true":
        attributes |= ATTR_UNBOOTABLE
    return attributes


def _entry(placement: Placement, rng: random.Random) -> bytes:
    entry = placement.entry
    unique = (
        uuid.UUID(entry["uniqueguid"]).bytes_le if "uniqueguid" in entry else _guid128(rng)
    )
    name = entry["label"][:36].encode("utf-16-le")
    return (
        uuid.UUID(entry["type"]).bytes_le
        + unique
        + struct.pack("<QQQ", placement.first, placement.last, _attributes(entry))
        + name.ljust(NAME_BYTES, b"\0")
    )


def _header(
    my_lba: int, alternate_lba: int, first_usable: int, last_usable: int,
    disk_guid: bytes, entries_lba: int, num_entries: int, entries_crc: int,
) -> bytes:
    """The 92-byte GPT header, with its CRC filled in."""
    def pack(crc: int) -> bytes:
        return (
            b"EFI PART" + struct.pack("<IIII", 0x00010000, 92, crc, 0)
            + struct.pack("<QQQQ", my_lba, alternate_lba, first_usable, last_usable)
            + disk_guid
            + struct.pack("<QIII", entries_lba, num_entries, ENTRY_SIZE, entries_crc)
        )
    return pack(zlib.crc32(pack(0)))


def _protective_mbr(sector: int) -> bytes:
    mbr = bytearray(sector)
    mbr[0x1BE:0x1CE] = bytes([0x00, 0x00, 0x01, 0x00, 0xEE, 0xFF, 0xFF, 0xFF]) + struct.pack(
        "<II", 1, 0xFFFFFFFF
    )
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def _empty(primary: bytes, sector: int) -> bytes:
    """A valid GPT with one placeholder entry; flashing it forces EDL."""
    image = bytearray(len(primary))
    image[: sector + 16] = primary[: sector + 16]
    h = sector
    image[h + 16 : h + 20] = bytes([0xD6, 0x51, 0x5B, 0x44])  # header CRC
    image[h + 24] = 0x01  # my LBA
    image[h + 40] = 0x22  # first usable LBA
    image[h + 56 : h + 72] = bytes.fromhex("321b1098e2bbf24ba06e2bb33d000c20")  # disk GUID
    image[h + 72] = 0x02  # partition entries LBA
    image[h + 80 : h + 96] = bytes.fromhex("040000008000000004875d3c00000000")  # entries, size, CRC
    e = 2 * sector
    image[e + 16 : e + 32] = bytes.fromhex("6bca1fef3126c9955c1361eb3fcf87f9")  # unique GUID
    image[e + 32] = 0x22  # first LBA
    image[e + 40 : e + 42] = bytes([0x21, 0x02])  # last LBA
    image[e + 56 : e + 65] = "empty".encode("utf-16-le")[:9]
    return bytes(image)


def build_tables(placements: list[Placement], geom: Geometry, rng: random.Random) -> Tables:
    """Primary, backup and empty GPT images of one LUN."""
    sector = geom.sector
    array_bytes = (geom.primary_lbas - 2) * sector
    entries = b"".join(_entry(p, rng) for p in placements)
    if len(entries) > array_bytes:
        raise ValueError("%d partitions do not fit in one GPT" % len(placements))
    array = entries.ljust(array_bytes, b"\0")

    per_sector = sector // ENTRY_SIZE
    num_entries = -(-len(placements) // per_sector) * per_sector
    entries_crc = zlib.crc32(array[: num_entries * ENTRY_SIZE])

    last_usable = placements[-1].last
    backup_lba = last_usable + geom.backup_lbas
    disk_guid = _guid128(rng)

    header = _header(1, backup_lba, geom.primary_lbas, last_usable, disk_guid, 2,
                     num_entries, entries_crc)
    backup_header = _header(backup_lba, 1, geom.primary_lbas, last_usable, disk_guid,
                            backup_lba - geom.backup_lbas + 1, num_entries, entries_crc)

    primary = _protective_mbr(sector) + header.ljust(sector, b"\0") + array
    backup = array + backup_header.ljust(sector, b"\0")
    return Tables(primary, backup, _empty(primary, sector), num_entries)
