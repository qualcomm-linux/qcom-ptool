#!/usr/bin/env python3

# Copyright (c) 2019, The Linux Foundation. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
#     * Neither the name of The Linux Foundation nor the names of its
#       contributors may be used to endorse or promote products derived
#       from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY EXPRESS OR IMPLIED
# WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
# IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import annotations

import getopt
import sys
import xml.etree.ElementTree as ET
from typing import NoReturn
from xml.dom import minidom

from qcom_ptool.loaders import load as load_spec
from qcom_ptool.spec import DiskParams, PartitionsByLun


def usage() -> NoReturn:
    print(
        "\n\tUsage:\n"
        "\t  %s -i <input> -o <output> "
        "[-m name1=image1,name2=image2,...]\n"
        "\t  %s --board <board.yaml> [--hlos <name>] [--boot-fw <name>] "
        "[--root <dir>] -o <out1> [-o <out2> ...]\n"
        "\n\tIn --board mode one -o is given per storage, in declared order.\n"
        "\tVersion 1.0\n" % (sys.argv[0], sys.argv[0])
    )
    sys.exit(1)


def generate_multi_lun_xml(
    disk_params: DiskParams, partitions: PartitionsByLun, output_xml: str
) -> None:
    root = ET.Element("configuration")
    parser_instruction_text = ""

    for key, value in disk_params.items():
        if key != "size" and key != "type":
            parser_instruction_text += "\n\t" + str(key) + "=" + str(value) + "\n\t"

    ET.SubElement(root, "parser_instructions").text = parser_instruction_text

    for _phys_part, entries in sorted(partitions.items(), key=lambda item: int(item[0])):
        found = False
        for part_entry in entries:

            # if there is no partition in the LUN, skip the physical_partition in XML
            # only create the physical_partition once we have at least one partition
            if not found:
                phy_part = ET.SubElement(root, "physical_partition")
            ET.SubElement(phy_part, "partition", attrib=part_entry)
            found = True

    xmlstr = minidom.parseString(ET.tostring(root)).toprettyxml()
    with open(output_xml, "w") as f:
        f.write(xmlstr)


def generate_partition_xml(
    disk_params: DiskParams, partitions: PartitionsByLun, output_xml: str
) -> None:
    print("Generating %s XML %s" % (disk_params["type"].upper(), output_xml))

    if disk_params["type"] in ("emmc", "nvme", "spinor", "ufs"):
        generate_multi_lun_xml(disk_params, partitions, output_xml)
    else:
        print(
            "%s XML generation is curently not supported."
            % (disk_params["type"].upper())
        )


###############################################################################
# main


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    if len(argv) < 3:
        usage()

    input_file: str | None = None
    board_file: str | None = None
    root: str | None = None
    hlos: str | None = None
    boot_fw: str | None = None
    outputs: list[str] = []
    image_map: dict[str, str] = {}

    if argv[1] == "-h" or argv[1] == "--help":
        usage()
    try:
        opts, _rem = getopt.getopt(
            argv[1:], "i:o:m:", ["board=", "hlos=", "boot-fw=", "root="]
        )
        for opt, arg in opts:
            if opt == "-i":
                input_file = arg
            elif opt == "-o":
                outputs.append(arg)
            elif opt == "--board":
                board_file = arg
            elif opt == "--hlos":
                hlos = arg
            elif opt == "--boot-fw":
                boot_fw = arg
            elif opt == "--root":
                root = arg
            elif opt == "-m":
                for mapping in arg.split(","):
                    tags = mapping.split("=")
                    if len(tags) > 1:
                        image_map[tags[0]] = tags[1]
            else:
                usage()
    except Exception as argerr:
        print(str(argerr))
        usage()

    if (board_file is None) == (input_file is None):
        print("Error: pass exactly one of -i <input> or --board <board.yaml>")
        usage()
    if not outputs:
        usage()

    if board_file is not None:
        return _run_board(board_file, root, hlos, boot_fw, outputs, image_map)

    if input_file is None or len(outputs) != 1:
        print("Error: -i single-storage mode takes exactly one -o")
        usage()
    try:
        spec = load_spec(input_file, image_map=image_map)
    except Exception as e:
        print("Error: ", e)
        return 1

    generate_partition_xml(spec["disk"], spec["partitions"], outputs[0])
    return 0


def _run_board(
    board_file: str,
    root: str | None,
    hlos: str | None,
    boot_fw: str | None,
    outputs: list[str],
    image_map: dict[str, str],
) -> int:
    # Late import so the -i path never pulls in PyYAML / jsonschema.
    from qcom_ptool.board import board_to_specs, resolve_board

    try:
        board = resolve_board(board_file, root=root, hlos=hlos, boot_fw=boot_fw)
        specs = board_to_specs(board, image_map=image_map)
    except Exception as e:
        print("Error: ", e)
        return 1

    if len(outputs) != len(specs):
        ids = ", ".join(sid for sid, _ in specs)
        print(
            "Error: board declares %d storage(s) [%s] but %d -o output(s) given"
            % (len(specs), ids, len(outputs))
        )
        return 1

    for (sid, spec), output in zip(specs, outputs):
        print("Storage %s -> %s" % (sid, output))
        generate_partition_xml(spec["disk"], spec["partitions"], output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
