# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
``qcom-ptool`` - the command line, and its only entry point.

Every subcommand module exposes ``register(subparsers)``, which declares
its arguments and binds them to its ``run(args) -> int``. The exception
is ``msp``, a legacy script that reads ``sys.argv`` itself: its arguments
are passed through unparsed.
"""

from __future__ import annotations

import argparse
import runpy
import sys

from qcom_ptool import __version__, build, gen_udev_rules, show

COMMANDS = (build, show, gen_udev_rules)
LEGACY = "msp"
SUBCOMMANDS = (*(command.NAME for command in COMMANDS), LEGACY)


def _run_legacy(args: argparse.Namespace) -> int:
    sys.argv = [f"qcom-ptool {LEGACY}", *args.rest]
    runpy.run_module(f"qcom_ptool.{LEGACY}", run_name="__main__")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="qcom-ptool",
        description="Qualcomm partition tool - GPT partition table and flashing artifact generator.",
    )
    root.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = root.add_subparsers(dest="subcommand", metavar="subcommand", required=True)
    for command in COMMANDS:
        command.register(subparsers)
    legacy = subparsers.add_parser(
        LEGACY, help="write rawprogram/patch XML to a block device", add_help=False
    )
    legacy.set_defaults(run=_run_legacy)
    return root


def main(argv: list[str] | None = None) -> int:
    root = parser()
    args, rest = root.parse_known_args(argv)
    if rest and args.subcommand != LEGACY:
        root.error("unrecognized arguments: " + " ".join(rest))
    args.rest = rest
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
