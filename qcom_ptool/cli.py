# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import runpy
import sys

from qcom_ptool import __version__

SUBCOMMANDS = {
    "gen_partition": "qcom_ptool.gen_partition",
    "gen_contents": "qcom_ptool.gen_contents",
    "gen_udev_rules": "qcom_ptool.gen_udev_rules",
    "ptool": "qcom_ptool.ptool",
    "msp": "qcom_ptool.msp",
    "show": "qcom_ptool.show",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qcom-ptool",
        description=(
            "Qualcomm partition tool - GPT partition table generator and "
            "mass storage programmer."
        ),
        epilog=(
            "Run 'qcom-ptool <subcommand> -h' to see the options accepted by "
            "each subcommand."
        ),
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "subcommand",
        choices=sorted(SUBCOMMANDS),
        metavar="subcommand",
        help="one of: " + ", ".join(sorted(SUBCOMMANDS)),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    raw_args = sys.argv[1:] if argv is None else argv[1:]

    # If the first argument is a recognized subcommand, pass all remaining
    # arguments (including -h/--help) directly to that subcommand instead of
    # letting the top-level ArgumentParser intercept them.
    if raw_args and raw_args[0] in SUBCOMMANDS:
        subcommand = raw_args[0]
        rest = raw_args[1:]
    else:
        parser = _build_parser()
        args, rest = parser.parse_known_args(raw_args)
        subcommand = args.subcommand

    module_name = SUBCOMMANDS[subcommand]
    # Present argv to the legacy script as if it had been invoked directly as
    # "<subcommand> <args...>". The scripts read sys.argv via getopt.
    sys.argv = [f"qcom-ptool {subcommand}", *rest]
    runpy.run_module(module_name, run_name="__main__")


if __name__ == "__main__":
    main()
