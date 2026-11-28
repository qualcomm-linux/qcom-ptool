# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Unit tests for the storage artifacts: layout rules, GPT images and the
firehose XML. The checksum manifest pins the bytes of every real board;
these tests pin the structure and the rules behind them.
"""

from __future__ import annotations

import random
import struct
import uuid
import xml.etree.ElementTree as ET
import zlib

import pytest

from qcom_ptool import build, cli
from qcom_ptool.artifacts import write_storage
from qcom_ptool.gpt import build_tables
from qcom_ptool.layout import Geometry, WriteProtect, place_lun, validate
from qcom_ptool.spec import DISK_PARAMS_DEFAULTS, PARTITION_ENTRY_DEFAULTS

EFI = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
DATA = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"


def part(label, kb, **extra):
    entry = dict(PARTITION_ENTRY_DEFAULTS, label=label, size_in_kb=str(kb), type=DATA)
    entry.update(extra)
    return entry


def geom(sector=512, wp=0, perf=4, align=True, grow=False):
    return Geometry(sector, wp, perf, align, grow)


def spec(luns, sector=512, wp=0, grow=True):
    disk = dict(DISK_PARAMS_DEFAULTS, type="ufs", size="1073741824")
    disk.update(
        SECTOR_SIZE_IN_BYTES=str(sector),
        WRITE_PROTECT_BOUNDARY_IN_KB=str(wp),
        GROW_LAST_PARTITION_TO_FILL_DISK="true" if grow else "false",
    )
    return {"disk": disk, "partitions": {str(i): lun for i, lun in enumerate(luns)}}


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sector,primary,backup", [(512, 34, 33), (4096, 6, 5)])
def test_gpt_sizes_follow_the_sector_size(sector, primary, backup):
    g = geom(sector)
    assert (g.primary_lbas, g.backup_lbas) == (primary, backup)


def test_partitions_are_aligned_to_the_performance_boundary():
    g = geom(perf=4)
    a, b = place_lun([part("a", 3, readonly="false"), part("b", 4, readonly="false")], g, WriteProtect(g))
    assert (a.first, a.sectors) == (40, 6)  # 34 rounded up to 4 KB = 8 sectors
    assert b.first == 48


def test_readonly_partitions_start_a_write_protect_region():
    g = geom(wp=64)  # 128 sectors
    wp = WriteProtect(g)
    ro, rw = place_lun([part("ro", 4), part("rw", 4, readonly="false")], g, wp)
    assert ro.first == 128  # moved to the next write-protect boundary
    assert rw.first == 256  # a writable partition leaves the protected region
    assert wp.end == 255


def test_write_protect_region_is_shared_by_the_luns_of_a_storage():
    g = geom(wp=64)
    wp = WriteProtect(g)
    place_lun([part("ro0", 4)], g, wp)
    (ro1,) = place_lun([part("ro1", 4)], g, wp)
    assert ro1.first == 40  # already covered by LUN 0's region: not moved


def test_grown_last_partition_has_no_size_of_its_own():
    g = geom(grow=True)
    *_, last = place_lun([part("a", 4), part("rootfs", 1024)], g, WriteProtect(g))
    assert last.grown and last.sectors == 0
    assert last.wipe_sectors == 2048


def test_size_zero_is_only_allowed_last():
    g = geom()
    with pytest.raises(ValueError, match="only allowed for the last"):
        place_lun([part("a", 0), part("b", 4)], g, WriteProtect(g))


@pytest.mark.parametrize(
    "luns,message",
    [
        ([[part("a", 4), part("a", 4)]], "duplicate partition name 'a'"),
        ([[part("boot_a", 4)]], "'boot_a' present but 'boot_b' missing"),
    ],
)
def test_validate_rejects_ambiguous_layouts(luns, message):
    with pytest.raises(ValueError, match=message):
        validate(luns)


def test_ab_pairs_may_span_luns():
    validate([[part("xbl_a", 4)], [part("xbl_b", 4)]])


# ---------------------------------------------------------------------------
# GPT images
# ---------------------------------------------------------------------------


def _tables(sector=512, entries=None):
    g = geom(sector)
    placements = place_lun(entries or [part("efi", 4, type=EFI), part("data", 8)], g, WriteProtect(g))
    return g, placements, build_tables(placements, g, random.Random(1))


@pytest.mark.parametrize("sector", [512, 4096])
def test_primary_and_backup_headers_are_consistent(sector):
    g, placements, t = _tables(sector)
    header = t.primary[sector : sector + 92]
    assert header[:8] == b"EFI PART"
    crc = struct.unpack_from("<I", header, 16)[0]
    assert zlib.crc32(header[:16] + b"\0" * 4 + header[20:]) == crc

    my_lba, alt_lba, first_usable, last_usable = struct.unpack_from("<QQQQ", header, 24)
    assert (my_lba, first_usable) == (1, g.primary_lbas)
    assert last_usable == placements[-1].last
    assert alt_lba == last_usable + g.backup_lbas

    entries_lba, num, size, entries_crc = struct.unpack_from("<QIII", header, 72)
    assert (entries_lba, size, num % (sector // 128)) == (2, 128, 0)
    assert zlib.crc32(t.primary[2 * sector : 2 * sector + num * 128]) == entries_crc

    backup = t.backup[-sector:][:92]
    assert struct.unpack_from("<QQ", backup, 24) == (alt_lba, 1)
    assert struct.unpack_from("<Q", backup, 72)[0] == alt_lba - g.backup_lbas + 1
    assert t.backup[: -sector] == t.primary[2 * sector :]
    assert len(t.primary) == g.primary_lbas * sector
    assert len(t.backup) == g.backup_lbas * sector


def test_protective_mbr():
    _, _, t = _tables()
    assert t.primary[510:512] == b"\x55\xaa"
    assert t.primary[0x1BE + 4] == 0xEE


def test_partition_entry_encoding():
    _, placements, t = _tables(entries=[part("efi", 4, type=EFI, active="true", priority="3")])
    entry = t.primary[1024:1152]
    assert entry[:16] == uuid.UUID(EFI).bytes_le
    first, last, attributes = struct.unpack_from("<QQQ", entry, 32)
    assert (first, last) == (placements[0].first, placements[0].last)
    assert attributes == (1 << 60) | (3 << 48) | (1 << 50)
    assert entry[56:62] == "efi".encode("utf-16-le")


def test_unique_guid_given_or_reproducibly_random():
    given = "11111111-2222-3333-4444-555555555555"
    _, _, t = _tables(entries=[part("a", 4, uniqueguid=given)])
    assert t.primary[1024 + 16 : 1024 + 32] == uuid.UUID(given).bytes_le
    assert _tables()[2] == _tables()[2]


# ---------------------------------------------------------------------------
# storage artifacts and console output
# ---------------------------------------------------------------------------


def test_write_storage_numbers_luns_by_position(tmp_path):
    layout = write_storage(spec([[part("a", 4)], [], [part("b", 4)]]), str(tmp_path))
    assert len(layout) == 2
    root = ET.parse(tmp_path / "rawprogram1.xml").getroot()
    labels = [p.get("label") for p in root.iter("program")]
    assert labels == ["b", "PrimaryGPT", "BackupGPT"]
    assert root.find("program[@label='BackupGPT']").get("start_sector") == "NUM_DISK_SECTORS-33."


def test_wipe_files_cover_the_declared_luns_only(tmp_path):
    write_storage(spec([[part("a", 4)], [part("b", 4)]]), str(tmp_path))
    assert sorted(p.name for p in tmp_path.glob("wipe_rawprogram_PHY*.xml")) == [
        "wipe_rawprogram_PHY0.xml",
        "wipe_rawprogram_PHY1.xml",
    ]


def test_grown_partition_is_patched(tmp_path):
    write_storage(spec([[part("a", 4), part("rootfs", 4)]], grow=True), str(tmp_path))
    whats = [p.get("what") for p in ET.parse(tmp_path / "patch0.xml").getroot().iter("patch")]
    assert "Update last partition 2 'rootfs' with actual size in Primary Header." in whats


def test_build_prints_a_summary_and_with_v_a_table(tmp_path, capsys):
    board = tmp_path / "board.yaml"
    board.write_text(
        "storage:\n"
        "  - id: ufs\n"
        "    type: ufs\n"
        "    size: 1073741824\n"
        "    sector-size: 4096\n"
        "    grow-last-partition: true\n"
        "    partitions:\n"
        '      - {name: efi, size: "512MB", type-guid: "%s", filename: efi.bin}\n'
        '      - {name: rootfs, size: "4KB", type-guid: "%s"}\n' % (EFI, DATA)
    )
    assert cli.main(["build", "-v", "-o", str(tmp_path / "out"), "-b", str(board)]) == 0
    out = capsys.readouterr().out
    assert "ufs: ufs, 2 partitions on 1 LUN" in out
    assert "512 MiB" in out and "rest of disk" in out and "efi.bin" in out


@pytest.mark.parametrize(
    "num,text", [(512, "512 B"), (1536, "1.5 KiB"), (64 << 20, "64 MiB"), (3 << 30, "3 GiB")]
)
def test_human_size(num, text):
    assert build.human_size(num) == text
