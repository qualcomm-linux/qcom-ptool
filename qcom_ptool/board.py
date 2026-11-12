# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Multi-storage board model and composition resolver.

A board file declares a ``platform`` and a list of ``storage`` devices, each
with its own partitions. Three composition mechanisms layer on top:

* board-level ``extends:`` - inherit a single base board and override by
  stable identifier (storage ``id``, partition ``name``);
* ``luns:`` / ``phys-parts:`` groups - group a storage's partitions by LUN
  (UFS) or physical partition (eMMC) instead of placing each entry
  individually; ``grow: false`` appends the zero-GUID ``last_parti``
  absorber so the group's partitions keep their declared sizes when the
  storage grows its last partition;
* ``include:`` directives - splice shared partition fragments from
  ``_common/`` into a partition list, in place between inline partitions
  or via the storage-level ``includes:`` prefix list;
* variant overlays (``--hlos`` / ``--boot-fw``) - applied last, merged by the
  same identifiers.

Groups are flattened into the plain ``partitions:`` list as each document
is read, so every merge below operates on flat lists keyed by
``(lun, name)`` regardless of which form a file uses.

Resolution order is: base board -> derived board -> storage includes ->
variant overlays. Merges are deep and field-by-field; entries are matched by
``id`` (storage) or ``name`` (partition), and anything unmatched is appended
in file order. There is no partition deletion in v1.

The resolver operates on raw YAML dicts. Each fully-resolved storage is then
validated against the strict single-storage ``partitions.schema.json`` and
reduced to a :class:`qcom_ptool.spec.LoadedSpec` through the very same
normalisation helpers the YAML loader uses, so a resolved board emits XML
byte-identical to an equivalent hand-written single-storage file.
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

# Storage keys that describe the disk geometry (everything except id / includes
# / partitions). Used to reduce a resolved storage into the single-storage
# document shape that partitions.schema.json validates.
_DISK_KEYS = (
    "type",
    "size",
    "sector-size",
    "write-protect-boundary",
    "grow-last-partition",
    "align-partitions",
)


class BoardResolveError(ValueError):
    """Raised when a board file cannot be loaded, composed or validated."""


class ResolvedBoard(TypedDict):
    """A board with every extends/includes/variant applied."""

    platform: dict[str, Any]
    storage: list[dict[str, Any]]


class ResolvedFlavor(TypedDict):
    """One flashable configuration of a board, fully resolved."""

    name: str
    layout: str | None
    platform: dict[str, Any]
    storage: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Schema / file helpers
# ---------------------------------------------------------------------------


