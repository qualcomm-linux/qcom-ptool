# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import getopt
import os
import sys
from xml.etree import ElementTree as ET


def usage():
    print(
        (
            "\n\tUsage:\n"
            "\t  %s [--flavor <name>] [-i <include-dir>] [-o <outdir>] "
            "[-b <build_id>] <board.yaml>\n"
            "\t  %s -t <template> -p <partitions_xml_path> -o <output> "
            "[-b <build_id>]\n"
            "\n\tIn board mode every flavor with contents metadata is "
            "generated to\n"
            "\t<outdir>/<flavor>/<storage>/contents.xml, or to "
            "<outdir>/<flavor>/contents.xml\n"
            "\twith 'location: /'. --flavor builds one flavor; "
            "the default builds\n"
            "\tthem all. -i is the include directory that layout / include "
            "references resolve\n"
            "\tagainst (default: the board file's own platforms tree).\n"
            "\tVersion 0.1\n" % (sys.argv[0], sys.argv[0])
        )
    )
    sys.exit(1)


def ParseXML(XMLFile):
    try:
        tree = ET.parse(XMLFile)
        root = tree.getroot()
        return root
    except FileNotFoundError:
        print(f"Error: File '{XMLFile}' not found")
        return None
    except ET.ParseError as e:
        print(f"Error: Failed parsing '{XMLFile}': {e}")
        return None


def RebaseFilePaths(TemplateRoot, PartitionXml, OutputXml):
    """Re-base every file_path from the partitions directory to the output
    directory, so references resolve from wherever contents.xml is written.
    A no-op when both live in the same directory."""
    rel = os.path.relpath(
        os.path.dirname(os.path.abspath(PartitionXml)),
        os.path.dirname(os.path.abspath(OutputXml)),
    )
    if rel == ".":
        return
    for element in TemplateRoot.iter("file_path"):
        element.text = os.path.normpath(os.path.join(rel, element.text or "."))


def UpdateMetaData(TemplateRoot, PartitionRoot, BuildId):
    ChipIdList = TemplateRoot.findall("product_info/chipid")
    DefaultStorageType: str = ""
    for ChipId in ChipIdList:
        Flavor = ChipId.get("flavor")
        StorageType = ChipId.get("storage_type")
        print(f"Chipid Flavor: {Flavor} Storage Type: {StorageType}")
        if Flavor == "default":
            DefaultStorageType = ChipId.get("storage_type", "")

    PhyPartition = PartitionRoot.findall("physical_partition")
    Partitions = []
    for partition in PartitionRoot.findall("physical_partition/partition"):
        label = partition.get("label")
        filename = partition.get("filename")
        if label and filename:
            Partitions.append({"label": label, "filename": filename})
    print(f"Partitions: {Partitions}")

    def _add_file_elements(parent_element, pathname, file_path_flavor=None):
        """Helper function to add file_name and file_path sub-elements."""
        file_name_text = os.path.basename(pathname)
        file_path_text = os.path.dirname(pathname)
        if not file_path_text:  # no directory, use explicit . as current dir
            file_path_text = "."

        new_file_name = ET.SubElement(parent_element, "file_name")
        new_file_name.text = file_name_text
        new_file_path = ET.SubElement(parent_element, "file_path")
        if file_path_flavor:
            new_file_path.set("flavor", file_path_flavor)
        new_file_path.text = file_path_text

    builds = TemplateRoot.findall("builds_flat/build")
    for build in builds:
        Name = build.find("name")
        if Name is None or Name.text is None:
            continue
        print(f"Build Name: {Name.text}")
        new_build_id = ET.SubElement(build, "build_id")
        new_build_id.text = BuildId
        if Name.text != "common":
            continue
        DownloadFile = build.find("download_file")
        if DownloadFile is not None:
            build.remove(DownloadFile)
            # Partition entires
            for Partition in Partitions:
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("fastboot_complete", Partition["label"])
                _add_file_elements(new_download_file, Partition["filename"])
            # GPT Main & GPT Backup entries
            for PhysicalPartitionNumber in range(0, len(PhyPartition)):
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("storage_type", DefaultStorageType)
                _add_file_elements(
                    new_download_file, "gpt_main%d.bin" % (PhysicalPartitionNumber)
                )
                new_download_file = ET.SubElement(build, "download_file")
                new_download_file.set("storage_type", DefaultStorageType)
                _add_file_elements(
                    new_download_file, "gpt_backup%d.bin" % (PhysicalPartitionNumber)
                )

        PartitionFile = build.find("partition_file")
        if PartitionFile is not None:
            build.remove(PartitionFile)
            # Rawprogram entries
            for PhysicalPartitionNumber in range(0, len(PhyPartition)):
                new_partition_file = ET.SubElement(build, "partition_file")
                new_partition_file.set("storage_type", DefaultStorageType)
                _add_file_elements(
                    new_partition_file,
                    "rawprogram%d.xml" % (PhysicalPartitionNumber),
                    "default",
                )

        PartitionPatchFile = build.find("partition_patch_file")
        if PartitionPatchFile is not None:
            build.remove(PartitionPatchFile)
            # Patch entries
            for PhysicalPartitionNumber in range(0, len(PhyPartition)):
                new_partition_patch_file = ET.SubElement(build, "partition_patch_file")
                new_partition_patch_file.set("storage_type", DefaultStorageType)
                _add_file_elements(
                    new_partition_patch_file,
                    "patch%d.xml" % (PhysicalPartitionNumber),
                    "default",
                )


