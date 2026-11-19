# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
``qcom-ptool build`` - a flashable configuration in one command.

Runs the gen_partition / ptool pipeline for every flashed storage:
partitions.xml plus the GPT and flashing artifacts, then contents.xml for
a configuration with contents metadata. A platform file builds each of
its configurations into ``<outdir>/<name>/<storage-id>/``; a board with
a flavor builds one configuration into ``<outdir>/<storage-id>/``, so a
custom configuration needs no file of its own:
``build -b <board.yaml> -f <flavor.yaml>``. A self-contained board (e.g.
out of tree) builds the same way without ``-f``. ``-I <dir>`` adds
include directories: references inside the files that do not resolve
relative to their own file are looked up there, in order, so files kept
out of tree can reuse the in-tree boards, flavors and fragments.
"""

from __future__ import annotations

import getopt
import os
import runpy
import sys
from collections.abc import Sequence
from typing import NoReturn


def usage() -> NoReturn:
    print(
        "\n\tUsage: %s [-I <dir>]... [-o <outdir>] <platform.yaml>\n"
        "\t       %s [-I <dir>]... [-o <outdir>] -b <board.yaml> [-f <flavor.yaml>]\n"
        "\n\tWrites partitions.xml and the GPT and flashing artifacts of every "
        "flashed\n"
        "\tstorage: a platform to <outdir>/<name>/<storage-id>/, a board to\n"
        "\t<outdir>/<storage-id>/ (default outdir: .), plus contents.xml with\n"
        "\tcontents metadata. A self-contained board takes no flavor.\n"
        "\t-I adds an include directory: references that do not resolve "
        "relative to\n"
        "\ttheir own file are looked up there, in order.\n"
        % (sys.argv[0], sys.argv[0])
    )
    sys.exit(1)


def _run_ptool(partitions_xml: str, outdir: str) -> int:
    """Run the GPT generator on one emitted partitions.xml."""
    saved = sys.argv
    sys.argv = ["qcom-ptool ptool", "-x", partitions_xml, "-t", outdir]
    try:
        runpy.run_module("qcom_ptool.ptool", run_name="__main__")
    except SystemExit as exc:
        if exc.code:
            return int(exc.code)
    finally:
        sys.argv = saved
    return 0


def build(
    platform_file: str | None,
    board_file: str | None,
    flavor_file: str | None,
    outdir: str,
    include_dirs: Sequence[str] = (),
) -> int:
    """Emit partitions.xml, the GPT artifacts and contents.xml of every configuration."""
    from qcom_ptool.board import config_to_specs, resolve, resolve_platform
    from qcom_ptool.gen_contents import generate_configuration
    from qcom_ptool.gen_partition import generate_partition_xml

    try:
        if platform_file is not None:
            configs = resolve_platform(platform_file, include_dirs)
            prefix = [c["name"] for c in configs]
        else:
            assert board_file is not None
            configs = [resolve(board_file, flavor_file, include_dirs=include_dirs)]
            prefix = [""]
        specs = [
            (os.path.join(outdir, p, sid), sid, spec)
            for p, c in zip(prefix, configs)
            for sid, spec in config_to_specs(c)
        ]
    except Exception as e:
        print("Error: ", e)
        return 1

    for storage_dir, sid, spec in specs:
        os.makedirs(storage_dir, exist_ok=True)
        partitions_xml = os.path.join(storage_dir, "partitions.xml")
        print("Storage %s -> %s" % (sid, storage_dir))
        generate_partition_xml(spec["disk"], spec["partitions"], partitions_xml)
        rc = _run_ptool(partitions_xml, storage_dir)
        if rc:
            return rc

    for p, config in zip(prefix, configs):
        try:
            generate_configuration(config, os.path.join(outdir, p), "")
        except Exception as e:
            print("Error: ", e)
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        usage()

    board_file: str | None = None
    flavor_file: str | None = None
    outdir = "."
    include_dirs: list[str] = []

    try:
        opts, rem = getopt.getopt(argv[1:], "b:f:o:I:")
        for opt, arg in opts:
            if opt == "-b":
                board_file = arg
            elif opt == "-f":
                if flavor_file is not None:
                    print("Error: -f takes one flavor")
                    usage()
                flavor_file = arg
            elif opt == "-o":
                outdir = arg
            elif opt == "-I":
                include_dirs.append(arg)
    except Exception as argerr:
        print(str(argerr))
        usage()

    if board_file is None:
        if flavor_file is not None or len(rem) != 1:
            print("Error: pass a platform file, or -b <board> [-f <flavor>]")
            usage()
        return build(rem[0], None, None, outdir, include_dirs)
    if rem:
        print("Error: pass a platform file, or -b <board> [-f <flavor>]")
        usage()
    return build(None, board_file, flavor_file, outdir, include_dirs)


if __name__ == "__main__":
    sys.exit(main())