def _load_schema(name: str) -> dict[str, Any]:
    text = resources.files(_SCHEMA_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def _canonicalize_refs(node: Any, base_dir: str, root: str) -> None:
    """Rewrite include / layout / extends references to root-relative form.

    A reference that resolves relative to its own file's directory wins over
    the platforms root, so a layout under ``platforms/flavors/`` can say
    ``_common/x.yaml`` and a fragment can name a sibling directly. Everything
    downstream keeps operating on root-relative paths.
    """

    def canon(ref: str) -> str:
        local = os.path.join(base_dir, ref)
        if os.path.isfile(local):
            return os.path.relpath(local, root)
        return ref

    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("include", "layout", "extends") and isinstance(value, str):
                node[key] = canon(value)
            elif key == "includes" and isinstance(value, list):
                node[key] = [canon(i) if isinstance(i, str) else i for i in value]
            else:
                _canonicalize_refs(value, base_dir, root)
    elif isinstance(node, list):
        for item in node:
            _canonicalize_refs(item, base_dir, root)


def _read_mapping(path: str, schema: str, root: str | None = None) -> dict[str, Any]:
    """Load ``path`` as YAML, validate against ``schema`` and return a copy.

    With ``root``, references in the document are canonicalized to
    root-relative form, resolving against the document's own directory first.
    """
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
    if root is not None:
        _canonicalize_refs(result, os.path.dirname(os.path.abspath(path)), root)
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
    """Merge one storage ``overlay`` into ``base`` (matched by id upstream)."""
    for key, value in overlay.items():
        if key == "id":
            continue
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


def _merge_storage_list(base: list[dict[str, Any]], overlay: Sequence[Mapping[str, Any]]) -> None:
    """Merge ``overlay`` storage entries into ``base`` by ``id``."""
    index = {s["id"]: s for s in base if "id" in s}
    for entry in overlay:
        sid = entry.get("id")
        target = index.get(sid)
        if target is not None:
            _merge_storage(target, entry)
        else:
            new_entry = copy.deepcopy(dict(entry))
            base.append(new_entry)
            if sid is not None:
                index[sid] = new_entry


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
                % (storage.get("id", "?"), " and ".join("'%s'" % k for k in present))
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
# Board-level extends
# ---------------------------------------------------------------------------


def _load_board_with_extends(path: str, root: str, chain: tuple[str, ...]) -> dict[str, Any]:
    """Load a board file and fold its single base (if any) underneath it."""
    real = os.path.realpath(path)
    if real in chain:
        raise BoardResolveError("extends cycle detected at %s" % path)
    board = _read_mapping(path, "board.schema.json", root=root)
    _normalize_luns(board)
    base_ref = board.pop("extends", None)
    if base_ref is None:
        return board
    base_path = os.path.join(root, base_ref)
    base = _load_board_with_extends(base_path, root, (*chain, real))
    _merge_storage_list(base.setdefault("storage", []), board.get("storage", []))
    if "platform" in board:
        base["platform"] = board["platform"]
    return base


# ---------------------------------------------------------------------------
# Storage-level includes
# ---------------------------------------------------------------------------


def _fragment_partitions(path: str, root: str, chain: tuple[str, ...]) -> list[dict[str, Any]]:
    """Resolve a ``_common/`` fragment (transitively) into a partition list."""
    real = os.path.realpath(path)
    if real in chain:
        raise BoardResolveError("includes cycle detected at %s" % path)
    fragment = _read_mapping(path, "include.schema.json", root=root)
    partitions: list[dict[str, Any]] = []
    for inc in fragment.get("includes", []):
        inc_parts = _fragment_partitions(os.path.join(root, inc), root, (*chain, real))
        _merge_partitions(partitions, inc_parts)
    _merge_partitions(partitions, fragment.get("partitions", []))
    return partitions


def _expand_includes(storage: dict[str, Any], root: str) -> None:
    """Replace a storage's ``includes:`` + ``partitions:`` with one flat list.

    ``partitions:`` items are walked in order; an ``include:`` directive is
    expanded in place, so fragments and inline partitions interleave freely
    and the list order is the layout order. A ``lun`` / ``phys-part``
    stamped on a directive by LUN-group flattening is forwarded to every
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
        parts = _fragment_partitions(os.path.join(root, item["include"]), root, ())
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


def _variant_path(root: str, axis: str, name: str) -> str:
    return os.path.join(root, "variants", axis, name + ".yaml")


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


def _default_root(path: str) -> str:
    parent = os.path.dirname(os.path.abspath(path))
    return os.path.dirname(parent) if os.path.basename(parent) == "boards" else parent


def _apply_variants_and_validate(
    storages: list[dict[str, Any]],
    root: str,
    hlos: str | None,
    boot_fw: str | None,
) -> None:
    """Apply variant overlays, then strictly validate every storage."""
    for axis, name in (("hlos", hlos), ("boot-fw", boot_fw)):
        if name is None:
            continue
        overlay = _read_mapping(_variant_path(root, axis, name), "board.schema.json", root=root)
        _normalize_luns(overlay)
        _merge_storage_list(storages, overlay.get("storage", []))

    for storage in storages:
        _validate_resolved_storage(storage)


def resolve_board(
    path: str,
    root: str | None = None,
    hlos: str | None = None,
    boot_fw: str | None = None,
) -> ResolvedBoard:
    """Resolve ``path`` into a fully-composed :class:`ResolvedBoard`.

    ``root`` is the platforms directory that ``extends:`` / ``includes:`` paths
    and variant names resolve against; it defaults to the parent of the board
    file's directory when that directory is ``boards/``, else the board file's
    own directory.
    """
    if root is None:
        root = _default_root(path)

    board = _load_board_with_extends(path, root, ())
    if board.get("flavors"):
        raise BoardResolveError(
            "%s: board defines flavors; resolve with resolve_board_flavors" % path
        )
    storages = board.get("storage", [])
    if not storages:
        raise BoardResolveError("%s: board declares no storage" % path)

    for storage in storages:
        _expand_includes(storage, root)

    _apply_variants_and_validate(storages, root, hlos, boot_fw)

    return {"platform": board.get("platform", {}), "storage": storages}


def resolve_board_flavors(
    path: str,
    root: str | None = None,
    hlos: str | None = None,
    boot_fw: str | None = None,
) -> list[ResolvedFlavor]:
    """Resolve ``path`` into its flashable flavors.

    A board without ``flavors:`` is a single flavor: its own storage list,
    named after the board file. A board with ``flavors:`` resolves each entry
    by loading the referenced layout (a complete flashable configuration under
    ``platforms/flavors/``), merging the board-level storage geometry into the
    layout's storages (matched by ``id``, only for storages the flavor
    declares), then merging the flavor's own in-place overrides on top -
    the same deep-merge the other composition mechanisms use. A flavor may
    instead define its storage entirely inline (no ``layout``), so a layout
    only one board uses never has to leave the board file. A flavor's
    ``name`` is the output directory under platforms/ and defaults to the
    board file's name, so a board's flavors may share it only when their
    storage ids do not collide.
    """
    if root is None:
        root = _default_root(path)
    default_name = os.path.splitext(os.path.basename(path))[0]

    board = _load_board_with_extends(path, root, ())
    platform = board.get("platform", {})
    flavors = board.get("flavors")

    if not flavors:
        single = resolve_board(path, root=root, hlos=hlos, boot_fw=boot_fw)
        return [
            {
                "name": default_name,
                "layout": None,
                "platform": single["platform"],
                "storage": single["storage"],
            }
        ]

    geometry = board.get("storage", [])
    resolved: list[ResolvedFlavor] = []
    outputs: set[tuple[str, Any]] = set()
    for flavor in flavors:
        ref = flavor.get("layout")
        storages: list[dict[str, Any]] = []
        if ref is not None:
            layout = _read_mapping(os.path.join(root, ref), "board.schema.json", root=root)
            _normalize_luns(layout)
            storages = copy.deepcopy(layout.get("storage", []))
            if not storages:
                raise BoardResolveError("%s: layout declares no storage" % ref)
        overlay = {"storage": copy.deepcopy(list(flavor.get("storage", [])))}
        _normalize_luns(overlay)
        if not storages and not overlay["storage"]:
            raise BoardResolveError(
                "%s: flavor defines neither a layout nor storage" % path
            )
        ids = {s.get("id") for s in storages}
        ids |= {s.get("id") for s in overlay["storage"]}
        _merge_storage_list(storages, [s for s in geometry if s.get("id") in ids])
        _merge_storage_list(storages, overlay["storage"])

        for storage in storages:
            _expand_includes(storage, root)
        _apply_variants_and_validate(storages, root, hlos, boot_fw)

        name = flavor.get("name", default_name)
        for storage in storages:
            key = (name, storage.get("id"))
            if key in outputs:
                raise BoardResolveError(
                    "%s: flavors collide on output %s/%s" % (path, key[0], key[1])
                )
            outputs.add(key)
        resolved.append(
            {"name": name, "layout": ref, "platform": platform, "storage": storages}
        )
    return resolved


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


def board_to_specs(
    board: ResolvedBoard | ResolvedFlavor,
    image_map: Mapping[str, str] | None = None,
) -> list[tuple[str, LoadedSpec]]:
    """Reduce a resolved board or flavor to ``[(storage_id, LoadedSpec), ...]``."""
    return [
        (storage.get("id", ""), storage_to_loaded_spec(storage, image_map))
        for storage in board["storage"]
    ]