def WriteContents(xml_root, output_xml):
    """Indent and write one generated contents tree."""
    OutputTree = ET.ElementTree(xml_root)
    ET.indent(OutputTree, space="\t", level=0)
    OutputTree.write(
        output_xml, encoding="utf-8", xml_declaration=True, short_empty_elements=False
    )


def generate_from_template(template, partition_xml, output_xml, build_id):
    """The classic path: fill one contents.xml.in template."""
    print("Selected Template:  " + template)
    xml_root = ParseXML(template)

    print("Selected Partition XML:  " + partition_xml)
    partition_root = ParseXML(partition_xml)

    UpdateMetaData(xml_root, partition_root, build_id)
    RebaseFilePaths(xml_root, partition_xml, output_xml)
    WriteContents(xml_root, output_xml)


def generate_from_board(board_file, flavor_name, outdir, build_id, root=None):
    """The YAML path: one contents.xml per flavor with contents metadata.

    The flavor's metadata builds the very tree parsing the equivalent
    template produced, then runs through the same UpdateMetaData /
    RebaseFilePaths / WriteContents pipeline.
    """
    # Late imports so the template path never pulls in PyYAML / jsonschema.
    from qcom_ptool.board import resolve_board_flavors
    from qcom_ptool.contents_yaml import build_contents_root, contents_paths, default_storage

    flavors = resolve_board_flavors(board_file, root=root)
    if flavor_name is not None:
        flavors = [f for f in flavors if f["name"] == flavor_name]
        if not flavors:
            print("Error: %s has no flavor %r" % (board_file, flavor_name))
            return 1

    base = outdir if outdir is not None else "."
    generated = 0
    for flavor in flavors:
        paths = contents_paths(flavor)
        if paths is None:
            continue
        meta = flavor["contents"]
        assert meta is not None  # contents_paths() returned a pair
        output_xml = os.path.join(base, paths[0])
        partition_xml = os.path.join(base, paths[1])
        print("Contents %s -> %s" % (flavor["name"], output_xml))
        xml_root = build_contents_root(meta, default_storage(flavor))
        partition_root = ParseXML(partition_xml)
        if partition_root is None:
            return 1
        UpdateMetaData(xml_root, partition_root, build_id)
        RebaseFilePaths(xml_root, partition_xml, output_xml)
        WriteContents(xml_root, output_xml)
        generated += 1
    if not generated:
        print("Error: %s defines no contents metadata" % board_file)
        return 1
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv

    if len(argv) < 3:
        usage()

    try:
        if argv[1] == "-h" or argv[1] == "--help":
            usage()
        try:
            build_id = ""
            template = None
            partition_xml = None
            output_xml = None
            flavor_name = None
            root = None
            opts, rem = getopt.getopt(argv[1:], "t:p:o:b:i:", ["flavor="])
            for opt, arg in opts:
                if opt in ["-t"]:
                    template = arg
                elif opt in ["-p"]:
                    partition_xml = arg
                elif opt in ["-o"]:
                    output_xml = arg
                elif opt in ["-b"]:
                    build_id = arg
                elif opt in ["-i"]:
                    root = arg
                elif opt == "--flavor":
                    flavor_name = arg
                else:
                    usage()
        except Exception as argerr:
            print(str(argerr))
            usage()

        if template is None:
            if len(rem) != 1:
                print("Error: pass exactly one board file")
                usage()
            return generate_from_board(rem[0], flavor_name, output_xml, build_id, root=root)

        generate_from_template(template, partition_xml, output_xml, build_id)
    except Exception as e:
        print(("Error: ", e))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
