# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Board / flavor / platform model and its composition resolver.

Three kinds of file describe flashable configurations:

* a **board** describes hardware: its storage devices (``id``, ``type``
  and geometry), no partitions, and the SoC part of the contents
  metadata (chip identity and boot-chain firmware);
* a **flavor** is a board-agnostic partition layout, keyed by storage
  ``type`` (e.g. a UFS layout with its LUNs). A flavor may ``extends:`` a
  single base flavor and add or override partitions;
* a **platform** lists the configurations of one board: each flavor
  entry is one, built into ``<name>/<storage-id>/``. It also carries the
  HLOS and flashing part of the contents metadata, including where
  contents.xml is written (``location``); an entry may replace it. The
  configuration's contents is the board's with the platform's laid over
  it: keys override, ``common`` entries are appended.

Each flavor storage lands on the board storage of the same type, which
contributes the geometry and the ``id``. A platform is only a shortcut:
``resolve(board, flavor)`` composes the same configuration from explicit
paths.

A board may instead be **self-contained**: its storages carry their own
partition layout (the keys a flavor storage has) and its ``contents:``
may be complete, so a single file describes one whole configuration,
e.g. an out-of-tree board. ``resolve(board)`` composes it without a
flavor.

Inside a flavor, partitions may be grouped by LUN (``luns:``, UFS) or by
physical partition (``phys-parts:``, eMMC); ``grow: false`` on a group
appends the zero-GUID ``last_parti`` absorber so the group keeps its
declared sizes when the storage grows its last partition. Shared
fragments are spliced in through ``includes:`` / in-place ``include:``
directives. Groups are flattened into the plain ``partitions:`` list as
each document is read, so every merge operates on flat lists keyed by
``(lun, name)``; merges are deep and field-by-field, unmatched entries
are appended in file order and nothing is ever deleted.

Every reference (``board``, ``flavor(s)``, ``extends``, ``include(s)``)
is relative to the file that makes it, or else to the first include
directory that has it; ``contents:`` holds none. Each
fully-resolved storage is validated against the strict single-storage ``partitions.schema.json``
and reduced to a :class:`qcom_ptool.spec.LoadedSpec` through the same
helpers the YAML loader uses, so it emits byte-identical XML.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import Any, TypedDict

import jsonschema
import yaml  # type: ignore[import-untyped]

from qcom_ptool.loaders.yaml import _disk_from_node, _partition_from_node
from qcom_ptool.spec import LoadedSpec, PartitionsByLun

_SCHEMA_PACKAGE = "qcom_ptool.schema"

# Storage keys that describe the disk (everything except id / includes /
# partitions). Used to reduce a resolved storage into the single-storage
# document shape that partitions.schema.json validates.
_DISK_KEYS = (
    "type",
    "size",
    "sector-size",
    "write-protect-boundary",
    "grow-last-partition",
    "align-partitions",
)

# Keys holding references to other files, resolved relative to the file
# that makes them.
_REF_KEYS = ("board", "flavor", "extends", "include")
_REF_LIST_KEYS = ("flavors", "includes")

# Storage keys that describe a partition layout: a flavor storage's keys,
# which a self-contained board storage may carry as well.
_LAYOUT_KEYS = ("grow-last-partition", "includes", "partitions", "luns", "phys-parts")

# Contents keys a board (that is not self-contained) may carry: the SoC
# identity and the boot-chain firmware entries.
_SOC_CONTENTS_KEYS = ("chip", "chipset", "additional-chipids", "common")


class BoardResolveError(ValueError):
    """Raised when a board, flavor or platform cannot be loaded or composed."""


class Configuration(TypedDict):
    """One flashable configuration: one entry per flashed storage."""

    name: str
    storage: list[dict[str, Any]]
    contents: dict[str, Any] | None


# ---------------------------------------------------------------------------
# Schema / file helpers
# ---------------------------------------------------------------------------


