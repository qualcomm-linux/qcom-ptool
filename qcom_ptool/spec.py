# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Internal representation shared by all input loaders.

Every loader (``loaders/yaml.py``) returns a ``LoadedSpec`` so the rest of
``gen_partition.py`` is independent of the source format.

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
# active, successful, unbootable. Optional keys: priority, triesremaining,
# attributes, uniqueguid, gptprio_priority, gptprio_tries_left,
# gptprio_successful.
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


# GPT attribute bits 48-63 are partition-type specific, and two A/B schemes
# use them differently:
#   - qbootctl (priority, triesremaining, active, successful, unbootable):
#     priority 48-49, active 50, tries 51-53, successful 54, unbootable 55
#   - GRUB's gptprio module (gptprio.next), using the ChromeOS layout:
#     priority 48-51, tries left 52-55, successful 56
# The gptprio fields are prefixed so they can't be mistaken for the qbootctl
# ones, and a partition may only use one of the two schemes.
QBOOTCTL_KEYS = ("priority", "triesremaining", "active", "successful", "unbootable")
GPTPRIO_KEYS = ("gptprio_priority", "gptprio_tries_left", "gptprio_successful")


class AttributeSchemeError(ValueError):
    """A partition mixes qbootctl and gptprio A/B attribute fields."""


def _sets_bits(value: str) -> bool:
    return value not in ("", "0", "false")


def check_ab_scheme(entry: PartitionEntry) -> None:
    """Reject a partition whose qbootctl and gptprio fields both set bits."""
    qbootctl = [k for k in QBOOTCTL_KEYS if _sets_bits(entry.get(k, ""))]
    gptprio = [k for k in GPTPRIO_KEYS if _sets_bits(entry.get(k, ""))]
    if qbootctl and gptprio:
        raise AttributeSchemeError(
            "partition '%s' mixes qbootctl fields (%s) with gptprio fields (%s); "
            "both use GPT attribute bits 48-56, pick one scheme"
            % (entry.get("label", ""), ", ".join(qbootctl), ", ".join(gptprio))
        )


class LoadedSpec(TypedDict):
    """What every loader returns from ``load(path)``."""

    disk: DiskParams
    partitions: PartitionsByLun
