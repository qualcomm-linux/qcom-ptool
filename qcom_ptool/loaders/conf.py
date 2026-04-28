# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Loader for the legacy ``--disk`` / ``--partition`` line-format files under
``platforms/``.

A ``.conf`` file is an unstructured stream of comment lines, blank lines,
exactly one ``--disk`` line, and any number of ``--partition`` lines. Each
significant line is itself a getopt-style option list. This module parses
both layers and returns a :class:`qcom_ptool.spec.LoadedSpec`.

The parsing helpers are kept individually addressable so the unit tests
under ``tests/unit/`` can characterise each layer in isolation.
"""

from __future__ import annotations

import getopt
import re
from collections.abc import Mapping

from qcom_ptool.spec import (
    DISK_PARAMS_DEFAULTS,
    PARTITION_ENTRY_DEFAULTS,
    DiskParams,
    LoadedSpec,
    PartitionEntry,
    PartitionsByLun,
)


class ConfParseError(ValueError):
    """Raised when a ``.conf`` file cannot be parsed."""


# ---------------------------------------------------------------------------
# Size string parsing
# ---------------------------------------------------------------------------


def partition_size_in_kb(size: str) -> int:
    """Convert a size string ("1024", "1KB", "2MB", "1GB") to KB.

    Bare integers are interpreted as bytes and divided by 1024. Strings with a
    K/M/G suffix (any case, with optional 'B') return the kilobyte equivalent.
    Anything else raises ``ValueError``; callers may catch and reformat.
    """
    if not re.search("[a-zA-Z]+", size):
        return int(size) // 1024
    m = re.search("([0-9]+)(?=[Kk][Bb]?)", size)
    if m:
        return int(m.group(0))
    m = re.search("([0-9]+)(?=[Mm][Bb]?)", size)
    if m:
        return int(m.group(0)) * 1024
    m = re.search("([0-9]+)(?=[Gg][Bb]?)", size)
    if m:
        return int(m.group(0)) * 1024 * 1024
    raise ValueError("Unrecognized size format: '%s'" % size)


# ---------------------------------------------------------------------------
# Option-list -> normalised dict
# ---------------------------------------------------------------------------


def disk_options(argv: list[tuple[str, str]]) -> DiskParams:
    """Translate parsed ``--disk`` options into the canonical disk dict."""
    disk = DISK_PARAMS_DEFAULTS.copy()
    for opt, arg in argv:
        if opt == "--type":
            disk["type"] = arg
        elif opt == "--size":
            disk["size"] = arg
        elif opt == "--sector-size-in-bytes":
            disk["SECTOR_SIZE_IN_BYTES"] = arg
        elif opt == "--write-protect-boundary":
            disk["WRITE_PROTECT_BOUNDARY_IN_KB"] = arg
        elif opt == "--grow-last-partition":
            disk["GROW_LAST_PARTITION_TO_FILL_DISK"] = "true"
        elif opt == "--align-partitions":
            disk["ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY"] = "true"
            disk["PERFORMANCE_BOUNDARY_IN_KB"] = str(int(arg) // 1024)
    return disk


def partition_options(
    argv: list[tuple[str, str]],
    image_map: Mapping[str, str] | None = None,
) -> tuple[str, PartitionEntry]:
    """Translate parsed ``--partition`` options into ``(phys_part, entry)``.

    ``image_map`` (if provided) overrides the entry's ``filename`` when the
    partition name matches a key. The override is applied after all options
    have been processed, so it always wins over an explicit ``--filename``.
    """
    if image_map is None:
        image_map = {}
    entry: PartitionEntry = PARTITION_ENTRY_DEFAULTS.copy()
    phys_part: str = "0"
    for opt, arg in argv:
        if opt in ("--lun", "--phys-part"):
            phys_part = arg
        elif opt == "--name":
            entry["label"] = arg
        elif opt == "--size":
            entry["size_in_kb"] = str(partition_size_in_kb(arg))
        elif opt == "--type-guid":
            entry["type"] = arg
        elif opt == "--attributes":
            attribute_bits = int(arg, 16)
            entry["bootable"] = "true" if attribute_bits & (1 << 2) else "false"
            entry["readonly"] = "true" if attribute_bits & (1 << 60) else "false"
        elif opt == "--filename":
            entry["filename"] = arg
        elif opt == "--sparse":
            entry["sparse"] = arg
    if entry["label"] in image_map:
        entry["filename"] = image_map[entry["label"]]
    return phys_part, entry


# ---------------------------------------------------------------------------
# Line-level parsing
# ---------------------------------------------------------------------------


_DISK_LONG_OPTS = [
    "type=",
    "size=",
    "sector-size-in-bytes=",
    "write-protect-boundary=",
    "grow-last-partition",
    "align-partitions=",
]

_PARTITION_LONG_OPTS = [
    "lun=",
    "phys-part=",
    "name=",
    "size=",
    "type-guid=",
    "filename=",
    "attributes=",
    "sparse=",
]


def parse_disk_line(line: str) -> DiskParams | None:
    """Parse a single ``--disk ...`` line; return None if the line isn't one."""
    opts_list = line.split(" ")
    if not opts_list or opts_list[0] != "--disk":
        return None
    options, _rem = getopt.gnu_getopt(opts_list[1:], "", _DISK_LONG_OPTS)
    return disk_options(options)


def parse_partition_lines(
    lines: list[str],
    image_map: Mapping[str, str] | None = None,
) -> PartitionsByLun:
    """Parse a list of ``--partition ...`` lines, grouped by LUN/phys-part."""
    if image_map is None:
        image_map = {}
    partitions: PartitionsByLun = {}
    for line in lines:
        opts_list = line.split(" ")
        if not opts_list or opts_list[0] != "--partition":
            continue
        options, _rem = getopt.gnu_getopt(opts_list[1:], "", _PARTITION_LONG_OPTS)
        phys_part, entry = partition_options(options, image_map)
        partitions.setdefault(phys_part, []).append(entry)
    return partitions


# ---------------------------------------------------------------------------
# File-level parsing
# ---------------------------------------------------------------------------


def read_conf(path: str) -> tuple[str, list[str]]:
    """Read ``path`` and return ``(disk_line, [partition_lines])``.

    Comments (``#``-prefixed) and blank lines are skipped. Multiple ``--disk``
    lines are an error. Lines that aren't ``--disk`` or ``--partition`` are
    printed as "Ignoring ..." for parity with the original behaviour.
    """
    disk_line: str | None = None
    partition_lines: list[str] = []
    with open(path) as f:
        for raw in f:
            if re.search(r"^\s*#", raw) or re.search(r"^\s*$", raw):
                continue
            line = raw.strip()
            if line.startswith("--disk"):
                if disk_line is not None:
                    raise ConfParseError(
                        "%s contains more than one --disk entries:\n%s\n%s"
                        % (path, disk_line, line)
                    )
                disk_line = line
            elif line.startswith("--partition"):
                partition_lines.append(line)
            else:
                print("Ignoring %s" % line)
    if disk_line is None:
        raise ConfParseError("%s contains no --disk entry" % path)
    return disk_line, partition_lines


def load(path: str, image_map: Mapping[str, str] | None = None) -> LoadedSpec:
    """Public entry point: read ``path`` and return a normalised ``LoadedSpec``."""
    disk_line, partition_lines = read_conf(path)
    disk = parse_disk_line(disk_line)
    if disk is None:
        # Should be unreachable: read_conf guarantees disk_line starts with --disk.
        raise ConfParseError("%s: failed to parse --disk line" % path)
    partitions = parse_partition_lines(partition_lines, image_map)
    return {"disk": disk, "partitions": partitions}
