# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
Build a contents template tree from a flavor's YAML metadata.

A flavor's ``contents:`` block carries everything a contents.xml.in
template used to: the product identity (product name, chip, chipids,
additional chipids, hlos/meta/build type), the product flavors, and the
ordered entries of the ``common`` build - device programmers and literal
download/partition/patch files.

The placeholder entries that
:func:`qcom_ptool.gen_contents.UpdateMetaData` replaces with the layout's
artifacts are injected implicitly, right after the build boilerplate:
UpdateMetaData removes them and appends the generated entries at the end
of the build, so their position in the source template never influenced
the output - only the relative order of the real entries does, which the
``common`` list preserves. The result is byte-identical contents.xml.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from xml.etree import ElementTree as ET

# The placeholder entries UpdateMetaData() looks for, verbatim from the
# templates: (child tag, file_path flavor, text) triples.
_PLACEHOLDERS: dict[str, tuple[str, list[tuple[str, str | None, str]]]] = {
    "downloads": (
        "download_file",
        [
            ("fastboot_complete", None, "{partition_name}"),
            ("file_name", None, "{image_name}"),
            ("file_path", None, "."),
        ],
    ),
    "partitions": (
        "partition_file",
        [
            ("storage_type", None, "{storage_type}"),
            ("file_name", None, "{partition_file_name}"),
            ("file_path", "default", "."),
        ],
    ),
    "patches": (
        "partition_patch_file",
        [
            ("storage_type", None, "{storage_type}"),
            ("file_name", None, "{partition_patch_file_name}"),
            ("file_path", "default", "."),
        ],
    ),
}

_ENTRY_TAGS = {
    "device-programmer": "device_programmer",
    "download": "download_file",
    "partition": "partition_file",
    "patch": "partition_patch_file",
}


class ContentsError(ValueError):
    """Raised when a contents block cannot be turned into a template."""


def _add_text(parent: ET.Element, tag: str, text: str) -> None:
    ET.SubElement(parent, tag).text = text


def _add_placeholder(parent: ET.Element, kind: str) -> None:
    tag, children = _PLACEHOLDERS[kind]
    element = ET.SubElement(parent, tag)
    for child_tag, flavor, text in children:
        child = ET.SubElement(element, child_tag)
        if flavor is not None:
            child.set("flavor", flavor)
        child.text = text


def _add_file_entry(parent: ET.Element, tag: str, entry: Mapping[str, Any]) -> None:
    attrib = {key: str(value) for key, value in (entry.get("attributes") or {}).items()}
    element = ET.SubElement(parent, tag, attrib)
    _add_text(element, "file_name", entry["file"])
    file_path = ET.SubElement(element, "file_path")
    if entry.get("path-flavor"):
        file_path.set("flavor", str(entry["path-flavor"]))
    file_path.text = str(entry.get("path", "."))


def _add_build(parent: ET.Element, name: str, chipset: str, image_dir: str) -> ET.Element:
    build = ET.SubElement(parent, "build")
    _add_text(build, "name", name)
    _add_text(build, "role", name)
    _add_text(build, "chipset", chipset)
    _add_text(build, "windows_root_path", ".\\")
    _add_text(build, "linux_root_path", "./")
    _add_text(build, "image_dir", image_dir)
    return build


def build_contents_root(meta: Mapping[str, Any], storage: str) -> ET.Element:
    """Build the template tree one contents.xml.in used to describe."""
    root = ET.Element("contents")

    flavors = ET.SubElement(root, "product_flavors", {"cmm_pf_var": "PRODUCT_FLAVORS"})
    pf_list: list[Mapping[str, Any]] = [
        {"name": "default", "components": meta.get("default-components", ["common", "apps"])}
    ]
    pf_list.extend(meta.get("product-flavors", []))
    for pf in pf_list:
        element = ET.SubElement(flavors, "pf")
        _add_text(element, "name", pf["name"])
        for component in pf["components"]:
            comp = ET.SubElement(element, "component")
            _add_text(comp, "name", component)
            _add_text(comp, "flavor", pf["name"])

    chip = meta["chip"]
    info = ET.SubElement(root, "product_info")
    _add_text(info, "product_name", meta["product-name"])
    if meta.get("hlos-type") is not None:
        _add_text(info, "hlos_type", meta["hlos-type"])
    chipids: list[Mapping[str, Any]] = [{"flavor": "default", "storage": storage, "flash-phase": 1}]
    chipids.extend(meta.get("chipids", []))
    for chipid in chipids:
        element = ET.SubElement(
            info,
            "chipid",
            {
                "flavor": chipid["flavor"],
                "storage_type": str(chipid["storage"]),
                "flash_phase": str(chipid["flash-phase"]),
            },
        )
        element.text = chipid.get("chip", chip)
    if meta.get("additional-chipids"):
        _add_text(info, "additional_chipid", ",".join(meta["additional-chipids"]))
    _add_text(info, "meta_type", meta.get("meta-type", "FULL_STACK"))
    _add_text(info, "build_type", meta.get("build-type", "K2L"))

    builds = ET.SubElement(root, "builds_flat")
    chipset = meta.get("chipset", chip)
    _add_build(builds, "apps", chipset, meta.get("apps-image-dir", "apps_proc"))
    common = _add_build(builds, "common", chipset, "common")
    # The implicit placeholders: first of their tag, so UpdateMetaData
    # replaces them (and never a literal entry below).
    for kind in ("downloads", "partitions", "patches"):
        _add_placeholder(common, kind)
    for entry in meta.get("common", []):
        if len(entry) != 1:
            raise ContentsError("common entries carry exactly one key: %r" % entry)
        kind, value = next(iter(entry.items()))
        if kind not in _ENTRY_TAGS:
            raise ContentsError("unknown common entry %r" % kind)
        _add_file_entry(common, _ENTRY_TAGS[kind], value)
    return root


def default_storage(flavor: Mapping[str, Any]) -> str:
    """The storage a flavor's contents is built from.

    'location' names it when it is a storage id; otherwise ('/' or unset)
    it is the flavor's first storage.
    """
    ids = [str(s["id"]) for s in flavor["storage"]]
    location = (flavor.get("contents") or {}).get("location")
    if location is None or location == "/":
        return ids[0]
    if location not in ids:
        raise ContentsError(
            "%s: contents location %r is neither '/' nor one of its storages %s" % (flavor["name"], location, ids)
        )
    return str(location)


def contents_paths(flavor: Mapping[str, Any]) -> tuple[str, str] | None:
    """One flavor's (contents.xml, partitions.xml) paths under the output tree.

    contents.xml lands in the default storage's directory, or at the
    flavor directory with 'location: /'. Returns ``None`` when the flavor
    defines no contents.
    """
    meta = flavor.get("contents")
    if not meta:
        return None
    name = flavor["name"]
    storage = default_storage(flavor)
    partitions = "%s/%s/partitions.xml" % (name, storage)
    if meta.get("location") == "/":
        return "%s/contents.xml" % name, partitions
    return "%s/%s/contents.xml" % (name, storage), partitions
