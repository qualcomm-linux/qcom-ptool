# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Internal representation shared by all input loaders.

Every loader (``loaders/yaml.py``) and the board resolver reduce a layout
to one ``LoadedSpec`` per storage, which the artifact generators consume.

``DiskParams`` and ``PartitionEntry`` are type aliases for ``dict[str, str]``
rather than ``TypedDict``s; the XML emitter passes the dicts straight to
``ET.SubElement(..., attrib=...)`` which requires a plain ``dict[str, str]``
at runtime, and aliasing keeps that contract precise without TypedDict's
``total=False`` ``object`` widening. Migrating to dataclasses (with explicit
``to_attrib()`` methods) is a clean follow-up if stronger validation becomes
worth its blast radius.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TypedDict

# Disk parameters normalised into the keys ``ptool`` consumes.
# Expected keys: type, size, SECTOR_SIZE_IN_BYTES, WRITE_PROTECT_BOUNDARY_IN_KB,
# GROW_LAST_PARTITION_TO_FILL_DISK, ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY,
# PERFORMANCE_BOUNDARY_IN_KB. See DISK_PARAMS_DEFAULTS for the canonical set.
DiskParams = dict[str, str]

# One partition normalised for the XML attribute set.
# Expected keys: label, size_in_kb, type, bootable, readonly, filename, sparse,
# active, successful, unbootable.
# See PARTITION_ENTRY_DEFAULTS for the canonical set.
PartitionEntry = dict[str, str]

# Mapping of physical partition / LUN id (kept as a string, as emitted in
# the XML) to its partition entries.
PartitionsByLun = dict[str, list[PartitionEntry]]


# Defaults every loader starts from. Kept as module-level constants so loaders can
# ``.copy()`` from them rather than rebuilding the structure each call.
# ``OrderedDict`` is preserved here because the XML emitter relies on its
# iteration order to produce stable output across Python versions.
DISK_PARAMS_DEFAULTS: DiskParams = OrderedDict(
    {
        "type": "",
        "size": "",
        "SECTOR_SIZE_IN_BYTES": "512",
        "WRITE_PROTECT_BOUNDARY_IN_KB": "65536",
        "GROW_LAST_PARTITION_TO_FILL_DISK": "false",
        "ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY": "true",
        "PERFORMANCE_BOUNDARY_IN_KB": "4",
    }
)


PARTITION_ENTRY_DEFAULTS: PartitionEntry = {
    "label": "",
    "size_in_kb": "",
    "type": "00000000-0000-0000-0000-000000000000",
    "bootable": "false",
    "readonly": "true",
    "filename": "",
    "sparse": "false",
    "active": "false",
    "successful": "false",
    "unbootable": "false",
}


class LoadedSpec(TypedDict):
    """What every loader returns from ``load(path)``."""

    disk: DiskParams
    partitions: PartitionsByLun
