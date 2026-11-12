# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
``qcom-ptool show`` - print a board's fully-resolved spec.

Derived boards and heavy ``includes:`` use make the effective partition
layout impossible to read from a single file. This subcommand resolves all
``extends`` / ``includes`` / variant overlays and prints the result as YAML,
so reviewers and integrators can see exactly what will be emitted without
chasing the composition chain by hand.
"""

from __future__ import annotations

import getopt
import os
import sys
from typing import NoReturn

import yaml  # type: ignore[import-untyped]

from qcom_ptool.board import resolve_board_flavors


def usage() -> NoReturn:
    print(
        "\n\tUsage:\n"
        "\t  %s --board <board.yaml> [--hlos <name>] "
        "[--boot-fw <name>] [--root <dir>]\n"
        "\t  %s --outputs <board.yaml> [<board.yaml> ...]\n"
        "\n\t--outputs prints one line per board for build systems:\n"
        "\t  <board>:<flavor-dir>/<storage>[:<flavor-dir>/<storage>...]\n" % (sys.argv[0], sys.argv[0])
    )
    sys.exit(1)


def _print_outputs(paths: list[str], root: str | None) -> int:
    """One line per board: '<board>:<flavor-dir>/<storage>...'."""
    status = 0
    for path in paths:
        try:
            flavors = resolve_board_flavors(path, root=root)
        except Exception as e:
            print("Error: %s" % e, file=sys.stderr)
            status = 1
            continue
        base = os.path.splitext(os.path.basename(path))[0]
        cells = [base] + [
            "%s/%s" % (flavor["name"], storage.get("id", ""))
            for flavor in flavors
            for storage in flavor["storage"]
        ]
        print(":".join(cells))
    return status


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    board_file: str | None = None
    root: str | None = None
    hlos: str | None = None
    boot_fw: str | None = None
    outputs = False

    try:
        opts, rem = getopt.getopt(
            argv[1:], "", ["board=", "hlos=", "boot-fw=", "root=", "outputs"]
        )
        for opt, arg in opts:
            if opt == "--board":
                board_file = arg
            elif opt == "--hlos":
                hlos = arg
            elif opt == "--boot-fw":
                boot_fw = arg
            elif opt == "--root":
                root = arg
            elif opt == "--outputs":
                outputs = True
    except Exception as argerr:
        print(str(argerr))
        usage()

    if outputs:
        paths = ([board_file] if board_file else []) + rem
        if not paths:
            usage()
        return _print_outputs(paths, root)

    if board_file is None:
        usage()

    try:
        flavors = resolve_board_flavors(board_file, root=root, hlos=hlos, boot_fw=boot_fw)
    except Exception as e:
        print("Error: ", e)
        return 1

    if len(flavors) == 1 and flavors[0]["layout"] is None:
        board = {"platform": flavors[0]["platform"], "storage": flavors[0]["storage"]}
        yaml.safe_dump(board, sys.stdout, sort_keys=False, default_flow_style=False)
    else:
        document = {
            "platform": flavors[0]["platform"],
            "flavors": [dict(flavor) for flavor in flavors],
        }
        yaml.safe_dump(document, sys.stdout, sort_keys=False, default_flow_style=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
