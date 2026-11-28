# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import runpy
import sys

from qcom_ptool import __version__

SUBCOMMANDS = {
    "build": "qcom_ptool.build",
    "show": "qcom_ptool.show",
    "gen_udev_rules": "qcom_ptool.gen_udev_rules",
    "msp": "qcom_ptool.msp",
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


def main() -> None:
    parser = _build_parser()
    args, rest = parser.parse_known_args()

    module_name = SUBCOMMANDS[args.subcommand]
    # Present argv to the legacy script as if it had been invoked directly as
    # "<subcommand> <args...>". The scripts read sys.argv via getopt.
    sys.argv = [f"qcom-ptool {args.subcommand}", *rest]
    runpy.run_module(module_name, run_name="__main__")


if __name__ == "__main__":
    main()
