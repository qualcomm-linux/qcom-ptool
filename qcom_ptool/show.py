# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
``qcom-ptool show`` - print fully-resolved configurations.

A configuration composes a board with a flavor that may extend other
flavors and include shared fragments, so the effective partition layout
cannot be read from a single file. This subcommand resolves the
composition and prints the result as YAML, so reviewers and integrators
can see exactly what will be emitted without chasing it by hand.

``--outputs`` prints instead one ``<platform>:<name>/<storage-id>...``
line per platform file, and ``--contents`` one
``<platform>:<contents.xml>^<partitions.xml>...`` line per platform file
with contents metadata - the build indexes the Makefile reads.
"""

from __future__ import annotations

import getopt
import os
import sys
from typing import NoReturn

import yaml  # type: ignore[import-untyped]

from qcom_ptool.board import Configuration, resolve, resolve_platform


def usage() -> NoReturn:
    print(
        "\n\tUsage: %s --platform <platform.yaml>\n"
        "\t       %s --board <board.yaml> [--flavor <flavor.yaml>]\n"
        "\t       %s --outputs | --contents <platform.yaml>...\n"
        "\n\tA board takes no flavor when it is self-contained.\n"
        % (sys.argv[0], sys.argv[0], sys.argv[0])
    )
    sys.exit(1)


def _print_outputs(paths: list[str]) -> int:
    for path in paths:
        try:
            configs = resolve_platform(path)
        except Exception as e:
            print("Error: ", e, file=sys.stderr)
            return 1
        outputs = [
            "%s/%s" % (c["name"], s["id"]) for c in configs for s in c["storage"]
        ]
        print(":".join([os.path.splitext(os.path.basename(path))[0], *outputs]))
    return 0


def _print_contents(paths: list[str]) -> int:
    from qcom_ptool.contents_yaml import contents_paths

    for path in paths:
        try:
            cells = []
            for config in resolve_platform(path):
                pair = contents_paths(config)
                if pair is not None:
                    cells.append("%s/%s^%s/%s" % (config["name"], pair[0], config["name"], pair[1]))
        except Exception as e:
            print("Error: ", e, file=sys.stderr)
            return 1
        if cells:
            print(":".join([os.path.splitext(os.path.basename(path))[0], *cells]))
    return 0


def _document(config: Configuration) -> dict[str, object]:
    document = dict(config)
    if document.get("contents") is None:
        del document["contents"]
    return document


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    platform_file: str | None = None
    board_file: str | None = None
    flavor_file: str | None = None
    outputs = False
    contents = False

    try:
        opts, rem = getopt.getopt(
            argv[1:], "", ["platform=", "board=", "flavor=", "outputs", "contents"]
        )
        for opt, arg in opts:
            if opt == "--platform":
                platform_file = arg
            elif opt == "--board":
                board_file = arg
            elif opt == "--flavor":
                flavor_file = arg
            elif opt == "--outputs":
                outputs = True
            elif opt == "--contents":
                contents = True
    except Exception as argerr:
        print(str(argerr))
        usage()

    if outputs or contents:
        if outputs and contents:
            usage()
        if platform_file is not None or board_file is not None or not rem:
            usage()
        return _print_contents(rem) if contents else _print_outputs(rem)

    if rem or (platform_file is None) == (board_file is None):
        usage()
    if flavor_file is not None and board_file is None:
        usage()

    try:
        configs: list[Configuration]
        if platform_file is not None:
            configs = resolve_platform(platform_file)
        else:
            assert board_file is not None
            configs = [resolve(board_file, flavor_file)]
    except Exception as e:
        print("Error: ", e)
        return 1

    yaml.safe_dump_all(
        [_document(c) for c in configs], sys.stdout, sort_keys=False, default_flow_style=False
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