def _load_schema(name: str) -> dict[str, Any]:
    text = resources.files(_SCHEMA_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def _absolutize_refs(node: Any, base_dir: str, include_dirs: Sequence[str]) -> None:
    """Rewrite every file reference in ``node`` to an absolute path.

    A reference resolves against ``base_dir`` (its file's directory), or
    else against the first of ``include_dirs`` that has it.
    """

    def resolve(ref: str) -> str:
        local = os.path.normpath(os.path.join(base_dir, ref))
        if not os.path.exists(local):
            for directory in include_dirs:
                candidate = os.path.join(directory, ref)
                if os.path.exists(candidate):
                    return os.path.normpath(os.path.abspath(candidate))
        return local

    if isinstance(node, dict):
        for key, value in node.items():
            if key == "contents":
                # Metadata, not references: e.g. a chipid's 'flavor' names
                # a product flavor, not a file.
                continue
            if key in _REF_KEYS and isinstance(value, str):
                node[key] = resolve(value)
            elif key in _REF_LIST_KEYS and isinstance(value, list):
                node[key] = [resolve(i) if isinstance(i, str) else i for i in value]
                _absolutize_refs(node[key], base_dir, include_dirs)
            else:
                _absolutize_refs(value, base_dir, include_dirs)
    elif isinstance(node, list):
        for item in node:
            _absolutize_refs(item, base_dir, include_dirs)


def _read_mapping(path: str, schema: str, include_dirs: Sequence[str] = ()) -> dict[str, Any]:
    """Load ``path`` as YAML, validate it against ``schema`` and return a copy
    with every file reference made absolute."""
    try:
        with open(path) as f:
            document = yaml.safe_load(f)
    except OSError as exc:
        raise BoardResolveError("cannot read %s: %s" % (path, exc)) from exc
    if not isinstance(document, Mapping):
        raise BoardResolveError(
            "%s: expected a top-level mapping, got %s" % (path, type(document).__name__)
        )
    try:
        jsonschema.validate(document, _load_schema(schema))
    except jsonschema.exceptions.ValidationError as exc:
        raise BoardResolveError("%s: schema validation failed: %s" % (path, exc.message)) from exc
    result = copy.deepcopy(dict(document))
    _absolutize_refs(result, os.path.dirname(os.path.abspath(path)), include_dirs)
    return result


# ---------------------------------------------------------------------------
# Deep-merge primitives (by stable identifier)
# ---------------------------------------------------------------------------


def _merge_partitions(base: list[dict[str, Any]], overlay: Sequence[Mapping[str, Any]]) -> None:
    """Merge ``overlay`` partitions into ``base`` by ``(lun, name)``.

    Names repeat across LUNs on multi-LUN storages, so identity is the
    (lun, name) pair. A matched partition is deep-merged field-by-field in
    place (so an override can set only ``size`` and inherit the rest); a new
    partition is appended in overlay order. Nothing is ever moved or removed.
    """

    def key(p: Mapping[str, Any]) -> tuple[Any, Any]:
        return (p.get("lun", p.get("phys-part")), p.get("name"))

    index = {key(p): p for p in base if "name" in p}
    for entry in overlay:
        target = index.get(key(entry))
        if target is not None:
            target.update(copy.deepcopy(dict(entry)))
        else:
            new_entry = copy.deepcopy(dict(entry))
            base.append(new_entry)
            if entry.get("name") is not None:
                index[key(entry)] = new_entry


def _merge_storage(base: dict[str, Any], overlay: Mapping[str, Any]) -> None:
    """Merge one flavor storage ``overlay`` into ``base`` (matched upstream)."""
    for key, value in overlay.items():
        if key == "partitions":
            base.setdefault("partitions", [])
            _merge_partitions(base["partitions"], value)
        elif key == "includes":
            merged = base.setdefault("includes", [])
            for inc in value:
                if inc not in merged:
                    merged.append(inc)
        else:
            base[key] = copy.deepcopy(value)


# ---------------------------------------------------------------------------
# LUN groups
# ---------------------------------------------------------------------------

# Appended to a group with ``grow: false``: a zero-GUID placeholder that
# absorbs the grow-last-partition patching, keeping the real partitions at
# their declared sizes.
_LAST_PARTI = {
    "name": "last_parti",
    "size": "0KB",
    "type-guid": "00000000-0000-0000-0000-000000000000",
}


def _normalize_luns(document: dict[str, Any]) -> None:
    """Flatten each storage's ``luns:`` / ``phys-parts:`` groups.

    ``luns:`` (groups keyed by ``lun``, for UFS) and ``phys-parts:`` (groups
    keyed by ``phys-part``, for eMMC) are the same mechanism under the name
    matching the storage. Groups flatten in listed order into the plain
    ``partitions:`` list; the group's placement is stamped on every item
    (partition or include directive) that does not place itself.
    ``grow: false`` appends the ``last_parti`` absorber after the group.
    Runs on every document as it is read, before any merging.
    """
    for storage in document.get("storage", []):
        present = [k for k in ("partitions", "luns", "phys-parts") if k in storage]
        if len(present) > 1:
            raise BoardResolveError(
                "storage %r: %s are mutually exclusive"
                % (storage.get("type", "?"), " and ".join("'%s'" % k for k in present))
            )
        groups = storage.pop("luns", None) or storage.pop("phys-parts", None)
        if groups is None:
            continue
        flat: list[dict[str, Any]] = []
        for group in groups:
            placement = {k: group[k] for k in ("lun", "phys-part") if k in group}
            for item in group.get("partitions", []):
                entry = copy.deepcopy(dict(item))
                if "lun" not in entry and "phys-part" not in entry:
                    entry.update(placement)
                flat.append(entry)
            if group.get("grow") is False:
                flat.append({**copy.deepcopy(_LAST_PARTI), **placement})
        storage["partitions"] = flat


# ---------------------------------------------------------------------------
# Flavors
# ---------------------------------------------------------------------------


def _load_flavor(
    path: str, include_dirs: Sequence[str], chain: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Load a flavor and fold its single base (if any) underneath it.

    Storages merge by ``type``; partitions by ``(lun, name)``.
    """
    real = os.path.realpath(path)
    if real in chain:
        raise BoardResolveError("extends cycle detected at %s" % path)
    flavor = _read_mapping(path, "flavor.schema.json", include_dirs)
    _normalize_luns(flavor)
    types = [s["type"] for s in flavor["storage"]]
    if len(types) != len(set(types)):
        raise BoardResolveError("%s: a storage type appears more than once" % path)
    base_ref = flavor.pop("extends", None)
    if base_ref is None:
        return flavor
    base = _load_flavor(base_ref, include_dirs, (*chain, real))
    index = {s["type"]: s for s in base["storage"]}
    for storage in flavor["storage"]:
        target = index.get(storage["type"])
        if target is None:
            base["storage"].append(storage)
        else:
            _merge_storage(target, storage)
    return base


# ---------------------------------------------------------------------------
# Includes
# ---------------------------------------------------------------------------


def _fragment_partitions(
    path: str, include_dirs: Sequence[str], chain: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Resolve a shared fragment (transitively) into a partition list."""
    real = os.path.realpath(path)
    if real in chain:
        raise BoardResolveError("includes cycle detected at %s" % path)
    fragment = _read_mapping(path, "include.schema.json", include_dirs)
    partitions: list[dict[str, Any]] = []
    for inc in fragment.get("includes", []):
        _merge_partitions(partitions, _fragment_partitions(inc, include_dirs, (*chain, real)))
    _merge_partitions(partitions, fragment.get("partitions", []))
    return partitions


def _expand_includes(storage: dict[str, Any], include_dirs: Sequence[str]) -> None:
    """Replace a storage's ``includes:`` + ``partitions:`` with one flat list.

    ``partitions:`` items are walked in order; an ``include:`` directive is
    expanded in place, so fragments and inline partitions interleave freely
    and the list order is the layout order. A ``lun`` / ``phys-part``
    stamped on a directive by group flattening is forwarded to every
    fragment entry that does not place itself, so one lun-less fragment can
    serve several storages (or several LUNs of one storage). The
    storage-level ``includes:`` list is sugar for directives ahead of
    ``partitions:``; identical directives (e.g. repeated through
    ``extends``) expand once.
    """
    items: list[dict[str, Any]] = [{"include": inc} for inc in storage.pop("includes", [])]
    items.extend(storage.get("partitions", []))
    expanded: list[dict[str, Any]] = []
    seen: list[dict[str, Any]] = []
    for item in items:
        if "include" not in item:
            _merge_partitions(expanded, [item])
            continue
        if item in seen:
            continue
        seen.append(item)
        parts = _fragment_partitions(item["include"], include_dirs, ())
        placement = {k: item[k] for k in ("lun", "phys-part") if k in item}
        if placement:
            for part in parts:
                if "lun" not in part and "phys-part" not in part:
                    part.update(placement)
        _merge_partitions(expanded, parts)
    storage["partitions"] = expanded


# ---------------------------------------------------------------------------
# Public resolution
# ---------------------------------------------------------------------------


def _validate_resolved_storage(storage: Mapping[str, Any]) -> None:
    """Validate a fully-resolved storage against the strict single-storage schema."""
    disk = {k: storage[k] for k in _DISK_KEYS if k in storage}
    document = {"disk": disk, "partitions": storage.get("partitions", [])}
    try:
        jsonschema.validate(document, _load_schema("partitions.schema.json"))
    except jsonschema.exceptions.ValidationError as exc:
        raise BoardResolveError(
            "storage %r resolved to an invalid spec: %s"
            % (storage.get("id", "?"), exc.message)
        ) from exc


def _validate_contents(meta: Any, where: str) -> dict[str, Any] | None:
    """Validate one complete ``contents:`` block against contents.schema.json."""
    if meta is None:
        return None
    try:
        jsonschema.validate(meta, _load_schema("contents.schema.json"))
    except jsonschema.exceptions.ValidationError as exc:
        raise BoardResolveError("%s: invalid contents: %s" % (where, exc.message)) from exc
    return dict(meta)


def _load_board(path: str, include_dirs: Sequence[str]) -> dict[str, Any]:
    board = _read_mapping(path, "board.schema.json", include_dirs)
    ids = [s["id"] for s in board["storage"]]
    if len(ids) != len(set(ids)):
        raise BoardResolveError("%s: storage ids must be unique" % path)
    for storage in board["storage"]:
        layout = {k: storage[k] for k in ("type", *_LAYOUT_KEYS) if k in storage}
        if len(layout) > 1:
            try:
                jsonschema.validate({"storage": [layout]}, _load_schema("flavor.schema.json"))
            except jsonschema.exceptions.ValidationError as exc:
                raise BoardResolveError(
                    "%s: storage %r: invalid layout: %s" % (path, storage["id"], exc.message)
                ) from exc
    meta = board.get("contents")
    if _is_self_contained(board):
        board["contents"] = _validate_contents(meta, path)
    elif meta is not None:
        extra = sorted(set(meta) - set(_SOC_CONTENTS_KEYS))
        if extra:
            raise BoardResolveError(
                "%s: board contents carries only %s; %s belong in the platform"
                % (path, ", ".join(_SOC_CONTENTS_KEYS), ", ".join(extra))
            )
    return board


def _is_self_contained(board: Mapping[str, Any]) -> bool:
    return any(k in s for s in board["storage"] for k in _LAYOUT_KEYS)


def _merge_contents(
    board: Mapping[str, Any] | None, platform: Mapping[str, Any], where: str
) -> dict[str, Any] | None:
    """Lay a platform's contents over the board's SoC part and validate it.

    Platform keys override the board's; ``common`` entries are appended
    after the board's (firmware first, then the flashing entries).
    """
    merged = copy.deepcopy(dict(board or {}))
    for key, value in platform.items():
        if key == "common":
            merged["common"] = merged.get("common", []) + copy.deepcopy(value)
        else:
            merged[key] = copy.deepcopy(value)
    return _validate_contents(merged, where)


def _resolve_self_contained(
    board_file: str, board: dict[str, Any], name: str, include_dirs: Sequence[str]
) -> Configuration:
    """Compose a self-contained board: each storage with a layout is flashed."""
    _normalize_luns(board)
    storages: list[dict[str, Any]] = []
    for storage in board["storage"]:
        if not any(k in storage for k in _LAYOUT_KEYS):
            continue
        _expand_includes(storage, include_dirs)
        _validate_resolved_storage(storage)
        storages.append(storage)
    if not storages:
        raise BoardResolveError(
            "%s: no storage carries partitions; pass a flavor to flash onto it" % board_file
        )
    return {"name": name, "storage": storages, "contents": board["contents"]}


def resolve(
    board_file: str,
    flavor_file: str | None = None,
    name: str | None = None,
    include_dirs: Sequence[str] = (),
) -> Configuration:
    """Compose one flashable configuration: ``flavor_file`` on ``board_file``.

    Every flavor storage lands on the board storage of the same type,
    which must be unique on the board; board storages the flavor does not
    target are not flashed. Without ``flavor_file`` the board must be
    self-contained and is composed on its own. ``name`` defaults to the
    board file's name. References inside the files that resolve neither
    relative to their file nor in any of ``include_dirs`` fail.
    """
    if name is None:
        name = os.path.splitext(os.path.basename(board_file))[0]
    board = _load_board(board_file, include_dirs)
    if flavor_file is None:
        return _resolve_self_contained(board_file, board, name, include_dirs)
    if _is_self_contained(board):
        raise BoardResolveError(
            "%s: a self-contained board (with partitions) takes no flavor" % board_file
        )

    by_type: dict[str, list[dict[str, Any]]] = {}
    for storage in board["storage"]:
        by_type.setdefault(storage["type"], []).append(storage)
    flavor = _load_flavor(os.path.abspath(flavor_file), include_dirs)

    storages: list[dict[str, Any]] = []
    for layout in flavor["storage"]:
        candidates = by_type.get(layout["type"], [])
        if len(candidates) != 1:
            raise BoardResolveError(
                "%s: %s %s storage for flavor %s"
                % (
                    board_file,
                    "no" if not candidates else "more than one",
                    layout["type"],
                    flavor_file,
                )
            )
        storage = copy.deepcopy(candidates[0])
        storage.update({k: v for k, v in layout.items() if k != "type"})
        _expand_includes(storage, include_dirs)
        _validate_resolved_storage(storage)
        storages.append(storage)

    # A board's contents is only its SoC part: complete only with a platform's.
    return {"name": name, "storage": storages, "contents": None}


def resolve_platform(path: str, include_dirs: Sequence[str] = ()) -> list[Configuration]:
    """Resolve every configuration of a platform file.

    Each flavor entry is one configuration, named by its ``name`` or the
    platform file's name. Two configurations may share a name only when
    their storage ids differ, as both build into ``<name>/<storage-id>/``.
    A configuration's contents metadata is the entry's own ``contents``, or
    else the platform's, laid over the board's SoC part; without either it
    has none.
    """
    platform = _read_mapping(path, "platform.schema.json", include_dirs)
    default = os.path.splitext(os.path.basename(path))[0]
    soc = _load_board(platform["board"], include_dirs).get("contents")
    configs = []
    for entry in platform["flavors"]:
        if isinstance(entry, str):
            entry = {"flavor": entry}
        config = resolve(
            platform["board"], entry["flavor"], entry.get("name", default), include_dirs
        )
        meta = entry.get("contents", platform.get("contents"))
        if meta is not None:
            where = "%s (%s)" % (path, config["name"])
            config["contents"] = _merge_contents(soc, meta, where)
        configs.append(config)
    outputs: set[tuple[str, str]] = set()
    for config in configs:
        for storage in config["storage"]:
            key = (config["name"], storage["id"])
            if key in outputs:
                raise BoardResolveError(
                    "%s: configurations collide on output %s/%s" % (path, *key)
                )
            outputs.add(key)
    return configs


def is_platform_file(path: str) -> bool:
    """Whether ``path`` is a platform file (as opposed to a board)."""
    try:
        with open(path) as f:
            document = yaml.safe_load(f)
    except OSError as exc:
        raise BoardResolveError("cannot read %s: %s" % (path, exc)) from exc
    return isinstance(document, Mapping) and "board" in document


def resolve_file(path: str) -> list[Configuration]:
    """Resolve a platform file, or a self-contained board, into its configurations."""
    if is_platform_file(path):
        return resolve_platform(path)
    return [resolve(path)]


# ---------------------------------------------------------------------------
# Reduction to the emitter's LoadedSpec
# ---------------------------------------------------------------------------


def storage_to_loaded_spec(
    storage: Mapping[str, Any],
    image_map: Mapping[str, str] | None = None,
) -> LoadedSpec:
    """Reduce one resolved storage to a LoadedSpec via the YAML loader helpers."""
    if image_map is None:
        image_map = {}
    disk = _disk_from_node(storage)
    partitions: PartitionsByLun = {}
    for node in storage.get("partitions", []):
        phys_part, entry = _partition_from_node(node, image_map)
        partitions.setdefault(phys_part, []).append(entry)
    return {"disk": disk, "partitions": partitions}


def config_to_specs(
    config: Configuration,
    image_map: Mapping[str, str] | None = None,
) -> list[tuple[str, LoadedSpec]]:
    """Reduce a configuration to ``[(storage_id, LoadedSpec), ...]``."""
    return [
        (storage["id"], storage_to_loaded_spec(storage, image_map))
        for storage in config["storage"]
    ]
