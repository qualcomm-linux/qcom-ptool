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

import os
import sys

import yaml  # type: ignore[import-untyped]

from qcom_ptool.board import Configuration
from qcom_ptool.build import check_target, resolve_target, target_parser
from qcom_ptool.contents_yaml import contents_paths


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


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    parser = target_parser(
        "qcom-ptool show",
        "Print the resolved configurations as YAML, or with -o the paths "
        "build would write.",
    )
    parser.set_defaults(outdir=None)
    args = parser.parse_args(argv[1:])
    check_target(parser, args)

    try:
        targets = resolve_target(args)
    except Exception as e:
        print("Error: ", e, file=sys.stderr)
        return 1

    if args.outdir is not None:
        print("\n".join(output_paths(targets, args.outdir)))
        return 0
    yaml.safe_dump_all(
        [_document(c) for _, c in targets], sys.stdout, sort_keys=False, default_flow_style=False
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
