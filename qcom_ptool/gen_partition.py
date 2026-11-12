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
import os
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
        "\t  %s --platform <platform.yaml> "
        "[-C <outdir> | -o <out1> -o <out2> ...]\n"
        "\t  %s --board <board.yaml> [--flavor <flavor.yaml>] "
        "[-C <outdir> | -o <out1> -o <out2> ...]\n"
        "\n\tA platform writes each configuration's storages to "
        "<outdir>/<name>/<storage-id>/;\n"
        "\ta board with a flavor, or a self-contained board without one, "
        "writes\n"
        "\t<outdir>/<storage-id>/ (default outdir: .).\n"
        "\tExplicit -o outputs are taken in the same order.\n"
        "\tVersion 1.0\n" % (sys.argv[0], sys.argv[0], sys.argv[0])
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
    platform_file: str | None = None
    board_file: str | None = None
    flavor_files: list[str] = []
    outputs: list[str] = []
    outdir: str | None = None
    image_map: dict[str, str] = {}

    if argv[1] == "-h" or argv[1] == "--help":
        usage()
    try:
        opts, _rem = getopt.getopt(
            argv[1:], "i:o:m:C:", ["platform=", "board=", "flavor="]
        )
        for opt, arg in opts:
            if opt == "-i":
                input_file = arg
            elif opt == "-o":
                outputs.append(arg)
            elif opt == "--platform":
                platform_file = arg
            elif opt == "--board":
                board_file = arg
            elif opt == "--flavor":
                flavor_files.append(arg)
            elif opt == "-C":
                outdir = arg
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

    sources = [x is not None for x in (input_file, platform_file, board_file)]
    if sum(sources) != 1:
        print(
            "Error: pass exactly one of -i <input>, --platform <platform.yaml> "
            "or --board <board.yaml>"
        )
        usage()
    if len(flavor_files) > (1 if board_file is not None else 0):
        print("Error: --board takes at most one --flavor, and only it does")
        usage()
    if outputs and outdir is not None:
        print("Error: pass either -C <outdir> or explicit -o outputs, not both")
        usage()

    if platform_file is not None or board_file is not None:
        return _run_platform(
            platform_file,
            board_file,
            flavor_files,
            outputs,
            outdir,
            image_map,
        )

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


def _run_platform(
    platform_file: str | None,
    board_file: str | None,
    flavor_files: list[str],
    outputs: list[str],
    outdir: str | None,
    image_map: dict[str, str],
) -> int:
    # Late import so the -i path never pulls in PyYAML / jsonschema.
    from qcom_ptool.board import config_to_specs, resolve, resolve_platform

    try:
        if platform_file is not None:
            configs = resolve_platform(platform_file)
            prefix = [c["name"] for c in configs]
        else:
            assert board_file is not None
            configs = [resolve(board_file, flavor_files[0] if flavor_files else None)]
            prefix = [""]
        specs = [
            (os.path.join(p, sid), sid, spec)
            for p, c in zip(prefix, configs)
            for sid, spec in config_to_specs(c, image_map=image_map)
        ]
    except Exception as e:
        print("Error: ", e)
        return 1

    if not outputs:
        # Default layout: <outdir>/[<name>/]<storage-id>/partitions.xml.
        base = outdir if outdir is not None else "."
        outputs = [os.path.join(base, rel, "partitions.xml") for rel, _, _ in specs]
        for path in outputs:
            os.makedirs(os.path.dirname(path), exist_ok=True)

    if len(outputs) != len(specs):
        rels = ", ".join(rel for rel, _, _ in specs)
        print(
            "Error: %d storage(s) flashed [%s] but %d -o output(s) given"
            % (len(specs), rels, len(outputs))
        )
        return 1

    for (_rel, sid, spec), output in zip(specs, outputs):
        print("Storage %s -> %s" % (sid, output))
        generate_partition_xml(spec["disk"], spec["partitions"], output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
