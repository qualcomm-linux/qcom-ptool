# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
``qcom-ptool show`` - print fully-resolved configurations.

A configuration composes a board with a flavor that may extend other
flavors and include shared fragments, so the effective partition layout
cannot be read from a single file. This subcommand takes the same
arguments as ``build``, resolves the composition and prints the result as
YAML, so reviewers and integrators can see exactly what will be emitted
without chasing it by hand. With ``-o`` it lists instead where ``build``
would write each storage and contents.xml.
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml  # type: ignore[import-untyped]

from qcom_ptool.board import Configuration
from qcom_ptool.build import add_target_arguments, check_target, resolve_target
from qcom_ptool.contents_yaml import contents_paths

NAME = "show"


def _document(config: Configuration) -> dict[str, object]:
    document = dict(config)
    if document.get("contents") is None:
        del document["contents"]
    return document


def output_paths(targets: list[tuple[str, Configuration]], outdir: str) -> list[str]:
    """What build writes: one directory per storage, then contents.xml."""
    paths = []
    for prefix, config in targets:
        base = os.path.join(outdir, prefix)
        paths += [os.path.join(base, s["id"], "") for s in config["storage"]]
        pair = contents_paths(config)
        if pair is not None:
            paths.append(os.path.join(base, pair[0]))
    return paths


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        NAME,
        help="print resolved configurations, or with -o the paths build writes",
        description="Print the resolved configurations as YAML, or with -o the "
        "paths build -o would write.",
    )
    add_target_arguments(parser, "list the directories and files build -o OUTDIR writes")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    check_target(args)
    try:
        targets = resolve_target(args)
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return 1

    if args.outdir is not None:
        print("\n".join(output_paths(targets, args.outdir)))
        return 0
    yaml.safe_dump_all(
        [_document(c) for _, c in targets], sys.stdout, sort_keys=False, default_flow_style=False
    )
    return 0
