# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
``qcom-ptool build`` - a flashable configuration in one command.

Emits the GPT and flashing artifacts of every flashed storage, then
contents.xml for a configuration with contents metadata. A platform file
builds each of its configurations into ``<outdir>/<name>/<storage-id>/``;
a board with a flavor builds one configuration into
``<outdir>/<storage-id>/``, so a custom configuration needs no file of its
own: ``build -b <board.yaml> -f <flavor.yaml>``. A self-contained board
(e.g. out of tree) builds the same way without ``-f``. ``-I <dir>`` adds
include directories: references inside the files that do not resolve
relative to their own file are looked up there, in order, so files kept
out of tree can reuse the in-tree boards, flavors and fragments.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from qcom_ptool.artifacts import write_storage
from qcom_ptool.board import Configuration, config_to_specs, resolve, resolve_platform
from qcom_ptool.gen_contents import generate_configuration
from qcom_ptool.layout import Placement, geometry
from qcom_ptool.spec import LoadedSpec


def target_parser(prog: str, description: str) -> argparse.ArgumentParser:
    """Arguments shared by build and show: what to resolve, and where."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("platform", nargs="?", help="platform file (platforms/<platform>.yaml)")
    parser.add_argument("-b", dest="board", metavar="BOARD", help="board file, instead of a platform")
    parser.add_argument("-f", dest="flavor", metavar="FLAVOR", action="append",
                        help="flavor to put on the board (omit for a self-contained board)")
    parser.add_argument("-o", dest="outdir", metavar="OUTDIR", default=".",
                        help="output directory (default: .)")
    parser.add_argument("-I", dest="include_dirs", metavar="DIR", action="append", default=[],
                        help="look up references that do not resolve relative to their "
                        "own file in DIR; repeatable, searched in order")
    return parser


def check_target(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Exactly one of a platform or -b, and at most one -f, only with -b."""
    if (args.platform is None) == (args.board is None):
        parser.error("pass a platform file, or -b <board> [-f <flavor>]")
    if args.flavor and args.board is None:
        parser.error("-f needs -b")
    if args.flavor and len(args.flavor) > 1:
        parser.error("-f takes one flavor")


def resolve_target(args: argparse.Namespace) -> list[tuple[str, Configuration]]:
    """Resolve the target into (output prefix, configuration) pairs.

    A platform's configurations build under ``<name>/``; a board's single
    configuration builds directly into the output directory.
    """
    if args.platform is not None:
        return [(c["name"], c) for c in resolve_platform(args.platform, args.include_dirs)]
    flavor = args.flavor[0] if args.flavor else None
    return [("", resolve(args.board, flavor, include_dirs=args.include_dirs))]


def human_size(num_bytes: int) -> str:
    """1536 -> '1.5 KiB'; whole numbers drop the decimal."""
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            break
        size /= 1024
    return ("%d %s" if size == int(size) else "%.1f %s") % (size, unit)


def summary(storage_dir: str, spec: LoadedSpec, layout: list[list[Placement]]) -> str:
    count = sum(len(lun) for lun in layout)
    return "%s: %s, %d partition%s on %d LUN%s" % (
        storage_dir, spec["disk"]["type"], count, "" if count == 1 else "s",
        len(layout), "" if len(layout) == 1 else "s",
    )


def partition_table(spec: LoadedSpec, layout: list[list[Placement]]) -> str:
    """The placed partitions, one aligned row each."""
    sector = geometry(spec["disk"]).sector
    rows = [("LUN", "START", "SIZE", "NAME", "IMAGE")]
    for lun, placements in enumerate(layout):
        for p in placements:
            size = "rest of disk" if p.grown else human_size(p.sectors * sector)
            rows.append((str(lun), str(p.first), size, p.entry["label"], p.entry.get("filename", "")))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    return "\n".join(
        "  " + "  ".join(cell.ljust(w) for cell, w in zip(row, widths)) + "  " + row[4]
        for row in rows
    ).rstrip()


def parse_image_map(text: str | None) -> dict[str, str]:
    """``name=file,name=file`` -> {name: file}."""
    image_map: dict[str, str] = {}
    for item in (text or "").split(","):
        name, sep, filename = item.partition("=")
        if sep:
            image_map[name] = filename
    return image_map


def build(
    targets: Sequence[tuple[str, Configuration]],
    outdir: str,
    image_map: Mapping[str, str] | None = None,
    build_id: str = "",
    verbose: bool = False,
) -> int:
    """Emit the GPT artifacts and contents.xml of every configuration."""
    try:
        specs = [
            (os.path.join(outdir, prefix, sid), spec)
            for prefix, config in targets
            for sid, spec in config_to_specs(config, image_map=image_map)
        ]
        for storage_dir, spec in specs:
            layout = write_storage(spec, storage_dir)
            print(summary(storage_dir, spec, layout))
            if verbose:
                print(partition_table(spec, layout))
        for prefix, config in targets:
            path = generate_configuration(
                config, os.path.join(outdir, prefix), build_id, image_map
            )
            if path is not None:
                print(path)
    except (OSError, ValueError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    parser = target_parser(
        "qcom-ptool build",
        "Write the GPT and flashing artifacts of every flashed storage - a "
        "platform's to OUTDIR/<name>/<storage-id>/, a board's to "
        "OUTDIR/<storage-id>/ - plus contents.xml for configurations with "
        "contents metadata.",
    )
    parser.add_argument("-m", dest="image_map", metavar="NAME=FILE,...",
                        help="override the image file of the named partitions")
    parser.add_argument("--build-id", default="", help="build_id recorded in contents.xml")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print the partition table of every storage")
    args = parser.parse_args(argv[1:])
    check_target(parser, args)

    try:
        targets = resolve_target(args)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return build(targets, args.outdir, parse_image_map(args.image_map), args.build_id, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
