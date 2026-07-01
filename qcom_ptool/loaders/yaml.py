# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Loader for the structured YAML partition source (single storage).

A YAML document describes one ``disk`` mapping and a ``partitions`` list; this
module validates it against ``qcom_ptool/schema/partitions.schema.json`` and
normalises it into the exact same :class:`qcom_ptool.spec.LoadedSpec` the
``.conf`` loader produces, so both formats emit byte-identical XML.

Normalisation mirrors ``loaders/conf.py`` field for field: the disk dict is
built by copying ``DISK_PARAMS_DEFAULTS`` and each partition by copying
``PARTITION_ENTRY_DEFAULTS``, so key order (and therefore XML attribute order)
matches the legacy loader. ``partition_size_in_kb`` and the attribute-bit
decoding are reused / replicated identically.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from typing import Any

import jsonschema
import yaml  # type: ignore[import-untyped]

from qcom_ptool.loaders.conf import partition_size_in_kb
from qcom_ptool.spec import (
    DISK_PARAMS_DEFAULTS,
    PARTITION_ENTRY_DEFAULTS,
    DiskParams,
    LoadedSpec,
    PartitionEntry,
    PartitionsByLun,
)

_SCHEMA_PACKAGE = "qcom_ptool.schema"
_SCHEMA_RESOURCE = "partitions.schema.json"


class YamlParseError(ValueError):
    """Raised when a YAML partition source is malformed or fails validation."""


def _bool_str(value: Any) -> str:
    """Render a YAML scalar as the lowercase "true"/"false" the .conf loader
    stores. ``str(True)`` would yield "True", which the emitter would then
    write verbatim and break parity, so booleans are normalised explicitly."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load_schema() -> dict[str, Any]:
    """Return the packaged partition JSON Schema as a dict."""
    text = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_RESOURCE).read_text(
        encoding="utf-8"
    )
    schema: dict[str, Any] = json.loads(text)
    return schema


def _disk_from_node(node: Mapping[str, Any]) -> DiskParams:
    """Normalise the ``disk`` mapping into the canonical disk dict.

    Starts from ``DISK_PARAMS_DEFAULTS`` and overrides only the keys present,
    exactly like ``conf.disk_options``, so unset fields keep their defaults and
    the key order is identical.
    """
    disk = DISK_PARAMS_DEFAULTS.copy()
    disk["type"] = str(node["type"])
    disk["size"] = str(node["size"])
    if "sector-size" in node:
        disk["SECTOR_SIZE_IN_BYTES"] = str(node["sector-size"])
    if "write-protect-boundary" in node:
        disk["WRITE_PROTECT_BOUNDARY_IN_KB"] = str(node["write-protect-boundary"])
    if node.get("grow-last-partition"):
        disk["GROW_LAST_PARTITION_TO_FILL_DISK"] = "true"
    if "align-partitions" in node:
        disk["ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY"] = "true"
        disk["PERFORMANCE_BOUNDARY_IN_KB"] = str(int(node["align-partitions"]) // 1024)
    return disk


def _partition_from_node(
    node: Mapping[str, Any],
    image_map: Mapping[str, str],
) -> tuple[str, PartitionEntry]:
    """Normalise one partition mapping into ``(phys_part, entry)``.

    Mirrors ``conf.partition_options``: same defaults, same attribute-bit
    decoding, and the image-map override applied last so it always wins.
    """
    entry: PartitionEntry = PARTITION_ENTRY_DEFAULTS.copy()
    phys_part = "0"
    if "lun" in node:
        phys_part = str(node["lun"])
    elif "phys-part" in node:
        phys_part = str(node["phys-part"])
    entry["label"] = str(node["name"])
    entry["size_in_kb"] = str(partition_size_in_kb(str(node["size"])))
    entry["type"] = str(node["type-guid"])
    if "attributes" in node:
        attribute_bits = int(str(node["attributes"]), 16)
        entry["bootable"] = "true" if attribute_bits & (1 << 2) else "false"
        entry["readonly"] = "true" if attribute_bits & (1 << 60) else "false"
    if "filename" in node:
        entry["filename"] = str(node["filename"])
    if "sparse" in node:
        entry["sparse"] = _bool_str(node["sparse"])
    if entry["label"] in image_map:
        entry["filename"] = image_map[entry["label"]]
    return phys_part, entry


def load(path: str, image_map: Mapping[str, str] | None = None) -> LoadedSpec:
    """Public entry point: read ``path`` and return a normalised ``LoadedSpec``."""
    if image_map is None:
        image_map = {}
    with open(path) as f:
        document = yaml.safe_load(f)
    if not isinstance(document, Mapping):
        raise YamlParseError(
            "%s: expected a top-level mapping, got %s" % (path, type(document).__name__)
        )
    try:
        jsonschema.validate(document, load_schema())
    except jsonschema.exceptions.ValidationError as exc:
        raise YamlParseError("%s: schema validation failed: %s" % (path, exc.message)) from exc

    disk = _disk_from_node(document["disk"])
    partitions: PartitionsByLun = {}
    for node in document.get("partitions", []):
        phys_part, entry = _partition_from_node(node, image_map)
        partitions.setdefault(phys_part, []).append(entry)
    return {"disk": disk, "partitions": partitions}
